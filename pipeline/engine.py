"""
Parallel Execution Engine.
Manages the concurrent processing of tracks across worker threads.
Each track autonomously executes:
Resolve Metadata -> Audio Fallback -> Transcode -> Concurrent Lyrics & Tagging
"""
import os
import re
import shutil
import tempfile
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Callable, Optional
from .config import PipelineConfig
from .metadata import MetadataResolver
from .audio import AudioResolver
from .transcoder import Transcoder
from .tagger import Tagger
from .qc import AcousticQC
from .artwork import ArtworkResolver
from .remediator import AudioRemediator
from .normalizer import BitrateNormalizer

logger = logging.getLogger(__name__)

def sanitize_filename(name: str) -> str:
    for ch in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(ch, '')
    return name.strip()

class PipelineEngine:
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.metadata_resolver = MetadataResolver()
        self.audio_resolver = AudioResolver(cookie_file=self.config.cookie_file, bitrate=self.config.bitrate)
        self.transcoder = Transcoder()
        self.tagger = Tagger()
        self.qc = AcousticQC()
        self.artwork_resolver = ArtworkResolver()
        self.remediator = AudioRemediator(
            target_bitrate=self.config.bitrate,
            sample_rate=self.config.sample_rate,
            artwork_size=self.config.artwork_size,
            cookie_file=self.config.cookie_file,
            strict_qc=self.config.strict_acoustic_qc
        )
        self.normalizer = BitrateNormalizer()
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

        # 1b. Enhance Artwork via 4-Tier Artwork Resolver
        if not meta.artwork_data and self.config.embed_artwork:
            art_bytes = self.artwork_resolver.resolve_artwork(
                title=meta.title,
                artist=meta.artist,
                spotify_art_url=meta.artwork_url,
                target_size=self.config.artwork_size
            )
            if art_bytes:
                meta.artwork_data = art_bytes

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

        # 3. Multi-tier Audio Acquisition with Acoustic QC & Topic Fast-Track
        target_duration = duration or (meta.duration_ms // 1000 if meta.duration_ms else None)
        candidates = self.audio_resolver.get_candidates(query=query, duration_sec=target_duration)

        raw_downloaded = None
        source_tier = None
        active_temp_dir = None

        for cand in candidates:
            temp_dir = tempfile.mkdtemp(prefix="audio_stream_")
            temp_template = os.path.join(temp_dir, "stream.%(ext)s")

            # Check fast-track eligibility (Topic channel + matching duration)
            is_fast_track = self.qc.is_fast_track_eligible(
                candidate_channel=cand.get("channel", ""),
                candidate_duration=cand.get("duration"),
                expected_duration=target_duration,
                tolerance=2
            ) and not self.config.strict_acoustic_qc

            downloaded = self.audio_resolver._run_ytdlp(cand["url"], temp_template)
            raw_files = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if not f.endswith(".part")]

            if not downloaded or not raw_files:
                shutil.rmtree(temp_dir, ignore_errors=True)
                continue

            cand_file = raw_files[0]

            # Run Acoustic QC if not fast-tracked
            if not is_fast_track and self.config.enable_acoustic_qc:
                qc_res = self.qc.verify_candidate(
                    candidate_path=cand_file,
                    title=meta.title,
                    artist=meta.artist,
                    candidate_channel=cand.get("channel", ""),
                    candidate_duration=cand.get("duration"),
                    expected_duration=target_duration,
                    strict=self.config.strict_acoustic_qc
                )
                qc_verdict = qc_res.get("verdict", "OK")

                if not qc_res.get("passed", True) or qc_verdict in ["LIVE_OR_DIFFERENT", "ANOMALOUS_DURATION"]:
                    logger.warning(f"Candidate rejected for '{query}': {cand['title']} (QC: {qc_verdict}, Score: {qc_res.get('score')})")
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    continue

            # Candidate accepted!
            raw_downloaded = cand_file
            source_tier = cand.get("tier", "YouTube")
            active_temp_dir = temp_dir
            break

        # Fallback if candidates failed
        if not raw_downloaded:
            active_temp_dir = tempfile.mkdtemp(prefix="audio_stream_")
            temp_template = os.path.join(active_temp_dir, "stream.%(ext)s")
            downloaded, source_tier = self.audio_resolver.download_stream(
                query=query,
                output_template=temp_template,
                duration_sec=target_duration,
                tolerance=self.config.duration_tolerance
            )
            raw_files = [os.path.join(active_temp_dir, f) for f in os.listdir(active_temp_dir) if not f.endswith(".part")]
            if downloaded and raw_files:
                raw_downloaded = raw_files[0]
            else:
                result["error"] = "Audio stream download failed across all tiers"
                shutil.rmtree(active_temp_dir, ignore_errors=True)
                if progress_callback:
                    progress_callback(query, "error")
                return result

        result["source"] = source_tier

        # 4. Transcode to uniform CBR standards (e.g. 128k CBR, 44.1kHz)
        transcoded = self.transcoder.transcode_to_cbr(
            input_path=raw_downloaded,
            target_bitrate=self.config.bitrate,
            sample_rate=self.config.sample_rate
        )

        if not transcoded:
            result["error"] = "FFmpeg transcode failed"
            shutil.rmtree(active_temp_dir, ignore_errors=True)
            if progress_callback:
                progress_callback(query, "error")
            return result

        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        if os.path.exists(target_path):
            os.remove(target_path)
        shutil.move(raw_downloaded, target_path)
        shutil.rmtree(active_temp_dir, ignore_errors=True)

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

    def remediate_local_folder(self, folder_path: str, progress_callback: Optional[Callable] = None) -> List[Dict[str, any]]:
        """
        Scans a local directory and remediates defective cuts, non-128k bitrates, and missing tags.
        """
        return self.remediator.remediate_folder(
            folder_path=folder_path,
            workers=self.config.workers,
            progress_callback=progress_callback
        )

    def normalize_local_folder(
        self,
        folder_path: str,
        target_bitrate: Optional[str] = None,
        force: bool = False,
        progress_callback: Optional[Callable] = None
    ) -> List[Dict[str, any]]:
        """
        Scans a local directory and normalizes audio streams to the target CBR bitrate in-place,
        losslessly preserving all ID3 tags, cover art, and synced lyrics.
        """
        return self.normalizer.normalize_folder(
            folder_path=folder_path,
            target_bitrate=target_bitrate or self.config.bitrate,
            sample_rate=self.config.sample_rate,
            workers=self.config.workers,
            force=force,
            progress_callback=progress_callback
        )

    def debloat_local_folder(
        self,
        folder_path: str,
        progress_callback: Optional[Callable] = None
    ) -> List[Dict[str, any]]:
        """
        Scans a local directory and strips non-audio metadata bloat (Adobe PRIV project histories,
        uncompressed PNG artwork) while strictly preserving canonical audio tags (TIT2, TPE1, TALB,
        TRCK, TDRC, TCON, SYLT, USLT). Zero audio transcoding, pure lossless size optimization.
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

        def _worker(f):
            filename = os.path.basename(f)
            res = self.tagger.strip_bloat_and_optimize(f, max_art_dim=self.config.artwork_size)
            res["filename"] = filename
            res["filepath"] = f
            return res

        results = []
        with ThreadPoolExecutor(max_workers=self.config.workers) as executor:
            futures = {executor.submit(_worker, f): f for f in mp3_files}
            for future in as_completed(futures):
                r = future.result()
                results.append(r)
                if progress_callback:
                    progress_callback(r["filename"], "debloated" if r["modified"] else "clean", r)

        return results

