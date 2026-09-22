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
from typing import Optional, List, Tuple, Dict, Any
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
        Queries reliable multi-source lyrics engines (Musixmatch, LRCLIB, NetEase).
        Excludes dead/stalled providers (e.g. Megalobiz) and suppresses intermediate timeout noise.
        """
        try:
            logging.getLogger("syncedlyrics").setLevel(logging.CRITICAL)
            return syncedlyrics.search(query, providers=["musixmatch", "lrclib", "netease"])
        except Exception:
            return None

    @classmethod
    def inspect_file(cls, filepath: str) -> Dict[str, any]:
        """
        Inspects an existing audio file for metadata and embedded elements:
        - title, artist, album
        - has_art (APIC frame with valid image data)
        - has_lyrics (USLT or SYLT frame)
        - art_bytes (size of cover art)
        """
        info = {
            "title": "",
            "artist": "",
            "album": "",
            "has_art": False,
            "has_lyrics": False,
            "art_bytes": 0,
            "query": ""
        }
        try:
            id3 = ID3(filepath)
            info["title"] = str(id3.get("TIT2", "")).strip()
            info["artist"] = str(id3.get("TPE1", "")).strip()
            info["album"] = str(id3.get("TALB", "")).strip()

            # APIC check
            for k, v in id3.items():
                if k.startswith("APIC") and hasattr(v, "data") and len(v.data) > 100:
                    info["has_art"] = True
                    info["art_bytes"] = len(v.data)
                    break

            # Lyrics check
            for k in id3.keys():
                if k.startswith("USLT") or k.startswith("SYLT"):
                    info["has_lyrics"] = True
                    break
        except Exception:
            pass

        # Fallback to filename parsing if ID3 tags are missing
        if not info["title"]:
            base = os.path.splitext(os.path.basename(filepath))[0]
            if " - " in base:
                parts = base.split(" - ", 1)
                info["artist"] = parts[0].strip()
                info["title"] = parts[1].strip()
            else:
                info["title"] = base

        if info["artist"] and info["title"]:
            info["query"] = f"{info['artist']} - {info['title']}"
        else:
            info["query"] = info["title"]

        return info

    @classmethod
    def enrich_file(
        cls,
        filepath: str,
        meta: CanonicalMetadata,
        update_art: bool = True,
        update_lyrics: bool = True
    ) -> Dict[str, bool]:
        """
        Enriches an existing audio file in-place without re-encoding audio or wiping unrelated tags.
        Updates missing/requested APIC cover art and SYLT/USLT lyrics.
        """
        result = {"art_added": False, "lyrics_added": False}
        try:
            try:
                id3 = ID3(filepath)
            except Exception:
                id3 = ID3()

            # Ensure basic canonical titles are set if missing
            if not id3.get("TIT2") and meta.title:
                id3.add(TIT2(encoding=Encoding.UTF8, text=meta.title))
            if not id3.get("TPE1") and meta.artist:
                id3.add(TPE1(encoding=Encoding.UTF8, text=meta.artist))
            if not id3.get("TALB") and meta.album:
                id3.add(TALB(encoding=Encoding.UTF8, text=meta.album))

            # 1. Update Artwork
            if update_art and meta.artwork_data:
                apic_keys = [k for k in id3.keys() if k.startswith("APIC")]
                for k in apic_keys:
                    del id3[k]
                id3.add(APIC(
                    encoding=Encoding.UTF8,
                    mime="image/jpeg",
                    type=3,
                    desc="Cover",
                    data=meta.artwork_data
                ))
                result["art_added"] = True

            # 2. Update Lyrics
            if update_lyrics:
                lyrics_text = cls.fetch_lyrics(f"{meta.artist} - {meta.title}")
                if not lyrics_text and meta.title != meta.artist:
                    lyrics_text = cls.fetch_lyrics(f"{meta.title}")

                if lyrics_text:
                    uslt_keys = [k for k in id3.keys() if k.startswith("USLT")]
                    for k in uslt_keys:
                        del id3[k]
                    id3.add(USLT(encoding=Encoding.UTF8, lang="eng", desc="", text=lyrics_text))

                    sylt_entries = cls.parse_lrc_to_sylt(lyrics_text)
                    if sylt_entries:
                        sylt_keys = [k for k in id3.keys() if k.startswith("SYLT")]
                        for k in sylt_keys:
                            del id3[k]
                        id3.add(SYLT(
                            encoding=Encoding.UTF8,
                            lang="eng",
                            format=2,
                            type=1,
                            desc="",
                            text=sylt_entries
                        ))
                    result["lyrics_added"] = True

            if result["art_added"] or result["lyrics_added"]:
                id3.save(filepath, v2_version=3)

            return result
        except Exception as e:
            logger.error(f"Error enriching {filepath}: {e}")
            return result

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

    @classmethod
    def strip_bloat_and_optimize(
        cls,
        filepath: str,
        tag_obj: Optional[ID3] = None,
        max_art_dim: int = 1000
    ) -> Dict[str, Any]:
        """
        Removes non-audio metadata baggage (Adobe Premiere/Audition PRIV XMP histories,
        camera reel logs, uncompressed PNG artwork) while strictly preserving canonical
        audio tags (TIT2, TPE1, TALB, TRCK, TDRC, TCON, SYLT, USLT, etc.).

        Returns a dictionary detailing:
        - priv_removed: Number of PRIV frames stripped
        - priv_bytes_saved: Estimated bytes reclaimed from PRIV removal
        - art_compressed: Boolean indicating if artwork was re-compressed
        - art_bytes_saved: Bytes saved by compressing oversized/PNG artwork
        - total_bytes_saved: Overall tag bytes reduced
        """
        from .artwork import ArtworkResolver

        res = {
            "priv_removed": 0,
            "priv_bytes_saved": 0,
            "art_compressed": False,
            "art_bytes_saved": 0,
            "total_bytes_saved": 0,
            "modified": False
        }

        try:
            id3 = tag_obj if tag_obj is not None else ID3(filepath)
        except Exception:
            return res

        # 1. Strip PRIV frames (e.g. Adobe XMP project histories)
        priv_keys = [k for k in id3.keys() if k.startswith("PRIV")]
        for k in priv_keys:
            frame = id3[k]
            data_len = len(getattr(frame, "data", b""))
            res["priv_bytes_saved"] += data_len
            res["priv_removed"] += 1
            del id3[k]
            res["modified"] = True

        # 2. Inspect and optimize APIC frames (compress PNG or oversized art > 500KB)
        apic_keys = [k for k in id3.keys() if k.startswith("APIC")]
        for k in apic_keys:
            frame = id3[k]
            raw_art = getattr(frame, "data", b"")
            # If PNG or large JPEG > 500KB
            is_png = frame.mime == "image/png" or raw_art[:8] == b"\x89PNG\r\n\x1a\n"
            if is_png or len(raw_art) > 500 * 1024:
                opt_art = ArtworkResolver.optimize_image_bytes(raw_art, target_size=max_art_dim, quality=90)
                if opt_art and len(opt_art) < len(raw_art):
                    saved = len(raw_art) - len(opt_art)
                    res["art_bytes_saved"] += saved
                    res["art_compressed"] = True
                    res["modified"] = True
                    frame.data = opt_art
                    frame.mime = "image/jpeg"
                    frame.encoding = Encoding.UTF8

        res["total_bytes_saved"] = res["priv_bytes_saved"] + res["art_bytes_saved"]

        # Only save back to disk if tag_obj was not externally managed
        if res["modified"] and tag_obj is None:
            try:
                id3.save(filepath, v2_version=3)
            except Exception as e:
                logger.warning(f"Failed to save optimized ID3 tag to {filepath}: {e}")

        return res

