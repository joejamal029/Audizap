"""
Multi-tier audio resolver with cascaded fallbacks:
Tier 1: YouTube Search (Official / Topic / Audio)
Tier 2: SoundCloud Search
Tier 3: Generic fallback
"""
import subprocess
import os
import sys
import shutil
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

class AudioResolver:
    def __init__(self, ytdlp_path: Optional[str] = None):
        # Always use python -m yt_dlp to remain robust against virtualenv folder relocation
        self.python_exe = sys.executable

    def download_stream(self, query: str, output_template: str, duration_sec: Optional[int] = None, tolerance: int = 25) -> Tuple[bool, str]:
        """
        Attempts multi-tier audio downloads in order.
        Returns: (success: bool, source_tier: str)
        """
        # Tier 1: YouTube Search (direct audio track)
        success = self._run_ytdlp(f"ytsearch1:{query} audio", output_template, duration_sec, tolerance)
        if success:
            return True, "YouTube"

        # Tier 2: SoundCloud Search
        success = self._run_ytdlp(f"scsearch1:{query}", output_template, duration_sec, tolerance)
        if success:
            return True, "SoundCloud"

        # Tier 3: Broad YouTube Search
        success = self._run_ytdlp(f"ytsearch1:{query}", output_template, duration_sec, tolerance)
        if success:
            return True, "YouTube Generic"

        return False, "Failed"

    def _run_ytdlp(self, search_url: str, output_template: str, duration_sec: Optional[int], tolerance: int) -> bool:
        cmd = [
            self.python_exe,
            "-m", "yt_dlp",
            search_url,
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", output_template,
            "--no-playlist",
            "--no-warnings",
            "--quiet"
        ]

        if duration_sec and duration_sec > 30:
            min_dur = max(10, duration_sec - tolerance)
            max_dur = duration_sec + tolerance
            cmd.extend([
                "--match-filter",
                f"duration >= {min_dur} & duration <= {max_dur}"
            ])

        res = subprocess.run(cmd, capture_output=True, text=True)
        return res.returncode == 0
