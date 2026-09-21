"""
FFmpeg audio transcode and normalizer.
Enforces constant bitrate (CBR) and sample rate standards.
"""
import subprocess
import os
import shutil
import logging

logger = logging.getLogger(__name__)

class Transcoder:
    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg = shutil.which(ffmpeg_path) or ffmpeg_path

    def transcode_to_cbr(self, input_path: str, target_bitrate: str = "128k", sample_rate: int = 44100) -> bool:
        """
        Transcodes any input audio file in-place to constant bitrate MP3.
        """
        # Snapshot existing ID3 tags before transcoding
        tag_snapshot = None
        try:
            from mutagen.id3 import ID3
            tag_snapshot = ID3(input_path)
        except Exception:
            pass

        temp_output = f"{input_path}.transcode_tmp.mp3"
        cmd = [
            self.ffmpeg, "-y",
            "-i", input_path,
            "-c:a", "libmp3lame",
            "-b:a", target_bitrate,
            "-ar", str(sample_rate),
            "-id3v2_version", "3",
            temp_output
        ]

        res = subprocess.run(cmd, capture_output=True)
        if res.returncode == 0 and os.path.exists(temp_output):
            os.replace(temp_output, input_path)
            # Restore ID3 tags losslessly
            if tag_snapshot is not None:
                try:
                    tag_snapshot.save(input_path, v2_version=3)
                except Exception as e:
                    logger.debug(f"Failed to restore ID3 tags after transcode: {e}")
            return True
        else:
            if os.path.exists(temp_output):
                os.remove(temp_output)
            return False
