# Developer Documentation: Architecture & Internals (`READMEDEV.md`)

This document details the internal architecture, mathematical algorithms, lifecycle flow, module breakdown, and extension points for developers contributing to or adapting **AudiZap**.

---

## 🏗️ Architecture & Per-Song Concurrency Model

Rather than executing stage-by-stage across the entire batch (which causes slow serialization and prevents real-time per-song enrichment), AudiZap delegates complete end-to-end responsibility to individual worker threads:

```
           [Input: Spotify URL / YouTube URL / Text Export / Folder]
                                       │
                             [pipeline/manifest.py]
                 (Paginated spotapi + Direct yt-dlp JSON Parser)
                                       │
                                [Job Work Queue]
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            ▼                          ▼                          ▼
      Worker Thread 1            Worker Thread 2            Worker Thread N
            │                          │                          │
     ┌──────┴──────────────────────────┴──────────────────────────┴──────┐
     │ 1. 4-Tier Canonical Metadata & 1000x1000 Square Artwork           │ (pipeline/artwork.py)
     │ 2. Deduplication & In-Place Enrichment Audit                      │ (Instant Skip if complete)
     │ 3. Isolated Temp Directory Allocation                             │ (tempfile.mkdtemp)
     │ 4. Candidate Search & Pre-Flight Gating                           │ (pipeline/audio.py)
     │ 5. ⚡ Topic Fast-Track Gate (Channel == "Topic" & |Δt| <= 2s)     │ (pipeline/qc.py)
     │ 6. 🔬 Acoustic QC (Normalized Pearson Cross-Correlation r>=0.60)  │ (pipeline/qc.py)
     │ 7. Deterministic 128k CBR Transcoding                             │ (pipeline/transcoder.py)
     │ 8. Real-Time Concurrent Lyrics Search                             │ (syncedlyrics: Musixmatch / LRCLIB)
     │ 9. Atomic ID3 Injection                                           │ (ID3v2.3: APIC + TIT2 + SYLT + USLT)
     └─────────────────────────────────┬─────────────────────────────────┘
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
│   ├── manifest.py            # Spotify & YouTube playlist/video manifest parser
│   ├── metadata.py            # Multi-source catalog resolver (iTunes + Deezer + Spotify)
│   ├── qc.py                  # [NEW] Acoustic QC, Pearson cross-correlation, multi-tier previews
│   ├── artwork.py             # [NEW] 4-Tier 1000x1000 square artwork resolver
│   ├── remediator.py          # [NEW] Audio Quality & Acoustic Remediation Engine
│   ├── audio.py               # AudioResolver, studio candidate scoring, cookies & cascade
│   ├── transcoder.py          # Transcoder, FFmpeg CBR normalization
│   ├── tagger.py              # Tagger, mutagen ID3v2.3, APIC, SYLT & USLT
│   └── engine.py              # PipelineEngine, ThreadPoolExecutor orchestrator
├── README.md                  # User-facing manual & benchmark summary
└── READMEDEV.md               # Developer documentation & mathematical foundations
```

---

## 🔬 Mathematical Foundations of Acoustic QC (`pipeline/qc.py`)

The Acoustic QC Engine provides mathematical proof that a downloaded candidate audio stream matches the official studio release, preventing live bootlegs, fan edits, and acoustic sessions from contaminating the archive.

### 1. Audio Envelope Extraction
1. The candidate audio and official 30-second reference preview are decoded via FFmpeg into 16-bit mono PCM sampled at $f_s = 4000\text{ Hz}$.
2. The absolute amplitude signal $|x[n]|$ is smoothed using a uniform moving-average box filter of width $W = \frac{f_s}{f_{\text{env}}} = 40$ samples (10ms):
   $$\tilde{x}[n] = \frac{1}{W} \sum_{k=0}^{W-1} |x[n - k]|$$
3. The smoothed signal is decimated by a factor of 40 to yield a clean **100 Hz energy envelope** $E[m]$.

### 2. Normalized Pearson Cross-Correlation ($r$)
Given candidate envelope $C[m]$ of length $M$ and reference preview envelope $P[k]$ of length $K$ ($K \le M$):
1. The reference preview is zero-mean centered:
   $$\tilde{P}[k] = \frac{P[k] - \mu_P}{\sigma_P}$$
2. The cross-correlation sequence is computed via FFT:
   $$R[m] = \sum_{k=0}^{K-1} C[m + k] \cdot \tilde{P}[k]$$
3. The sliding-window standard deviation of the candidate $\sigma_C[m]$ is computed over window $K$:
   $$\sigma_C[m] = \sqrt{\frac{1}{K} \sum_{k=0}^{K-1} C[m + k]^2 - \left(\frac{1}{K} \sum_{k=0}^{K-1} C[m + k]\right)^2}$$
4. The normalized cross-correlation coefficient $r[m]$ is obtained:
   $$r[m] = \frac{R[m]}{K \cdot \sigma_C[m]}$$
5. The peak correlation is extracted:
   $$r_{\text{max}} = \max_m r[m], \quad \Delta t = \frac{\arg\max_m r[m]}{100\text{ Hz}}$$

