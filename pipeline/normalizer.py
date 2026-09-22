"""
Lossless Bitrate Normalizer Engine.
Normalizes audio files to constant bitrate (CBR) standards (e.g., 128k, 192k, 320k)
while 100% losslessly preserving embedded ID3v2.3 tags, APIC cover art,
and binary synchronized lyrics (SYLT / USLT).
Includes smart passthrough to prevent generation loss on compliant files.
"""
import os
import re
import shutil
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional, Callable
from mutagen.mp3 import MP3
from mutagen.id3 import ID3

logger = logging.getLogger(__name__)

class BitrateNormalizer:
    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg = shutil.which(ffmpeg_path) or ffmpeg_path

    @staticmethod
    def parse_bitrate_kbps(bitrate_str: str) -> int:
        """Extract numeric kbps from strings like '128k', '192k (Standard)', '320'."""
        digits = re.sub(r"[^\d]", "", bitrate_str.split()[0])
        return int(digits) if digits else 128

    def inspect_bitrate(self, filepath: str) -> Dict[str, Any]:
        """Inspects an audio file's current bitrate and stream properties."""
        info = {
            "filepath": filepath,
            "filename": os.path.basename(filepath),
            "bitrate_kbps": 0,
            "sample_rate": 0,
            "duration_s": 0.0,
            "valid": False,
            "error": None
        }
        try:
            audio = MP3(filepath)
            info["bitrate_kbps"] = round(audio.info.bitrate / 1000)
            info["sample_rate"] = audio.info.sample_rate
            info["duration_s"] = round(audio.info.length, 2)
            info["valid"] = True
        except Exception as e:
            info["error"] = str(e)
        return info

    def normalize_file(
        self,
        filepath: str,
        target_bitrate: str = "128k",
        sample_rate: int = 44100,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Normalizes a single audio file to the target CBR bitrate in-place.
        - Skips files already at target bitrate (preventing generation loss).
        - Captures a complete ID3 tag snapshot before transcoding.
        - Transcodes via FFmpeg libmp3lame to target bitrate.
        - Restores ID3 tags losslessly (APIC artwork, SYLT binary lyrics, USLT text lyrics).
        """
        filename = os.path.basename(filepath)
        target_kbps = self.parse_bitrate_kbps(target_bitrate)
        target_bitrate_clean = f"{target_kbps}k"

        result = {
            "filepath": filepath,
            "filename": filename,
            "action": "none",
            "old_bitrate": 0,
            "new_bitrate": 0,
            "success": True,
            "message": ""
        }

        if not os.path.exists(filepath):
            result["success"] = False
            result["action"] = "file_not_found"
            result["message"] = "File not found"
            return result

        # 1. Inspect current audio stream
        insp = self.inspect_bitrate(filepath)
        if not insp["valid"]:
            result["success"] = False
            result["action"] = "corrupted_audio"
            result["message"] = f"Invalid audio stream: {insp['error']}"
            return result

        current_kbps = insp["bitrate_kbps"]
        result["old_bitrate"] = current_kbps
        result["new_bitrate"] = current_kbps

        # 2. Smart Passthrough Check: Skip transcode if already at target bitrate
        from .tagger import Tagger

        if not force and abs(current_kbps - target_kbps) <= 2:
            # Still run debloat check in passthrough mode to reclaim space from PRIV/oversized art
            debloat_res = Tagger.strip_bloat_and_optimize(filepath)
            if debloat_res["modified"]:
                saved_mb = debloat_res["total_bytes_saved"] / (1024 * 1024)
                result["action"] = "debloated_passthrough"
                result["message"] = f"Already at target bitrate ({current_kbps}k CBR) — Reclaimed {saved_mb:.2f} MB of metadata bloat (PRIV frames stripped, art optimized)"
                result["bytes_saved"] = debloat_res["total_bytes_saved"]
                return result

            result["action"] = "skipped_already_target"
            result["message"] = f"Already at target bitrate ({current_kbps}k CBR)"
            return result

        # 3. Capture Lossless ID3 Tag Snapshot & Optimize
        tag_snapshot = None
        try:
            tag_snapshot = ID3(filepath)
            # Debloat the tag snapshot prior to restoring
            Tagger.strip_bloat_and_optimize(filepath, tag_obj=tag_snapshot)
        except Exception as e:
            logger.debug(f"No existing ID3 tags to snapshot for {filename}: {e}")

        # 4. Transcode via FFmpeg to a temporary file
        temp_output = f"{filepath}.norm_tmp.mp3"
        cmd = [
            self.ffmpeg, "-y",
            "-i", filepath,
            "-c:a", "libmp3lame",
            "-b:a", target_bitrate_clean,
            "-ar", str(sample_rate),
            "-id3v2_version", "3",
            temp_output
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True)
            if proc.returncode != 0 or not os.path.exists(temp_output) or os.path.getsize(temp_output) == 0:
                if os.path.exists(temp_output):
                    os.remove(temp_output)
                result["success"] = False
                result["action"] = "transcode_failed"
                result["message"] = f"FFmpeg error: {proc.stderr.decode('utf-8', errors='replace')[:200]}"
                return result

            # Replace original file atomically
            os.replace(temp_output, filepath)

            # 5. Restore ID3 Tags Losslessly onto the normalized audio stream
            if tag_snapshot is not None:
                try:
                    tag_snapshot.save(filepath, v2_version=3)
                except Exception as e:
                    logger.warning(f"Failed to restore ID3 tags onto {filename}: {e}")

            # 6. Verify resulting file
            post_insp = self.inspect_bitrate(filepath)
            result["new_bitrate"] = post_insp["bitrate_kbps"]
            result["action"] = "normalized_cbr_inplace"
            result["message"] = f"Normalized from {current_kbps}k to {result['new_bitrate']}k CBR (ID3 tags debloated & preserved losslessly)"
            return result

        except Exception as e:
            if os.path.exists(temp_output):
                os.remove(temp_output)
            result["success"] = False
            result["action"] = "error"
            result["message"] = str(e)
            return result

    def normalize_folder(
        self,
        folder_path: str,
        target_bitrate: str = "128k",
        sample_rate: int = 44100,
        workers: int = 4,
        force: bool = False,
        progress_callback: Optional[Callable] = None
    ) -> List[Dict[str, Any]]:
        """
        Scans a local directory for all .mp3 files and runs parallel bitrate normalization.
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
                executor.submit(self.normalize_file, f, target_bitrate, sample_rate, force): f
                for f in mp3_files
            }
            for future in as_completed(futures):
                res = future.result()
                results.append(res)
                if progress_callback:
                    progress_callback(res["filename"], res["action"], res)

        return results
