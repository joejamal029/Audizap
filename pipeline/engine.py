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
        self.audio_resolver = AudioResolver()
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
            "file": None,
            "source": None,
            "error": None
        }

        if progress_callback:
            progress_callback(query, "Resolving metadata...")

        # 1. Resolve Canonical Metadata & Square Artwork
        meta = self.metadata_resolver.resolve(
            query=query,
            fallback_artist=artist,
            fallback_title=title,
            artwork_size=self.config.artwork_size
        )

        filename_base = sanitize_filename(f"{meta.artist} - {meta.title}")
        target_path = os.path.abspath(os.path.join(self.config.output_dir, f"{filename_base}.mp3"))
        result["file"] = target_path

        # Check existing
        if os.path.exists(target_path) and not self.config.overwrite_existing:
            if progress_callback:
                progress_callback(query, "Already exists (Skipping)")
            result["success"] = True
            return result

        # 2. Multi-tier Audio Acquisition using isolated temp dir
        if progress_callback:
            progress_callback(query, "Downloading audio stream...")

        temp_dir = tempfile.mkdtemp(prefix="audio_stream_")
        temp_template = os.path.join(temp_dir, "stream.%(ext)s")

        downloaded, source_tier = self.audio_resolver.download_stream(
            query=query,
            output_template=temp_template,
            duration_sec=duration,
            tolerance=self.config.duration_tolerance
        )

        # Locate raw downloaded file in temp_dir
        raw_files = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir)]
        if not downloaded or not raw_files:
            result["error"] = "Audio stream download failed across all tiers"
            if progress_callback:
                progress_callback(query, "Failed audio stream")
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            return result

        raw_downloaded = raw_files[0]
        result["source"] = source_tier

        # 3. Transcode to uniform CBR standards (e.g. 128k CBR, 44.1kHz)
        if progress_callback:
            progress_callback(query, f"Transcoding ({self.config.bitrate} CBR)...")

        transcoded = self.transcoder.transcode_to_cbr(
            input_path=raw_downloaded,
            target_bitrate=self.config.bitrate,
            sample_rate=self.config.sample_rate
        )

        if not transcoded:
            result["error"] = "FFmpeg transcode failed"
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            return result

        # Move to target output directory
        import shutil
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        if os.path.exists(target_path):
            os.remove(target_path)
        shutil.move(raw_downloaded, target_path)
        shutil.rmtree(temp_dir, ignore_errors=True)

        # 4. Concurrent Tagging & Real-Time Synced Lyrics Retrieval
        if progress_callback:
            progress_callback(query, "Tagging & Embedding Synced Lyrics...")

        tagged = self.tagger.tag_file(
            filepath=target_path,
            meta=meta,
            embed_lyrics=self.config.embed_lyrics
        )

        result["success"] = tagged
        if progress_callback:
            progress_callback(query, "Complete!")

        return result

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
