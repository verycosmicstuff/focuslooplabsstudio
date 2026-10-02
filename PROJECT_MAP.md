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
- Fixed macOS release workflow failure (`build-macos.yml`):
  - Added missing `httpx` dependency to `requirements.txt` and CI workflow for FastAPI `TestClient`.
  - Updated `TagManager.get_distinct_folders` & `query_catalog` to handle both `/` and `\` cross-platform.
  - Made `test_tags.py` fixtures use platform-neutral `Path` objects.
- Fixed Transcoding Pause bug:
  - Recursive process suspension for FFmpeg and child threads with `psutil`.
  - Added queue-level pause loop preventing unpause or next-job execution.
  - DB status updates to `'paused'` with 0 FPS / 0x speed frozen in database and UI.
  - Synchronized header & queue pause buttons and added amber pause badges.
- 50/50 unit tests passing.

## Active Objective
- Package and trigger updated macOS and Windows builds.
