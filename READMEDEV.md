# Developer Documentation: Architecture & Internals (`READMEDEV.md`)

This document details the internal architecture, lifecycle flow, module breakdown, and extension points for developers contributing to or adapting **AudiZap**.

---

## 🏗️ Architecture & Per-Song Concurrency Model

Rather than executing stage-by-stage across the entire batch (which causes slow serialization and prevents real-time per-song enrichment), AudiZap delegates complete end-to-end responsibility to individual worker threads:

```
           [Input: Spotify URL / Text Export / Query]
                              │
                     [pipeline/manifest.py]
         (Paginated spotapi Extraction + Embed Fallback)
                               │
                      [Job Work Queue]
                              │
           ┌───────────────────┼───────────────────┐
           ▼                   ▼                   ▼
     Worker Thread 1     Worker Thread 2     Worker Thread N
           │                   │                   │
    ┌──────┴───────────────────┴───────────────────┴──────┐
    │ 1. Canonical Metadata & Square Artwork Resolution   │ (Apple Music / iTunes / Spotify CDN)
    │ 2. Deduplication Check (Instant Skip if exists)     │ (os.path.exists check)
    │ 3. Isolated Temp Directory Allocation                │ (tempfile.mkdtemp)
    │ 4. Smart Multi-Tier Audio Cascade                    │ (Clean Artist Query: YT -> SC -> Generic)
    │ 5. Deterministic CBR Transcoding                     │ (FFmpeg libmp3lame 128k/320k)
    │ 6. Move from Temp to Output Path                     │
    │ 7. Real-Time Lyrics Search                           │ (syncedlyrics: Musixmatch / NetEase / LRCLIB)
    │ 8. Atomic ID3 Injection                              │ (ID3v2.3: APIC + TIT2 + TCON + SYLT + USLT)
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
│   ├── manifest.py            # Uncapped paginated Spotify & text manifest parser
│   ├── metadata.py            # Canonical catalog resolver (Apple Music/iTunes API)
│   ├── audio.py               # AudioResolver, cascaded multi-tier audio search
│   ├── transcoder.py          # Transcoder, FFmpeg CBR normalization
│   ├── tagger.py              # Tagger, mutagen ID3v2.3, APIC, SYLT & USLT
│   └── engine.py              # PipelineEngine, ThreadPoolExecutor orchestrator
├── README.md                  # User-facing manual & benchmark summary
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
- `duration_tolerance`: Allowed deviation in seconds.
- `embed_lyrics`: Boolean toggle for lyrics enrichment.
- `embed_artwork`: Boolean toggle for square cover art.
- `overwrite_existing`: Boolean flag to force re-download of existing tracks.

### 3. `pipeline/manifest.py` (`ManifestParser`)
- **Uncapped Pagination**: Uses `spotapi.PublicPlaylist` and `spotapi.PublicAlbum` pagination generators to retrieve complete tracklists of any size (e.g. 116, 500, 1,000+ songs) without requiring Spotify API developer credentials.
- **Fail-Safe Fallback**: Automatically falls back to Spotify Embed API (`__NEXT_DATA__`) with strict 8-second timeout guards if pagination encounters network limits or for single track links.
- **Plaintext Support**: Parses `.txt` tracklists formatted as `Artist - Title` or single queries seamlessly.

### 4. `pipeline/metadata.py` (`MetadataResolver`)
- Queries `https://itunes.apple.com/search`.
- **Zero API Key Requirement**: Requires no OAuth tokens, developer registrations, or secret keys.
- **Modern User-Agent**: Configured with a modern desktop browser user-agent to prevent CDN `403 Forbidden` firewall blocks.
- **Canonical Decoupling**: Extracts `trackName`, `artistName`, `collectionName`, `trackNumber`, `trackCount`, `discNumber`, and `primaryGenreName`.
- **Artwork CDN Resizing**: Converts standard `100x100bb.jpg` thumbnail links to high-res `1000x1000bb.jpg` square uncompressed images.

### 5. `pipeline/audio.py` (`AudioResolver`)
Implements an ordered, resilient cascade:
- **Query Sanitization**: Automatically strips excessive featured artists and brackets (e.g. `Artist1, Artist2 - Title (feat. X)` becomes `Artist1 Title`) to match search algorithms reliably.
- **Tier 1**: YouTube Search with clean query (`ytsearch1:{clean_query} audio`).
- **Tier 2**: Direct YouTube Search (`ytsearch1:{clean_query}`).
- **Tier 3**: SoundCloud Search (`scsearch1:{clean_query}`).
- **Tier 4**: Broad YouTube Search with original query.
- **Robust Python Invocation**: Uses `sys.executable -m yt_dlp` to ensure immunity to virtual environment relocations.

### 6. `pipeline/transcoder.py` (`Transcoder`)
- Invokes `ffmpeg -c:a libmp3lame -b:a {bitrate} -ar {sample_rate}`.
- Enforces uniform Constant Bitrate (CBR) audio regardless of whether the source stream was Opus 251, AAC 140, or MP3.

### 7. `pipeline/tagger.py` (`Tagger`)
- **Sanitization**: Calls `id3.delete()` when performing initial tagging to completely wipe dirty source platform tags (channel names, video titles with `(MV)`, `Gaming` genres).
- **ID3v2.3 Specification**: Uses `v2_version=3` for universal compatibility across Windows Explorer, macOS, iOS, Android, and car audio systems.
- **Dual Lyrics Engine**:
  - `SYLT`: Binary ID3 synchronized lyrics tag in milliseconds (`format=2, type=1`).
  - `USLT`: Text lyrics frame populated with LRC timestamps `[mm:ss.xx]`.
- **In-Place Inspection & Enrichment**:
  - `inspect_file(filepath)`: Inspects existing ID3 headers for `APIC` (cover art with valid payload) and `SYLT`/`USLT` (lyrics frames) without loading full audio files.
  - `enrich_file(filepath, meta)`: Injects missing cover art and synchronized lyrics directly into existing files on disk without touching or re-encoding audio.

### 8. `pipeline/engine.py` (`PipelineEngine`)
- Manages `concurrent.futures.ThreadPoolExecutor`.
- Provides **Thread-Safe Temp Isolation**: Every worker creates its own isolated directory via `tempfile.mkdtemp(prefix="audio_stream_")`.
- **Smart Deduplication & In-Place Enrichment**: Detects existing files in the download folder. If `enrich_existing=True`, audits the file: if art or lyrics are missing, it enriches them in-place; if already complete, it skips instantly.
- **Local Folder Auditor**: `enrich_local_folder(folder_path)` discovers and audits all existing `.mp3` files in parallel across worker threads.


---

## 🔌 How to Extend

### Adding a New Audio Source (e.g. Bandcamp, Deezer, Archive.org)
In `pipeline/audio.py`, add your new tier to `download_stream()`:
```python
# New Tier: Bandcamp search
success = self._run_ytdlp(f"bcsearch1:{simplified}", output_template)
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
