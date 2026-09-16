import os
import json
import uuid
import ctypes
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from src.core.db import get_db, db_transaction
from src.core.logger import get_logger

logger = get_logger("volume")

VOLUME_MARKER_FILE = ".focusloop_id"

def get_volume_marker_path(root_path: Path | str) -> Path:
    """Returns the expected path to the .focusloop_id marker file."""
    return Path(root_path).resolve() / VOLUME_MARKER_FILE

def read_volume_uuid(root_path: Path | str) -> Optional[str]:
    """Reads volume_uuid from the .focusloop_id marker file if it exists."""
    marker = get_volume_marker_path(root_path)
    if not marker.exists():
        return None
    try:
        with open(marker, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("volume_uuid")
    except Exception as e:
        logger.warning(f"Failed to read volume marker at {marker}: {e}")
        return None

def get_or_create_volume_uuid(root_path: Path | str, label: Optional[str] = None) -> Optional[str]:
    """
    Retrieves existing volume_uuid from .focusloop_id or creates a new one.
    Attempts to set Windows hidden file attribute so it remains unobtrusive.
    """
    p = Path(root_path).resolve()
    if not p.exists():
        return None

    existing_uuid = read_volume_uuid(p)
    if existing_uuid:
        return existing_uuid

    # Create new volume marker
    vol_uuid = str(uuid.uuid4())
    marker = p / VOLUME_MARKER_FILE
    marker_data = {
        "volume_uuid": vol_uuid,
        "created_at": datetime.now().isoformat(),
        "initial_label": label or p.name or "StorageVolume"
    }

    try:
        with open(marker, "w", encoding="utf-8") as f:
            json.dump(marker_data, f, indent=2)

        # Set Windows hidden attribute if running on Windows
        if os.name == "nt":
            try:
                ctypes.windll.kernel32.SetFileAttributesW(str(marker), 0x02) # FILE_ATTRIBUTE_HIDDEN
            except Exception:
                pass

        logger.info(f"Created new volume fingerprint {vol_uuid} at {marker}")
        return vol_uuid
    except (PermissionError, OSError) as e:
        logger.warning(f"Could not write volume marker to {marker} (read-only filesystem?): {e}")
        return None

def verify_volume_match(root_path: Path | str, expected_uuid: Optional[str]) -> bool:
    """Verifies that the target path contains a marker matching expected_uuid."""
    if not expected_uuid:
        return False
    current_uuid = read_volume_uuid(root_path)
    return current_uuid is not None and current_uuid == expected_uuid

def find_source_by_volume_uuid(volume_uuid: str) -> Optional[Dict[str, Any]]:
    """Looks up a registered source by its volume_uuid."""
    if not volume_uuid:
        return None
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sources WHERE volume_uuid = ?", (volume_uuid,))
    row = cur.fetchone()
    if row:
        return dict(row)
    return None

def update_source_mount_path(source_id: int, new_root_path: str) -> Dict[str, Any]:
    """
    Switches the active mount path of a source to new_root_path.
    Synchronizes alternate_paths list and updates abs_path for all files
    belonging to this source within an atomic database transaction.
    """
    new_root = Path(new_root_path).resolve()
    if not new_root.exists():
        return {"success": False, "error": f"Path '{new_root_path}' does not exist"}

    with db_transaction() as tx:
        cur = tx.cursor()
        cur.execute("SELECT id, path, alternate_paths, volume_uuid, label FROM sources WHERE id = ?", (source_id,))
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": f"Source {source_id} not found"}

        old_root = Path(row["path"]).resolve()

        # Parse and update alternate_paths
        try:
            alts = json.loads(row["alternate_paths"] or "[]")
        except Exception:
            alts = []

        alt_dict = {str(Path(p).resolve()).lower(): str(Path(p).resolve()) for p in alts if p}
        alt_dict[str(old_root).lower()] = str(old_root)
        alt_dict[str(new_root).lower()] = str(new_root)
        updated_alts = list(alt_dict.values())

        # Update source active path
        cur.execute("""
            UPDATE sources 
            SET path = ?, alternate_paths = ?, is_online = 1
            WHERE id = ?
        """, (str(new_root), json.dumps(updated_alts), source_id))

        # Batch update files abs_path based on rel_path
        cur.execute("SELECT id, rel_path FROM files WHERE source_id = ?", (source_id,))
        file_rows = cur.fetchall()

        file_updates = [
            (str((new_root / r["rel_path"]).resolve()), r["id"])
            for r in file_rows
        ]

        if file_updates:
            cur.executemany("UPDATE files SET abs_path = ? WHERE id = ?", file_updates)

        logger.info(
            f"Migrated source {source_id} ('{row['label']}') mount path: "
            f"'{old_root}' -> '{new_root}' ({len(file_updates)} files synchronized)"
        )

    return {
        "success": True,
        "source_id": source_id,
        "old_path": str(old_root),
        "new_path": str(new_root),
        "files_updated": len(file_updates),
        "alternate_paths": updated_alts
    }
