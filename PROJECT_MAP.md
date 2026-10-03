# PROJECT_MAP: Focusloop Labs

## Stack
- **Backend**: Python 3.11, FastAPI, SQLite (WAL mode).
- **Imaging & AI**: FFmpeg (NVENC RTX 3060), OpenCV (YuNet/SFace), Pillow, rawpy / exifread.
- **UI**: Native Desktop App (PyWebView + WebView2), Focusloop Studio dark dashboard.

## Architecture Map
- `src/core/`: `db.py` (WAL SQLite, people, faces, notes), `tag_manager.py`, `logger.py`, `session.py`.
- `src/scanner/`: `indexer.py` (crawler), `volume.py` (UUID & mount aliasing), `meta_extractor.py`.
- `src/analyzer/`: `culler.py`, `deduper.py`, `face_engine.py` (face detection, recognition, clustering).
- `src/sync/`: `doctor.py` (Backup Doctor & Mirror Repair), `tracker.py` (SSD space reclaim).
- `src/transcoder/`: `engine.py` (batch H.265 NVENC, individual job resume/pause/restart/remove).
- `src/organizer/`: `manager.py` (trash, moves, sidecar bundling).
- `src/proofing/`: `watermarker.py`, `contact_sheet.py`, `presets.py`.
- `src/api/server.py`: REST API (mounts, stats, transcode controls, face catalog, sync doctor).
- `ui/`: Dark dashboard (`index.html`, `js/app.js`, `css/app.css`).

## Recent Changes
- Released **v2.3.7** Strict Drive & Folder Scoping for Face Engine:
  - Scoped face browsing, face scanning, filename lookup, target hunting, and profile modals to selected drive and folder.
  - Added Windows backslash-normalized SQL matching (`_build_folder_sql`) supporting both relative and absolute paths.
  - Scoped avatar thumbnails and appearance counts to active scope, preventing cross-drive avatar bleeding.
  - Added dynamic folder dropdowns to toolbar (`#sel-faces-folder`) and scan modal (`#modal-scan-folder`).
- 59/59 unit tests passing.

## Active Objective
- Scoped Face Engine features verified live in Focusloop Studio dashboard.
