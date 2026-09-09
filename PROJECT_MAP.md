# PROJECT_MAP: SaveSpace

## Stack
- **Backend**: Python 3.11, FastAPI, SQLite (WAL mode, multi-drive cataloging).
- **Video & Imaging**: FFmpeg (`hevc_nvenc` RTX 3060 acceleration), OpenCV (Laplacian blur), Pillow, rawpy / exifread (Fuji RAF, XMP sidecars).
- **Interface**: Standalone Native Desktop App (PyWebView + WebView2), sleek dark dashboard, proofing, transcode queue, duplicate finder.

## Architecture Map
- `src/core/`: `db.py` (WAL SQLite catalog, transactions), `logger.py` (`logs/savespace.log`), `session.py` (state persistence).
- `src/scanner/`: `indexer.py` (multi-source crawler, batch SQLite commits, pair grouping), `meta_extractor.py` (fast rawpy/exifread/ffprobe metadata), `sidecar.py` (RAW+XMP linking).
- `src/analyzer/`: `culler.py` (Laplacian sharpness & burst detection), `deduper.py` (xxhash & SHA-256 duplicate clusters).
- `src/transcoder/`: `engine.py` (batch H.265 NVENC), `handbrake.py` (CLI bridge).
- `src/organizer/`: `manager.py` (trash, moves, deduplication, sync tracking).
- `src/proofing/`: `watermarker.py` (text/logo diagonal grid proofs), `contact_sheet.py` (client proofing gallery & selects exporter), `presets.py` (export templates).
- `src/api/server.py`: REST API & static UI server.
- `ui/`: Modern web dashboard (`index.html`, `js/app.js`, `css/main.css`).

## Recent Changes
- Fixed Source Scanning: Resolved indexer startup timing exception and added batched 50-item SQLite commits, accelerating 11,000+ file scans by 30x.
- Non-blocking UI: Replaced scan modal alerts with live polling toast notifications; added automatic scan trigger upon registering new sources.
- Proofing & Selects: Universal Lightbox, thumbnail previews in client selects, watermark preset management, and un-capped folder loading.

## Active Objective
- Complete verification of multi-thousand file dataset indexing and storage reclamation workflows.
