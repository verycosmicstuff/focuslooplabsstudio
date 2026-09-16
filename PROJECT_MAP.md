# PROJECT_MAP: Focusloop Labs

## Stack
- **Backend**: Python 3.11, FastAPI, SQLite (WAL mode).
- **Imaging**: FFmpeg (NVENC RTX 3060), OpenCV, Pillow, rawpy / exifread (Fuji RAF, XMP).
- **UI**: Native Desktop App (PyWebView + WebView2), Focusloop Labs Studio dashboard.

## Architecture Map
- `src/core/`: `db.py` (WAL SQLite, volume_uuid & aliases), `logger.py`, `session.py`.
- `src/scanner/`: `indexer.py` (crawler), `volume.py` (UUID & mount aliasing), `meta_extractor.py`, `sidecar.py`.
- `src/analyzer/`: `culler.py` (sharpness, burst grouping), `deduper.py` (alias-safe duplicate checks).
- `src/transcoder/`: `engine.py` (batch H.265 NVENC), `handbrake.py`.
- `src/organizer/`: `manager.py` (trash, moves, sync tracking).
- `src/proofing/`: `watermarker.py`, `contact_sheet.py`, `presets.py`.
- `src/api/server.py`: REST API (mounts, culling, transcodes, scan controls).
- `ui/`: Responsive dark dashboard (`index.html`, `js/app.js`, `css/app.css`).

## Recent Changes
- Implemented dynamic volume fingerprinting (`.focusloop_id`) and multi-mount aliasing for USB (`E:\`) and NAS (`\\10.0.0.87\...`) switching without duplicate entries.
- Replaced terminology with "Primary Working Directory" and "Backup Directory".
- Added 250-file progress heartbeat logging in `indexer.py`.
- Designed and integrated new circular Autofocus Reticle icon (`app_icon.png`, `app_icon.ico`).
- Added drive label/role editing (`PATCH /api/sources/{id}`) and modal with Enter-to-save.
- Added live Pause, Resume, Cancel controls for indexing (`/api/sources/{id}/pause|resume|cancel`).
- Persisted live scanning/paused states across refreshes (`GET /api/sources` reports active indexer status; UI maintains Pause/Resume buttons and live polling).
- All 34/34 unit tests passing.

## Active Objective
- Assist user with testing, workflow refinements, and release packaging.

