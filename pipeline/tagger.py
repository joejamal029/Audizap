"""
Tagging and lyrics injection engine.
Fetches real-time synced lyrics per track and dual-embeds:
1. Native binary SYLT (Synchronised Lyrics in milliseconds)
2. Timestamped USLT (for universal player compatibility)
3. Canonical metadata fields (TIT2, TPE1, TALB, TRCK, TPOS, TCON, TDRC, APIC)
"""
import re
import os
import logging
from typing import Optional, List, Tuple
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, TPOS, TDRC, TCON, APIC, USLT, SYLT, Encoding
import syncedlyrics
from .metadata import CanonicalMetadata

logger = logging.getLogger(__name__)

class Tagger:
    @staticmethod
    def parse_lrc_to_sylt(text: str) -> List[Tuple[str, int]]:
        """
        Parses LRC timestamps [mm:ss.xx] into (lyric_line, milliseconds) tuples for binary SYLT.
        """
        entries = []
        for line in text.splitlines():
            match = re.match(r"\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)", line.strip())
            if match:
                minutes = int(match.group(1))
                seconds = int(match.group(2))
                millis_raw = match.group(3)
                millis = int(millis_raw) * 10 if len(millis_raw) == 2 else int(millis_raw)
                total_ms = (minutes * 60 + seconds) * 1000 + millis
                lyric_text = match.group(4).strip()
                entries.append((lyric_text, total_ms))
        return entries

    @classmethod
    def fetch_lyrics(cls, query: str) -> Optional[str]:
        """
        Queries multi-source lyrics engines (Musixmatch, NetEase, Megalobiz, LRCLIB).
        """
        try:
            return syncedlyrics.search(query)
        except Exception:
            return None

    @classmethod
    def tag_file(cls, filepath: str, meta: CanonicalMetadata, embed_lyrics: bool = True) -> bool:
        """
        Wipes source platform residue tags and embeds canonical tags + cover art + internal lyrics.
        """
        try:
            id3 = ID3(filepath)
            id3.delete() # Completely purge dirty YouTube/SoundCloud scrapings
        except Exception:
            id3 = ID3()

        try:
            # 1. Canonical Core Metadata
            id3.add(TIT2(encoding=Encoding.UTF8, text=meta.title))
            id3.add(TPE1(encoding=Encoding.UTF8, text=meta.artist))
            id3.add(TALB(encoding=Encoding.UTF8, text=meta.album))
            id3.add(TRCK(encoding=Encoding.UTF8, text=f"{meta.track_number}/{meta.track_total}"))
            id3.add(TPOS(encoding=Encoding.UTF8, text=f"{meta.disc_number}/{meta.disc_total}"))
            id3.add(TCON(encoding=Encoding.UTF8, text=meta.genre))

            if meta.release_year:
                id3.add(TDRC(encoding=Encoding.UTF8, text=str(meta.release_year)))

            # 2. High-Resolution Square Cover Art
            if meta.artwork_data:
                id3.add(APIC(
                    encoding=Encoding.UTF8,
                    mime="image/jpeg",
                    type=3, # Front Cover
                    desc="Cover",
                    data=meta.artwork_data
                ))

            # 3. Real-Time Lyrics Retrieval & Dual-Embedding
            if embed_lyrics:
                lyrics_text = cls.fetch_lyrics(f"{meta.artist} - {meta.title}")
                if not lyrics_text and meta.title != meta.artist:
                    lyrics_text = cls.fetch_lyrics(f"{meta.title}")

                if lyrics_text:
                    # Tagged USLT
                    id3.add(USLT(encoding=Encoding.UTF8, lang="eng", desc="", text=lyrics_text))

                    # Native binary SYLT (millisecond synced)
                    sylt_entries = cls.parse_lrc_to_sylt(lyrics_text)
                    if sylt_entries:
                        id3.add(SYLT(
                            encoding=Encoding.UTF8,
                            lang="eng",
                            format=2, # Milliseconds
                            type=1,   # Lyrics
                            desc="",
                            text=sylt_entries
                        ))

            id3.save(filepath, v2_version=3)
            return True
        except Exception as e:
            logger.error(f"Error tagging {filepath}: {e}")
            return False
