import os
import sys
import json
import hashlib
import subprocess
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import psutil
from PIL import Image

from src.config import (
    BASE_DIR, THUMBNAILS_DIR, PERFORMANCE_MODES, DEFAULT_PORT, DEFAULT_HOST,
    RAW_EXTS, PHOTO_EXTS, VIDEO_EXTS
)
from src.core.db import get_db, init_db, db_transaction
from src.core.models import SourceCreate, SourceExclusionsUpdate, CullingAction, TranscodeRequest, OrganizeRule
from src.core.logger import get_logger, LOG_FILE, LOGS_DIR
from src.core.session import get_session_state, save_session_state, record_last_task
from src.scanner.indexer import SourceIndexer
from src.scanner.meta_extractor import generate_thumbnail
from src.analyzer.culler import CullingEngine, compute_blur_score
from src.analyzer.deduper import DuplicateDetector
from src.transcoder.engine import transcode_queue, TRANSCODE_PROFILES
from src.transcoder.handbrake import HandBrakeBridge
from src.sync.tracker import SyncTracker
from src.organizer.manager import FileOrganizer
from src.analyzer.video_advisor import analyze_video_suitability, format_bitrate
from src.proofing.watermarker import (
    watermark_manager, generate_watermark_preview, process_single_image, open_image_source
)
from src.proofing.contact_sheet import (
    generate_contact_sheet_package, parse_client_selects,
    resolve_selects_against_directory_or_db, execute_selects_export
)
from src.proofing.presets import get_all_presets, save_preset, delete_preset

logger = get_logger("api")

