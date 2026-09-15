import os
import json
import time
import xxhash
import hashlib
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List
from datetime import datetime
import psutil

from src.config import ALL_MEDIA_EXTS, RAW_EXTS, PHOTO_EXTS, VIDEO_EXTS, SIDECAR_EXTS
from src.core.db import get_db, db_transaction
from src.scanner.sidecar import compute_pair_id, get_base_stem, find_sidecars_for_file
from src.scanner.meta_extractor import extract_image_meta, extract_video_meta

def compute_fast_hash(file_path: str, file_size: int) -> str:
    """Computes xxhash on head, middle, and tail chunks + file size."""
    h = xxhash.xxh64()
    h.update(str(file_size).encode("utf-8"))
    
    CHUNK_SIZE = 64 * 1024 # 64KB
    if file_size <= CHUNK_SIZE * 3:
        try:
            with open(file_path, "rb") as f:
                h.update(f.read())
        except Exception:
            return ""
        return h.hexdigest()

    try:
        with open(file_path, "rb") as f:
            # Head
            h.update(f.read(CHUNK_SIZE))
            # Mid
            f.seek(file_size // 2)
            h.update(f.read(CHUNK_SIZE))
            # Tail
            f.seek(max(0, file_size - CHUNK_SIZE))
            h.update(f.read(CHUNK_SIZE))
    except Exception:
        return ""

    return h.hexdigest()

def compute_full_hash(file_path: str) -> str:
    """Computes complete SHA-256 for exact duplicate verification."""
    h = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(256 * 1024):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""

class SourceIndexer:
    def __init__(self, source_id: int, root_path: str, progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.source_id = source_id
        self.root_path = Path(root_path).resolve()
        self.progress_cb = progress_cb
        self.scanned_count = 0
        self.total_size = 0
        self.is_running = True

    def stop(self):
        self.is_running = False

    def scan(self):
        start_time = time.time()
        conn = get_db()
        cursor = conn.cursor()

        # Update source capacity
        try:
            usage = psutil.disk_usage(str(self.root_path))
            with db_transaction() as tx:
                tx.execute(
                    "UPDATE sources SET total_bytes = ?, free_bytes = ?, is_online = 1 WHERE id = ?",
                    (usage.total, usage.free, self.source_id)
                )
        except Exception:
            pass

        discovered_paths = set()
        pending_items = []

        def flush_pending():
            nonlocal pending_items
            if not pending_items:
                return
            with db_transaction() as tx:
                tx_cur = tx.cursor()
                for item in pending_items:
                    abs_str = item["abs_str"]
                    size = item["size"]
                    mtime = item["mtime"]
                    ctime = item["ctime"]
                    fast_hash = item["fast_hash"]
                    pair_id = item["pair_id"]
                    mtype = item["mtype"]
                    rel_p = item["rel_p"]
                    fname = item["fname"]
                    ext = item["ext"]
                    meta = item.get("meta")

                    tx_cur.execute("SELECT id, size_bytes, mtime FROM files WHERE abs_path = ?", (abs_str,))
                    row = tx_cur.fetchone()

                    if row:
                        file_id = row["id"]
                        if row["size_bytes"] != size or abs(row["mtime"] - mtime) > 1.0:
                            tx_cur.execute("""
                                UPDATE files SET size_bytes = ?, mtime = ?, ctime = ?, fast_hash = ?, pair_id = ?, status = 'active'
                                WHERE id = ?
                            """, (size, mtime, ctime, fast_hash, pair_id, file_id))
                    else:
                        tx_cur.execute("""
                            INSERT INTO files (source_id, rel_path, abs_path, filename, ext, size_bytes, mtime, ctime, media_type, fast_hash, pair_id, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                        """, (self.source_id, rel_p, abs_str, fname, ext, size, mtime, ctime, mtype, fast_hash, pair_id))
                        file_id = tx_cur.lastrowid

                        if meta:
                            tx_cur.execute("""
                                INSERT OR REPLACE INTO media_meta 
                                (file_id, width, height, duration_sec, video_codec, audio_codec, bitrate, fps, camera_make, camera_model, lens, iso, shutter, aperture, capture_date)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                file_id, meta.get("width"), meta.get("height"), meta.get("duration_sec"),
                                meta.get("video_codec"), meta.get("audio_codec"), meta.get("bitrate"),
                                meta.get("fps"), meta.get("camera_make"), meta.get("camera_model"),
                                meta.get("lens"), meta.get("iso"), meta.get("shutter"), meta.get("aperture"),
                                meta.get("capture_date")
                            ))
            pending_items = []

        # Load excluded subfolders for this source
        cursor.execute("SELECT excluded_paths FROM sources WHERE id = ?", (self.source_id,))
        s_row = cursor.fetchone()
        excluded_raw = s_row["excluded_paths"] if s_row and s_row["excluded_paths"] else "[]"
        try:
            excluded_list = json.loads(excluded_raw)
        except Exception:
            excluded_list = []

        excluded_paths_norm = set()
        for ep in excluded_list:
            if not ep:
                continue
            ep_str = str(Path(ep).resolve()).lower() if os.path.isabs(ep) else str((self.root_path / ep).resolve()).lower()
            excluded_paths_norm.add(ep_str)

        system_skips = {"$recycle.bin", "system volume information", ".git", ".idea", ".vscode", "node_modules", ".gemini"}

        for root, dirs, files in os.walk(str(self.root_path)):
            if not self.is_running:
                break

            # In-place directory filtering: prune excluded or system subfolders so os.walk skips them entirely
            kept_dirs = []
            for d in dirs:
                d_lower = d.lower()
                if d_lower in system_skips:
                    continue
                dir_abs = str((Path(root) / d).resolve()).lower()
                is_excluded = False
                for ex in excluded_paths_norm:
                    if dir_abs == ex or dir_abs.startswith(ex + os.sep):
                        is_excluded = True
                        break
                if not is_excluded:
                    kept_dirs.append(d)
            dirs[:] = kept_dirs

            for fname in files:
                if not self.is_running:
                    break

                # Ignore system fragments, Windows Recycle Bin files ($I..., $R...), and hidden files
                if fname.startswith("$") or fname.startswith("._") or fname.startswith("~"):
                    continue
                if "$recycle.bin" in root.lower() or "system volume information" in root.lower():
                    continue

                ext = Path(fname).suffix.lower()
                if ext not in ALL_MEDIA_EXTS:
                    continue

                abs_p = Path(root) / fname
                try:
                    st = abs_p.stat()
                except (PermissionError, FileNotFoundError):
                    continue

                rel_p = str(abs_p.relative_to(self.root_path))
                size = st.st_size
                mtime = st.st_mtime
                ctime = st.st_ctime
                abs_str = str(abs_p.resolve())

                discovered_paths.add(abs_str)
                self.scanned_count += 1
                self.total_size += size

                # Media type classification
                if ext in RAW_EXTS:
                    mtype = "raw"
                elif ext in PHOTO_EXTS:
                    mtype = "photo"
                elif ext in VIDEO_EXTS:
                    mtype = "video"
                elif ext in SIDECAR_EXTS:
                    mtype = "sidecar"
                else:
                    mtype = "other"

                # Sidecar grouping
                base_stem = get_base_stem(abs_p)
                pair_id = compute_pair_id(abs_p.parent, base_stem)
                fast_hash = compute_fast_hash(abs_str, size)

                # Extract metadata in memory first WITHOUT holding DB lock
                meta = {}
                if mtype in ("raw", "photo"):
                    meta = extract_image_meta(abs_str)
                elif mtype == "video":
                    meta = extract_video_meta(abs_str)

                pending_items.append({
                    "abs_str": abs_str,
                    "size": size,
                    "mtime": mtime,
                    "ctime": ctime,
                    "fast_hash": fast_hash,
                    "pair_id": pair_id,
                    "mtype": mtype,
                    "rel_p": rel_p,
                    "fname": fname,
                    "ext": ext,
                    "meta": meta
                })

                if len(pending_items) >= 50:
                    flush_pending()

                if self.scanned_count % 25 == 0 or self.scanned_count == 1:
                    if self.progress_cb:
                        self.progress_cb({
                            "source_id": self.source_id,
                            "scanned_count": self.scanned_count,
                            "total_size": self.total_size,
                            "current_file": fname,
                            "elapsed_sec": round(time.time() - start_time, 1)
                        })

        # Flush any remaining items
        flush_pending()

        # Update last scanned time
        with db_transaction() as tx:
            tx.execute("UPDATE sources SET last_scanned = ? WHERE id = ?", (datetime.now().isoformat(), self.source_id))

        if self.progress_cb:
            self.progress_cb({
                "source_id": self.source_id,
                "scanned_count": self.scanned_count,
                "total_size": self.total_size,
                "status": "completed",
                "elapsed_sec": round(time.time() - start_time, 1)
            })
