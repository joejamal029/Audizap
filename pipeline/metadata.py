"""
Canonical metadata provider.
Resolves official release metadata (Title, Artist, Album, Year, Track#, Genre, Square Art)
using Apple Music / iTunes Catalog API without requiring API keys or auth tokens.
"""
import urllib.request
import urllib.parse
import json
import logging
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

    @classmethod
    def _search_spotify(cls, query: str) -> Optional[dict]:
        """
        Searches Spotify's public catalog via spotapi.
        Immunized against Apple CDN 403 blocks with full global & indie coverage.
        """
        if not HAS_SPOTAPI:
            return None
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
        """
        clean_query = query.replace("\xa0", " ").strip()
        meta = CanonicalMetadata(
            title=fallback_title or clean_query,
            artist=fallback_artist or "Unknown Artist",
            album=fallback_album or fallback_title or clean_query,
            release_year=fallback_release_year,
            artwork_url=fallback_artwork_url,
            track_number=fallback_track_number or 1,
            track_total=fallback_track_total or 1
        )

        # Step 1: Query Apple Music / iTunes as the PRIMARY catalog resolver
        params = {
            "term": clean_query,
            "entity": "song",
            "limit": 1
        }
        url = f"{cls.ITUNES_URL}?{urllib.parse.urlencode(params)}"
        itunes_succeeded = False
        try:
            req = urllib.request.Request(url, headers=cls.HEADERS)
            with urllib.request.urlopen(req, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if payload.get("results"):
                    r = payload["results"][0]
                    meta.title = r.get("trackName") or meta.title
                    meta.artist = r.get("artistName") or meta.artist
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
        except Exception as e:
            logger.debug(f"Primary iTunes lookup for '{clean_query}': {e}")

        # Step 2: Fallback to Spotify catalog ONLY IF iTunes had no art or failed
        if not itunes_succeeded and not meta.artwork_url:
            sp_res = cls._search_spotify(clean_query)
            if sp_res and sp_res.get("artwork_url"):
                if not meta.title or meta.title == clean_query:
                    meta.title = sp_res.get("title") or meta.title
                if not meta.artist or meta.artist == "Unknown Artist":
                    meta.artist = sp_res.get("artist") or meta.artist
                if not meta.album or meta.album == clean_query:
                    meta.album = sp_res.get("album") or meta.album
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
