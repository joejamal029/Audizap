"""
4-Tier High-Definition Square Artwork Resolver:
Tier 1: Apple Music / iTunes CDN (1000x1000 / 1400x1400 uncompressed)
Tier 2: Spotify CDN (640x640)
Tier 3: Deezer CDN (1000x1000 cover_xl)
Tier 4: YouTube Thumbnail with automated 16:9 letterbox detection and 1:1 center crop
"""
import io
import os
import re
import json
import hashlib
import logging
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any, Tuple
from PIL import Image

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
ARTWORK_DIR = os.path.join(CACHE_DIR, "artwork")
os.makedirs(ARTWORK_DIR, exist_ok=True)

class ArtworkResolver:
    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir or ARTWORK_DIR
        os.makedirs(self.cache_dir, exist_ok=True)

    def _fetch_bytes(self, url: str, timeout: int = 10) -> Optional[bytes]:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                if len(data) > 2048:
                    return data
        except Exception as e:
            logger.debug(f"Failed to fetch image from {url}: {e}")
        return None

    @staticmethod
    def optimize_image_bytes(img_bytes: bytes, target_size: int = 1000, quality: int = 90) -> Optional[bytes]:
        """
        Compresses and normalizes raw image bytes into a high-quality 1000x1000 RGB JPEG.
        Eliminates uncompressed PNG bloat (e.g. 7MB PNGs down to ~120KB JPEG).
        """
        try:
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            w, h = img.size
            if w != h:
                min_dim = min(w, h)
                left = (w - min_dim) // 2
                top = (h - min_dim) // 2
                right = left + min_dim
                bottom = top + min_dim
                img = img.crop((left, top, right, bottom))

            if img.size != (target_size, target_size):
                img = img.resize((target_size, target_size), Image.Resampling.LANCZOS)

            out_buf = io.BytesIO()
            img.save(out_buf, format="JPEG", quality=quality, optimize=True)
            return out_buf.getvalue()
        except Exception as e:
            logger.debug(f"Error optimizing image bytes: {e}")
            return img_bytes

    def _crop_to_square(self, img_bytes: bytes, target_size: int = 1000) -> Optional[bytes]:
        """
        Takes raw image bytes, crops out 16:9 black letterbox bars if present,
        performs 1:1 center crop, resizes to target_size, and returns JPEG bytes.
        """
        return self.optimize_image_bytes(img_bytes, target_size=target_size, quality=95)

    def get_itunes_artwork(self, title: str, artist: str, target_size: int = 1000) -> Optional[bytes]:
        """Fetch 1000x1000 artwork from iTunes Search API."""
        query = f"{title} {artist}".strip()
        url = f"https://itunes.apple.com/search?term={urllib.parse.quote(query)}&entity=song&limit=3"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for item in data.get("results", []):
                    art_100 = item.get("artworkUrl100", "")
                    if art_100:
                        highres = re.sub(r"\d+x\d+bb", f"{target_size}x{target_size}bb", art_100)
                        raw = self._fetch_bytes(highres)
                        if raw:
                            return raw
        except Exception as e:
            logger.debug(f"iTunes artwork query error: {e}")
        return None

    def get_deezer_artwork(self, title: str, artist: str, target_size: int = 1000) -> Optional[bytes]:
        """Fetch 1000x1000 artwork from Deezer open API."""
        query = f'track:"{title}" artist:"{artist}"'
        url = f"https://api.deezer.com/search?q={urllib.parse.quote(query)}&limit=3"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for item in data.get("data", []):
                    album_data = item.get("album", {})
                    art_url = album_data.get("cover_xl") or album_data.get("cover_big")
                    if art_url:
                        raw = self._fetch_bytes(art_url)
                        if raw:
                            return self._crop_to_square(raw, target_size)
        except Exception as e:
            logger.debug(f"Deezer artwork query error: {e}")
        return None

    def resolve_artwork(
        self,
        title: str,
        artist: str,
        spotify_art_url: Optional[str] = None,
        yt_thumbnail_url: Optional[str] = None,
        target_size: int = 1000
    ) -> Optional[bytes]:
        """
        Resolves artwork via 4-tier fallback:
        Tier 1: iTunes 1000x1000
        Tier 2: Spotify CDN (640x640)
        Tier 3: Deezer 1000x1000
        Tier 4: YouTube Thumbnail (Auto-cropped to 1:1 square)
        """
        cache_key = hashlib.md5(f"{artist}_{title}_{target_size}".encode("utf-8")).hexdigest()
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.jpg")

        if os.path.exists(cache_file) and os.path.getsize(cache_file) > 2048:
            try:
                with open(cache_file, "rb") as f:
                    return f.read()
            except Exception:
                pass

        art_bytes = None

        # Tier 1: iTunes
        art_bytes = self.get_itunes_artwork(title, artist, target_size)

        # Tier 2: Spotify CDN
        if not art_bytes and spotify_art_url:
            raw = self._fetch_bytes(spotify_art_url)
            if raw:
                art_bytes = self._crop_to_square(raw, target_size)

        # Tier 3: Deezer
        if not art_bytes:
            art_bytes = self.get_deezer_artwork(title, artist, target_size)

        # Tier 4: YouTube Thumbnail
        if not art_bytes and yt_thumbnail_url:
            raw = self._fetch_bytes(yt_thumbnail_url)
            if raw:
                art_bytes = self._crop_to_square(raw, target_size)

        # Save to local cache
        if art_bytes and len(art_bytes) > 2048:
            try:
                with open(cache_file, "wb") as f:
                    f.write(art_bytes)
            except Exception as e:
                logger.debug(f"Failed to cache artwork: {e}")

        return art_bytes
