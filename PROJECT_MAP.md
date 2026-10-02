# PROJECT_MAP: Focusloop Labs

## Stack
- **Backend**: Python 3.11, FastAPI, SQLite (WAL mode).
- **Imaging**: FFmpeg (NVENC RTX 3060 / VideoToolbox), OpenCV, Pillow, rawpy / exifread.
- **UI**: Native Desktop App (PyWebView + WebView2), Focusloop Studio dark dashboard.

## Architecture Map
- `src/core/`: `db.py` (WAL SQLite, people, faces, notes), `tag_manager.py`, `logger.py`, `session.py`.
- `src/scanner/`: `indexer.py` (crawler), `volume.py` (UUID & mount aliasing), `meta_extractor.py`.
- `src/analyzer/`: `culler.py`, `deduper.py`, `face_engine.py` (face detection & clustering).
- `src/sync/`: `doctor.py` (Backup Doctor & Mirror Repair), `tracker.py` (SSD space reclaim).
- `src/transcoder/`: `engine.py` (batch H.265 NVENC, pause/resume sync).
- `src/organizer/`: `manager.py` (trash, moves, sidecar bundling).
- `src/proofing/`: `watermarker.py`, `contact_sheet.py`, `presets.py`.
- `src/api/server.py`: REST API (mounts, faces, sync doctor, proofing).
- `ui/`: Dark dashboard (`index.html`, `js/app.js`, `css/app.css`).

## Recent Changes
- Released **v2.3.5** Backup Doctor & Mirror Sync:
  - Added `src/sync/doctor.py` (`BackupDoctor` engine): audits master (e.g. NAS) vs backup folders, pinpointing 0-byte corrupt files, missing items, and size mismatches in seconds.
  - Added atomic repair with 4MB `.part` streaming, size validation, atomic `os.replace`, and `mtime` preservation to prevent corrupt stubs.
  - Added API routes: `/api/sync/doctor/audit`, `/repair`, `/status`, `/cancel`.
  - Added full UI in `#tab-sync`: folder pickers, diagnostic stat cards, defect inspector table, live transfer progress card, and quick repair buttons.
- 58/58 unit tests passing cross-platform.

## Active Objective
- Successfully repaired all 10 corrupted files on `D:\Awaaz Backup\pgwp\Jan 18` (now 217/217 files, 84.18 GB verified matching NAS `\\10.0.0.87\awaaz\Awaaz\pgwp\Jan 18`). Ready for next user requests or workflows.
