"""
Pipeline configuration and defaults.
Fully customizable via CLI flags or config overrides.
"""
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class PipelineConfig:
    output_dir: str = "."
    bitrate: str = "128k"              # e.g., "128k", "192k", "320k"
    sample_rate: int = 44100
    workers: int = 4                   # Number of parallel worker threads
    embed_lyrics: bool = True          # Real-time per-song lyrics retrieval
    embed_artwork: bool = True         # Square official catalog artwork
    artwork_size: int = 1000           # 1000x1000 high-res
    duration_tolerance: int = 20       # Max deviation in seconds
    audio_providers: List[str] = field(default_factory=lambda: ["youtube-music", "soundcloud", "youtube"])
    clean_filenames: bool = True
    overwrite_existing: bool = False
