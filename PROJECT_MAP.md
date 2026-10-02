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
- Enhanced Local **People & Faces** engine (Google Photos style):
  - SQLite tables `people` & `face_detections` with 128-d vector embeddings and avatar thumbnails.
  - Media type filtering (`all`, `video`, `photo`) and sort modes (`video_count`, `photo_count`, `count`, `name`, `recent`).
  - Targeted single-person search (`find-everywhere`): hunts a specific face across all drives & folders immediately without waiting for library scans.
  - Live real-time scan updates: clusters faces on-the-fly, displaying newly detected people cards and increments live during scans.
  - Google Photos-style Naming, Combining/Merging, Unlinking false matches, and auto-syncing with `file_tags` (`speaker`).
- 52/52 unit tests passing.

## Active Objective
- Complete verification of real-time face scanning and targeted searches.
