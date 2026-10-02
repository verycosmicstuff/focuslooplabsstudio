# PROJECT_MAP: Focusloop Labs

## Stack
- **Backend**: Python 3.11, FastAPI, SQLite (WAL mode).
- **Imaging**: FFmpeg (NVENC RTX 3060 / VideoToolbox), OpenCV, Pillow, rawpy / exifread.
- **UI**: Native Desktop App (PyWebView + WebView2), Focusloop Studio dark dashboard.

## Architecture Map
- `src/core/`: `db.py` (WAL SQLite, volume_uuid, file_tags, media_notes, people, face_detections), `tag_manager.py` (catalog filters, tag groups), `logger.py`, `session.py`.
- `src/scanner/`: `indexer.py` (crawler), `volume.py` (UUID & mount aliasing), `meta_extractor.py`, `sidecar.py`.
- `src/analyzer/`: `culler.py`, `deduper.py`, `face_engine.py` (face detection & clustering).
- `src/transcoder/`: `engine.py` (batch H.265 NVENC/VideoToolbox, pause/resume sync).
- `src/organizer/`: `manager.py` (trash, moves, sync tracking).
- `src/proofing/`: `watermarker.py`, `contact_sheet.py`, `presets.py`.
- `src/api/server.py`: REST API (mounts, transcodes, tags, catalog, faces, streaming).
- `ui/`: Responsive dark dashboard (`index.html`, `js/app.js`, `css/app.css`).

## Recent Changes
- Released **v2.3.0** of Local **People & Faces** engine:
  - SQLite tables `people` & `face_detections` with 128-d vector embeddings and avatar thumbnails.
  - CUDA GPU acceleration on RTX 3060 (~2.02 ms per face) + CPU thread clamping.
  - Media type filtering (`all`, `video`, `photo`) and sort modes (`video_count`, `photo_count`, `count`, `name`, `recent`).
  - Targeted single-person search (`find-everywhere`) across unindexed files and folders.
  - Upload Reference Photo: Drop or browse any external photo, auto-extract face chips for selection, register person, and launch instant background hunt across all folders.
  - Fixed thumbnail route pluralization and added picture-in-picture face crop overlay badges with local disk fallback.
- 53/53 unit tests passing.

## Active Objective
- Assist user with testing, live workflow verification, and production usage.
