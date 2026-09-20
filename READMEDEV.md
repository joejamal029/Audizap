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
    │ 1. Canonical Metadata & Square Artwork Resolution   │ (iTunes -> Deezer Fallback -> Spotify Source)
    │ 2. Deduplication & In-Place Enrichment Audit        │ (Instant Skip if complete, or enrich in-place)
    │ 3. Isolated Temp Directory Allocation                │ (tempfile.mkdtemp)
    │ 4. Authenticated Studio Audio Cascade               │ (YTM Studio -> Scored Anti-Live YT -> SoundCloud)
    │ 5. Deterministic CBR Transcoding                     │ (FFmpeg libmp3lame 128k/320k)
    │ 6. Move from Temp to Output Path                     │
    │ 7. Real-Time Concurrent Lyrics Search                │ (syncedlyrics: Musixmatch / NetEase / LRCLIB)
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
├── gui.py                     # CustomTkinter modern dark UI application with live auth badge
├── setup.py                   # Packaging & console script entry points (audizap, audizap-gui)
├── requirements.txt           # Project dependencies
├── Run_GUI.bat                # Windows quick launcher batch file
├── cookies.txt                # Optional Netscape session cookies (strictly gitignored)
├── pipeline/
│   ├── __init__.py            # Package initializer
│   ├── config.py              # PipelineConfig dataclass
│   ├── manifest.py            # Uncapped paginated Spotify & text manifest parser
│   ├── metadata.py            # Multi-source catalog resolver (iTunes + Deezer + Spotify)
│   ├── audio.py               # AudioResolver, studio candidate scoring, cookies & cascade
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
- `bitrate`: Default `128k` (or `192k`, `320k`).
- `sample_rate`: `44100` Hz standard.
- `workers`: Default `4` concurrent threads.
- `duration_tolerance`: Allowed deviation in seconds (default: `20`s).
- `embed_lyrics`: Boolean toggle for lyrics enrichment.
- `embed_artwork`: Boolean toggle for square cover art.
- `overwrite_existing`: Boolean flag to force re-download of existing tracks.
- `enrich_existing`: Boolean flag to audit and enrich existing files on disk in-place.
- `cookie_file`: Optional path to Netscape-format `cookies.txt` file (auto-detected if None).

### 3. `pipeline/manifest.py` (`ManifestParser`)
- **Uncapped Pagination**: Uses `spotapi.PublicPlaylist` and `spotapi.PublicAlbum` pagination generators to retrieve complete tracklists of any size (e.g. 116, 500, 1,000+ songs) without requiring Spotify API developer credentials.
- **Fail-Safe Fallback**: Automatically falls back to Spotify Embed API (`__NEXT_DATA__`) with strict 8-second timeout guards if pagination encounters network limits or for single track links.
- **Plaintext Support**: Parses `.txt` tracklists formatted as `Artist - Title` or single queries seamlessly.

### 4. `pipeline/metadata.py` (`MetadataResolver`)
Multi-source canonical metadata resolver with strict anti-mismatch filtering:
- **Candidate Verification Filter (`_is_valid_candidate`)**: Evaluates string similarity ($\ge 0.60$) and token overlap between the requested song and returned candidates, instantly rejecting unrelated popular tracks.
- **Multi-Candidate iTunes Search (`limit=5`)**: Inspects candidates sequentially and selects the first verified authentic track.
- **Deezer API Fallback (`_search_deezer`)**: If iTunes lacks coverage (common in regional, Afrobeats, and indie releases), queries Deezer's public search API (< 200ms) for official metadata and uncompressed **1000×1000 square artwork**.
- **Source Metadata Preservation**: Retains Spotify manifest title, artist, album, and artwork if external catalog searches yield no valid match.

### 5. `pipeline/audio.py` (`AudioResolver`)
Implements an authenticated, scored multi-tier audio cascade with anti-live defense:
- **Cookie Discovery (`get_cookie_file`)**: Hierarchically discovers Netscape session cookies from explicit config $\rightarrow$ environment variables (`AUDIZAP_COOKIES`, `YTDLP_COOKIES`) $\rightarrow$ project root `cookies.txt` $\rightarrow$ working directory $\rightarrow$ user config directories. Automatically injects `--cookies` into both searches and downloads.
- **Tier 1 (YouTube Music API)**: Uses `ytmusicapi.search(filter="songs")` to target official studio label releases directly, filtering out fan concert uploads and live recordings.
- **Tier 2 (Scored Multi-Candidate Search `ytsearch5`)**:
  - **Negative Live Penalty (-100 pts)**: Disqualifies `"live"`, `"concert"`, `"livehouse"`, `"performance"`, `"现场"`, `"acoustic session"` (unless explicitly requested in track title).
  - **Derivative Penalty (-60 pts)**: Penalizes `"cover"`, `"remix"`, `"tribute"`, `"karaoke"`, `"slowed"`, `"reverb"`.
  - **Studio Audio Prioritization Over Music Videos**:
    - **Topic Channels (`"- Topic"`)**: +60 pts (Official record label unedited album audio).
    - **Official Audio (`"(Official Audio)"`)**: +50 pts (Pure album master without visual artifacts).
    - **Lyric Videos (`"Lyric Video"`, `"Lyrics"`)**: +35 pts (Exact album audio synced to lyrics; avoids movie scenes or dialogue).
    - **Music Videos (`"Official Music Video"`, `"MV"`)**: Minimal +5 pts only if duration matches studio catalog ($\le 4$s); **-30 pts penalty** if duration drifts ($> 4$s) to filter out extended intro skits, cinematic sound effects, or movie dialogues.
  - **Duration Gating**: Rewards $\le 3$s catalog duration matching (+40 pts) and severely penalizes length drift $> 35$s (-80 pts).
- **Tier 3 (SoundCloud Search `scsearch1`)**: Resilient secondary streaming fallback.
- **Tier 4 (Broad Search)**: Fallback using the original query.
- **Windows UTF-8 Encoding**: Subprocesses run with `encoding="utf-8", errors="replace"` to prevent `cp1252` encoding crashes on Asian and non-Latin characters.

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
- **Manifest Duration Gating**: Passes canonical track duration from resolved metadata to `AudioResolver` so even plain `.txt` file imports benefit from strict duration gating.
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
