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
- Added 100% Local **People & Faces** engine (Google Photos style):
  - SQLite tables `people` & `face_detections` with 128-d vector embeddings and avatar thumbnails.
  - Backend `FaceEngine` using OpenCV YuNet (detection) and SFace (embeddings) with video keyframe sampling and temporal de-duplication.
  - Agglomerative cosine clustering for auto-grouping unnamed faces into People.
  - Google Photos-style Naming, Combining/Merging, Unlinking false matches, and auto-syncing with `file_tags` (`speaker`).
  - Frontend "People & Faces" tab with live scan progress bar, people cards grid, multi-select merge toolbar, and detail media gallery with video timestamp badges (`▶ 01:24`).
- 50/50 unit tests passing.

## Active Objective
- Assist user with testing, workflow refinements, and release packaging.
