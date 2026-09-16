"""
Manifest parser supporting:
1. Spotify playlist/album/track links (Fast Embed API extraction with timeout guard)
2. Plain text files (e.g. "My Spotify Library.txt" or artist - title lists)
3. Direct track queries
"""
import re
import os
import json
import logging
import urllib.request
import urllib.parse
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class ManifestParser:
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    @classmethod
    def _fetch_spotify_embed_tracks(cls, entity_type: str, entity_id: str) -> Optional[List[Dict[str, any]]]:
        """
        Extracts tracks quickly and directly from Spotify Embed API.
        Does not hang or freeze; returns None if not found, 404, or private.
        """
        embed_url = f"https://open.spotify.com/embed/{entity_type}/{entity_id}"
        try:
            req = urllib.request.Request(embed_url, headers=cls.HEADERS)
            with urllib.request.urlopen(req, timeout=8) as response:
                html = response.read().decode("utf-8")
                match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html)
                if not match:
                    return None

                data = json.loads(match.group(1))
                page_props = data.get("props", {}).get("pageProps", {})

                # Check if 404 or page not found
                if page_props.get("status") == 404:
                    return None

                state = page_props.get("state", {}).get("data", {}).get("entity", {})
                raw_tracks = state.get("trackList", [])

                if not raw_tracks and "title" in state:
                    # Single track embed
                    raw_tracks = [state]

                results = []
                for t in raw_tracks:
                    title = t.get("title", "")
                    artist = t.get("subtitle", "")
                    duration_ms = t.get("duration", 0)
                    uri = t.get("uri", "")

                    if title:
                        query_str = f"{artist} - {title}" if artist else title
                        results.append({
                            "artist": artist,
                            "title": title,
                            "query": query_str,
                            "url": f"https://open.spotify.com/track/{uri.split(':')[-1]}" if "track:" in uri else None,
                            "duration": duration_ms // 1000 if duration_ms else None
                        })
                return results
        except urllib.error.HTTPError as he:
            logger.warning(f"Spotify embed returned HTTP {he.code} for {entity_type}/{entity_id}")
            return None
        except Exception as e:
            logger.warning(f"Error reading Spotify embed: {e}")
            return None

    @classmethod
    def parse_input(cls, source: str) -> List[Dict[str, any]]:
        """
        Takes a file path, Spotify URL, or text query and returns a list of song dicts.
        """
        # 1. Text file input
        if os.path.isfile(source):
            songs = []
            with open(source, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
            for line in lines:
                if " - " in line:
                    parts = line.split(" - ", 1)
                    artist = parts[0].strip()
                    title = parts[1].strip()
                else:
                    artist = ""
                    title = line
                songs.append({
                    "artist": artist,
                    "title": title,
                    "query": f"{artist} - {title}" if artist else title,
                    "url": None,
                    "duration": None
                })
            return songs

        # 2. Spotify URL input
        if "open.spotify.com" in source:
            # Parse entity type and ID
            match = re.search(r"open\.spotify\.com\/(playlist|album|track)\/([a-zA-Z0-9]+)", source)
            if match:
                entity_type = match.group(1)
                entity_id = match.group(2)

                # Fast, non-blocking Embed extraction
                tracks = cls._fetch_spotify_embed_tracks(entity_type, entity_id)
                if tracks:
                    return tracks

                # If embed failed (e.g. private or 404), return empty list so GUI can notify user
                return []

        # 3. Direct song query fallback
        if " - " in source:
            parts = source.split(" - ", 1)
            artist, title = parts[0].strip(), parts[1].strip()
        else:
            artist, title = "", source.strip()

        return [{
            "artist": artist,
            "title": title,
            "query": source.strip(),
            "url": None,
            "duration": None
        }]
