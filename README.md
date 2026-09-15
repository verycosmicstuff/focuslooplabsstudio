# Focusloop Studio 🚀
### Creative Media Assistant & Storage Manager for Photographers & Videographers

Focusloop Studio is a high-performance, standalone desktop application built to crawl, catalog, and reclaim storage across internal drives, high-speed working SSDs, and external NAS archives. It pairs hardware-accelerated video transcoding with computer vision blur culling, exact duplicate detection, and client proofing safeguards.

📖 **For deep architectural specs, database schemas, and mathematical models, see [TECH_DOCUMENTATION.md](TECH_DOCUMENTATION.md).**

---

## ✨ Key Features

### 🎬 1. Hardware-Accelerated H.265 Transcoding
- **NVIDIA NVENC RTX 3060 Acceleration**: Transcodes large ProRes, H.264, and camera raw video to visually lossless 10-bit H.265 (CQ 22, Preset p6) at 5×–10× real-time speeds.
- **Background Throttling**: Runs with `BELOW_NORMAL_PRIORITY_CLASS` on Windows so your PC remains snappy and responsive during heavy gaming or editing sessions.
- **Metadata & Timestamp Preservation**: Preserves original file modification times, audio channels, and camera metadata.

### 🧠 2. Intelligent Bitrate Advisor & Zero-Bloat Guarantee
- **Suitability Scoring**: Analyzes resolution, duration, and bitrates beforehand to prevent transcoding bloat on low-bitrate screen captures or web clips (e.g., OBS 2.5 Mbps recordings).
- **Zero-Bloat Engine Safeguard**: If any re-encoded file finishes larger than the original (or saves less than 3%), the engine automatically deletes the bloated file, keeps the original, and marks the job as optimal. No disk space is ever lost.

### 🔍 3. Computer Vision Blur & Junk Culler
- **OpenCV Laplacian Score**: Analyzes RAW files (Fuji RAF, Sony ARW, Canon CR3) and JPGs to detect blurry, out-of-focus, or junk shots.
- **Visual Grid & EXIF Inspection**: Preview high-resolution photos alongside ISO, shutter speed, aperture, and camera model.
- **Sidecar-Aware Actions**: Moving, trashing, or quarantining photos safely moves their accompanying `.xmp` sidecars.

### 👯 4. Duplicate Media Finder with Sidecar Protection
- **Two-Tier Hashing**: Rapid xxHash sample hashing followed by full SHA-256 verification.
- **Safe Matching**: Strictly separates metadata sidecars (`.xmp`, `.thm`) from actual media files and provides an `Exact Same Filename Only` filter.
- **Cross-Drive Comparison**: Pinpoint duplicate photo sets between working SSDs and backup storage.

### 📂 5. Native Windows File Explorer Integration
- **Right-Click Context Menu**: Right-click any photo, video, or duplicate candidate to reveal in Windows Explorer, open containing folders, or copy file paths.
- **Interactive Queue Breakdown**: Real-time progress monitoring with live FPS, speed multipliers, and folder origin displays.

---

## 🛠️ Tech Stack

- **Desktop Shell**: PyWebView (native Microsoft WebView2 runtime)
- **Backend**: Python 3.11, FastAPI, Uvicorn
- **Database**: SQLite (WAL mode, concurrent read/write locks)
- **Computer Vision & Media**: OpenCV, Pillow, RawPy, ExifRead
- **Video Engine**: FFmpeg (NVENC hardware acceleration), FFprobe
- **Frontend**: Clean, responsive modern dark UI with vanilla JS & CSS

---

## 🚀 Getting Started

### Prerequisites
1. **Python 3.11+** installed on Windows.
2. **NVIDIA GPU** (RTX series recommended) with updated drivers for NVENC hardware acceleration.
3. **FFmpeg** and **FFprobe** installed and accessible in system `PATH` (or configured via environment variable).

### Installation

1. **Clone the repository**:
   ```powershell
   git clone https://github.com/verycosmicstuff/focuslooplabsstudio.git
   cd focuslooplabsstudio
   ```

2. **Install dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

3. **Launch the application**:
   - Double-click `run_savespace.bat` or run:
   ```powershell
   python main.py
   ```

---

## 📂 Project Structure

```text
saveSpace/
├── main.py                  # PyWebView desktop launcher & FastAPI server runner
├── run_savespace.bat        # 1-click Windows launcher
├── requirements.txt         # Python package dependencies
├── src/
│   ├── analyzer/
│   │   ├── culler.py        # OpenCV Laplacian blur analyzer & culling engine
│   │   ├── deduper.py       # Exact duplicate finder with sidecar protection
│   │   └── video_advisor.py # Bitrate & compression suitability advisor
│   ├── api/
│   │   └── server.py        # FastAPI endpoints & REST interface
│   ├── core/
│   │   ├── config.py        # Global settings, extensions, hardware profiles
│   │   ├── db.py            # SQLite database schema & transaction management
│   │   └── models.py        # Pydantic data schemas
│   ├── gui/
│   │   └── app_window.py    # PyWebView desktop window configuration
│   ├── organizer/
│   │   └── manager.py       # Safe file mover, trash recycling, sidecar handling
│   ├── scanner/
│   │   ├── indexer.py       # Multi-drive filesystem crawler & hasher
│   │   ├── meta_extractor.py# FFprobe & ExifRead metadata extractors
│   │   └── sidecar.py       # RAW + XMP sidecar pairing logic
│   ├── sync/
│   │   └── tracker.py       # Working SSD vs Backup drive comparison
│   └── transcoder/
│       ├── engine.py        # RTX 3060 NVENC job runner & zero-bloat safeguard
│       └── handbrake.py     # HandBrakeCLI alternative engine bridge
└── ui/
    ├── index.html           # Modern dark dashboard layout
    ├── css/app.css          # Styling, glassmorphism, responsive grid
    └── js/app.js            # Reactive state manager, context menus, polling
```

---

## 📄 License
MIT License. Built for creators and storage enthusiasts.
