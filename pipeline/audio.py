"""
Multi-tier studio audio resolver with live/concert avoidance:
Tier 1: YouTube Music API (Direct official studio track query via ytmusicapi)
Tier 2: YouTube Scored Search (Multi-candidate retrieval with anti-live penalty & duration matching)
Tier 3: SoundCloud Search
Tier 4: Broad YouTube Search with original query
"""
import subprocess
import os
import sys
import re
import logging
from typing import Optional, Tuple, List, Dict, Any

try:
    from ytmusicapi import YTMusic
    HAS_YTMUSIC = True
except ImportError:
    HAS_YTMUSIC = False

logger = logging.getLogger(__name__)

FORBIDDEN_LIVE_WORDS = [
    "live", "concert", "livehouse", "performance", "live session", "live at",
    "in concert", "tour", "rehearsal", "acoustic session", "festival",
    "现场", "現場", "演唱会", "音樂會"
]

FORBIDDEN_DERIVATIVE_WORDS = [
    "cover", "remix", "tribute", "karaoke", "instrumental", "slowed",
    "reverb", "sped up", "reaction", "parody"
]

class AudioResolver:
    def __init__(self, ytdlp_path: Optional[str] = None, cookie_file: Optional[str] = None):
        self.python_exe = sys.executable
        self.cookie_file = cookie_file
        self.ytmusic = None
        if HAS_YTMUSIC:
            try:
                self.ytmusic = YTMusic()
            except Exception as e:
                logger.debug(f"YTMusic init skipped: {e}")

    def get_cookie_file(self) -> Optional[str]:
        """
        Resolves the absolute path to a valid cookies.txt file.
        Searches:
        1. Explicitly configured path (self.cookie_file)
        2. Environment variables (AUDIZAP_COOKIES, YTDLP_COOKIES)
        3. Project root directory (alongside pipeline/)
        4. Current working directory
        5. User config directories (~/.config/yt-dlp/cookies.txt, ~/cookies.txt)
        """
        candidates = []
        if self.cookie_file:
            candidates.append(self.cookie_file)

        env_cookie = os.environ.get("AUDIZAP_COOKIES") or os.environ.get("YTDLP_COOKIES")
        if env_cookie:
            candidates.append(env_cookie)

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates.append(os.path.join(project_root, "cookies.txt"))
        candidates.append(os.path.join(os.getcwd(), "cookies.txt"))
        candidates.append(os.path.expanduser("~/.config/yt-dlp/cookies.txt"))
        candidates.append(os.path.expanduser("~/cookies.txt"))

        for path in candidates:
            if path and os.path.isfile(path) and os.path.getsize(path) > 0:
                return os.path.abspath(path)

        return None

    def _clean_query(self, query: str) -> str:
        # If query has multiple artists e.g. "Artist1, Artist2, Artist3 - Title", simplify to "Artist1 - Title"
        if " - " in query:
            artist_part, title_part = query.split(" - ", 1)
            primary_artist = artist_part.split(",")[0].split("&")[0].split("feat.")[0].strip()
            # Clean brackets from title if present
            clean_title = re.sub(r"\(feat\.[^\)]+\)", "", title_part, flags=re.IGNORECASE).strip()
            return f"{primary_artist} {clean_title}"
        return query

    def _parse_artist_and_title(self, query: str) -> Tuple[str, str]:
        if " - " in query:
            parts = query.split(" - ", 1)
            return parts[0].strip(), parts[1].strip()
        return "", query.strip()

    def _score_candidate(
        self,
        target_title: str,
        target_artist: str,
        target_duration: Optional[int],
        cand_title: str,
        cand_channel: str,
        cand_duration: Optional[int]
    ) -> float:
        score = 50.0
        c_title_lower = cand_title.lower()
        t_title_lower = target_title.lower()
        c_channel_lower = cand_channel.lower()

        # 1. Negative live keywords (unless explicitly requested in song title)
        is_live_requested = any(k in t_title_lower for k in ["live", "concert", "现场", "現場"])
        if not is_live_requested:
            for kw in FORBIDDEN_LIVE_WORDS:
                if kw in c_title_lower or kw in c_channel_lower:
                    score -= 100.0
                    break

        # 2. Derivative penalties (cover, remix, etc. unless requested)
        for kw in FORBIDDEN_DERIVATIVE_WORDS:
            if (kw in c_title_lower or kw in c_channel_lower) and kw not in t_title_lower:
                score -= 60.0
                break

        # 3. Positive official signals
        if cand_channel.endswith("- Topic"):
            score += 60.0
        if any(k in c_title_lower for k in ["(official audio)", "[official audio]", "official audio"]):
            score += 50.0
        elif any(k in c_title_lower for k in ["official music video", "official video"]):
            score += 30.0
        elif any(k in c_title_lower for k in ["lyric video", "lyrics"]):
            score += 25.0

        # 4. Title similarity
        clean_t = re.sub(r"[^a-z0-9\u4e00-\u9fff\s]", " ", t_title_lower).strip()
        clean_c = re.sub(r"[^a-z0-9\u4e00-\u9fff\s]", " ", c_title_lower).strip()
        if clean_t and (clean_t in clean_c or clean_c in clean_t):
            score += 30.0

        # 5. Duration match
        if target_duration and cand_duration:
            diff = abs(cand_duration - target_duration)
            if diff <= 3:
                score += 40.0
            elif diff <= 10:
                score += 20.0
            elif diff <= 25:
                score += 5.0
            elif diff > 35:
                score -= 80.0

        return score

    def _search_ytmusic_candidates(self, query: str, target_title: str, target_duration: Optional[int]) -> List[Tuple[float, str, str]]:
        """
        Queries YouTube Music API for official studio master releases.
        Returns list of (score, video_id, title).
        """
        if not self.ytmusic:
            return []
        candidates = []
        try:
            results = self.ytmusic.search(query, filter="songs")
            is_live_requested = any(k in target_title.lower() for k in ["live", "concert", "现场", "現場"])
            for r in results[:5]:
                vid = r.get("videoId")
                if not vid:
                    continue
                title = r.get("title", "")
                dur_str = r.get("duration")
                dur_sec = None
                if dur_str and ":" in dur_str:
                    parts = dur_str.split(":")
                    if len(parts) == 2:
                        dur_sec = int(parts[0]) * 60 + int(parts[1])
                    elif len(parts) == 3:
                        dur_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])

                # Check for live title
                t_lower = title.lower()
                if not is_live_requested and any(kw in t_lower for kw in FORBIDDEN_LIVE_WORDS):
                    continue

                # Base score for official studio track from YTMusic
                score = 120.0
                if target_duration and dur_sec:
                    diff = abs(dur_sec - target_duration)
                    if diff <= 5:
                        score += 30.0
                    elif diff > 30:
                        score -= 50.0

                candidates.append((score, vid, title))
        except Exception as e:
            logger.debug(f"YTMusic search error for '{query}': {e}")
        return candidates

    def _search_youtube_candidates(self, search_query: str, target_title: str, target_artist: str, target_duration: Optional[int]) -> List[Tuple[float, str, str]]:
        """
        Retrieves top 5 YouTube search results via flat-playlist and scores them.
        Filters out live versions, concerts, and covers.
        """
        cmd = [
            self.python_exe,
            "-m", "yt_dlp",
            f"ytsearch5:{search_query}",
            "--flat-playlist",
            "--print", "%(id)s\t%(title)s\t%(duration)s\t%(channel)s",
            "--no-warnings"
        ]
        cookie_path = self.get_cookie_file()
        if cookie_path:
            cmd.extend(["--cookies", cookie_path])

        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _ = p.communicate()
        raw_text = out.decode("utf-8", errors="replace").strip()
        if not raw_text:
            return []

        candidates = []
        for line in raw_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                vid = parts[0].strip()
                title = parts[1].strip()
                dur = None
                if len(parts) >= 3 and parts[2].strip().isdigit():
                    dur = int(parts[2].strip())
                chan = parts[3].strip() if len(parts) >= 4 else ""

                score = self._score_candidate(target_title, target_artist, target_duration, title, chan, dur)
                # Only keep non-disqualified candidates
                if score > 0:
                    candidates.append((score, vid, title))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates

    def download_stream(self, query: str, output_template: str, duration_sec: Optional[int] = None, tolerance: int = 25) -> Tuple[bool, str]:
        """
        Attempts multi-tier audio downloads prioritizing authentic studio masters and filtering out live versions.
        """
        simplified = self._clean_query(query)
        target_artist, target_title = self._parse_artist_and_title(query)
        if not target_title:
            target_title = simplified

        # Tier 1: YouTube Music API (Official studio masters)
        ytm_candidates = self._search_ytmusic_candidates(simplified, target_title, duration_sec)
        for score, vid, title in ytm_candidates:
            url = f"https://www.youtube.com/watch?v={vid}"
            if self._run_ytdlp(url, output_template):
                return True, "YouTube Music (Official Studio)"

        # Tier 2: Scored YouTube Search (Live & Concert Penalty Filter)
        yt_candidates = self._search_youtube_candidates(f"{simplified} audio", target_title, target_artist, duration_sec)
        if not yt_candidates:
            yt_candidates = self._search_youtube_candidates(simplified, target_title, target_artist, duration_sec)

        for score, vid, title in yt_candidates:
            url = f"https://www.youtube.com/watch?v={vid}"
            if self._run_ytdlp(url, output_template):
                return True, "YouTube (Studio Scored)"

        # Tier 3: SoundCloud Search
        if self._run_ytdlp(f"scsearch1:{simplified}", output_template):
            return True, "SoundCloud"

        # Tier 4: Broad YouTube Search with original query
        if query != simplified:
            if self._run_ytdlp(f"ytsearch1:{query}", output_template):
                return True, "YouTube Broad"

        return False, "Failed"

    def _run_ytdlp(self, target_url: str, output_template: str) -> bool:
        cmd = [
            self.python_exe,
            "-m", "yt_dlp",
            target_url,
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", output_template,
            "--no-playlist",
            "--retries", "3",
            "--fragment-retries", "3",
            "--no-warnings",
            "--quiet"
        ]

        cookie_path = self.get_cookie_file()
        if cookie_path:
            cmd.extend(["--cookies", cookie_path])

        res = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
        return res.returncode == 0
