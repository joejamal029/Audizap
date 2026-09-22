"""
Audio Quality & Acoustic Remediation Engine.
Audits existing music folders for audio defects (live/bootleg rips, 28-minute video rips,
non-128k bitrates, missing 1000x1000 artwork, missing synced lyrics) and automatically
re-resolves and replaces them with verified studio masters.
"""
import os
import re
import shutil
import tempfile
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional, Callable, Tuple
from mutagen.mp3 import MP3
from mutagen.id3 import ID3

from .qc import AcousticQC
from .artwork import ArtworkResolver
from .audio import AudioResolver
from .transcoder import Transcoder
from .tagger import Tagger
from .metadata import CanonicalMetadata

logger = logging.getLogger(__name__)

class AudioRemediator:
    def __init__(
        self,
        target_bitrate: str = "128k",
        sample_rate: int = 44100,
        artwork_size: int = 1000,
        cookie_file: Optional[str] = None,
        backup_dir: Optional[str] = None,
        strict_qc: bool = False
    ):
        self.target_bitrate = target_bitrate
        self.target_bitrate_kbps = int(re.sub(r"[^\d]", "", target_bitrate) or "128")
        self.sample_rate = sample_rate
        self.artwork_size = artwork_size
        self.strict_qc = strict_qc
        self.backup_dir = backup_dir

        self.qc = AcousticQC()
        self.artwork_resolver = ArtworkResolver()
        self.audio_resolver = AudioResolver(cookie_file=cookie_file, bitrate=target_bitrate)
        self.transcoder = Transcoder()
        self.tagger = Tagger()

    def _parse_filename(self, filename: str) -> Tuple[str, str]:
        """Extract artist and title from filename when ID3 tags are missing."""
        base = os.path.splitext(filename)[0]
        if " - " in base:
            parts = base.split(" - ", 1)
            return parts[0].strip(), parts[1].strip()
        elif "_" in base:
            parts = base.split("_", 1)
            return parts[1].strip(), parts[0].strip()
        return "", base.strip()

    def audit_file(self, filepath: str) -> Dict[str, Any]:
        """
        Audits a single audio file on disk:
        1. Reads bitrate, sample rate, duration from audio stream.
        2. Reads ID3 tags (artist, title, album, ISRC).
        3. Runs AcousticQC against official reference preview.
        """
        info = {
            "filepath": filepath,
            "filename": os.path.basename(filepath),
            "artist": "",
            "title": "",
            "album": "",
            "bitrate_kbps": 0,
            "sample_rate": 0,
            "duration_s": 0.0,
            "has_art": False,
            "has_lyrics": False,
            "qc_result": None,
            "needs_bitrate_fix": False,
            "needs_audio_replacement": False,
            "needs_tag_enrich": False,
            "error": None
        }

        if not os.path.exists(filepath):
            info["error"] = "File not found"
            return info

        # 1. Inspect Audio Stream
        try:
            audio = MP3(filepath)
            info["bitrate_kbps"] = round(audio.info.bitrate / 1000)
            info["sample_rate"] = audio.info.sample_rate
            info["duration_s"] = round(audio.info.length, 2)
        except Exception as e:
            info["error"] = f"Corrupted or invalid MP3 audio stream: {e}"
            info["needs_audio_replacement"] = True
            return info

        # 2. Inspect ID3 Tags
        try:
            id3 = ID3(filepath)
            info["title"] = str(id3.get("TIT2", "")).strip()
            info["artist"] = str(id3.get("TPE1", "")).strip()
            info["album"] = str(id3.get("TALB", "")).strip()

            for k, v in id3.items():
                if k.startswith("APIC") and hasattr(v, "data") and len(v.data) > 1000:
                    info["has_art"] = True
                    break
            for k in id3.keys():
                if k.startswith("USLT") or k.startswith("SYLT"):
                    info["has_lyrics"] = True
                    break
        except Exception:
            pass

        # Fallback to filename if ID3 is blank
        if not info["artist"] or not info["title"]:
            parsed_a, parsed_t = self._parse_filename(os.path.basename(filepath))
            info["artist"] = info["artist"] or parsed_a
            info["title"] = info["title"] or parsed_t

        # 3. Bitrate Check
        if abs(info["bitrate_kbps"] - self.target_bitrate_kbps) > 2:
            info["needs_bitrate_fix"] = True

        # 4. Acoustic QC Check
        qc_res = self.qc.verify_candidate(
            candidate_path=filepath,
            title=info["title"],
            artist=info["artist"],
            candidate_duration=int(info["duration_s"]),
            strict=self.strict_qc
        )
        info["qc_result"] = qc_res

        # Determine if audio needs replacement
        if not qc_res.get("passed", True) or qc_res.get("verdict") in ["LIVE_OR_DIFFERENT", "ANOMALOUS_DURATION"]:
            info["needs_audio_replacement"] = True

        if not info["has_art"] or not info["has_lyrics"]:
            info["needs_tag_enrich"] = True

        return info

    def remediate_file(
        self,
        filepath: str,
        audit_info: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Remediates an existing audio file on disk:
        - If defective (live/bootleg/wrong duration/corrupted): auto-hunts and replaces with verified studio cut.
        - If bitrate is off: in-place transcodes to target CBR standard.
        - If art/lyrics are missing: injects 1000x1000 artwork and synced lyrics.
        """
        info = audit_info or self.audit_file(filepath)
        filename = os.path.basename(filepath)
        artist = info["artist"]
        title = info["title"]
        query = f"{artist} - {title}".strip(" -")

        result = {
            "filepath": filepath,
            "filename": filename,
            "action": "none",
            "success": True,
            "old_bitrate": info["bitrate_kbps"],
            "new_bitrate": info["bitrate_kbps"],
            "qc_score": info.get("qc_result", {}).get("score", 1.0),
            "qc_verdict": info.get("qc_result", {}).get("verdict", "OK"),
            "message": ""
        }

        # Case A: Audio Replacement Needed (Live, Anomaly, or Corrupted)
        if info["needs_audio_replacement"]:
            logger.info(f"Remediating defective cut: {filename} (Verdict: {info.get('qc_result', {}).get('verdict')})")

            # Try candidate hunting queries
            candidate_queries = [
                f"{artist} {title} Topic",
                f"{artist} {title} Official Audio",
                f"{artist} - {title}",
                query
            ]

            replacement_success = False
            temp_dir = tempfile.mkdtemp(prefix="remediate_")

            try:
                for q in candidate_queries:
                    temp_template = os.path.join(temp_dir, "cand.%(ext)s")
                    downloaded, source_tier = self.audio_resolver.download_stream(
                        query=q,
                        output_template=temp_template
                    )
                    raw_files = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if not f.endswith(".part")]
                    if not downloaded or not raw_files:
                        continue

                    cand_audio = raw_files[0]

                    # Verify candidate audio
                    cand_qc = self.qc.verify_candidate(
                        candidate_path=cand_audio,
                        title=title,
                        artist=artist,
                        strict=self.strict_qc
                    )

                    if cand_qc.get("passed", True) and cand_qc.get("verdict") != "LIVE_OR_DIFFERENT":
                        # Candidate is verified! Transcode to target bitrate
                        self.transcoder.transcode_to_cbr(
                            input_path=cand_audio,
                            target_bitrate=self.target_bitrate,
                            sample_rate=self.sample_rate
                        )

                        # Resolve 1000x1000 artwork
                        art_bytes = self.artwork_resolver.resolve_artwork(title, artist, target_size=self.artwork_size)

                        # Tag candidate
                        meta = CanonicalMetadata(
                            title=title,
                            artist=artist,
                            album=info["album"] or title,
                            artwork_bytes=art_bytes
                        )
                        self.tagger.tag_file(cand_audio, meta, embed_lyrics=True)

                        # Safe backup of original file
                        backup_folder = self.backup_dir or os.path.join(os.path.dirname(filepath), ".remediation_backup")
                        os.makedirs(backup_folder, exist_ok=True)
                        backup_path = os.path.join(backup_folder, filename)
                        if os.path.exists(filepath):
                            shutil.copy2(filepath, backup_path)

                        # Replace original file atomically
                        shutil.move(cand_audio, filepath)

                        replacement_success = True
                        result["action"] = "replaced_studio_master"
                        result["qc_score"] = cand_qc.get("score", 1.0)
                        result["qc_verdict"] = cand_qc.get("verdict", "STUDIO_MASTER")
                        result["new_bitrate"] = self.target_bitrate_kbps
                        result["message"] = f"Replaced with verified studio master from '{source_tier}' (Score: {cand_qc.get('score')})"
                        break
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

            if not replacement_success:
                result["success"] = False
                result["action"] = "replacement_failed"
                result["message"] = "Could not find a candidate passing acoustic QC"
                if progress_callback:
                    progress_callback(filename, "failed", result)
                return result

        # Case B: Bitrate Fix Only (Fast In-Place Transcode)
        elif info["needs_bitrate_fix"]:
            logger.info(f"Fixing bitrate for: {filename} ({info['bitrate_kbps']}k -> {self.target_bitrate})")
            transcoded = self.transcoder.transcode_to_cbr(
                input_path=filepath,
                target_bitrate=self.target_bitrate,
                sample_rate=self.sample_rate
            )
            if transcoded:
                result["action"] = "transcoded_cbr_inplace"
                result["new_bitrate"] = self.target_bitrate_kbps
                result["message"] = f"Transcoded in-place from {info['bitrate_kbps']}k to {self.target_bitrate}"
            else:
                result["success"] = False
                result["action"] = "transcode_failed"
                result["message"] = "FFmpeg transcode failed"

        # Case C: Enrich Missing Artwork / Lyrics
        if info["needs_tag_enrich"] and result["action"] != "replaced_studio_master":
            art_bytes = None
            if not info["has_art"]:
                art_bytes = self.artwork_resolver.resolve_artwork(title, artist, target_size=self.artwork_size)

            meta = CanonicalMetadata(
                title=title,
                artist=artist,
                album=info["album"] or title,
                artwork_bytes=art_bytes
            )
            self.tagger.enrich_file(
                filepath=filepath,
                meta=meta,
                update_art=not info["has_art"],
                update_lyrics=not info["has_lyrics"]
            )
        # Case D: Debloat Metadata (Strip PRIV frames & optimize PNG/oversized art)
        if result["action"] != "replaced_studio_master":
            debloat_res = self.tagger.strip_bloat_and_optimize(filepath, max_art_dim=self.artwork_size)
            if debloat_res["modified"]:
                saved_mb = debloat_res["total_bytes_saved"] / (1024 * 1024)
                if result["action"] == "none":
                    result["action"] = "debloated_tags"
                    result["message"] = f"Reclaimed {saved_mb:.2f} MB metadata bloat (stripped PRIV frames & optimized art)"
                else:
                    result["message"] += f" + reclaimed {saved_mb:.2f} MB metadata bloat"

        if result["action"] == "none":
            result["action"] = "verified_ok"
            result["message"] = "File already 100% verified studio master at target bitrate"

        if progress_callback:
            progress_callback(filename, result["action"], result)

        return result

    def remediate_folder(
        self,
        folder_path: str,
        workers: int = 4,
        progress_callback: Optional[Callable] = None
    ) -> List[Dict[str, Any]]:
        """
        Scans a directory for all .mp3 files and runs parallel remediation.
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
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self.remediate_file, f, None, progress_callback): f
                for f in mp3_files
            }
            for future in as_completed(futures):
                results.append(future.result())

        return results
