# PROJECT_MAP: Focusloop Labs

## Stack
- **Backend**: Python 3.11, FastAPI, SQLite (WAL mode).
- **Imaging**: FFmpeg (NVENC RTX 3060), OpenCV, Pillow, rawpy / exifread (Fuji RAF, XMP).
- **UI**: Native Desktop App (PyWebView + WebView2), Focusloop Labs Studio dashboard.

## Architecture Map
- `src/core/`: `db.py` (WAL SQLite, volume_uuid, file_tags, media_notes), `tag_manager.py` (speakers, topics, mentions, catalog filters), `logger.py`, `session.py`.
- `src/scanner/`: `indexer.py` (crawler), `volume.py` (UUID & mount aliasing), `meta_extractor.py`, `sidecar.py`.
- `src/analyzer/`: `culler.py` (sharpness, burst grouping), `deduper.py` (alias-safe duplicate checks).
- `src/transcoder/`: `engine.py` (batch H.265 NVENC), `handbrake.py`.
- `src/organizer/`: `manager.py` (trash, moves, sync tracking).
- `src/proofing/`: `watermarker.py`, `contact_sheet.py`, `presets.py`.
- `src/api/server.py`: REST API (mounts, culling, transcodes, tags & catalog, media streaming).
- `ui/`: Responsive dark dashboard (`index.html`, `js/app.js`, `css/app.css`).

## Recent Changes
- Added full **Media Tags & Catalog** feature:
  - SQLite tables `file_tags` (with categories: `speaker`, `topic`, `mention`, `general`) and `media_notes` (notes, 5-star ratings).
  - Backend `TagManager` and REST endpoints: `/api/tags/catalog`, `/api/tags/all`, `/api/tags/folders`, `/api/tags/update`, `/api/tags/batch`, `/api/tags/notes`, `/api/media/stream/{id}`, `/api/files/open-system`.
  - Frontend "Media Tags & Catalog" tab with scope filter (Whole collection / specific drive), folder/subfolder dropdown, media type toggle (videos vs photos), tagged/untagged status filter, quick tag cloud, and multi-field search.
  - Interactive Media Inspector drawer/modal with HTML5 video player, technical specs, keyboard shortcut navigation (`◀`/`▶`), quick speaker/topic/mention addition, notes, and 1-click VLC / Explorer launch.
  - Batch tagging modal to tag dozens of videos/photos at once across folders.
- Released **v2.1**: Built & packaged Windows portable ZIP (`FocusloopLabs-v2.1-Portable.zip`, 198.2 MB) and triggered cloud build on GitHub Actions.
- 41/41 unit tests passing.

## Active Objective
- Assist user with testing, workflow refinements, and release packaging.
