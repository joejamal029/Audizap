"""
Manifest parser supporting:
1. Spotify playlist/album/track links (Paginated extraction with fallback to Embed API)
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

try:
    import spotapi
    HAS_SPOTAPI = True
except ImportError:
    HAS_SPOTAPI = False

logger = logging.getLogger(__name__)

class ManifestParser:
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    @classmethod
    def _parse_spotapi_track(cls, item: dict) -> Optional[Dict[str, any]]:
        """Parses a track entry from spotapi PublicPlaylist or PublicAlbum."""
        if not isinstance(item, dict):
            return None

        data = None
        if "itemV2" in item and isinstance(item["itemV2"], dict):
            data = item["itemV2"].get("data")
        elif "track" in item and isinstance(item["track"], dict):
            data = item["track"]
        elif "item" in item and isinstance(item["item"], dict):
            data = item["item"]
        else:
            data = item

        if not data or not isinstance(data, dict):
            return None

        name = data.get("name") or data.get("title")
        if not name:
            return None

        # Artists extraction
        artists = []
        art_data = data.get("artists")
        if isinstance(art_data, dict) and "items" in art_data:
            for a in art_data["items"]:
                if isinstance(a, dict):
                    prof = a.get("profile") or {}
                    a_name = prof.get("name") or a.get("name")
                    if a_name:
                        artists.append(a_name)
        elif isinstance(art_data, list):
            for a in art_data:
                if isinstance(a, dict):
                    prof = a.get("profile") or {}
                    a_name = prof.get("name") or a.get("name")
                    if a_name:
                        artists.append(a_name)
                elif isinstance(a, str):
                    artists.append(a)

        artist_str = ", ".join(artists) if artists else data.get("artist", "")

        # Duration extraction
        duration_ms = 0
        if "trackDuration" in data and isinstance(data["trackDuration"], dict):
            duration_ms = data["trackDuration"].get("totalMilliseconds", 0)
        elif "duration" in data and isinstance(data["duration"], dict):
            duration_ms = data["duration"].get("totalMilliseconds", 0)
        elif "duration_ms" in data:
            duration_ms = data.get("duration_ms", 0)

        uri = data.get("uri", "")
        track_id = uri.split(":")[-1] if "track:" in uri else None
        url = f"https://open.spotify.com/track/{track_id}" if track_id else None

        return {
            "artist": artist_str,
            "title": name,
            "query": f"{artist_str} - {name}" if artist_str else name,
            "url": url,
            "duration": duration_ms // 1000 if duration_ms else None
        }

    @classmethod
    def _fetch_spotify_paginated(cls, entity_type: str, entity_id: str) -> Optional[List[Dict[str, any]]]:
        """
        Fetches all tracks from Spotify using spotapi pagination.
        Bypasses the 100-track embed limit without requiring API keys.
        """
        if not HAS_SPOTAPI:
            return None

        tracks = []
        try:
            if entity_type == "playlist":
                playlist = spotapi.PublicPlaylist(entity_id)
                for chunk in playlist.paginate_playlist():
                    items = chunk.get("items", []) if isinstance(chunk, dict) else (chunk if isinstance(chunk, list) else [])
                    for it in items:
                        parsed = cls._parse_spotapi_track(it)
                        if parsed:
                            tracks.append(parsed)
            elif entity_type == "album":
                album = spotapi.PublicAlbum(entity_id)
                for chunk in album.paginate_album():
                    items = chunk.get("items", []) if isinstance(chunk, dict) else (chunk if isinstance(chunk, list) else [])
                    for it in items:
                        parsed = cls._parse_spotapi_track(it)
                        if parsed:
                            tracks.append(parsed)

            if tracks:
                return tracks
        except Exception as e:
            logger.warning(f"spotapi pagination failed for {entity_type}/{entity_id}: {e}")
        return None

    @classmethod
    def _fetch_spotify_embed_tracks(cls, entity_type: str, entity_id: str) -> Optional[List[Dict[str, any]]]:
        """
        Extracts tracks quickly and directly from Spotify Embed API.
        Used for single tracks or as a fallback if paginator fails.
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
            match = re.search(r"open\.spotify\.com\/(playlist|album|track)\/([a-zA-Z0-9]+)", source)
            if match:
                entity_type = match.group(1)
                entity_id = match.group(2)

                # Step 1: For playlists and albums, use spotapi pagination (no 100-song cap)
                if entity_type in ("playlist", "album"):
                    tracks = cls._fetch_spotify_paginated(entity_type, entity_id)
                    if tracks:
                        logger.info(f"Retrieved {len(tracks)} tracks via Spotify paginator.")
                        return tracks

                # Step 2: Embed API extraction (primary for single tracks, fallback for lists)
                tracks = cls._fetch_spotify_embed_tracks(entity_type, entity_id)
                if tracks:
                    return tracks

                # If extraction failed (e.g. private or 404), return empty list
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
