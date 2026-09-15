# PROJECT_MAP: Focusloop Labs

## Stack
- **Backend**: Python 3.11, FastAPI, SQLite (WAL mode, multi-drive cataloging).
- **Video & Imaging**: FFmpeg (`hevc_nvenc` RTX 3060 acceleration), OpenCV (Laplacian blur), Pillow, rawpy / exifread (Fuji RAF, XMP sidecars).
- **Interface**: Standalone Native Desktop App (PyWebView + WebView2), Focusloop Labs studio dashboard (`https://focuslooplabs.vercel.app/`).

## Architecture Map
- `src/core/`: `db.py` (WAL SQLite catalog), `logger.py` (`logs/savespace.log`), `session.py` (state persistence & ignored pairs).
- `src/scanner/`: `indexer.py` (multi-source crawler, system file/recycle bin exclusion), `meta_extractor.py`, `sidecar.py` (RAW+XMP linking).
- `src/analyzer/`: `culler.py` (sharpness, burst grouping, intentional keep), `deduper.py` (pair omission, xxhash/SHA-256 clusters).
- `src/transcoder/`: `engine.py` (batch H.265 NVENC), `handbrake.py` (CLI bridge).
- `src/organizer/`: `manager.py` (trash, moves, deduplication, sync tracking).
- `src/proofing/`: `watermarker.py`, `contact_sheet.py`, `presets.py`.
- `src/api/server.py`: REST API (culling folders, duplicate pair omission/restoration).
- `scripts/`: `build_dist.ps1` (portable builder), `build_installer.ps1` (Inno Setup 6), `FocusloopLabs.iss` (installer spec with disclaimer), `compile_launcher.ps1` (C# launcher).
- `ui/`: Responsive dark dashboard (`index.html`, `js/app.js`, `css/app.css`).

## Recent Changes
- Added cross-platform macOS support: Apple VideoToolbox (`hevc_videotoolbox` with `-tag:v hvc1`) hardware transcoding, Homebrew binary discovery, and Cocoa data/log directory resolution.
- Added `run_focusloop.sh` POSIX shell launcher and `.github/workflows/build-macos.yml` for automated Apple Silicon (`macos-14`) standalone portable `.app` bundle builds.
- Added MIT LICENSE, 29/29 unit tests passing.
- Rebranded to Focusloop Studio with official site `https://focuslooplabs.vercel.app/` and live portable release download.

## Active Objective
- Assist user with macOS workflow trigger, verification, and feedback.

