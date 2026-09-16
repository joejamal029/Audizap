"""
Manifest parser supporting:
1. Spotify playlist/album links
2. Plain text files (e.g. "My Spotify Library.txt" or artist - title lists)
3. Direct track queries
"""
import re
import os
from typing import List, Dict, Tuple
from spotdl.utils.spotify import SpotifyClient
from spotdl.types.playlist import Playlist
from spotdl.types.album import Album
from spotdl.types.song import Song
from spotdl.console.entry_point import parse_arguments, create_settings

class ManifestParser:
    @staticmethod
    def parse_input(source: str) -> List[Dict[str, str]]:
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
                # Initialize spotdl client if needed
                arguments = parse_arguments()
                spotify_settings, _, _ = create_settings(arguments)
                try:
                    SpotifyClient.init(**spotify_settings)
                except Exception:
                    pass

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
                # Fallback: if Spotify API limits trigger, return source as a search query
                pass

        # 3. Direct query
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
