# PROJECT_MAP: Focusloop Labs

## Stack
- **Backend**: Python 3.11, FastAPI, SQLite (WAL mode).
- **Imaging**: FFmpeg (NVENC RTX 3060 / VideoToolbox), OpenCV, Pillow, rawpy / exifread.
- **UI**: Native Desktop App (PyWebView + WebView2), Focusloop Studio dark dashboard.

## Architecture Map
- `src/core/`: `db.py` (WAL SQLite, people, faces, notes), `tag_manager.py`, `logger.py`, `session.py`.
- `src/scanner/`: `indexer.py` (crawler), `volume.py` (UUID & mount aliasing), `meta_extractor.py`.
- `src/analyzer/`: `culler.py`, `deduper.py` (instant SQL duplicate savings), `face_engine.py`.
- `src/sync/`: `doctor.py` (Backup Doctor & Mirror Repair), `tracker.py` (SSD space reclaim).
- `src/transcoder/`: `engine.py` (batch H.265 NVENC, individual job resume/pause/restart/remove).
- `src/organizer/`: `manager.py` (trash, moves, sidecar bundling).
- `src/proofing/`: `watermarker.py`, `contact_sheet.py`, `presets.py`.
- `src/api/server.py`: REST API (mounts, stats, transcode controls, sync doctor).
- `ui/`: Dark dashboard (`index.html`, `js/app.js`, `css/app.css`).

## Recent Changes
- Released **v2.3.6** Transcoder Recovery & Performance Fixes:
  - Replaced synchronous duplicate scan in `/api/stats` with instant SQL estimation (0.6s vs infinite hang).
  - Fixed subfolder source ownership in `indexer.py`: nested folders (e.g. `E:\GBIA2026\webSized`) correctly claim their indexed files.
  - Added individual transcode controls: per-job Resume (`▶`), Pause (`⏸`), Restart from 0% (`🔄`), and Remove (`✕`).
  - Added auto-recovery for orphaned `transcoding` records on startup.
- 59/59 unit tests passing.

## Active Objective
- Restart application process and verify all features live in Focusloop Studio dashboard.
