# PROJECT_MAP: SaveSpace

## Stack
- **Backend & Core**: Python 3.11, SQLite (WAL mode for cross-drive cataloging)
- **Video Engine**: FFmpeg (`hevc_nvenc` RTX 3060 hardware acceleration + `libx265`), HandBrakeCLI support
- **Media & Quality Analysis**: Pillow, OpenCV (Laplacian blur score), imagehash (perceptual & exact duplicates), rawpy / exifread (Fuji RAF, XMP sidecar awareness)
- **Interface**: Standalone Native Desktop App (PyWebView + WebView2) with sleek dark UI, visual gallery, blur culler, transcode queue, and sync manager.

## Architecture Map
- `src/core/db.py`: SQLite catalog tracking multi-drive files, sha256/xxhash, metadata, conversion & sync states.
- `src/scanner/indexer.py`: Multi-source crawler (Drives, SSDs, NAS) with pair detection (RAW+XMP, Video+sidecar).
- `src/analyzer/culler.py`: Blurry/junk image detector, duplicate detector (exact & perceptual), burst analyzer.
- `src/analyzer/video_advisor.py`: Video bitrate, resolution, and codec suitability analyzer for anti-bloat recommendations.
- `src/transcoder/engine.py`: Batch H.265 transcoder (RTX 3060 NVENC), zero-bloat safeguard, process throttling, metadata copier.
- `src/organizer/manager.py`: Safe file operations (move, archive, delete to trash, dedupe, sync tracking between backup and sources).
- `src/proofing/watermarker.py`: Bulk text & PNG logo watermarking with diagonal repeating grid protection, web proof resizing, and instant live preview.
- `src/proofing/contact_sheet.py`: Standalone client proofing HTML gallery generator with lightbox selection, plus smart client selects resolver & safe exporter with XMP sidecar binding.
- `src/core/logger.py`: Rotating file logger writing to `logs/savespace.log` with unhandled exception hooks.
- `src/core/session.py`: Persistent session state and completed task memory manager (`data/session_state.json`).
- `src/api/server.py`: FastAPI server serving endpoints & interactive dashboard UI.
- `src/gui/app_window.py`: Standalone desktop window shell using WebView2 with AppUserModelID.
- `SaveSpace.exe`: Native Windows executable launcher (embedded icon, zero-console launch, single-instance mutex).
- `TECH_DOCUMENTATION.md`: Complete living technical specification, ER diagram, algorithms, and API catalog.

## Recent Changes
- Native Desktop App: Compiled `SaveSpace.exe` with multi-res icon, single-instance mutex, Start Menu shortcut, and rotating file logger (`logs/savespace.log`).
- Proofing & Watermarking: Multi-folder picker, PNG logo picker, long edge slider, and configurable subfolder naming styles (`prefix`, `custom`, `suffix`).
- Disk & Session Integrity: Auto-restoring session state, Explorer reveal, and non-destructive proof subfolder isolation.

## Active Objective
- Client media proofing, watermarking, batch transcoding, and storage reclamation.
