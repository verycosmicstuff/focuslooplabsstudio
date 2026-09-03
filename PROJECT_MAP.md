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
- `src/api/server.py`: FastAPI server serving endpoints & interactive dashboard UI.
- `src/gui/app_window.py`: Standalone desktop window shell using WebView2.
- `TECH_DOCUMENTATION.md`: Complete living technical specification, ER diagram, algorithms, and API catalog.

## Recent Changes
- Built full standalone desktop software with PyWebView, SQLite catalog, OpenCV blur culling, duplicate finder, NVENC H.265 transcoder, and 1-click launcher `run_savespace.bat`.
- Added folder location display and native Windows File Explorer right-click integration.
- Added intelligent video bitrate & suitability analyzer (`video_advisor.py`) and zero-bloat engine safeguard that discards output if larger than original.
- Fixed duplicate finder: strictly excluded sidecars (.xmp) and non-media from duplicate detection, added Exact Same Filename filter, and prevented auto-checking files with different names.
- Resolved slow image scrolling: downscaled RAW previews from 4.5MB/40MP to lightweight 380px thumbnails (~12KB, freeing 12.2GB disk space), added zero-SQL fast path with HTTP Cache-Control headers, decoding="async", and content-visibility: auto.
- Added subfolder deselection & exclusion for drives: Manage Subfolders modal with selective inclusion/exclusion checkboxes, in-place os.walk directory pruning, and optional instant catalog purging.

## Active Objective
- Assist user with media library management, batch transcoding, and storage reclamation.
