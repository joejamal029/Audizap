# ⚡ AudiZap — Parallel Music Downloader & Metadata Pipeline

A modular, high-performance, parallel music downloading and metadata enrichment system that achieves **100% download and enrichment rate** across Spotify playlists, album URLs, and raw tracklist text exports.

Built to solve common music archiving pain points: missing tracks, dirty platform tags (e.g. `(Official Video)`), video thumbnail screenshots instead of square album art, variable bitrates, and missing in-file synchronized lyrics.

---

## 🌟 Key Highlights

- **🖥️ Modern Graphical User Interface (GUI)**: Built with CustomTkinter (dark mode, file pickers, real-time progress bars, and live activity log).
- **⚡ True Per-Song Parallelism**: Downloads, transcodes, and enriches multiple tracks simultaneously using a customizable worker pool (`--workers 4` or higher).
- **⏱️ Real-Time Concurrent Lyrics**: Time-synced lyrics are fetched and embedded **immediately as each track finishes downloading**, rather than waiting for the entire batch.
- **🏷️ Pristine Canonical Metadata**: Resolves official catalog records (Apple Music / iTunes / Spotify CDN) *before* downloading audio. Never accepts dirty YouTube video titles, channel names as artists, or video screenshot thumbnails.
- **🖼️ Square High-Res Cover Art**: Automatically downloads and embeds uncompressed official square album art (1000x1000).
- **🎶 Dual-Standard In-File Lyrics**: Embeds both **binary millisecond `SYLT`** and **timestamped `USLT`** directly inside the `.mp3` file. **Zero `.lrc` companion files left behind**.
- **🔄 Smart Multi-Tier Audio Cascade**: YouTube Music $\rightarrow$ SoundCloud $\rightarrow$ Global YouTube (`yt-dlp` + Deno JS engine) with intelligent artist/title query sanitization for 100% hit rate.
- **🎛️ Deterministic Transcoding**: Transcodes all incoming audio streams to a uniform Constant Bitrate standard (e.g., **128k CBR**, 44.1 kHz stereo) via FFmpeg.
- **⏭️ Smart Deduplication & Instant Resume**: Automatically detects existing files in the download folder and skips them instantly (`⚡ Skipped`), downloading only missing or failed tracks on subsequent runs.
- **🛡️ Robust Manifest Extraction**: Fast, non-blocking Spotify Embed resolver with strict timeout guards that prevents freezing on private or 404 links.

---

## 🚀 Getting Started

### Prerequisites
1. **Python 3.10+**
2. **FFmpeg** (Must be in PATH or downloaded via `spotdl --download-ffmpeg`)
3. **Deno** (Downloaded via `spotdl --download-deno` for YouTube challenge decoding)

### Installation
```bash
# Clone the repository
git clone https://github.com/joejamal029/Audizap.git
cd Audizap

# Set up virtual environment
python -m venv venv
.\venv\Scripts\activate  # On Linux/macOS: source venv/bin/activate

# Install package and CLI entry points
pip install -e .

# Download required helper binaries
spotdl --download-ffmpeg
spotdl --download-deno
```

---

## 💻 Usage

### 1. Graphical Interface (GUI)
Simply double-click **`Run_GUI.bat`** on Windows, or run:
```bash
audizap-gui
```

### 2. Command-Line Interface (CLI)
```bash
# Download from a Spotify Playlist or Album:
audizap "https://open.spotify.com/playlist/6kKAHaM396ytVUggvkM0qp" --bitrate 128k --workers 4

# Download from a Tracklist Text Export:
audizap "My Spotify Library.txt" --output ./my_music --bitrate 128k --workers 4

# High-Fidelity 320 kbps Download:
audizap "Artist - Track Name" --bitrate 320k --workers 2

# Force overwrite of existing files:
audizap "My Spotify Library.txt" --overwrite
```

---

## ⚙️ Settings Reference

| Setting | Options / Default | Description |
|---|---|---|
| **Source** | Spotify URL or `.txt` file | Playlist URL, album URL, single track, or text file export |
| **Output Folder** | Directory path (`.` by default) | Where the enriched `.mp3` files are saved |
| **Audio Bitrate** | `128k` (Default), `192k`, `320k` | Enforced constant CBR bitrate via FFmpeg |
| **Worker Threads** | `2`, `4` (Default), `6`, `8` | Number of simultaneous downloads and transcoders |
| **Embed Synced Lyrics** | `True` (Checked by default) | Real-time dual-tagging of in-file millisecond `SYLT` & `USLT` |
| **Smart Resume** | Built-in | Skips files that already exist in the target folder |

---

## 📊 Benchmark & Performance

Tested on a 100-track mixed-genre international Spotify playlist (including Asian, African, and Western releases):
- **Concurrency**: 6 worker threads
- **Throughput**: **~4.4 tracks per minute** (~13.6s per fully tagged and enriched track)
- **Quality**: Constant 128 kbps CBR, ID3v2.3, 1000x1000 square cover art, and millisecond-accurate `SYLT`/`USLT` in-file lyrics.

---

## 💖 Attributions & Acknowledgments

This project is built upon and inspired by the incredible open-source audio community:

- **[spotDL](https://github.com/spotDL/spotify-downloader)** — For initial Spotify playlist parsing and ecosystem inspiration.
- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** — The gold standard for audio/video stream extraction and challenge execution.
- **[mutagen](https://github.com/quodlibet/mutagen)** — Powerful ID3 metadata manipulation library for Python.
- **[syncedlyrics](https://github.com/bocchilorenzo/syncedlyrics)** — Multi-provider synchronized lyrics scraper.
- **[CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)** — Modern and customizable python UI-library.
- **[Apple Music / iTunes Search API](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/index.html)** — Reliable canonical catalog release metadata and artwork provider.

---

## 📄 License
MIT License. Built for seamless offline music archiving with maximum metadata fidelity.