### 3. Classification Thresholds:
- **$r_{\text{max}} \ge 0.60$**: **`STUDIO_MASTER`** (Definitive acoustic match).
- **$r_{\text{max}} < 0.40$**: **`LIVE_OR_DIFFERENT`** (Rejected; candidate is a live performance, fan remix, or different song).
- **$0.40 \le r_{\text{max}} < 0.60$**: **`AMBIGUOUS`** (Deferred to duration consensus).

### 4. ⚡ Zero-Cost Topic Fast-Track:
To preserve maximum download throughput, candidates sourced from official **`" - Topic"`** channels whose duration matches the catalog within $\pm 2$ seconds bypass the 30-second preview download and cross-correlation step, completing in 0 milliseconds.

---

## 🎨 4-Tier High-Definition Artwork Resolver (`pipeline/artwork.py`)

AudiZap guarantees commercial-grade square cover art without relying on low-resolution or letterboxed YouTube thumbnails:

1. **Tier 1: Apple Music / iTunes CDN**:
   - Queries iTunes Search API for `artworkUrl100`.
   - Performs URL rewriting: `100x100bb.jpg` $\rightarrow$ `1000x1000bb.jpg` (or `1400x1400bb.jpg`).
   - Yields uncompressed square images direct from the distributor master.
2. **Tier 2: Spotify CDN**:
   - Extracts highest resolution from Spotify manifest `images[0].url` (640×640).
3. **Tier 3: Deezer CDN**:
   - Queries Deezer Open API for `album.cover_xl` (1000×1000).
4. **Tier 4: YouTube Thumbnail (Auto-Cropped)**:
   - Downloads `maxresdefault.jpg` (1280×720, 16:9).
   - Detects aspect ratio and executes a mathematical 1:1 center-crop with Pillow Lanczos resampling, eliminating black letterbox bars.

---

## 🛠️ Audio Quality & Acoustic Remediation Engine (`pipeline/remediator.py`)

The `AudioRemediator` transforms AudiZap into a complete maintenance tool for existing music collections:

```
                            [Existing MP3 File]
                                     │
                    ┌────────────────┴────────────────┐
                    ▼                                 ▼
         [Technical Stream Audit]           [Acoustic QC Audit]
         - Bitrate (MP3 header)             - Cross-correlation vs Preview
         - Duration vs Canonical Catalog    - Live / bootleg detection
                    │                                 │
                    └────────────────┬────────────────┘
                                     │
                             Status Evaluation
                                    / \
                              PASS /   \ FAIL (Live / 28m Rip / Non-128k)
                                  /     \
                 ┌───────────────┐       ┌─────────────────────────────────────┐
                 │  ⚡ SKIPPED   │       │ A. Bitrate only: In-Place Transcode │
                 │ (Verified OK) │       │ B. Defective cut: Candidate Hunting │
                 └───────────────┘       └──────────────────┬──────────────────┘
                                                            │
                                               [Candidate passes QC r >= 0.60]
                                                            │
                                             ┌──────────────┴──────────────┐
                                             │ 1. Backup old to .backup/   │
                                             │ 2. Transcode to 128k CBR    │
                                             │ 3. Embed 1000x1000 art & LRC│
                                             │ 4. Atomic file replacement  │
                                             └─────────────────────────────┘
```

- **In-Place Bitrate Transcoding**: Files that pass acoustic QC but have non-128k bitrates are transcoded in-place via FFmpeg in ~0.2s without downloading anything from the internet.
- **Defective Track Auto-Hunting**: Defective files trigger search query permutations (`"{Artist} {Title} Topic"`, `"(Official Audio)"`, ISRC). Once a candidate passes `AcousticQC`, it replaces the defective file while preserving the original in `.remediation_backup/`.

---

## 🎶 Dual-Standard In-File Lyrics (`pipeline/tagger.py`)

AudiZap embeds synchronized lyrics directly into the `.mp3` container using two simultaneous ID3v2.3 frames:

1. **Binary `SYLT` (Synchronised Lyrics/Text Frame)**:
   - ID3v2.3 binary specification: `format=2` (milliseconds), `type=1` (lyrics).
   - Compatible with advanced digital audio players, car infotainment systems, and Walkman devices.
2. **Text `USLT` (Unsynchronised Lyrics Frame with Timestamps)**:
   - Contains LRC-formatted text lines `[mm:ss.xx] Lyric text`.
   - Universal fallback for standard desktop players (VLC, MusicBee, Foobar2000).

---

## 🧪 Testing & Verification

To run the automated test suite verifying all new modules:
```bash
python test_audizap_breakthroughs.py
```

Tests:
- **`PreviewService`**: iTunes + Deezer unauthenticated preview fetching.
- **`ArtworkResolver`**: 1000×1000 image resolution and cropping.
- **`AcousticQC`**: Fast-track logic and Pearson cross-correlation.
- **`AudioRemediator`**: File inspection and QC verification.
- **`ManifestParser`**: Direct YouTube video and playlist extraction.