app = FastAPI(title="SaveSpace Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    is_poll = request.url.path in ("/api/health", "/api/proofing/batch_status", "/api/transcodes/queue")
    if not is_poll:
        logger.info(f"{request.method} {request.url.path}")
    try:
        response = await call_next(request)
        if response.status_code >= 400 and not is_poll:
            logger.warning(f"{request.method} {request.url.path} -> status {response.status_code}")
        return response
    except Exception as e:
        logger.exception(f"Unhandled error handling {request.method} {request.url.path}: {e}")
        raise

# In-memory scan states
scan_progress = {}

@app.on_event("startup")
def on_startup():
    init_db()

@app.get("/api/health")
def health():
    return {
        "status": "online",
        "performance_mode": transcode_queue.perf_mode,
        "handbrake": HandBrakeBridge.get_info()
    }

# ----------------- SOURCES & STORAGE -----------------

@app.get("/api/sources")
def list_sources():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sources ORDER BY id ASC")
    sources = [dict(r) for r in cursor.fetchall()]

    for s in sources:
        try:
            s["excluded_paths"] = json.loads(s.get("excluded_paths") or "[]")
        except Exception:
            s["excluded_paths"] = []

        # Get live capacity if possible
        try:
            p = Path(s["path"])
            if p.exists():
                usage = psutil.disk_usage(str(p))
                s["total_bytes"] = usage.total
                s["free_bytes"] = usage.free
                s["is_online"] = True
            else:
                s["is_online"] = False
        except Exception:
            s["is_online"] = False

        # File stats
        cursor.execute("""
            SELECT COUNT(*) as count, COALESCE(SUM(size_bytes), 0) as total_size
            FROM files WHERE source_id = ? AND status = 'active'
        """, (s["id"],))
        stats = cursor.fetchone()
        s["file_count"] = stats["count"]
        s["total_media_size"] = stats["total_size"]

    return sources

@app.post("/api/sources")
def add_source(data: SourceCreate):
    p = Path(data.path).resolve()
    if not p.exists():
        raise HTTPException(status_code=400, detail="Path does not exist on this computer")

    conn = get_db()
    cursor = conn.cursor()
    try:
        usage = psutil.disk_usage(str(p))
        total_b = usage.total
        free_b = usage.free
    except Exception:
        total_b = 0
        free_b = 0

    try:
        cursor.execute("""
            INSERT INTO sources (path, label, drive_type, total_bytes, free_bytes, is_online, excluded_paths)
            VALUES (?, ?, ?, ?, ?, 1, ?)
        """, (str(p), data.label, data.drive_type or "LOCAL", total_b, free_b, json.dumps(data.excluded_paths or [])))
        conn.commit()
        return {"id": cursor.lastrowid, "message": "Source registered successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Source already registered or invalid: {str(e)}")

@app.get("/api/sources/{source_id}/subfolders")
def get_source_subfolders(source_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, path, label, excluded_paths FROM sources WHERE id = ?", (source_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    root = Path(row["path"])
    if not root.exists():
        return {"source_id": source_id, "path": row["path"], "is_online": False, "subfolders": []}

    try:
        excluded_list = json.loads(row["excluded_paths"] or "[]")
    except Exception:
        excluded_list = []

    norm_excluded = {
        str(Path(p).resolve()).lower() if os.path.isabs(p) else str((root / p).resolve()).lower()
        for p in excluded_list if p
    }

    system_skips = {"$recycle.bin", "system volume information", ".git", ".idea", ".vscode", "node_modules", ".gemini"}
    subfolders = []

    try:
        with os.scandir(str(root)) as it:
            for entry in sorted(it, key=lambda e: e.name.lower()):
                if entry.is_dir(follow_symlinks=False):
                    name = entry.name
                    if name.lower() in system_skips:
                        continue
                    full_p = str(Path(entry.path).resolve())
                    is_excluded = (full_p.lower() in norm_excluded or name.lower() in norm_excluded or name in excluded_list)
                    subfolders.append({
                        "name": name,
                        "path": full_p,
                        "rel_path": name,
                        "is_excluded": is_excluded
                    })
    except Exception as e:
        pass

    return {
        "source_id": source_id,
        "path": str(root),
        "label": row["label"],
        "is_online": True,
        "subfolders": subfolders
    }

@app.post("/api/sources/{source_id}/exclusions")
def update_source_exclusions(source_id: int, data: SourceExclusionsUpdate):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, path FROM sources WHERE id = ?", (source_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    root = Path(row["path"])
    clean_exclusions = list(set(data.excluded_paths))

    with db_transaction() as tx:
        tx.execute(
            "UPDATE sources SET excluded_paths = ? WHERE id = ?",
            (json.dumps(clean_exclusions), source_id)
        )

        purged_count = 0
        if data.purge_indexed:
            for ep in clean_exclusions:
                abs_prefix = str(Path(ep).resolve()) if os.path.isabs(ep) else str((root / ep).resolve())
                cur = tx.cursor()
                cur.execute(
                    "DELETE FROM files WHERE source_id = ? AND (abs_path = ? OR abs_path LIKE ?)",
                    (source_id, abs_prefix, abs_prefix + "\\%")
                )
                purged_count += cur.rowcount

    return {
        "source_id": source_id,
        "excluded_count": len(clean_exclusions),
        "purged_files_count": purged_count,
        "message": f"Updated exclusions ({len(clean_exclusions)} folders deselected, {purged_count} files removed from catalog)."
    }

@app.post("/api/utils/list_subfolders")
def list_directory_subfolders(payload: Dict[str, Any]):
    target_path = payload.get("path", "").strip()
    include_counts = payload.get("include_counts", True)
    if not target_path:
        return {"subfolders": [], "direct_photo_count": 0, "folder_name": "", "folder_path": ""}

    p = Path(target_path).resolve()
    if not p.exists() or not p.is_dir():
        return {"subfolders": [], "direct_photo_count": 0, "folder_name": "", "folder_path": ""}

    system_skips = {"$recycle.bin", "system volume information", ".git", ".idea", ".vscode", "node_modules", ".gemini", "_proofs", "proofs"}
    valid_exts = set(PHOTO_EXTS) | set(RAW_EXTS)
    subfolders = []
    direct_photo_count = 0

    try:
        with os.scandir(str(p)) as it:
            for entry in sorted(it, key=lambda e: e.name.lower()):
                if entry.is_dir(follow_symlinks=False):
                    nl = entry.name.lower()
                    if nl in system_skips or nl.startswith(("_proof", "_web_proof")) or nl.endswith(("_proofs", "_proof", "proofs")) or "_proofs" in nl:
                        continue
                    sub_p = str(Path(entry.path).resolve())
                    sub_item = {
                        "name": entry.name,
                        "path": sub_p,
                        "rel_path": entry.name,
                        "photo_count": 0
                    }
                    if include_counts:
                        try:
                            c = 0
                            with os.scandir(entry.path) as sub_it:
                                for se in sub_it:
                                    if se.is_file() and Path(se.name).suffix.lower() in valid_exts:
                                        c += 1
                            sub_item["photo_count"] = c
                        except Exception:
                            pass
                    subfolders.append(sub_item)
                elif entry.is_file():
                    if Path(entry.name).suffix.lower() in valid_exts:
                        direct_photo_count += 1
    except Exception:
        pass

    return {
        "subfolders": subfolders,
        "direct_photo_count": direct_photo_count,
        "folder_name": p.name if p.name else str(p),
        "folder_path": str(p)
    }

@app.get("/api/sources/{source_id}/photos")
def get_source_photos(source_id: int):
    """Returns all active photos and RAW files for the given source without artificial limits."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, abs_path, filename, size_bytes, media_type
        FROM files
        WHERE source_id = ? AND status = 'active'
          AND media_type IN ('photo', 'raw')
          AND ext NOT IN ('.xmp', '.thm', '.lrf', '.xml', '.json', '.txt')
        ORDER BY filename ASC
    """, (source_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    return {"photos": rows, "total": len(rows)}

@app.delete("/api/sources/{source_id}")
def delete_source(source_id: int):
    conn = get_db()
    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    conn.commit()
    return {"message": "Source removed"}

@app.post("/api/sources/{source_id}/scan")
def trigger_scan(source_id: int, background_tasks: BackgroundTasks):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, path FROM sources WHERE id = ?", (source_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    def run_indexer():
        scan_progress[source_id] = {"status": "scanning", "scanned": 0, "size": 0}
        def on_prog(p):
            scan_progress[source_id] = p
        
        indexer = SourceIndexer(source_id, row["path"], progress_cb=on_prog)
        indexer.scan()

        # Run blur analysis in background
        culler = CullingEngine()
        culler.analyze_source(source_id)
        scan_progress[source_id] = {"status": "idle", "scanned": indexer.scanned_count}

    background_tasks.add_task(run_indexer)
    return {"message": "Scan started in background"}

@app.get("/api/sources/{source_id}/scan_status")
def get_scan_status(source_id: int):
    return scan_progress.get(source_id, {"status": "idle"})

# ----------------- DASHBOARD STATS -----------------

@app.get("/api/stats")
def get_stats():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            COUNT(*) as total_files,
            COALESCE(SUM(size_bytes), 0) as total_size,
            SUM(CASE WHEN media_type = 'raw' THEN 1 ELSE 0 END) as raw_count,
            SUM(CASE WHEN media_type = 'photo' THEN 1 ELSE 0 END) as photo_count,
            SUM(CASE WHEN media_type = 'video' THEN 1 ELSE 0 END) as video_count,
            SUM(CASE WHEN media_type = 'sidecar' THEN 1 ELSE 0 END) as sidecar_count,
            SUM(CASE WHEN media_type = 'raw' THEN size_bytes ELSE 0 END) as raw_size,
            SUM(CASE WHEN media_type = 'video' THEN size_bytes ELSE 0 END) as video_size
        FROM files WHERE status = 'active'
    """)
    media = dict(cursor.fetchone())

    # Blurry count & potential reclaim
    cursor.execute("""
        SELECT COUNT(*) as blurry_count, COALESCE(SUM(f.size_bytes), 0) as blurry_size
        FROM culling c
        JOIN files f ON c.file_id = f.id
        WHERE c.is_blurry = 1 AND f.status = 'active'
    """)
    blurry = dict(cursor.fetchone())

    # Duplicates potential savings
    dupes = DuplicateDetector.find_duplicates()
    dupe_savings = sum(d["potential_savings_bytes"] for d in dupes)

    # Transcode potential savings (est. 65% reduction on videos)
    cursor.execute("SELECT COALESCE(SUM(size_bytes), 0) as vid_bytes FROM files WHERE media_type = 'video' AND status = 'active'")
    vid_bytes = cursor.fetchone()["vid_bytes"]
    transcode_savings_est = int(vid_bytes * 0.65)

    return {
        "media": media,
        "blurry": blurry,
        "duplicate_savings_bytes": dupe_savings,
        "transcode_savings_est_bytes": transcode_savings_est,
        "total_potential_savings_bytes": blurry["blurry_size"] + dupe_savings + transcode_savings_est
    }

# ----------------- CULLING & BLUR -----------------

@app.get("/api/culling")
def get_culling_items(threshold: float = 25.0, source_id: Optional[int] = None, burst_only: bool = False, limit: int = 80, offset: int = 0):
    conn = get_db()
    cursor = conn.cursor()

    query = """
        SELECT f.id, f.abs_path, f.filename, f.size_bytes, f.media_type, f.pair_id,
               c.blur_score, c.is_blurry, c.burst_group, c.is_burst_best, c.disposition,
               m.camera_model, m.capture_date, s.label as source_label
        FROM files f
        JOIN culling c ON f.id = c.file_id
        LEFT JOIN media_meta m ON f.id = m.file_id
        JOIN sources s ON f.source_id = s.id
        WHERE f.status = 'active'
    """
    params = []
    if source_id:
        query += " AND f.source_id = ?"
        params.append(source_id)
    if burst_only:
        query += " AND c.burst_group IS NOT NULL"

    query += " ORDER BY c.blur_score ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(query, params)
    items = [dict(r) for r in cursor.fetchall()]
    return items

@app.post("/api/culling/action")
def execute_culling(data: CullingAction):
    res = CullingEngine.execute_culling_action(data.file_ids, data.action, data.include_sidecars)
    return res

# ----------------- DUPLICATES -----------------

@app.get("/api/duplicates")
def get_duplicates(source_id: Optional[int] = None, cross_source_only: bool = False, same_name_only: bool = True):
    return DuplicateDetector.find_duplicates(source_id, cross_source_only, same_name_only)

@app.post("/api/duplicates/resolve")
def resolve_duplicates(file_ids: List[int], action: str = "trash"):
    res = CullingEngine.execute_culling_action(file_ids, action, include_sidecars=True)
    return res

# ----------------- UTILITIES & FOLDER PICKER -----------------

@app.post("/api/utils/pick_folder")
def pick_folder():
    """Opens native Windows folder picker dialog."""
    import tkinter as tk
    from tkinter import filedialog
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected_dir = filedialog.askdirectory(title="Select Drive or Folder for SaveSpace", master=root)
        root.destroy()
        if selected_dir:
            p = Path(selected_dir).resolve()
            label = p.name if p.name else str(p)
            return {"path": str(p), "label": label, "selected": True}
        return {"path": "", "label": "", "selected": False}
    except Exception as e:
        return {"path": "", "label": "", "error": str(e), "selected": False}

@app.post("/api/utils/pick_file")
def pick_file(payload: Optional[Dict[str, Any]] = None):
    """Opens native Windows file picker dialog."""
    import tkinter as tk
    from tkinter import filedialog
    payload = payload or {}
    title = payload.get("title", "Select Logo or Watermark Image")
    file_type_mode = payload.get("type", "image")

    if file_type_mode in ("image", "logo"):
        filetypes = [
            ("Image Files (*.png;*.jpg;*.jpeg;*.webp)", "*.png;*.jpg;*.jpeg;*.webp"),
            ("PNG Transparent Logos (*.png)", "*.png"),
            ("All Files (*.*)", "*.*")
        ]
    else:
        filetypes = [("All Files (*.*)", "*.*")]

    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected_file = filedialog.askopenfilename(
            title=title,
            filetypes=filetypes,
            master=root
        )
        root.destroy()
        if selected_file:
            p = Path(selected_file).resolve()
            return {"path": str(p), "filename": p.name, "selected": True}
        return {"path": "", "filename": "", "selected": False}
    except Exception as e:
        return {"path": "", "filename": "", "error": str(e), "selected": False}

# ----------------- TRANSCODING -----------------

@app.get("/api/transcodes/candidates")
def get_transcode_candidates(
    source_id: Optional[int] = None,
    min_size_mb: int = 50,
    codec: Optional[str] = None,
    search: Optional[str] = None,
    suitability: Optional[str] = None
):
    conn = get_db()
    cursor = conn.cursor()
    min_bytes = min_size_mb * 1024 * 1024

    query = """
        SELECT f.id, f.abs_path, f.rel_path, f.filename, f.size_bytes, m.video_codec, m.duration_sec, m.width, m.height, m.bitrate, m.fps,
               s.label as source_label, s.id as source_id, s.path as source_root,
               t.status as transcode_status, t.saved_bytes, t.progress as transcode_progress
        FROM files f
        LEFT JOIN media_meta m ON f.id = m.file_id
        JOIN sources s ON f.source_id = s.id
        LEFT JOIN transcodes t ON f.id = t.source_file_id
        WHERE f.media_type = 'video' AND f.size_bytes >= ? AND f.status = 'active'
    """
    params = [min_bytes]

    if source_id:
        query += " AND f.source_id = ?"
        params.append(source_id)

    if codec:
        query += " AND LOWER(m.video_codec) LIKE ?"
        params.append(f"%{codec.lower()}%")

    if search:
        query += " AND LOWER(f.filename) LIKE ?"
        params.append(f"%{search.lower()}%")

    query += " ORDER BY f.size_bytes DESC"
    cursor.execute(query, params)
    candidates = [dict(r) for r in cursor.fetchall()]
    filtered_candidates = []

    for c in candidates:
        abs_p = c.get("abs_path")
        if abs_p:
            p = Path(abs_p)
            parent = p.parent
            parent_name = parent.name
            if not parent_name:
                parent_name = f"{parent.drive}\\ (Root)" if parent.drive else "Root"
            c["folder_name"] = parent_name
            c["folder_path"] = str(parent)
        else:
            c["folder_name"] = ""
            c["folder_path"] = ""

        # Compute intelligent compression suitability & bitrate advice
        advice = analyze_video_suitability(
            codec=c.get("video_codec"),
            width=c.get("width") or 0,
            height=c.get("height") or 0,
            duration_sec=c.get("duration_sec") or 0.0,
            size_bytes=c.get("size_bytes") or 0,
            reported_bitrate=c.get("bitrate") or 0,
            fps=c.get("fps") or 0.0
        )
        c.update(advice)

        # Apply suitability filter if requested
        if suitability == "recommended":
            if not c.get("is_recommended"):
                continue
        elif suitability == "high_savings":
            if c.get("suitability") != "high_savings":
                continue
        elif suitability == "already_compact":
            if c.get("suitability") != "already_compact":
                continue
        elif suitability == "already_hevc":
            if c.get("suitability") != "already_hevc":
                continue

        filtered_candidates.append(c)

    return filtered_candidates

@app.get("/api/transcodes/queue")
def get_transcode_queue():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.*, f.filename, f.abs_path as source_path, f.rel_path, s.label as source_label, s.path as source_root
        FROM transcodes t
        JOIN files f ON t.source_file_id = f.id
        JOIN sources s ON f.source_id = s.id
        ORDER BY t.id DESC
    """)
    items = [dict(r) for r in cursor.fetchall()]
    for item in items:
        sp = item.get("source_path")
        if sp:
            p = Path(sp)
            parent = p.parent
            parent_name = parent.name
            if not parent_name:
                parent_name = f"{parent.drive}\\ (Root)" if parent.drive else "Root"
            item["folder_name"] = parent_name
            item["folder_path"] = str(parent)
        else:
            item["folder_name"] = ""
            item["folder_path"] = ""

    # Calculate overall queue metrics
    total_jobs = len(items)
    completed_jobs = sum(1 for i in items if i["status"] == "completed")
    pending_jobs = sum(1 for i in items if i["status"] == "pending")
    active_job = next((i for i in items if i["status"] == "transcoding"), None)
    total_orig_bytes = sum(i["original_size"] for i in items)
    total_saved_bytes = sum(i["saved_bytes"] or 0 for i in items if i["status"] == "completed")

    # Queue progress percentage
    if total_jobs == 0:
        overall_progress = 0.0
    else:
        # Sum completed jobs as 100% plus active job's progress
        weighted_sum = sum(100.0 if i["status"] == "completed" else (i["progress"] if i["status"] == "transcoding" else 0.0) for i in items)
        overall_progress = round(weighted_sum / total_jobs, 1)

    return {
        "items": items,
        "summary": {
            "total_jobs": total_jobs,
            "completed_jobs": completed_jobs,
            "pending_jobs": pending_jobs,
            "has_active": active_job is not None,
            "active_job": active_job,
            "overall_progress": overall_progress,
            "total_orig_bytes": total_orig_bytes,
            "total_saved_bytes": total_saved_bytes,
            "is_running": transcode_queue.is_running,
            "is_paused": transcode_queue.current_job.is_paused if transcode_queue.current_job else False
        }
    }

@app.get("/api/transcodes/profiles")
def get_transcode_profiles():
    return {
        "profiles": TRANSCODE_PROFILES,
        "performance_modes": PERFORMANCE_MODES,
        "current_perf_mode": transcode_queue.perf_mode
    }

@app.post("/api/transcodes/queue")
def queue_transcode(req: TranscodeRequest):
    queued_ids = []
    for fid in req.file_ids:
        jid = transcode_queue.add_job(fid, profile_key=req.profile, dest_dir=req.output_dir)
        queued_ids.append(jid)
    return {"queued": queued_ids, "count": len(queued_ids)}

@app.post("/api/transcodes/control")
def control_transcode(action: str, value: Optional[str] = None):
    if action == "start":
        transcode_queue.start_worker_if_needed()
    elif action == "pause":
        transcode_queue.pause_current()
    elif action == "resume":
        transcode_queue.resume_current()
    elif action == "set_perf_mode" and value:
        transcode_queue.set_performance_mode(value)
    elif action == "cancel" and value:
        transcode_queue.cancel_job(int(value))
    elif action == "clear_completed":
        with db_transaction() as tx:
            tx.execute("DELETE FROM transcodes WHERE status IN ('completed', 'cancelled')")
    return {"status": "ok", "current_mode": transcode_queue.perf_mode}

# ----------------- SYNC MATRIX -----------------

@app.get("/api/sync/matrix")
def get_sync_matrix(working_source_id: int, backup_source_id: int):
    return SyncTracker.get_sync_matrix(working_source_id, backup_source_id)

@app.post("/api/sync/reclaim")
def reclaim_safe_space(file_ids: List[int], action: str = "trash"):
    return SyncTracker.reclaim_safe_files(file_ids, action)

# ----------------- ORGANIZER -----------------

@app.post("/api/organize/preview")
def preview_organize(rule: OrganizeRule):
    return FileOrganizer.preview_organization(rule.source_id, rule.destination_root, rule.pattern)

@app.post("/api/organize/execute")
def execute_organize(rule: OrganizeRule):
    plan = FileOrganizer.preview_organization(rule.source_id, rule.destination_root, rule.pattern)
    return FileOrganizer.execute_organization(plan, operation="move")

# ----------------- THUMBNAILS & STREAMING -----------------

THUMB_CACHE_HEADERS = {
    "Cache-Control": "public, max-age=31536000, immutable"
}

@app.get("/api/thumbnail/{file_id}")
def get_thumbnail(file_id: int):
    # Ultra-fast path: return cached thumbnail directly from disk without SQLite lock
    cached_thumb = THUMBNAILS_DIR / f"{file_id}.jpg"
    if cached_thumb.is_file():
        return FileResponse(str(cached_thumb), media_type="image/jpeg", headers=THUMB_CACHE_HEADERS)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT abs_path FROM files WHERE id = ?", (file_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="File not found")

    thumb = generate_thumbnail(row["abs_path"], file_id)
    if thumb and os.path.isfile(thumb):
        return FileResponse(thumb, media_type="image/jpeg", headers=THUMB_CACHE_HEADERS)
    
    # Fallback to direct file if standard image
    ext = Path(row["abs_path"]).suffix.lower()
    if ext in PHOTO_EXTS and os.path.isfile(row["abs_path"]):
        return FileResponse(row["abs_path"], headers=THUMB_CACHE_HEADERS)

    raise HTTPException(status_code=404, detail="Thumbnail unavailable")

@app.get("/api/thumbnail_by_path")
def get_thumbnail_by_path(path: str):
    """Returns or generates a cached 380x380 thumbnail for an arbitrary file path (supports RAW & standard photos)."""
    if not path:
        raise HTTPException(status_code=400, detail="Path parameter required")

    p = Path(path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="File not found on disk")

    cache_key = hashlib.md5(str(p.resolve()).encode("utf-8")).hexdigest()
    thumb_path = THUMBNAILS_DIR / f"thumb_path_{cache_key}.jpg"
    if thumb_path.is_file():
        return FileResponse(str(thumb_path), media_type="image/jpeg", headers=THUMB_CACHE_HEADERS)

    img = open_image_source(str(p))
    if not img:
        # If standard photo, try direct file fallback
        ext = p.suffix.lower()
        if ext in PHOTO_EXTS:
            return FileResponse(str(p), headers=THUMB_CACHE_HEADERS)
        raise HTTPException(status_code=415, detail="Unable to extract thumbnail from media")

    try:
        img.thumbnail((380, 380), Image.Resampling.BILINEAR)
        rgb_img = img.convert("RGB")
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        rgb_img.save(str(thumb_path), "JPEG", quality=80, optimize=True)
        return FileResponse(str(thumb_path), media_type="image/jpeg", headers=THUMB_CACHE_HEADERS)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate thumbnail: {e}")

@app.get("/api/preview_by_path")
def get_preview_by_path(path: str, max_dim: int = 1600):
    """Returns or generates a crisp high-resolution preview image (up to max_dim) for lightbox viewing."""
    if not path:
        raise HTTPException(status_code=400, detail="Path parameter required")

    p = Path(path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="File not found on disk")

    cache_key = hashlib.md5(f"{str(p.resolve())}_{max_dim}".encode("utf-8")).hexdigest()
    prev_path = THUMBNAILS_DIR / f"prev_path_{cache_key}.jpg"
    if prev_path.is_file():
        return FileResponse(str(prev_path), media_type="image/jpeg", headers=THUMB_CACHE_HEADERS)

    img = open_image_source(str(p))
    if not img:
        ext = p.suffix.lower()
        if ext in PHOTO_EXTS:
            return FileResponse(str(p), headers=THUMB_CACHE_HEADERS)
        raise HTTPException(status_code=415, detail="Unable to extract preview from media")

    try:
        w, h = img.size
        if max(w, h) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.BILINEAR)
        rgb_img = img.convert("RGB")
        prev_path.parent.mkdir(parents=True, exist_ok=True)
        rgb_img.save(str(prev_path), "JPEG", quality=85, optimize=True)
        return FileResponse(str(prev_path), media_type="image/jpeg", headers=THUMB_CACHE_HEADERS)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate preview: {e}")

# ----------------- FILE SYSTEM REVEAL / OPEN -----------------

@app.post("/api/files/open-location")
def open_file_location(payload: Dict[str, Any]):
    """
    Reveals a file or folder in native Windows File Explorer (or macOS/Linux equivalent).
    If target is a file, selects/highlights the file in Explorer using explorer.exe /select,"path".
    If open_folder is True, opens the containing directory in Explorer.
    """
    file_id = payload.get("file_id")
    target_path = payload.get("path")
    open_folder = payload.get("open_folder", False)

    if file_id and not target_path:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT abs_path FROM files WHERE id = ?", (file_id,))
        row = cursor.fetchone()
        if row:
            target_path = row["abs_path"]

    if not target_path:
        raise HTTPException(status_code=400, detail="No file path or file_id specified")

    p = Path(target_path).resolve()

    try:
        if sys.platform == "win32":
            if open_folder or p.is_dir():
                folder_to_open = p if p.is_dir() else p.parent
                if folder_to_open.exists():
                    subprocess.Popen(f'explorer.exe "{str(folder_to_open)}"')
                    return {"status": "ok", "opened": str(folder_to_open), "mode": "folder"}
                else:
                    raise HTTPException(status_code=404, detail=f"Folder not found: {folder_to_open}")
            else:
                if p.exists():
                    # explorer.exe /select,"C:\path\to\file" highlights the file
                    subprocess.Popen(f'explorer.exe /select,"{str(p)}"')
                    return {"status": "ok", "opened": str(p), "mode": "file_select"}
                elif p.parent.exists():
                    subprocess.Popen(f'explorer.exe "{str(p.parent)}"')
                    return {"status": "ok", "opened": str(p.parent), "mode": "parent_folder"}
                else:
                    raise HTTPException(status_code=404, detail=f"File not found: {p}")
        elif sys.platform == "darwin":
            if open_folder or p.is_dir():
                folder = p if p.is_dir() else p.parent
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["open", "-R", str(p)])
            return {"status": "ok", "opened": str(p), "mode": "darwin"}
        else:
            folder = p if p.is_dir() else p.parent
            subprocess.Popen(["xdg-open", str(folder)])
            return {"status": "ok", "opened": str(folder), "mode": "linux"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open explorer: {str(e)}")

# ----------------- CLIENT PROOFING & WATERMARKING -----------------

@app.get("/api/proofing/presets")
def api_get_presets():
    return {"presets": get_all_presets()}

@app.post("/api/proofing/presets")
def api_save_preset(payload: Dict[str, Any]):
    name = payload.get("name", "").strip()
    config = payload.get("config", {})
    preset_id = payload.get("id")
    if not name:
        raise HTTPException(status_code=400, detail="Preset name is required")
    if not config:
        raise HTTPException(status_code=400, detail="Preset configuration is required")
    saved = save_preset(name, config, preset_id=preset_id)
    return saved

@app.delete("/api/proofing/presets/{preset_id}")
def api_delete_preset(preset_id: str):
    success = delete_preset(preset_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot delete preset (built-in or not found)")
    return {"status": "deleted", "id": preset_id}

@app.post("/api/proofing/preview")
def preview_watermark(payload: Dict[str, Any]):
    file_id = payload.get("file_id")
    file_path = payload.get("file_path")
    config = payload.get("config", {})

    if file_id and not file_path:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT abs_path FROM files WHERE id = ?", (file_id,))
        row = cursor.fetchone()
        if row:
            file_path = row["abs_path"]

    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(status_code=400, detail="Valid sample file path or file_id required")

    preview_b64 = generate_watermark_preview(file_path, config)
    if not preview_b64:
        raise HTTPException(status_code=500, detail="Failed to generate watermark preview")

    return {"preview_data_url": preview_b64}

@app.post("/api/proofing/batch_watermark")
def start_watermark_batch(payload: Dict[str, Any]):
    file_ids = payload.get("file_ids", [])
    file_paths = payload.get("file_paths", [])
    source_id = payload.get("source_id")
    source_dir = payload.get("source_dir")
    output_dir = (payload.get("output_dir") or "").strip()
    output_mode = payload.get("output_mode") or "custom_dir"  # "custom_dir", "original_folder", "original_subfolder"
    subfolder_name = (payload.get("subfolder_name") or "_proofs").strip()
    subfolder_type = (payload.get("subfolder_type") or "suffix").strip()
    suffix = (payload.get("suffix") or "_proof").strip()
    config = payload.get("config") or {}

    if output_mode == "custom_dir" and not output_dir:
        raise HTTPException(status_code=400, detail="Output destination folder is required for custom directory mode")

    files_to_process = []
    seen = set()

    if file_paths:
        for fp in file_paths:
            p = Path(fp)
            if p.is_file():
                abs_p = str(p.resolve())
                if abs_p not in seen:
                    seen.add(abs_p)
                    files_to_process.append({"abs_path": abs_p, "filename": p.name})
    elif file_ids:
        conn = get_db()
        cursor = conn.cursor()
        placeholders = ",".join("?" * len(file_ids))
        cursor.execute(f"SELECT id, abs_path, filename FROM files WHERE id IN ({placeholders})", file_ids)
        for r in cursor.fetchall():
            abs_p = r["abs_path"]
            if abs_p not in seen:
                seen.add(abs_p)
                files_to_process.append(dict(r))
    elif source_dirs:
        for sdir in source_dirs:
            if sdir and os.path.isdir(sdir):
                p = Path(sdir)
                for entry in p.rglob("*"):
                    if entry.is_file():
                        ext = entry.suffix.lower()
                        if ext in PHOTO_EXTS or ext in RAW_EXTS:
                            abs_p = str(entry.resolve())
                            if abs_p not in seen:
                                seen.add(abs_p)
                                files_to_process.append({"abs_path": abs_p, "filename": entry.name})
    elif source_id:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, abs_path, filename FROM files WHERE source_id = ? AND media_type IN ('photo', 'raw') AND status = 'active'", (source_id,))
        files_to_process = [dict(r) for r in cursor.fetchall()]
    elif source_dir and os.path.isdir(source_dir):
        p = Path(source_dir)
        for entry in p.rglob("*"):
            if entry.is_file():
                ext = entry.suffix.lower()
                if ext in PHOTO_EXTS or ext in RAW_EXTS:
                    abs_p = str(entry.resolve())
                    if abs_p not in seen:
                        seen.add(abs_p)
                        files_to_process.append({"abs_path": abs_p, "filename": entry.name})

    if not files_to_process:
        raise HTTPException(status_code=400, detail="No photos found or selected to watermark")

    started = watermark_manager.start_batch(
        files_to_process,
        output_dir if output_mode == "custom_dir" else None,
        config,
        suffix=suffix,
        output_mode=output_mode,
        subfolder_name=subfolder_name,
        subfolder_type=subfolder_type
    )
    if not started:
        raise HTTPException(status_code=409, detail="A watermarking batch is already running")

    return {
        "status": "started",
        "total_files": len(files_to_process),
        "output_mode": output_mode,
        "output_dir": output_dir if output_mode == "custom_dir" else f"Respective Original Folders ({output_mode})"
    }

@app.get("/api/proofing/batch_status")
def get_watermark_batch_status():
    return watermark_manager.get_status()

@app.post("/api/proofing/cancel_batch")
def cancel_watermark_batch():
    watermark_manager.cancel()
    return {"status": "cancelling"}

@app.post("/api/proofing/generate_contact_sheet")
def generate_contact_sheet(payload: Dict[str, Any]):
    file_ids = payload.get("file_ids", [])
    file_paths = payload.get("file_paths", [])
    source_id = payload.get("source_id")
    source_dir = payload.get("source_dir")
    source_dirs = payload.get("source_dirs", [])
    output_dir = (payload.get("output_dir") or "").strip()
    project_title = (payload.get("project_title") or "Client Proofing Gallery").strip()
    client_name = (payload.get("client_name") or "Valued Client").strip()
    instructions = (payload.get("instructions") or "Click the heart icon on your favorite photos, then click 'Copy Selected Filenames' below to send us your picks.").strip()
    watermark_text = (payload.get("watermark_text") or "PROOF ONLY").strip()

    if not output_dir:
        raise HTTPException(status_code=400, detail="Output directory is required")

    files_to_process = []
    seen = set()

    if file_paths:
        for fp in file_paths:
            p = Path(fp)
            if p.is_file():
                abs_p = str(p.resolve())
                if abs_p not in seen:
                    seen.add(abs_p)
                    files_to_process.append({"abs_path": abs_p, "filename": p.name})
    elif file_ids:
        conn = get_db()
        cursor = conn.cursor()
        placeholders = ",".join("?" * len(file_ids))
        cursor.execute(f"SELECT id, abs_path, filename FROM files WHERE id IN ({placeholders})", file_ids)
        for r in cursor.fetchall():
            abs_p = r["abs_path"]
            if abs_p not in seen:
                seen.add(abs_p)
                files_to_process.append(dict(r))
    elif source_dirs:
        for sdir in source_dirs:
            if sdir and os.path.isdir(sdir):
                p = Path(sdir)
                for entry in p.rglob("*"):
                    if entry.is_file():
                        ext = entry.suffix.lower()
                        if ext in PHOTO_EXTS or ext in RAW_EXTS:
                            abs_p = str(entry.resolve())
                            if abs_p not in seen:
                                seen.add(abs_p)
                                files_to_process.append({"abs_path": abs_p, "filename": entry.name})
    elif source_id:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, abs_path, filename FROM files WHERE source_id = ? AND media_type IN ('photo', 'raw') AND status = 'active'", (source_id,))
        files_to_process = [dict(r) for r in cursor.fetchall()]
    elif source_dir and os.path.isdir(source_dir):
        p = Path(source_dir)
        for entry in p.rglob("*"):
            if entry.is_file():
                ext = entry.suffix.lower()
                if ext in PHOTO_EXTS or ext in RAW_EXTS:
                    abs_p = str(entry.resolve())
                    if abs_p not in seen:
                        seen.add(abs_p)
                        files_to_process.append({"abs_path": abs_p, "filename": entry.name})

    if not files_to_process:
        raise HTTPException(status_code=400, detail="No photos found to include in contact sheet")

    res = generate_contact_sheet_package(
        files=files_to_process,
        output_dir=output_dir,
        project_title=project_title,
        client_name=client_name,
        instructions=instructions,
        watermark_text=watermark_text
    )
    record_last_task(
        task_type="contact_sheet",
        summary=f"Created Contact Sheet '{project_title}' ({len(files_to_process)} photos)",
        details={"output_dir": output_dir, "total_photos": len(files_to_process), "html_path": res.get("html_path")}
    )
    return res

@app.post("/api/proofing/resolve_selects")
def resolve_client_selections(payload: Dict[str, Any]):
    raw_input = payload.get("client_input", "").strip()
    source_dir = payload.get("source_dir")
    source_id = payload.get("source_id")

    queries = parse_client_selects(raw_input)
    if not queries:
        return {
            "matched": [],
            "unmatched": [],
            "total_queries": 0,
            "matched_count": 0,
            "unmatched_count": 0,
            "match_rate_pct": 0.0
        }

    return resolve_selects_against_directory_or_db(queries, source_dir=source_dir, source_id=source_id)

@app.post("/api/proofing/export_selects")
def export_client_selections(payload: Dict[str, Any]):
    items = payload.get("matched_items", [])
    destination_dir = payload.get("destination_dir", "").strip()
    action = payload.get("action", "copy")

    if not destination_dir:
        raise HTTPException(status_code=400, detail="Destination directory is required")
    if not items:
        raise HTTPException(status_code=400, detail="No matched items to export")

    res = execute_selects_export(items, destination_dir, action=action)
    dest_name = Path(destination_dir).name
    record_last_task(
        task_type="selects_export",
        summary=f"Exported {res.get('processed_count', 0)} selects ({action}) to {dest_name}",
        details=res
    )
    return res

@app.post("/api/utils/list_photos")
def list_photos_in_dir(payload: Dict[str, Any]):
    paths = payload.get("paths", [])
    dir_path = payload.get("path", "").strip()
    folder_items = payload.get("folder_items", [])
    if dir_path:
        paths.append(dir_path)

    # Build targets: List[Tuple[Path, bool]]
    scan_targets = []
    if folder_items:
        for item in folder_items:
            p_str = item.get("path", "").strip()
            if p_str and os.path.isdir(p_str):
                scan_targets.append((Path(p_str), item.get("recursive", True)))
    else:
        for dp in paths:
            dp_clean = dp.strip()
            if dp_clean and os.path.isdir(dp_clean):
                scan_targets.append((Path(dp_clean), True))

    if not scan_targets:
        return {"photos": [], "total": 0}

    photos = []
    seen = set()
    valid_exts = set(PHOTO_EXTS) | set(RAW_EXTS)

    try:
        for root_p, is_rec in scan_targets:
            if is_rec:
                entries_iter = root_p.rglob("*")
            else:
                entries_iter = root_p.glob("*")

            for entry in entries_iter:
                if entry.is_file():
                    # Skip previously exported proof subfolders
                    if any(part.lower() in ("proofs", "_proofs") or part.lower().startswith(("_proof", "_web_proof")) or part.lower().endswith(("_proofs", "_proof", "proofs")) or "_proofs" in part.lower() for part in entry.parts[:-1]):
                        continue
                    ext = entry.suffix.lower()
                    if ext in valid_exts:
                        abs_p = str(entry.resolve())
                        if abs_p not in seen:
                            seen.add(abs_p)
                            photos.append({
                                "abs_path": abs_p,
                                "filename": entry.name,
                                "size_bytes": entry.stat().st_size,
                                "folder_name": entry.parent.name,
                                "folder_path": str(entry.parent)
                            })
    except Exception:
        pass

    limit = payload.get("limit")
    if limit and isinstance(limit, int) and limit > 0:
        return {"photos": photos[:limit], "total": len(photos)}
    return {"photos": photos, "total": len(photos)}

# ----------------- SESSION STATE & TASK MEMORY -----------------

@app.get("/api/session/state")
def api_get_session_state():
    return get_session_state()

@app.post("/api/session/state")
def api_save_session_state(payload: Dict[str, Any]):
    return save_session_state(payload)

# ----------------- APPLICATION LOGGING & MONITORING -----------------

@app.get("/api/logs/recent")
def api_get_recent_logs(lines: int = 150):
    if not LOG_FILE.exists():
        return {
            "path": str(LOG_FILE),
            "size_bytes": 0,
            "lines": ["No log entries recorded yet."]
        }
    try:
        size = LOG_FILE.stat().st_size
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
            recent = all_lines[-lines:] if len(all_lines) > lines else all_lines
        return {
            "path": str(LOG_FILE),
            "size_bytes": size,
            "lines": [line.rstrip("\r\n") for line in recent]
        }
    except Exception as e:
        logger.error(f"Failed to read log file: {e}")
        return {
            "path": str(LOG_FILE),
            "size_bytes": 0,
            "lines": [f"Error reading log file: {e}"]
        }

@app.post("/api/logs/open")
def api_open_logs_folder():
    try:
        if os.name == "nt":
            os.startfile(str(LOGS_DIR))
        else:
            subprocess.Popen(["xdg-open", str(LOGS_DIR)])
        logger.info(f"Opened logs directory: {LOGS_DIR}")
        return {"status": "opened", "path": str(LOGS_DIR)}
    except Exception as e:
        logger.error(f"Failed to open logs directory: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to open logs folder: {e}")

# Serve Frontend static assets
UI_DIR = BASE_DIR / "ui"
if UI_DIR.exists():
    app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
