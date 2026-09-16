"""
Manifest parser supporting:
1. Spotify playlist/album links
2. Plain text files (e.g. "My Spotify Library.txt" or artist - title lists)
3. Direct track queries
"""
import re
import os
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class ManifestParser:
    @staticmethod
    def _init_spotify():
        """Initialize spotdl SpotifyClient safely without triggering spotdl CLI argument parsing."""
        try:
            from spotdl.utils.config import get_config
            from spotdl.utils.spotify import SpotifyClient

            config = get_config()
            spotify_keys = [
                'client_id', 'client_secret', 'user_auth', 'no_cache',
                'headless', 'max_retries', 'use_cache_file', 'use_official_api',
                'auth_token', 'cache_path'
            ]
            spotify_settings = {k: config[k] for k in spotify_keys if k in config}
            try:
                SpotifyClient.init(**spotify_settings)
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Could not initialize SpotifyClient: {e}")

    @classmethod
    def parse_input(cls, source: str) -> List[Dict[str, any]]:
        """
        Takes a file path, Spotify URL, or text query and returns a list of song dicts:
        [{'artist': str, 'title': str, 'query': str, 'url': Optional[str], 'duration': Optional[int]}]
        """
        songs = []

        # 1. Text file input
        if os.path.isfile(source):
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
            try:
                cls._init_spotify()
                from spotdl.types.playlist import Playlist
                from spotdl.types.album import Album
                from spotdl.types.song import Song

                if "playlist" in source:
                    pl = Playlist.from_url(source)
                    for s in pl.songs:
                        songs.append({
                            "artist": s.artist,
                            "title": s.name,
                            "query": f"{s.artist} - {s.name}",
                            "url": s.url,
                            "duration": s.duration
                        })
                elif "album" in source:
                    alb = Album.from_url(source)
                    for s in alb.songs:
                        songs.append({
                            "artist": s.artist,
                            "title": s.name,
                            "query": f"{s.artist} - {s.name}",
                            "url": s.url,
                            "duration": s.duration
                        })
                elif "track" in source:
                    s = Song.from_url(source)
                    songs.append({
                        "artist": s.artist,
                        "title": s.name,
                        "query": f"{s.artist} - {s.name}",
                        "url": s.url,
                        "duration": s.duration
                    })
                return songs
            except Exception as e:
                logger.warning(f"Failed to fetch Spotify playlist metadata via spotdl: {e}")

        # 3. Direct query fallback
        if " - " in source:
            parts = source.split(" - ", 1)
            artist, title = parts[0].strip(), parts[1].strip()
        else:
            artist, title = "", source.strip()

        songs.append({
            "artist": artist,
            "title": title,
            "query": source.strip(),
            "url": None,
            "duration": None
        })
        return songs
