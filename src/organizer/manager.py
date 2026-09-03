import os
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from src.core.db import get_db
from src.scanner.sidecar import find_sidecars_for_file

class FileOrganizer:
    @staticmethod
    def preview_organization(source_id: int, target_root: str, pattern: str = "{year}/{year}-{month}/{camera}/{filename}") -> List[Dict[str, Any]]:
        """
        Generates a dry-run plan of organized file destinations with sidecar locking.
        """
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT f.id, f.abs_path, f.filename, f.ext, f.media_type, f.mtime,
                   m.capture_date, m.camera_model
            FROM files f
            LEFT JOIN media_meta m ON f.id = m.file_id
            WHERE f.source_id = ? AND f.status = 'active'
        """, (source_id,))
        rows = cursor.fetchall()

        plan = []
        target_base = Path(target_root).resolve()

        for r in rows:
            abs_p = Path(r["abs_path"])
            fname = r["filename"]
            
            # Determine date
            date_str = r["capture_date"]
            dt = None
            if date_str:
                for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        clean_d = date_str.split(".")[0].replace("Z", "")
                        dt = datetime.strptime(clean_d, fmt)
                        break
                    except Exception:
                        pass

            if not dt:
                dt = datetime.fromtimestamp(r["mtime"])

            year = dt.strftime("%Y")
            month = dt.strftime("%m")
            day = dt.strftime("%d")
            date_formatted = dt.strftime("%Y-%m-%d")
            camera = (r["camera_model"] or "UnknownCamera").replace(" ", "_")

            # Resolve pattern
            rel_dir = pattern.replace("{year}", year)\
                             .replace("{month}", month)\
                             .replace("{year}-{month}", f"{year}-{month}")\
                             .replace("{day}", day)\
                             .replace("{date}", date_formatted)\
                             .replace("{camera}", camera)\
                             .replace("{filename}", fname)

            dest_file = target_base / rel_dir
            sidecars = find_sidecars_for_file(str(abs_p))
            sidecar_moves = []
            for sc in sidecars:
                sc_p = Path(sc)
                # Map sidecar extension onto dest
                if sc_p.name.lower().endswith(".xmp"):
                    sc_dest = dest_file.parent / f"{dest_file.stem}{sc_p.suffix}"
                    sidecar_moves.append({"source": str(sc_p), "dest": str(sc_dest)})

            plan.append({
                "file_id": r["id"],
                "source_path": str(abs_p),
                "dest_path": str(dest_file),
                "sidecars": sidecar_moves
            })

        return plan

    @staticmethod
    def execute_organization(plan: List[Dict[str, Any]], operation: str = "move") -> Dict[str, Any]:
        """
        Executes file moves/copies along with sidecars atomically.
        """
        conn = get_db()
        cursor = conn.cursor()
        success_count = 0
        errors = []

        for item in plan:
            src = Path(item["source_path"])
            dst = Path(item["dest_path"])

            if not src.exists():
                continue

            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if operation == "move":
                    shutil.move(str(src), str(dst))
                    cursor.execute("UPDATE files SET abs_path = ?, rel_path = ? WHERE id = ?", 
                                   (str(dst), dst.name, item["file_id"]))
                else:
                    shutil.copy2(str(src), str(dst))

                # Handle sidecars
                for sc in item.get("sidecars", []):
                    sc_src = Path(sc["source"])
                    sc_dst = Path(sc["dest"])
                    if sc_src.exists():
                        sc_dst.parent.mkdir(parents=True, exist_ok=True)
                        if operation == "move":
                            shutil.move(str(sc_src), str(sc_dst))
                        else:
                            shutil.copy2(str(sc_src), str(sc_dst))

                success_count += 1
            except Exception as e:
                errors.append(f"Error organizing {src.name}: {str(e)}")

        conn.commit()
        return {"success_count": success_count, "errors": errors}
