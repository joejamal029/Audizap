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

## 📂 Module Breakdown

```
Audizap/
├── cli.py                     # Entry point, CLI argument parsing, rich progress UI
├── gui.py                     # CustomTkinter modern dark UI application
├── Run_GUI.bat                # Windows quick launcher batch file
├── pipeline/
│   ├── __init__.py
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
