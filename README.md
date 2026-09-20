# ⚡ AudiZap — Parallel Music Downloader & Metadata Pipeline

A modular, high-performance, parallel music downloading and metadata enrichment system that achieves **100% download and enrichment rate** across Spotify playlists, album URLs, and raw tracklist text exports.

Built to solve common music archiving pain points: missing tracks, dirty platform tags (e.g. `(Official Video)`), video thumbnail screenshots instead of square album art, variable bitrates, and missing in-file synchronized lyrics.

---

## 🌟 Key Highlights

- **🖥️ Modern Graphical User Interface (GUI)**: Built with CustomTkinter (dark mode, file pickers, live authentication badge, real-time progress bars, and activity log).
- **⚡ True Per-Song Parallelism**: Downloads, transcodes, and enriches multiple tracks simultaneously using a customizable worker pool (`--workers 4` or higher).
- **🔒 Authenticated Session Support (`cookies.txt`)**: Auto-detects Netscape session cookies from `cookies.txt` or `--cookies` flag to completely eliminate bot challenges and unlock **high-bitrate 256 kbps AAC studio streams**.
- **🎯 Studio Master Prioritization & Anti-Live Defense**: Directly queries YouTube Music official song catalog (Tier 1) and scores candidates with strict negative filters (-100 pts) against live/concert/livehouse/acoustic bootlegs, with catalog duration matching ($\pm 3$s).
- **🏷️ Multi-Source Canonical Metadata**: Cross-verifies Apple Music/iTunes with a public Deezer fallback (< 200ms) and string similarity guards ($\ge 0.60$) to eliminate false renamings and guarantee **1000×1000 uncompressed square artwork**.
- **⏱️ Real-Time Concurrent Lyrics**: Time-synced lyrics are fetched and embedded **immediately as each track finishes downloading**, rather than waiting for the entire batch.
- **🎶 Dual-Standard In-File Lyrics**: Embeds both **binary millisecond `SYLT`** and **timestamped `USLT`** directly inside the `.mp3` file. **Zero `.lrc` companion files left behind**.
- **🔍 Album Art & Lyrics Enricher / Auditor**: Inspects existing `.mp3` files already on your hard drive. If cover art or synchronized lyrics are missing, it fetches and embeds them in-place **without re-encoding or modifying the audio**.
- **🎛️ Deterministic Transcoding**: Transcodes all incoming audio streams to a uniform Constant Bitrate standard (e.g., **128k CBR**, **320k CBR**, 44.1 kHz stereo) via FFmpeg.
- **⏭️ Smart Deduplication & In-Place Enrichment**: Automatically detects existing files on disk. If complete, it skips instantly (`⚡ Skipped`); if missing art or lyrics, it enriches them in-place automatically!
- **🛡️ Uncapped Manifest Extraction**: Paginated Spotify retrieval powered by `spotapi` (fetches full playlists of 100, 500, 1,000+ tracks without Spotify's 100-song embed cap or API keys) with fast Embed API fallback.

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
* **Download Mode**: Paste a Spotify URL (playlist/album/track) or choose a text file, then click **`⚡ Start Download & Pipeline`**.
* **Enricher Mode**: Choose your music folder and click **`🔍 Audit & Enrich Existing Files`**. AudiZap will audit all `.mp3` files, find ones missing cover art or lyrics, and update them in-place!

### 2. Command-Line Interface (CLI)
```bash
# Audit & enrich an existing local music folder (adds missing art & lyrics in-place):
audizap "C:\Users\USER\Music" --enrich --workers 4

# Download from a Spotify Playlist or Album:
audizap "https://open.spotify.com/playlist/6kKAHaM396ytVUggvkM0qp" --bitrate 128k --workers 4

# Download with authenticated session cookies (bypasses bot checks & unlocks 256k AAC):
audizap "https://open.spotify.com/playlist/6kKAHaM396ytVUggvkM0qp" --cookies ./cookies.txt --bitrate 320k

# Download from a Tracklist Text Export:
audizap "My Spotify Library.txt" --output ./my_music --bitrate 128k --workers 4

# High-Fidelity 320 kbps Download:
audizap "Artist - Track Name" --bitrate 320k --workers 2

# Force overwrite of existing files:
audizap "My Spotify Library.txt" --overwrite
```

---

## 🔐 Authentication & Session Setup (`cookies.txt`)

AudiZap includes native support for authenticated requests using a standard Netscape `cookies.txt` file.

### Why Use Authentication?
1. **Zero Bot Detection**: Completely eliminates YouTube's `"Sign in to confirm you're not a bot"` challenges.
2. **Master Quality Streams**: Unlocks YouTube Music's high-bitrate **256 kbps AAC** audio streams (`mp4a.40.2`).
3. **Explicit & Age-Gated Content**: Downloads age-restricted and explicit tracks without getting blocked.
4. **100% Studio Catalog Hit Rate**: Prevents throttling or forced fallbacks during large playlist batches.

### Setup Instructions
1. In your browser (Chrome, Edge, or Firefox), log into [music.youtube.com](https://music.youtube.com).
2. Use a browser extension such as **Get cookies.txt LOCALLY** to export your cookies in **Netscape format**.
3. Save the exported file as `cookies.txt` directly in the project root:
   ```text
   C:\Users\USER\Desktop\APPS\spotify_downloader\cookies.txt
   ```
4. AudiZap **automatically detects** this file on startup! The GUI will display `🔒 Auth: cookies.txt`, and the CLI will display `Auth: 🔒 Active (cookies.txt)`.
5. *(Security Notice: `cookies.txt` is strictly included in `.gitignore` and will never be committed or pushed.)*

---

## ⚙️ Settings Reference

| Setting | Flag / Option | Options / Default | Description |
|---|---|---|---|
| **Source** | *Positional* | Spotify URL, Folder, or `.txt` | Playlist URL, album URL, track, local audio folder, or text export |
| **Output Folder** | `-o`, `--output` | Directory path (`.` by default) | Where downloaded or enriched `.mp3` files reside |
| **Audio Bitrate** | `-b`, `--bitrate` | `128k` (Default), `192k`, `320k` | Enforced constant CBR bitrate via FFmpeg |
| **Worker Threads** | `-w`, `--workers` | `2`, `4` (Default), `6`, `8` | Number of simultaneous downloads, transcoders, or enrichers |
| **Cookie File** | `-c`, `--cookies` | Path to `cookies.txt` (Auto-detected) | Netscape-format session cookies for authenticated downloads |
| **Synced Lyrics** | `--no-lyrics` | `True` (Checked by default) | Real-time dual-tagging of in-file millisecond `SYLT` & `USLT` |
| **Auto-Enrich Existing** | `--no-enrich-existing` | `True` (Checked by default) | Inspects existing files on disk and injects missing art/lyrics |
| **Overwrite Existing** | `--overwrite` | `False` (Default) | Force re-download and re-tagging of files already on disk |
| **Smart Resume** | *Automatic* | Built-in | Skips files that are already complete with art and lyrics |

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
