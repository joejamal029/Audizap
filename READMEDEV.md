# Developer Documentation: Architecture & Internals (`READMEDEV.md`)

This document details the internal architecture, lifecycle flow, module breakdown, and extension points for developers contributing to or adapting **AudiZap**.

---

## 🏗️ Architecture & Per-Song Concurrency Model

Rather than executing stage-by-stage across the entire batch (which causes slow serialization and prevents real-time per-song enrichment), AudiZap delegates complete end-to-end responsibility to individual worker threads:

```
           [Input: Spotify URL / Text Export / Query]
                              │
                    [pipeline/manifest.py]
                              │
                     [Job Work Queue]
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
    Worker Thread 1     Worker Thread 2     Worker Thread N
          │                   │                   │
   ┌──────┴───────────────────┴───────────────────┴──────┐
   │ 1. Canonical Metadata & Square Artwork Resolution   │ (Apple Music / iTunes / Spotify CDN)
   │ 2. Isolated Temp Directory Allocation                │ (tempfile.mkdtemp)
   │ 3. Multi-Tier Audio Stream Retrieval                 │ (YT Music -> SoundCloud -> yt-dlp + Deno)
   │ 4. Deterministic CBR Transcoding                     │ (FFmpeg libmp3lame 128k/320k)
   │ 5. Move from Temp to Output Path                     │
   │ 6. Real-Time Lyrics Search                           │ (syncedlyrics: Musixmatch / NetEase / LRCLIB)
   │ 7. Atomic ID3 Injection                              │ (ID3v2.3: APIC + TIT2 + TCON + SYLT + USLT)
   └─────────────────────────────────────────────────────┘
                              │
                     [Output Directory]
```

---

## 📂 Project Structure & Module Breakdown

```
Audizap/
├── cli.py                     # CLI entry point, argument parsing, rich progress UI
├── gui.py                     # CustomTkinter modern dark UI application
├── setup.py                   # Packaging & console script entry points (audizap, audizap-gui)
├── requirements.txt           # Project dependencies
├── Run_GUI.bat                # Windows quick launcher batch file
├── pipeline/
│   ├── __init__.py            # Package initializer
│   ├── config.py              # PipelineConfig dataclass
│   ├── manifest.py            # Parses URLs, text files, and generates queue
│   ├── metadata.py            # Catalog resolver, Apple Music / iTunes API
│   ├── audio.py               # AudioResolver, multi-tier fallback cascade
│   ├── transcoder.py          # Transcoder, FFmpeg CBR normalization
│   ├── tagger.py              # Tagger, mutagen ID3v2.3, APIC, SYLT & USLT
│   └── engine.py              # PipelineEngine, ThreadPoolExecutor orchestrator
├── README.md                  # User-facing manual & usage guide
└── READMEDEV.md               # Developer documentation & extension guide
```

---

## ⚙️ Module Responsibilities

### 1. `setup.py`
Defines the distribution package and registers console script entry points:
- `audizap` $\rightarrow$ `cli:main`
- `audizap-gui` $\rightarrow$ `gui:main`

To install locally in editable development mode:
```bash
pip install -e .
```

### 2. `pipeline/config.py`
Defines `PipelineConfig` containing all mutable configuration parameters:
- `output_dir`: Target directory.
- `bitrate`: Default `128k` (or `320k`).
- `sample_rate`: `44100` Hz standard.
- `workers`: Default `4` concurrent threads.
- `duration_tolerance`: Allowed deviation in seconds (default `25`s).
- `embed_lyrics`: Boolean toggle for lyrics enrichment.
- `embed_artwork`: Boolean toggle for square cover art.

### 3. `pipeline/metadata.py` (`MetadataResolver`)
- Queries `https://itunes.apple.com/search`.
- **Zero API Key Requirement**: Requires no OAuth tokens, developer registrations, or secret keys.
- **Canonical Decoupling**: Extracts `trackName`, `artistName`, `collectionName`, `trackNumber`, `trackCount`, `discNumber`, and `primaryGenreName`.
- **Artwork CDN Resizing**: Converts standard `100x100bb.jpg` thumbnail links to high-res `1000x1000bb.jpg` square uncompressed images.

### 4. `pipeline/audio.py` (`AudioResolver`)
Implements an ordered, resilient cascade:
- **Tier 1**: YouTube Direct Audio Query (`ytsearch1:{query} audio`).
- **Tier 2**: SoundCloud Search (`scsearch1:{query}`).
- **Tier 3**: Generic Fallback (`ytsearch1:{query}`).
- **Duration Gating**: Filters out streams where duration deviates by more than `±tolerance` seconds.
- **Deno Integration**: Leverages `~/.spotdl/deno.exe` to decode modern YouTube bot-challenges (visionOS, player cipher tokens).

### 5. `pipeline/transcoder.py` (`Transcoder`)
- Invokes `ffmpeg -c:a libmp3lame -b:a {bitrate} -ar {sample_rate}`.
- Enforces uniform Constant Bitrate (CBR) audio regardless of whether the source stream was Opus 251, AAC 140, or MP3.

### 6. `pipeline/tagger.py` (`Tagger`)
- **Sanitization**: Calls `id3.delete()` to completely wipe dirty source platform tags (channel names, video titles with `(MV)`, `Gaming` genres).
- **ID3v2.3 Specification**: Uses `v2_version=3` for universal compatibility across Windows Explorer, macOS, iOS, Android, and car audio systems.
- **Dual Lyrics Engine**:
  - `SYLT`: Binary ID3 synchronized lyrics tag in milliseconds (`format=2, type=1`).
  - `USLT`: Text lyrics frame populated with LRC timestamps `[mm:ss.xx]`.

### 7. `pipeline/engine.py` (`PipelineEngine`)
- Manages `concurrent.futures.ThreadPoolExecutor`.
- Provides **Thread-Safe Temp Isolation**: Every worker creates its own isolated directory via `tempfile.mkdtemp(prefix="audio_stream_")`, preventing filename collisions when processing multiple songs by the same artist concurrently.

---

## 🔌 How to Extend

### Adding a New Audio Source (e.g. Bandcamp, Deezer, Archive.org)
In `pipeline/audio.py`, add your new tier to `download_stream()`:
```python
# New Tier: Bandcamp search
success = self._run_ytdlp(f"bcsearch1:{query}", output_template, duration_sec, tolerance)
if success:
    return True, "Bandcamp"
```

### Adding a Custom Lyrics Provider
In `pipeline/tagger.py`, extend `fetch_lyrics()` with additional providers or custom fallback endpoints:
```python
@classmethod
def fetch_lyrics(cls, query: str) -> Optional[str]:
    # 1. Primary: syncedlyrics (Musixmatch / NetEase / Megalobiz / LRCLIB)
    try:
        lyrics = syncedlyrics.search(query)
        if lyrics:
            return lyrics
    except Exception:
        pass

    # 2. Custom Fallback Provider
    # return custom_provider_fetch(query)
    return None
```

---

## 🧪 Testing & Verification

Run the test suite on sample tracks using the installed CLI:
```bash
audizap "Aimee Carty - Painter" --output ./test_run --bitrate 128k
```
Or test the GUI entry point:
```bash
audizap-gui
```
