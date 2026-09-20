"""
Acoustic Quality Control & Authenticity Engine.
Provides mathematical verification of audio tracks against official studio previews
via iTunes, Deezer, and Spotify with zero-cost fast-tracking for Topic channels.
"""
import os
import re
import sys
import json
import hashlib
import tempfile
import logging
import subprocess
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any, Tuple
import numpy as np
import scipy.signal

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
PREVIEWS_DIR = os.path.join(CACHE_DIR, "previews")
os.makedirs(PREVIEWS_DIR, exist_ok=True)

def clean_text(text: str) -> str:
    """Normalize text for search matching."""
    text = re.sub(r"[\(\[\{].*?[\)\]\}]", "", text)  # remove brackets
    text = re.sub(r"[^\w\s\u4e00-\u9fff\u3040-\u30ff]", " ", text)  # keep words & CJK
    return " ".join(text.split()).strip().lower()

class PreviewService:
    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir or PREVIEWS_DIR
        os.makedirs(self.cache_dir, exist_ok=True)

    def search_itunes(self, title: str, artist: str) -> Optional[Dict[str, Any]]:
        """Query Apple Music / iTunes Search API for official 30s preview and 1000x1000 art."""
        clean_t = clean_text(title)
        primary_artist = re.split(r"[,&/]|feat\.?|ft\.?", artist, flags=re.IGNORECASE)[0].strip()
        clean_a = clean_text(primary_artist)

        query = f"{clean_t} {clean_a}".strip()
        if not query:
            return None

        url = f"https://itunes.apple.com/search?term={urllib.parse.quote(query)}&entity=song&limit=5"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("results", [])
                for item in results:
                    preview_url = item.get("previewUrl")
                    if preview_url:
                        # Construct 1000x1000 square artwork URL
                        art_100 = item.get("artworkUrl100", "")
                        art_1000 = re.sub(r"\d+x\d+bb", "1000x1000bb", art_100) if art_100 else None
                        return {
                            "source": "itunes",
                            "preview_url": preview_url,
                            "artwork_url": art_1000,
                            "title": item.get("trackName", title),
                            "artist": item.get("artistName", artist),
                            "album": item.get("collectionName", ""),
                            "duration_ms": item.get("trackTimeMillis", 0),
                            "isrc": item.get("isrc", "")
                        }
        except Exception as e:
            logger.debug(f"iTunes preview search failed for {artist} - {title}: {e}")
        return None

    def search_deezer(self, title: str, artist: str) -> Optional[Dict[str, Any]]:
        """Query Deezer open unauthenticated REST API for 30s MP3 preview and album art."""
        clean_t = clean_text(title)
        primary_artist = re.split(r"[,&/]|feat\.?|ft\.?", artist, flags=re.IGNORECASE)[0].strip()
        clean_a = clean_text(primary_artist)

        query = f'track:"{clean_t}" artist:"{clean_a}"'
        url = f"https://api.deezer.com/search?q={urllib.parse.quote(query)}&limit=5"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("data", [])
                if not results:
                    # Broad fallback search
                    broad_url = f"https://api.deezer.com/search?q={urllib.parse.quote(f'{clean_t} {clean_a}')}&limit=5"
                    broad_req = urllib.request.Request(broad_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(broad_req, timeout=10) as b_resp:
                        data = json.loads(b_resp.read().decode("utf-8"))
                        results = data.get("data", [])

                for item in results:
                    preview_url = item.get("preview")
                    if preview_url:
                        album_data = item.get("album", {})
                        art_1000 = album_data.get("cover_xl") or album_data.get("cover_big")
                        return {
                            "source": "deezer",
                            "preview_url": preview_url,
                            "artwork_url": art_1000,
                            "title": item.get("title", title),
                            "artist": item.get("artist", {}).get("name", artist),
                            "album": album_data.get("title", ""),
                            "duration_ms": item.get("duration", 0) * 1000,
                            "isrc": ""
                        }
        except Exception as e:
            logger.debug(f"Deezer preview search failed for {artist} - {title}: {e}")
        return None

    def get_preview_audio(self, title: str, artist: str, spotify_preview_url: Optional[str] = None) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Retrieves official preview info and downloads the 30s preview file to cache.
        Returns: (local_preview_filepath, metadata_dict) or None
        """
        # Tier 1: iTunes
        info = self.search_itunes(title, artist)
        # Tier 2: Deezer
        if not info:
            info = self.search_deezer(title, artist)
        # Tier 3: Spotify preview URL
        if not info and spotify_preview_url:
            info = {
                "source": "spotify",
                "preview_url": spotify_preview_url,
                "artwork_url": None,
                "title": title,
                "artist": artist,
                "album": "",
                "duration_ms": 0,
                "isrc": ""
            }

        if not info or not info.get("preview_url"):
            return None

        # Download preview audio to local cache
        preview_url = info["preview_url"]
        url_hash = hashlib.md5(f"{artist}_{title}_{preview_url}".encode("utf-8")).hexdigest()
        ext = ".m4a" if "m4a" in preview_url or info["source"] == "itunes" else ".mp3"
        cached_file = os.path.join(self.cache_dir, f"{url_hash}{ext}")

        if not os.path.exists(cached_file) or os.path.getsize(cached_file) < 1000:
            try:
                req = urllib.request.Request(preview_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    with open(cached_file, "wb") as out_f:
                        out_f.write(resp.read())
            except Exception as e:
                logger.debug(f"Failed to download preview audio from {preview_url}: {e}")
                return None

        return cached_file, info


class AcousticQC:
    def __init__(self, sample_rate: int = 4000, env_rate: int = 100):
        self.sample_rate = sample_rate
        self.env_rate = env_rate
        self.decimation_factor = sample_rate // env_rate
        self.preview_service = PreviewService()

    def _extract_envelope(self, audio_path: str, max_duration_s: Optional[float] = None) -> Optional[np.ndarray]:
        """
        Extract 100Hz audio energy envelope using FFmpeg.
        Reads 16-bit mono PCM at sample_rate, takes absolute value, applies low-pass smoothing, and decimates.
        """
        if not os.path.exists(audio_path):
            return None

        cmd = ["ffmpeg", "-v", "error", "-i", audio_path]
        if max_duration_s:
            cmd.extend(["-t", str(max_duration_s)])
        cmd.extend([
            "-ac", "1",
            "-ar", str(self.sample_rate),
            "-f", "s16le",
            "pipe:1"
        ])

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            raw_bytes, _ = proc.communicate()
            if proc.returncode != 0 or not raw_bytes:
                return None

            samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32)
            if len(samples) < self.sample_rate * 2:
                return None

            abs_signal = np.abs(samples)
            box = np.ones(self.decimation_factor, dtype=np.float32) / self.decimation_factor
            smoothed = np.convolve(abs_signal, box, mode="same")
            envelope = smoothed[::self.decimation_factor]
            return envelope
        except Exception as e:
            logger.debug(f"Envelope extraction error for {audio_path}: {e}")
            return None

    def compare_audio(self, candidate_path: str, preview_path: str) -> Dict[str, Any]:
        """
        Cross-correlate candidate audio against 30s studio preview.
        Returns: score, verdict, time_offset_seconds, confidence
        """
        preview_env = self._extract_envelope(preview_path)
        if preview_env is None or len(preview_env) < self.env_rate * 5:
            return {
                "score": 0.0,
                "verdict": "ERROR",
                "time_offset_seconds": 0.0,
                "confidence": 0.0,
                "message": "Failed to extract preview audio envelope"
            }

        candidate_env = self._extract_envelope(candidate_path)
        if candidate_env is None or len(candidate_env) < len(preview_env):
            return {
                "score": 0.0,
                "verdict": "ERROR",
                "time_offset_seconds": 0.0,
                "confidence": 0.0,
                "message": "Failed to extract candidate audio envelope or file too short"
            }

        p_mean = np.mean(preview_env)
        p_std = np.std(preview_env)
        if p_std < 1e-6:
            return {
                "score": 0.0,
                "verdict": "ERROR",
                "time_offset_seconds": 0.0,
                "confidence": 0.0,
                "message": "Preview envelope has near-zero variance"
            }

        preview_norm = (preview_env - p_mean) / p_std
        p_len = len(preview_norm)

        # Cross-correlation via FFT
        corr = scipy.signal.correlate(candidate_env, preview_norm, mode="valid")

        # Sliding window energy of candidate
        cand_sq = candidate_env ** 2
        window = np.ones(p_len, dtype=np.float32)
        cand_energy = np.convolve(cand_sq, window, mode="valid")

        cand_sum = np.convolve(candidate_env, window, mode="valid")
        cand_var = cand_energy - (cand_sum ** 2) / p_len
        cand_var = np.maximum(cand_var, 1e-6)
        cand_std = np.sqrt(cand_var)

        norm_corr = corr / (cand_std * np.sqrt(p_len))
        norm_corr = np.nan_to_num(norm_corr, nan=-1.0, posinf=-1.0, neginf=-1.0)

        max_idx = int(np.argmax(norm_corr))
        max_score = float(norm_corr[max_idx])
        time_offset_s = max_idx / float(self.env_rate)

        # Classify verdict
        if max_score >= 0.60:
            verdict = "STUDIO_MASTER"
        elif max_score < 0.40:
            verdict = "LIVE_OR_DIFFERENT"
        else:
            verdict = "AMBIGUOUS"

        confidence = max(0.0, min(1.0, (max_score - 0.35) / 0.55))

        return {
            "score": round(max_score, 4),
            "verdict": verdict,
            "time_offset_seconds": round(time_offset_s, 2),
            "confidence": round(confidence, 3),
            "passed": max_score >= 0.60
        }

    def is_fast_track_eligible(
        self,
        candidate_channel: str,
        candidate_duration: Optional[int],
        expected_duration: Optional[int],
        tolerance: int = 2
    ) -> bool:
        """
        Determines whether a candidate can be fast-tracked without downloading and correlating preview.
        Eligible when sourced from an official Topic channel AND duration matches within tolerance.
        """
        if not candidate_channel or not candidate_channel.endswith("- Topic"):
            return False

        if candidate_duration and expected_duration:
            if abs(candidate_duration - expected_duration) <= tolerance:
                return True
            return False

        return False

    def verify_candidate(
        self,
        candidate_path: str,
        title: str,
        artist: str,
        candidate_channel: str = "",
        candidate_duration: Optional[int] = None,
        expected_duration: Optional[int] = None,
        spotify_preview_url: Optional[str] = None,
        strict: bool = False
    ) -> Dict[str, Any]:
        """
        End-to-end QC verification for a candidate audio file:
        1. Fast-track check (Topic channel + matching duration) if strict=False.
        2. Multi-tier preview retrieval (iTunes -> Deezer -> Spotify).
        3. Cross-correlation against official studio cut.
        4. Fallback to duration consensus if no preview is available anywhere.
        """
        # 1. Fast-track check
        if not strict and self.is_fast_track_eligible(candidate_channel, candidate_duration, expected_duration):
            return {
                "passed": True,
                "score": 1.0,
                "verdict": "FAST_TRACK_TOPIC",
                "method": "fast_track_topic",
                "time_offset_seconds": 0.0,
                "confidence": 1.0,
                "message": f"Fast-tracked from official Topic channel '{candidate_channel}' with matching duration"
            }

        # 2. Retrieve preview
        preview_res = self.preview_service.get_preview_audio(title, artist, spotify_preview_url)
        if preview_res:
            preview_file, info = preview_res
            result = self.compare_audio(candidate_path, preview_file)
            result["method"] = f"acoustic_{info['source']}"
            result["preview_source"] = info["source"]
            result["artwork_url"] = info.get("artwork_url")
            return result

        # 3. Fallback: Duration Consensus when no preview exists anywhere
        if candidate_duration and expected_duration:
            diff = abs(candidate_duration - expected_duration)
            if diff <= 3:
                return {
                    "passed": True,
                    "score": round(max(0.7, 1.0 - (diff * 0.1)), 2),
                    "verdict": "DURATION_CONSENSUS",
                    "method": "duration_consensus",
                    "time_offset_seconds": 0.0,
                    "confidence": 0.75,
                    "message": f"Verified via duration consensus (diff: {diff}s, no online preview found)"
                }
            elif diff > 10:
                return {
                    "passed": False,
                    "score": 0.2,
                    "verdict": "ANOMALOUS_DURATION",
                    "method": "duration_consensus",
                    "time_offset_seconds": 0.0,
                    "confidence": 0.9,
                    "message": f"Rejected due to duration mismatch (expected: {expected_duration}s, got: {candidate_duration}s)"
                }

        # Unknown / Ambiguous
        return {
            "passed": True,
            "score": 0.5,
            "verdict": "UNVERIFIED_PASSTHROUGH",
            "method": "passthrough",
            "time_offset_seconds": 0.0,
            "confidence": 0.5,
            "message": "Passed without acoustic verification (no reference preview or duration available)"
        }
