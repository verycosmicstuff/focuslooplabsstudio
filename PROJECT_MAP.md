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
- Rebranded to Focusloop Labs with official site `https://focuslooplabs.vercel.app/` and added early-access responsibility notice (`DISCLAIMER.txt`) to Inno Setup installer.
- Built 1-click Windows installer `dist/Focusloop-Labs-Setup-v1.0.0.exe` (124.8 MB) and portable distribution `dist/FocusloopLabs-v1.0-Portable.zip` (192.5 MB).
- Added Duplicate Pair Omission ("🚫 Omit this Pair" & Omitted Pairs management modal) to hide intentional duplicate folders (e.g. Leela selects).
- Added Folder Selection dropdown & "⭐ Keep" button to Blur & Burst Culler (card action & Lightbox preview modal) to preserve intentional soft shots.
- Purged and permanently excluded Windows `$RECYCLE.BIN` / `$I...` ghost entries from scanner and culler.

## Active Objective
- Assist user with testing installer deployment and verifying duplicate/culling workflows.
