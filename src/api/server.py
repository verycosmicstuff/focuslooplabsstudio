import os
import sys
import json
import subprocess
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import psutil

from src.config import (
    BASE_DIR, THUMBNAILS_DIR, PERFORMANCE_MODES, DEFAULT_PORT, DEFAULT_HOST,
    RAW_EXTS, PHOTO_EXTS, VIDEO_EXTS
)
from src.core.db import get_db, init_db
from src.core.models import SourceCreate, CullingAction, TranscodeRequest, OrganizeRule
from src.scanner.indexer import SourceIndexer
from src.scanner.meta_extractor import generate_thumbnail
from src.analyzer.culler import CullingEngine, compute_blur_score
from src.analyzer.deduper import DuplicateDetector
from src.transcoder.engine import transcode_queue, TRANSCODE_PROFILES
from src.transcoder.handbrake import HandBrakeBridge
from src.sync.tracker import SyncTracker
from src.organizer.manager import FileOrganizer
from src.analyzer.video_advisor import analyze_video_suitability, format_bitrate

app = FastAPI(title="SaveSpace Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
            INSERT INTO sources (path, label, drive_type, total_bytes, free_bytes, is_online)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (str(p), data.label, data.drive_type or "LOCAL", total_b, free_b))
        conn.commit()
        return {"id": cursor.lastrowid, "message": "Source registered successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Source already registered or invalid: {str(e)}")

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

# Serve Frontend static assets
UI_DIR = BASE_DIR / "ui"
if UI_DIR.exists():
    app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
