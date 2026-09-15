import os
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional
import cv2
import numpy as np
from datetime import datetime, timedelta
import send2trash

from src.core.db import get_db, db_transaction, db_write_lock
from src.config import QUARANTINE_DIR, RAW_EXTS, PHOTO_EXTS
from src.scanner.meta_extractor import generate_thumbnail
from src.scanner.sidecar import find_sidecars_for_file

def compute_blur_score(image_path: str) -> float:
    """
    Calculates image sharpness score (0 to 100) using Laplacian variance.
    Higher score = sharper. Low score (< 20) = blurry/out-of-focus.
    """
    try:
        img = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return 0.0

        h, w = img.shape
        if max(h, w) > 1024:
            scale = 1024.0 / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        variance = cv2.Laplacian(img, cv2.CV_64F).var()
        norm_score = min(100.0, max(0.0, np.log1p(variance) * 14.5))
        return round(float(norm_score), 1)
    except Exception:
        return 0.0

class CullingEngine:
    def __init__(self, blur_threshold: float = 25.0):
        self.blur_threshold = blur_threshold

    def analyze_source(self, source_id: Optional[int] = None):
        """Analyzes all photos for blur scores and burst groupings without holding DB locks."""
        conn = get_db()
        cursor = conn.cursor()

        query = """
            SELECT f.id, f.abs_path, f.mtime, m.capture_date
            FROM files f
            LEFT JOIN media_meta m ON f.id = m.file_id
            WHERE f.media_type IN ('raw', 'photo') AND f.status = 'active'
              AND f.filename NOT LIKE '$%' AND f.abs_path NOT LIKE '%$recycle.bin%'
        """
        params = []
        if source_id:
            query += " AND f.source_id = ?"
            params.append(source_id)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        for r in rows:
            fid = r["id"]
            abs_p = r["abs_path"]

            cursor.execute("SELECT blur_score FROM culling WHERE file_id = ?", (fid,))
            existing = cursor.fetchone()
            if existing and existing["blur_score"] is not None:
                continue

            # Heavy computation executed completely OUTSIDE DB transaction
            thumb = generate_thumbnail(abs_p, fid)
            eval_path = thumb if thumb else abs_p

            score = compute_blur_score(eval_path)
            is_blurry = 1 if score < self.blur_threshold else 0

            # Instantaneous write transaction
            with db_transaction() as tx:
                tx.execute("""
                    INSERT INTO culling (file_id, blur_score, is_blurry, disposition)
                    VALUES (?, ?, ?, 'review')
                    ON CONFLICT(file_id) DO UPDATE SET blur_score = ?, is_blurry = ?
                """, (fid, score, is_blurry, score, is_blurry))

        self.detect_bursts(source_id)

    def detect_bursts(self, source_id: Optional[int] = None):
        conn = get_db()
        cursor = conn.cursor()

        query = """
            SELECT f.id, f.abs_path, f.mtime, m.capture_date, c.blur_score
            FROM files f
            LEFT JOIN media_meta m ON f.id = m.file_id
            LEFT JOIN culling c ON f.id = c.file_id
            WHERE f.media_type IN ('raw', 'photo') AND f.status = 'active'
        """
        params = []
        if source_id:
            query += " AND f.source_id = ?"
            params.append(source_id)

        query += " ORDER BY f.mtime ASC"
        cursor.execute(query, params)
        rows = cursor.fetchall()

        if not rows:
            return

        burst_groups = []
        current_burst = [rows[0]]

        for i in range(1, len(rows)):
            prev = rows[i - 1]
            curr = rows[i]

            time_diff = abs(curr["mtime"] - prev["mtime"])
            if time_diff <= 1.8:
                current_burst.append(curr)
            else:
                if len(current_burst) >= 2:
                    burst_groups.append(current_burst)
                current_burst = [curr]

        if len(current_burst) >= 2:
            burst_groups.append(current_burst)

        for group in burst_groups:
            group_id = f"burst_{int(group[0]['mtime'])}_{len(group)}"
            best_item = max(group, key=lambda x: (x["blur_score"] or 0))
            with db_transaction() as tx:
                for item in group:
                    is_best = 1 if item["id"] == best_item["id"] else 0
                    tx.execute("""
                        UPDATE culling SET burst_group = ?, is_burst_best = ?
                        WHERE file_id = ?
                    """, (group_id, is_best, item["id"]))

    @staticmethod
    def execute_culling_action(file_ids: List[int], action: str, include_sidecars: bool = True) -> Dict[str, Any]:
        """
        Executes safe culling:
        - trash: Sends to Windows Recycle Bin
        - quarantine: Moves to isolated quarantine directory
        - keep: Flags to keep
        Always moves/trashes paired XMP sidecars atomically!
        """
        conn = get_db()
        cursor = conn.cursor()

        affected_files = []
        errors = []

        for fid in file_ids:
            cursor.execute("SELECT abs_path, filename FROM files WHERE id = ?", (fid,))
            row = cursor.fetchone()
            if not row:
                continue

            target_path = Path(row["abs_path"])
            paths_to_process = [target_path]

            if include_sidecars:
                sidecars = find_sidecars_for_file(str(target_path))
                for sc in sidecars:
                    paths_to_process.append(Path(sc))

            for p in paths_to_process:
                if not p.exists():
                    continue

                try:
                    if action == "trash":
                        send2trash.send2trash(str(p))
                        affected_files.append(str(p))
                    elif action == "quarantine":
                        dest = QUARANTINE_DIR / p.name
                        # Handle collision
                        if dest.exists():
                            dest = QUARANTINE_DIR / f"{p.stem}_{int(datetime.now().timestamp())}{p.suffix}"
                        shutil.move(str(p), str(dest))
                        affected_files.append(str(p))
                    elif action == "keep":
                        affected_files.append(str(p))
                except Exception as e:
                    errors.append(f"Failed on {p.name}: {str(e)}")

            if action in ("trash", "quarantine"):
                cursor.execute("UPDATE files SET status = ? WHERE id = ?", (action, fid))
            elif action == "keep":
                cursor.execute("UPDATE culling SET disposition = 'keep' WHERE file_id = ?", (fid,))

        conn.commit()
        return {
            "action": action,
            "processed_count": len(affected_files),
            "affected_files": affected_files,
            "errors": errors
        }
