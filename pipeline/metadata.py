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

    @classmethod
    def resolve(cls, query: str, fallback_artist: str = "", fallback_title: str = "", artwork_size: int = 1000) -> CanonicalMetadata:
        """
        Query official music catalog for canonical metadata and artwork.
        """
        params = {
            "term": query,
            "entity": "song",
            "limit": 1
        }
        url = f"{cls.ITUNES_URL}?{urllib.parse.urlencode(params)}"
        meta = CanonicalMetadata(
            title=fallback_title or query,
            artist=fallback_artist or "Unknown Artist",
            album=fallback_title or query
        )

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if payload.get("results"):
                    r = payload["results"][0]
                    meta.title = r.get("trackName") or meta.title
                    meta.artist = r.get("artistName") or meta.artist
                    meta.album = r.get("collectionName") or meta.album
                    meta.track_number = r.get("trackNumber", 1)
                    meta.track_total = r.get("trackCount", 1)
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
        except Exception as e:
            logger.warning(f"Metadata lookup failed for '{query}': {e}")

        # Fetch artwork binary if available
        if meta.artwork_url:
            try:
                art_req = urllib.request.Request(meta.artwork_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(art_req, timeout=10) as art_res:
                    meta.artwork_data = art_res.read()
            except Exception as e:
                logger.warning(f"Failed to download artwork from {meta.artwork_url}: {e}")

        return meta
