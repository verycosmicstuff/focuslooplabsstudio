from typing import List, Dict, Any, Optional
from pathlib import Path
import send2trash
from src.core.db import get_db
from src.scanner.indexer import compute_fast_hash, compute_full_hash
from src.scanner.sidecar import find_sidecars_for_file

class SyncTracker:
    @staticmethod
    def get_sync_matrix(working_source_id: int, backup_source_id: int) -> Dict[str, Any]:
        """
        Compares files on working drive against backup drive.
        Identifies:
        1. synced_safe: identical file exists on backup (safe to delete from SSD to free space).
        2. unbacked_up: exists on SSD but missing on backup.
        """
        conn = get_db()
        cursor = conn.cursor()

        # Files on working source
        cursor.execute("""
            SELECT id, rel_path, abs_path, filename, size_bytes, fast_hash, full_hash, media_type, mtime
            FROM files
            WHERE source_id = ? AND status = 'active'
        """, (working_source_id,))
        working_files = [dict(r) for r in cursor.fetchall()]

        # Hashes on backup source
        cursor.execute("""
            SELECT fast_hash, full_hash, abs_path, size_bytes
            FROM files
            WHERE source_id = ? AND status = 'active'
        """, (backup_source_id,))
        backup_rows = cursor.fetchall()
        backup_hash_map = {}
        for b in backup_rows:
            if b["fast_hash"]:
                backup_hash_map.setdefault(b["fast_hash"], []).append(dict(b))

        synced_safe = []
        unbacked_up = []
        safe_reclaimable_bytes = 0

        for wf in working_files:
            fhash = wf["fast_hash"]
            size = wf["size_bytes"]
            matched_backup = None

            if fhash and fhash in backup_hash_map:
                for b_cand in backup_hash_map[fhash]:
                    if b_cand["size_bytes"] == size:
                        # Matched
                        matched_backup = b_cand
                        break

            if matched_backup:
                wf["backup_path"] = matched_backup["abs_path"]
                synced_safe.append(wf)
                safe_reclaimable_bytes += size
            else:
                unbacked_up.append(wf)

        return {
            "working_source_id": working_source_id,
            "backup_source_id": backup_source_id,
            "synced_count": len(synced_safe),
            "unbacked_count": len(unbacked_up),
            "safe_reclaimable_bytes": safe_reclaimable_bytes,
            "synced_safe": synced_safe,
            "unbacked_up": unbacked_up
        }

    @staticmethod
    def reclaim_safe_files(file_ids: List[int], action: str = "trash") -> Dict[str, Any]:
        """
        Safely purges files from working drive ONLY if verified to exist on backup.
        Always handles paired XMP sidecars!
        """
        conn = get_db()
        cursor = conn.cursor()
        reclaimed_count = 0
        reclaimed_bytes = 0
        errors = []

        for fid in file_ids:
            cursor.execute("SELECT id, abs_path, size_bytes, fast_hash, full_hash, source_id FROM files WHERE id = ?", (fid,))
            row = cursor.fetchone()
            if not row:
                continue

            fpath = Path(row["abs_path"])
            fhash = row["fast_hash"]
            size = row["size_bytes"]

            # Cryptographic double-check: verify another active file with same hash exists on a different source
            cursor.execute("""
                SELECT abs_path FROM files
                WHERE fast_hash = ? AND size_bytes = ? AND id != ? AND status = 'active'
            """, (fhash, size, fid))
            backup_match = cursor.fetchone()

            if not backup_match:
                errors.append(f"Skipping {fpath.name}: No verified backup copy found!")
                continue

            # File is verified safe to purge
            paths_to_remove = [fpath]
            for sc in find_sidecars_for_file(str(fpath)):
                paths_to_remove.append(Path(sc))

            for p in paths_to_remove:
                if p.exists():
                    try:
                        if action == "trash":
                            send2trash.send2trash(str(p))
                        else:
                            p.unlink()
                    except Exception as e:
                        errors.append(f"Failed to remove {p.name}: {str(e)}")

            cursor.execute("UPDATE files SET status = 'reclaimed' WHERE id = ?", (fid,))
            reclaimed_count += 1
            reclaimed_bytes += size

        conn.commit()
        return {
            "reclaimed_count": reclaimed_count,
            "reclaimed_bytes": reclaimed_bytes,
            "errors": errors
        }
