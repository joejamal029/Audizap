"""
Parallel Execution Engine.
Manages the concurrent processing of tracks across worker threads.
Each track autonomously executes:
Resolve Metadata -> Audio Fallback -> Transcode -> Concurrent Lyrics & Tagging
"""
import os
import re
import tempfile
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Callable, Optional
from .config import PipelineConfig
from .metadata import MetadataResolver
from .audio import AudioResolver
from .transcoder import Transcoder
from .tagger import Tagger

logger = logging.getLogger(__name__)

def sanitize_filename(name: str) -> str:
    for ch in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(ch, '')
    return name.strip()

class PipelineEngine:
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.metadata_resolver = MetadataResolver()
        self.audio_resolver = AudioResolver(cookie_file=self.config.cookie_file)
        self.transcoder = Transcoder()
        self.tagger = Tagger()
        os.makedirs(self.config.output_dir, exist_ok=True)

    def process_single_song(self, song_item: Dict[str, str], progress_callback: Optional[Callable] = None) -> Dict[str, any]:
        artist = song_item.get("artist", "")
        title = song_item.get("title", "")
        query = song_item.get("query", f"{artist} - {title}")
        duration = song_item.get("duration")

        result = {
            "query": query,
            "success": False,
            "skipped": False,
            "file": None,
            "source": None,
            "error": None
        }

        # 1. Resolve Canonical Metadata & Square Artwork
        meta = self.metadata_resolver.resolve(
            query=query,
            fallback_artist=artist,
            fallback_title=title,
            fallback_album=song_item.get("album", ""),
            fallback_artwork_url=song_item.get("artwork_url"),
            fallback_release_year=song_item.get("release_year"),
            fallback_track_number=song_item.get("track_number", 1),
            artwork_size=self.config.artwork_size
        )

        filename_base = sanitize_filename(f"{meta.artist} - {meta.title}")
        target_path = os.path.abspath(os.path.join(self.config.output_dir, f"{filename_base}.mp3"))
        result["file"] = target_path

        # 2. Check if file already exists in download folder
        if os.path.exists(target_path) and not self.config.overwrite_existing:
            if self.config.enrich_existing:
                inspection = self.tagger.inspect_file(target_path)
                need_art = (not inspection["has_art"] or self.config.force_update_art) and self.config.embed_artwork
                need_lyrics = (not inspection["has_lyrics"] or self.config.force_update_lyrics) and self.config.embed_lyrics

                if need_art or need_lyrics:
                    enrich_res = self.tagger.enrich_file(
                        filepath=target_path,
                        meta=meta,
                        update_art=need_art,
                        update_lyrics=need_lyrics
                    )
                    result["success"] = True
                    result["skipped"] = False
                    result["enriched"] = True
                    result["art_added"] = enrich_res["art_added"]
                    result["lyrics_added"] = enrich_res["lyrics_added"]
                    if progress_callback:
                        progress_callback(query, "enriched")
                    return result

            result["success"] = True
            result["skipped"] = True
            if progress_callback:
                progress_callback(query, "skipped")
            return result

        # 3. Multi-tier Audio Acquisition using isolated temp dir
        temp_dir = tempfile.mkdtemp(prefix="audio_stream_")
        temp_template = os.path.join(temp_dir, "stream.%(ext)s")

        target_duration = duration or (meta.duration_ms // 1000 if meta.duration_ms else None)
        downloaded, source_tier = self.audio_resolver.download_stream(
            query=query,
            output_template=temp_template,
            duration_sec=target_duration,
            tolerance=self.config.duration_tolerance
        )

        raw_files = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir)]
        if not downloaded or not raw_files:
            result["error"] = "Audio stream download failed across all tiers"
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            if progress_callback:
                progress_callback(query, "error")
            return result

        raw_downloaded = raw_files[0]
        result["source"] = source_tier

        # 4. Transcode to uniform CBR standards (e.g. 128k CBR, 44.1kHz)
        transcoded = self.transcoder.transcode_to_cbr(
            input_path=raw_downloaded,
            target_bitrate=self.config.bitrate,
            sample_rate=self.config.sample_rate
        )

        if not transcoded:
            result["error"] = "FFmpeg transcode failed"
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            if progress_callback:
                progress_callback(query, "error")
            return result

        import shutil
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        if os.path.exists(target_path):
            os.remove(target_path)
        shutil.move(raw_downloaded, target_path)
        shutil.rmtree(temp_dir, ignore_errors=True)

        # 5. Concurrent Tagging & Real-Time Synced Lyrics Retrieval
        tagged = self.tagger.tag_file(
            filepath=target_path,
            meta=meta,
            embed_lyrics=self.config.embed_lyrics
        )

        result["success"] = tagged
        if progress_callback:
            progress_callback(query, "done" if tagged else "error")
        return result

    def enrich_single_local_file(self, filepath: str, progress_callback: Optional[Callable] = None) -> Dict[str, any]:
        """
        Audits an existing local audio file on disk and enriches missing artwork or lyrics in-place.
        """
        inspection = self.tagger.inspect_file(filepath)
        query = inspection.get("query") or os.path.splitext(os.path.basename(filepath))[0]

        result = {
            "file": filepath,
            "query": query,
            "success": True,
            "skipped": False,
            "enriched": False,
            "art_added": False,
            "lyrics_added": False,
            "inspection": inspection,
            "error": None
        }

        need_art = (not inspection["has_art"] or self.config.force_update_art) and self.config.embed_artwork
        need_lyrics = (not inspection["has_lyrics"] or self.config.force_update_lyrics) and self.config.embed_lyrics

        if not need_art and not need_lyrics:
            result["skipped"] = True
            if progress_callback:
                progress_callback(query, "skipped")
            return result

        # Resolve metadata for the local file
        meta = self.metadata_resolver.resolve(
            query=query,
            fallback_artist=inspection.get("artist", ""),
            fallback_title=inspection.get("title", ""),
            fallback_album=inspection.get("album", ""),
            artwork_size=self.config.artwork_size
        )

        enrich_res = self.tagger.enrich_file(
            filepath=filepath,
            meta=meta,
            update_art=need_art,
            update_lyrics=need_lyrics
        )

        result["enriched"] = enrich_res["art_added"] or enrich_res["lyrics_added"]
        result["art_added"] = enrich_res["art_added"]
        result["lyrics_added"] = enrich_res["lyrics_added"]

        if progress_callback:
            status = "enriched" if result["enriched"] else "skipped"
            progress_callback(query, status)

        return result

    def enrich_local_folder(self, folder_path: str, status_callback: Optional[Callable] = None) -> List[Dict[str, any]]:
        """
        Scans a local directory for all .mp3 files and concurrently audits/enriches missing tags in-place.
        """
        if not os.path.isdir(folder_path):
            return []

        mp3_files = [
            os.path.abspath(os.path.join(folder_path, f))
            for f in os.listdir(folder_path)
            if f.lower().endswith(".mp3")
        ]

        if not mp3_files:
            return []

        results = []
        with ThreadPoolExecutor(max_workers=self.config.workers) as executor:
            futures = {
                executor.submit(self.enrich_single_local_file, f, status_callback): f
                for f in mp3_files
            }
            for future in as_completed(futures):
                results.append(future.result())

        return results

    def run(self, song_list: List[Dict[str, str]], status_callback: Optional[Callable] = None) -> List[Dict[str, any]]:
        os.makedirs(self.config.output_dir, exist_ok=True)
        results = []

        with ThreadPoolExecutor(max_workers=self.config.workers) as executor:
            futures = {
                executor.submit(self.process_single_song, song, status_callback): song
                for song in song_list
            }

            for future in as_completed(futures):
                res = future.result()
                results.append(res)

        return results

