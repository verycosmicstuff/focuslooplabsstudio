import os
import time
import shutil
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.core.logger import get_logger

logger = get_logger("backup_doctor")

class BackupDoctor:
    """
    Audits and repairs backup folders, identifying 0-byte stubs,
    corrupted/truncated files, missing items, and size mismatches
    between master/source and backup destinations.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._cancel_event = threading.Event()
        self.repair_state: Dict[str, Any] = {
            "is_running": False,
            "source_path": "",
            "target_path": "",
            "mode": "",
            "current_file": "",
            "total_files": 0,
            "completed_files": 0,
            "total_bytes": 0,
            "transferred_bytes": 0,
            "progress_pct": 0.0,
            "speed_mb_s": 0.0,
            "errors": [],
            "start_time": 0.0,
            "status": "idle" # idle, running, completed, cancelled, error
        }

    def audit_folders(
        self,
        source_dir: str,
        target_dir: str
    ) -> Dict[str, Any]:
        """
        Recursively scans source and target directories,
        comparing files by relative path and byte size.
        """
        src = Path(source_dir.strip())
        tgt = Path(target_dir.strip())

        if not src.exists() or not src.is_dir():
            raise ValueError(f"Source folder does not exist or is not a directory: {source_dir}")

        if not tgt.exists() or not tgt.is_dir():
            raise ValueError(f"Target folder does not exist or is not a directory: {target_dir}")

        # Scan source files
        source_files: Dict[Path, int] = {}
        for p in src.rglob("*"):
            if p.is_file():
                rel = p.relative_to(src)
                try:
                    source_files[rel] = p.stat().st_size
                except Exception:
                    source_files[rel] = -1

        # Scan target files
        target_files: Dict[Path, int] = {}
        for p in tgt.rglob("*"):
            if p.is_file():
                rel = p.relative_to(tgt)
                try:
                    target_files[rel] = p.stat().st_size
                except Exception:
                    target_files[rel] = -1

        corrupted = []   # Exists on target with 0 bytes while source > 0
        missing = []     # Exists on source, completely absent on target
        mismatch = []    # Exists on both, but target size != source size (and target > 0)
        healthy = []     # Identical sizes
        orphans = []     # Exists on target, absent on source

        corrupt_repair_bytes = 0
        missing_sync_bytes = 0

        for rel, s_size in source_files.items():
            s_abs = str(src / rel)
            t_abs = str(tgt / rel)

            if rel not in target_files:
                missing.append({
                    "rel_path": str(rel),
                    "filename": rel.name,
                    "source_size": s_size,
                    "target_size": 0,
                    "source_path": s_abs,
                    "target_path": t_abs,
                    "issue": "missing"
                })
                missing_sync_bytes += max(0, s_size)
            else:
                t_size = target_files[rel]
                if t_size == 0 and s_size > 0:
                    corrupted.append({
                        "rel_path": str(rel),
                        "filename": rel.name,
                        "source_size": s_size,
                        "target_size": 0,
                        "source_path": s_abs,
                        "target_path": t_abs,
                        "issue": "corrupted_zero_byte"
                    })
                    corrupt_repair_bytes += s_size
                elif t_size != s_size:
                    mismatch.append({
                        "rel_path": str(rel),
                        "filename": rel.name,
                        "source_size": s_size,
                        "target_size": t_size,
                        "size_diff": s_size - t_size,
                        "source_path": s_abs,
                        "target_path": t_abs,
                        "issue": "size_mismatch"
                    })
                else:
                    healthy.append({
                        "rel_path": str(rel),
                        "filename": rel.name,
                        "size": s_size
                    })

        for rel, t_size in target_files.items():
            if rel not in source_files:
                orphans.append({
                    "rel_path": str(rel),
                    "filename": rel.name,
                    "target_size": t_size,
                    "target_path": str(tgt / rel)
                })

        total_source_bytes = sum(max(0, s) for s in source_files.values())
        total_target_bytes = sum(max(0, t) for t in target_files.values())

        return {
            "source_dir": str(src),
            "target_dir": str(tgt),
            "summary": {
                "source_file_count": len(source_files),
                "source_total_bytes": total_source_bytes,
                "target_file_count": len(target_files),
                "target_total_bytes": total_target_bytes,
                "healthy_count": len(healthy),
                "corrupted_count": len(corrupted),
                "corrupted_bytes": corrupt_repair_bytes,
                "missing_count": len(missing),
                "missing_bytes": missing_sync_bytes,
                "mismatch_count": len(mismatch),
                "orphan_count": len(orphans),
                "is_healthy": (len(corrupted) == 0 and len(missing) == 0 and len(mismatch) == 0)
            },
            "corrupted_files": corrupted,
            "missing_files": missing,
            "mismatched_files": mismatch,
            "orphans": orphans[:100]
        }

    def start_repair(
        self,
        source_dir: str,
        target_dir: str,
        mode: str = "corrupted_only", # "corrupted_only", "missing_only", "all_defects", "selected"
        selected_rel_paths: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Starts an atomic, safe background transfer job to repair
        damaged, 0-byte, or missing files from source to target.
        """
        with self._lock:
            if self.repair_state["is_running"]:
                raise ValueError("A repair or sync job is already in progress.")

            audit = self.audit_folders(source_dir, target_dir)
            files_to_transfer: List[Dict[str, Any]] = []

            if mode == "corrupted_only":
                files_to_transfer = audit["corrupted_files"]
            elif mode == "missing_only":
                files_to_transfer = audit["missing_files"]
            elif mode == "all_defects":
                files_to_transfer = audit["corrupted_files"] + audit["missing_files"] + audit["mismatched_files"]
            elif mode == "selected" and selected_rel_paths:
                rel_set = set(selected_rel_paths)
                all_candidates = audit["corrupted_files"] + audit["missing_files"] + audit["mismatched_files"]
                files_to_transfer = [f for f in all_candidates if f["rel_path"] in rel_set]
            else:
                files_to_transfer = audit["corrupted_files"]

            if not files_to_transfer:
                return {
                    "status": "nothing_to_repair",
                    "message": "No corrupted or missing files detected matching the selected mode.",
                    "total_files": 0,
                    "total_bytes": 0
                }

            total_bytes = sum(max(0, f["source_size"]) for f in files_to_transfer)

            self._cancel_event.clear()
            self.repair_state = {
                "is_running": True,
                "source_path": str(Path(source_dir)),
                "target_path": str(Path(target_dir)),
                "mode": mode,
                "current_file": "",
                "total_files": len(files_to_transfer),
                "completed_files": 0,
                "total_bytes": total_bytes,
                "transferred_bytes": 0,
                "progress_pct": 0.0,
                "speed_mb_s": 0.0,
                "errors": [],
                "start_time": time.time(),
                "status": "running"
            }

            thread = threading.Thread(
                target=self._run_repair_worker,
                args=(files_to_transfer,),
                daemon=True
            )
            thread.start()

            return {
                "status": "started",
                "total_files": len(files_to_transfer),
                "total_bytes": total_bytes,
                "mode": mode
            }

    def _run_repair_worker(self, files: List[Dict[str, Any]]):
        """Worker thread transferring files safely with atomic .part staging."""
        chunk_size = 4 * 1024 * 1024 # 4 MB buffer
        total_bytes = self.repair_state["total_bytes"]
        bytes_copied_so_far = 0
        start_time = time.time()
        last_speed_check_time = start_time
        last_speed_bytes = 0

        logger.info(f"Starting repair transfer of {len(files)} files ({total_bytes / (1024**3):.2f} GB)")

        for idx, item in enumerate(files):
            if self._cancel_event.is_set():
                logger.info("Repair job cancelled by user.")
                self.repair_state["status"] = "cancelled"
                self.repair_state["is_running"] = False
                return

            src_file = Path(item["source_path"])
            tgt_file = Path(item["target_path"])
            rel_name = item["rel_path"]
            file_size = item["source_size"]

            self.repair_state["current_file"] = rel_name
            tgt_file.parent.mkdir(parents=True, exist_ok=True)
            part_file = tgt_file.parent / f"{tgt_file.name}.part_{os.getpid()}"

            try:
                # Stream copy with atomic staging
                with open(src_file, "rb") as f_in, open(part_file, "wb") as f_out:
                    while True:
                        if self._cancel_event.is_set():
                            part_file.unlink(missing_ok=True)
                            self.repair_state["status"] = "cancelled"
                            self.repair_state["is_running"] = False
                            return

                        chunk = f_in.read(chunk_size)
                        if not chunk:
                            break
                        f_out.write(chunk)
                        bytes_copied_so_far += len(chunk)

                        # Update progress & speed
                        now = time.time()
                        if now - last_speed_check_time >= 0.5:
                            duration = now - last_speed_check_time
                            bytes_diff = bytes_copied_so_far - last_speed_bytes
                            speed_mb = (bytes_diff / duration) / (1024 * 1024)
                            last_speed_check_time = now
                            last_speed_bytes = bytes_copied_so_far

                            pct = min(99.9, round((bytes_copied_so_far / total_bytes) * 100, 1)) if total_bytes > 0 else 0.0
                            self.repair_state["transferred_bytes"] = bytes_copied_so_far
                            self.repair_state["progress_pct"] = pct
                            self.repair_state["speed_mb_s"] = round(speed_mb, 1)

                # Verify copied file size
                part_size = part_file.stat().st_size
                if file_size > 0 and part_size != file_size:
                    raise IOError(f"Copied size ({part_size}) does not match source size ({file_size})")

                # Atomically replace target
                try:
                    os.replace(part_file, tgt_file)
                except OSError:
                    if tgt_file.exists():
                        try:
                            os.chmod(tgt_file, 0o777)
                            tgt_file.unlink(missing_ok=True)
                        except Exception:
                            pass
                    os.replace(part_file, tgt_file)

                # Preserve modification time
                try:
                    src_mtime = src_file.stat().st_mtime
                    os.utime(tgt_file, (src_mtime, src_mtime))
                except Exception:
                    pass

                self.repair_state["completed_files"] = idx + 1
                self.repair_state["transferred_bytes"] = bytes_copied_so_far
                if total_bytes > 0:
                    self.repair_state["progress_pct"] = min(100.0, round((bytes_copied_so_far / total_bytes) * 100, 1))

            except Exception as e:
                logger.error(f"Failed to repair file {rel_name}: {e}")
                part_file.unlink(missing_ok=True)
                self.repair_state["errors"].append(f"{rel_name}: {str(e)}")

        self.repair_state["is_running"] = False
        self.repair_state["current_file"] = ""
        self.repair_state["progress_pct"] = 100.0
        self.repair_state["status"] = "completed_with_errors" if self.repair_state["errors"] else "completed"
        logger.info(f"Repair transfer completed: {self.repair_state['completed_files']}/{len(files)} files fixed.")

    def get_status(self) -> Dict[str, Any]:
        """Return current live status of the repair job."""
        return dict(self.repair_state)

    def cancel_repair(self) -> bool:
        """Cancel ongoing repair transfer."""
        if self.repair_state["is_running"]:
            self._cancel_event.set()
            return True
        return False

# Global singleton
backup_doctor = BackupDoctor()
