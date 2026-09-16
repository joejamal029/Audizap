"""
Multi-tier audio resolver with cascaded fallbacks:
Tier 1: YouTube Search (Primary Artist + Title)
Tier 2: SoundCloud Search
Tier 3: Full Query Search
Tier 4: Title Only Search
"""
import subprocess
import os
import sys
import re
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

class AudioResolver:
    def __init__(self, ytdlp_path: Optional[str] = None):
        self.python_exe = sys.executable

    def _clean_query(self, query: str) -> str:
        # If query has multiple artists e.g. "Artist1, Artist2, Artist3 - Title", simplify to "Artist1 - Title"
        if " - " in query:
            artist_part, title_part = query.split(" - ", 1)
            primary_artist = artist_part.split(",")[0].split("&")[0].split("feat.")[0].strip()
            # Clean brackets from title if present
            clean_title = re.sub(r"\(feat\.[^\)]+\)", "", title_part, flags=re.IGNORECASE).strip()
            return f"{primary_artist} {clean_title}"
        return query

    def download_stream(self, query: str, output_template: str, duration_sec: Optional[int] = None, tolerance: int = 25) -> Tuple[bool, str]:
        """
        Attempts multi-tier audio downloads without strict duration blocks.
        """
        simplified = self._clean_query(query)

        # Tier 1: YouTube Search with clean simplified query (Artist + Title)
        success = self._run_ytdlp(f"ytsearch1:{simplified} audio", output_template)
        if success:
            return True, "YouTube Audio"

        # Tier 2: YouTube Search directly with simplified query
        success = self._run_ytdlp(f"ytsearch1:{simplified}", output_template)
        if success:
            return True, "YouTube"

        # Tier 3: SoundCloud Search
        success = self._run_ytdlp(f"scsearch1:{simplified}", output_template)
        if success:
            return True, "SoundCloud"

        # Tier 4: Broad YouTube Search with original query
        if query != simplified:
            success = self._run_ytdlp(f"ytsearch1:{query}", output_template)
            if success:
                return True, "YouTube Broad"

        return False, "Failed"

    def _run_ytdlp(self, search_url: str, output_template: str) -> bool:
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

        res = subprocess.run(cmd, capture_output=True, text=True)
        return res.returncode == 0
