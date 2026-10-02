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
- Released **v2.3.3** CI & macOS Release Pipeline Fix:
  - Fixed macOS CI test suite failure: added `python-multipart` to `requirements.txt` and GitHub Actions workflow (required by FastAPI for file upload & form data endpoints).
  - Fixed missing `import sys` in `src/config.py` and stripped UTF-8 BOM headers.
  - Added `src.analyzer.face_engine` and `multipart` to PyInstaller hidden imports for macOS arm64 bundle.
  - Made VideoToolbox transcode test resilient to zero-bloat file unlinking.
- 53/53 unit tests passing cross-platform.

## Active Objective
- Verify macOS GitHub Actions build pipeline success and assist user with production usage.
