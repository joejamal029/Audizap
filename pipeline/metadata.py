"""
Canonical metadata provider.
Resolves official release metadata (Title, Artist, Album, Year, Track#, Genre, Square Art)
using Apple Music / iTunes Catalog API without requiring API keys or auth tokens.
"""
import urllib.request
import urllib.parse
import json
import logging
import re
from difflib import SequenceMatcher
from dataclasses import dataclass
from typing import Optional

try:
    import spotapi
    HAS_SPOTAPI = True
except ImportError:
    HAS_SPOTAPI = False

logger = logging.getLogger(__name__)

@dataclass
class CanonicalMetadata:
    title: str
    artist: str
    album: str
    track_number: int = 1
    track_total: int = 1
    disc_number: int = 1
    disc_total: int = 1
    release_year: Optional[str] = None
    genre: str = "Pop"
    duration_ms: Optional[int] = None
    artwork_url: Optional[str] = None
    artwork_data: Optional[bytes] = None

class MetadataResolver:
    ITUNES_URL = "https://itunes.apple.com/search"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    @staticmethod
    def _clean_string(s: str) -> str:
        if not s:
            return ""
        s = s.lower()
        # Remove parenthetical details: (feat. ...), [remastered], (deluxe edition), etc.
        s = re.sub(r'[\(\[\{].*?[\)\]\}]', '', s)
        # Replace non-alphanumeric characters with spaces
        s = re.sub(r'[^a-z0-9\s]', ' ', s)
        return " ".join(s.split())

    @classmethod
    def _string_similarity(cls, a: str, b: str) -> float:
        ca, cb = cls._clean_string(a), cls._clean_string(b)
        if not ca or not cb:
            return 0.0
        if ca == cb or ca in cb or cb in ca:
            return 1.0
        return SequenceMatcher(None, ca, cb).ratio()

    @classmethod
    def _is_valid_candidate(cls, target_title: str, target_artist: str, cand_title: str, cand_artist: str) -> bool:
        """
        Validates whether a catalog search candidate genuinely matches the requested song.
        Prevents iTunes fuzzy fallback from replacing missing songs with completely unrelated tracks.
        """
        if not cand_title:
            return False

        # 1. Title verification
        t_words = set(cls._clean_string(target_title).split())
        cand_t_words = set(cls._clean_string(cand_title).split())
        title_sim = cls._string_similarity(target_title, cand_title)

        has_title_word_overlap = bool(
            t_words and cand_t_words and (len(t_words & cand_t_words) >= min(len(t_words), len(cand_t_words)))
        )
        if title_sim < 0.60 and not has_title_word_overlap:
            return False

        # 2. Artist verification (if target artist is known and not generic)
        if target_artist and target_artist.lower() not in ("unknown artist", "unknown", ""):
            a_words = set(cls._clean_string(target_artist).split())
            cand_a_words = set(cls._clean_string(cand_artist).split())
            art_sim = cls._string_similarity(target_artist, cand_artist)
            if art_sim < 0.50 and not (a_words & cand_a_words):
                return False

        return True

    @classmethod
    def _search_deezer(cls, query: str, target_title: str, target_artist: str) -> Optional[dict]:
        """
        Public global catalog search via Deezer API (open, high-speed, 1000x1000 square artwork).
        Used as a resilient secondary catalog when iTunes lacks regional or indie releases.
        """
        try:
            clean = query.replace("\xa0", " ").strip()
            params = {"q": clean, "limit": 5}
            url = f"https://api.deezer.com/search?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, headers=cls.HEADERS)
            with urllib.request.urlopen(req, timeout=4) as response:
                data = json.loads(response.read().decode("utf-8"))
                for item in data.get("data", []):
                    title = item.get("title", "")
                    artist = item.get("artist", {}).get("name", "")
                    if cls._is_valid_candidate(target_title, target_artist, title, artist):
                        album_obj = item.get("album", {})
                        art = album_obj.get("cover_xl") or album_obj.get("cover_big")
                        return {
                            "title": title,
                            "artist": artist,
                            "album": album_obj.get("title", ""),
                            "artwork_url": art
                        }
        except Exception as e:
            logger.debug(f"Deezer search error for '{query}': {e}")
        return None

    @classmethod
    def _search_spotify(cls, query: str) -> Optional[dict]:
        """
        Searches Spotify's public catalog via spotapi.
        Guarded by a strict 4s timeout to prevent network blocking.
        """
        if not HAS_SPOTAPI:
            return None

        def _do_search():
            try:
                clean = query.replace("\xa0", " ").strip()
                gen = spotapi.Public.song_search(clean)
                items = next(gen)
                if not items:
                    return None
                first = items[0]
                data = first.get("item", {}).get("data", {})
                if not data:
                    return None

                title = data.get("name", "")
                artists = [a.get("profile", {}).get("name") for a in data.get("artists", {}).get("items", []) if a.get("profile", {}).get("name")]
                artist = ", ".join(artists) if artists else ""
                album_data = data.get("albumOfTrack", {})
                album = album_data.get("name", "")

                covers = album_data.get("coverArt", {}).get("sources", [])
                artwork_url = None
                if covers:
                    sorted_covers = sorted(covers, key=lambda c: c.get("width", 0), reverse=True)
                    artwork_url = sorted_covers[0].get("url")

                return {
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "artwork_url": artwork_url
                }
            except Exception as e:
                logger.debug(f"Spotify catalog search error for '{query}': {e}")
                return None

        from concurrent.futures import ThreadPoolExecutor, TimeoutError
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_do_search)
                return future.result(timeout=4.0)
        except (TimeoutError, Exception) as e:
            logger.debug(f"Spotify search timed out or failed for '{query}': {e}")
            return None

    @classmethod
    def resolve(
        cls,
        query: str,
        fallback_artist: str = "",
        fallback_title: str = "",
        fallback_album: str = "",
        fallback_artwork_url: Optional[str] = None,
        fallback_release_year: Optional[str] = None,
        fallback_track_number: int = 1,
        fallback_track_total: int = 1,
        artwork_size: int = 1000
    ) -> CanonicalMetadata:
        """
        Query official music catalog for canonical metadata and artwork.
        Prefers verified direct metadata/artwork when already provided.
        Rejects unrelated fuzzy search results from iTunes/Spotify.
        """
        clean_query = query.replace("\xa0", " ").strip()

        # Determine target title and artist for candidate validation
        target_artist = fallback_artist or ""
        target_title = fallback_title or ""
        if not target_title and " - " in clean_query:
            parts = clean_query.split(" - ", 1)
            target_artist = target_artist or parts[0].strip()
            target_title = parts[1].strip()
        elif not target_title:
            target_title = clean_query

        meta = CanonicalMetadata(
            title=fallback_title or target_title,
            artist=fallback_artist or target_artist or "Unknown Artist",
            album=fallback_album or fallback_title or target_title,
            release_year=fallback_release_year,
            artwork_url=fallback_artwork_url,
            track_number=fallback_track_number or 1,
            track_total=fallback_track_total or 1
        )

        # Step 1: Query Apple Music / iTunes as the PRIMARY catalog resolver
        params = {
            "term": clean_query,
            "entity": "song",
            "limit": 5
        }
        url = f"{cls.ITUNES_URL}?{urllib.parse.urlencode(params)}"
        itunes_succeeded = False
        try:
            req = urllib.request.Request(url, headers=cls.HEADERS)
            with urllib.request.urlopen(req, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
                for r in payload.get("results", []):
                    cand_title = r.get("trackName", "")
                    cand_artist = r.get("artistName", "")
                    if cls._is_valid_candidate(target_title, target_artist, cand_title, cand_artist):
                        meta.title = cand_title or meta.title
                        meta.artist = cand_artist or meta.artist
                        meta.album = r.get("collectionName") or meta.album
                        meta.track_number = r.get("trackNumber", meta.track_number)
                        meta.track_total = r.get("trackCount", meta.track_total)
                        meta.disc_number = r.get("discNumber", 1)
                        meta.disc_total = r.get("discCount", 1)
                        meta.genre = r.get("primaryGenreName") or meta.genre
                        meta.duration_ms = r.get("trackTimeMillis")

                        release_date = r.get("releaseDate")
                        if release_date and len(release_date) >= 4:
                            meta.release_year = release_date[:4]

                        raw_art = r.get("artworkUrl100")
                        if raw_art:
                            meta.artwork_url = raw_art.replace("100x100bb.jpg", f"{artwork_size}x{artwork_size}bb.jpg")
                            itunes_succeeded = True
                        break
        except Exception as e:
            logger.debug(f"Primary iTunes lookup for '{clean_query}': {e}")

        # Step 2: Fallback to Deezer / Spotify if iTunes had no verified match
        if not itunes_succeeded:
            # 2a: Try Deezer public catalog (fast, open, 1000x1000 square artwork)
            dz_res = cls._search_deezer(clean_query, target_title, target_artist)
            if dz_res:
                if not meta.title or meta.title == clean_query:
                    meta.title = dz_res.get("title") or meta.title
                if not meta.artist or meta.artist == "Unknown Artist":
                    meta.artist = dz_res.get("artist") or meta.artist
                if not meta.album or meta.album == clean_query or not fallback_album:
                    meta.album = dz_res.get("album") or meta.album
                if not meta.artwork_url or dz_res.get("artwork_url"):
                    meta.artwork_url = dz_res.get("artwork_url") or meta.artwork_url
            elif not meta.artwork_url:
                # 2b: Try Spotify catalog only if artwork_url is still missing
                sp_res = cls._search_spotify(clean_query)
                if sp_res:
                    sp_title = sp_res.get("title", "")
                    sp_artist = sp_res.get("artist", "")
                    if cls._is_valid_candidate(target_title, target_artist, sp_title, sp_artist):
                        if not meta.title or meta.title == clean_query:
                            meta.title = sp_title or meta.title
                        if not meta.artist or meta.artist == "Unknown Artist":
                            meta.artist = sp_artist or meta.artist
                        if not meta.album or meta.album == clean_query:
                            meta.album = sp_res.get("album") or meta.album
                        if sp_res.get("artwork_url"):
                            meta.artwork_url = sp_res.get("artwork_url")

        # Fetch artwork binary if available
        if meta.artwork_url:
            try:
                art_req = urllib.request.Request(meta.artwork_url, headers=cls.HEADERS)
                with urllib.request.urlopen(art_req, timeout=10) as art_res:
                    meta.artwork_data = art_res.read()
            except Exception as e:
                logger.debug(f"Artwork download skipped from {meta.artwork_url}: {e}")

        return meta
