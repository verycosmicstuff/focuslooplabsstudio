import os
import re
import time
import subprocess
import threading
import collections
from pathlib import Path
from typing import Optional, Callable, Dict, Any
import psutil

import sys
from src.config import FFMPEG_PATH, FFPROBE_PATH, PERFORMANCE_MODES
from src.core.db import get_db, db_transaction

# Windows Process Creation Flags
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
IDLE_PRIORITY_CLASS = 0x00000040
CREATE_NO_WINDOW = 0x08000000

TRANSCODE_PROFILES = {
    # Apple Silicon VideoToolbox Profiles (macOS hardware media engine)
    "vt_hq_10bit": {
        "name": "Apple VideoToolbox 10-Bit HQ (M1/M2/M3/M4 Hardware)",
        "desc": "Hardware-accelerated HEVC 10-bit preservation using Apple Silicon Media Engine with QuickTime/Finder tag compatibility.",
        "vcodec": "hevc_videotoolbox",
        "params": ["-q:v", "65", "-pix_fmt", "p010le", "-tag:v", "hvc1"],
        "acodec": "copy"
    },
    "vt_lossless": {
        "name": "Apple VideoToolbox Ultra Master (High Bitrate)",
        "desc": "Pristine Apple Silicon hardware transcode for camera master archives.",
        "vcodec": "hevc_videotoolbox",
        "params": ["-q:v", "80", "-pix_fmt", "p010le", "-tag:v", "hvc1"],
        "acodec": "copy"
    },
    "vt_compact": {
        "name": "Apple VideoToolbox Space Saver",
        "desc": "Maximum storage reclamation (65-80% smaller) for sharing and dailies.",
        "vcodec": "hevc_videotoolbox",
        "params": ["-q:v", "50", "-pix_fmt", "p010le", "-tag:v", "hvc1"],
        "acodec": "aac",
        "audio_bitrate": "192k"
    },
    # NVIDIA NVENC Profiles (Windows / Linux)
    "nvenc_hq_10bit": {
        "name": "NVIDIA NVENC High Quality 10-Bit (Recommended for Fuji)",
        "desc": "Visually lossless HEVC/H.265 using RTX hardware encoder with 10-bit color preservation for F-Log/ProRes.",
        "vcodec": "hevc_nvenc",
        "params": ["-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "22", "-pix_fmt", "p010le", "-tag:v", "hvc1"],
        "acodec": "copy"
    },
    "nvenc_lossless": {
        "name": "NVIDIA NVENC Ultra Master (CQ 18)",
        "desc": "Pristine archival quality, near identical to original high bitrate camera footage.",
        "vcodec": "hevc_nvenc",
        "params": ["-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", "18", "-pix_fmt", "p010le", "-tag:v", "hvc1"],
        "acodec": "copy"
    },
    "nvenc_compact": {
        "name": "NVIDIA NVENC Maximum Space Saving (CQ 26)",
        "desc": "Aggressive file size reduction (75-85% smaller) while retaining crisp 4K playback.",
        "vcodec": "hevc_nvenc",
        "params": ["-preset", "p5", "-rc", "vbr", "-cq", "26", "-pix_fmt", "p010le", "-tag:v", "hvc1"],
        "acodec": "aac",
        "audio_bitrate": "192k"
    },
    # Universal Software Profile
    "cpu_x265_hq": {
        "name": "CPU libx265 (High Efficiency Software Encoder)",
        "desc": "Maximum compression efficiency using CPU cores.",
        "vcodec": "libx265",
        "params": ["-crf", "22", "-preset", "medium", "-pix_fmt", "yuv420p10le", "-tag:v", "hvc1"],
        "acodec": "copy"
    }
}

class TranscodeJob:
    def __init__(self, transcode_id: int, source_path: str, output_path: str, profile_key: str = "nvenc_hq_10bit",
                 perf_mode: str = "balanced", progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.transcode_id = transcode_id
        self.source_path = Path(source_path).resolve()
        self.output_path = Path(output_path).resolve()
        self.profile_key = profile_key
        self.perf_mode = perf_mode
        self.progress_cb = progress_cb
        
        self.process: Optional[subprocess.Popen] = None
        self.is_paused = False
        self.is_cancelled = False
        self.total_duration_sec = 0.0

    def pause(self):
        if self.process and self.process.poll() is None:
            try:
                p = psutil.Process(self.process.pid)
                p.suspend()
                self.is_paused = True
            except Exception:
                pass

    def resume(self):
        if self.process and self.process.poll() is None:
            try:
                p = psutil.Process(self.process.pid)
                p.resume()
                self.is_paused = False
            except Exception:
                pass

    def cancel(self):
        self.is_cancelled = True
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
            except Exception:
                pass

    def run(self) -> bool:
        if not FFMPEG_PATH or not os.path.isfile(FFMPEG_PATH):
            self._update_db_error("FFmpeg executable not found")
            return False

        # On macOS, auto-alias NVENC profile requests to native VideoToolbox
        profile_key = self.profile_key
        if sys.platform == "darwin":
            if profile_key.startswith("nvenc_") or profile_key not in TRANSCODE_PROFILES:
                profile_key = "vt_hq_10bit"
        profile = TRANSCODE_PROFILES.get(profile_key, TRANSCODE_PROFILES["vt_hq_10bit" if sys.platform == "darwin" else "nvenc_hq_10bit"])
        perf = PERFORMANCE_MODES.get(self.perf_mode, PERFORMANCE_MODES["balanced"])

        # Create output directory
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        # Get original file stats
        orig_stat = self.source_path.stat()
        orig_size = orig_stat.st_size
        orig_mtime = orig_stat.st_mtime

        # Probe duration for progress percentage
        self.total_duration_sec = self._probe_duration()

        # Build FFmpeg command
        cmd = [
            FFMPEG_PATH,
            "-y",
            "-nostats",
            "-loglevel", "error",
            "-i", str(self.source_path),
            "-c:v", profile["vcodec"],
        ]
        cmd.extend(profile["params"])

        # Audio handling
        if profile["acodec"] == "copy":
            cmd.extend(["-c:a", "copy"])
        else:
            cmd.extend(["-c:a", "aac", "-b:a", profile.get("audio_bitrate", "192k")])

        # Metadata preservation (Camera tags, creation date, timecode)
        cmd.extend([
            "-map_metadata", "0",
            "-movflags", "+use_metadata_tags+faststart",
            "-threads", str(perf["cpu_threads"]),
            "-progress", "pipe:1",
            str(self.output_path)
        ])

        # Subprocess spawn arguments (creationflags is Windows-only)
        popen_kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "bufsize": 1
        }
        if sys.platform == "win32":
            flags = CREATE_NO_WINDOW
            if perf["os_priority"] == "IDLE":
                flags |= IDLE_PRIORITY_CLASS
            elif perf["os_priority"] == "BELOW_NORMAL":
                flags |= BELOW_NORMAL_PRIORITY_CLASS
            popen_kwargs["creationflags"] = flags

        self._update_db_status("transcoding")

        try:
            self.process = subprocess.Popen(cmd, **popen_kwargs)

            # Set POSIX process nice level if on macOS/Linux
            if sys.platform != "win32" and perf.get("os_priority") in ("IDLE", "BELOW_NORMAL"):
                try:
                    p = psutil.Process(self.process.pid)
                    p.nice(10 if perf["os_priority"] == "BELOW_NORMAL" else 19)
                except Exception:
                    pass

            # Continually drain stderr in a daemon thread to prevent pipe buffer deadlock
            stderr_lines = collections.deque(maxlen=40)
            def _drain_stderr():
                try:
                    for err_line in self.process.stderr:
                        stderr_lines.append(err_line)
                except Exception:
                    pass

            stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
            stderr_thread.start()

            last_update_time = 0.0

            # Read progress in real-time
            for line in self.process.stdout:
                if self.is_cancelled:
                    break

                line = line.strip()
                if not line:
                    continue

                if "=" in line:
                    key, val = line.split("=", 1)
                    val = val.strip()
                    if key in ("out_time_ms", "out_time_us"):
                        try:
                            cur_us = int(val)
                            cur_sec = cur_us / 1_000_000.0
                            if self.total_duration_sec > 0:
                                progress = min(99.9, round((cur_sec / self.total_duration_sec) * 100, 1))
                                now = time.time()
                                if now - last_update_time >= 0.4:
                                    last_update_time = now
                                    self._update_progress(progress)
                        except Exception:
                            pass
                    elif key == "speed":
                        now = time.time()
                        if now - last_update_time >= 0.4:
                            self._update_speed(val)
                    elif key == "fps":
                        try:
                            fps_val = float(val)
                            now = time.time()
                            if now - last_update_time >= 0.4:
                                self._update_fps(fps_val)
                        except Exception:
                            pass

            self.process.wait()
            stderr_thread.join(timeout=1.0)

            if self.is_cancelled:
                self._cleanup_failed()
                self._update_db_status("cancelled")
                return False

            if self.process.returncode != 0:
                err_msg = "".join(stderr_lines)
                self._cleanup_failed()
                self._update_db_error(f"FFmpeg error: {err_msg[-300:]}")
                return False

            # Verify transcoded output
            if not self._verify_output():
                self._cleanup_failed()
                self._update_db_error("Transcoded file verification failed via ffprobe")
                return False

            # Preserve original creation and modification timestamp
            try:
                os.utime(str(self.output_path), (orig_mtime, orig_mtime))
            except Exception:
                pass

            conv_size = self.output_path.stat().st_size

            # Anti-Bloat Safeguard (Zero-Bloat Guarantee)
            # If the transcoded file is larger than the original or saves < 3%:
            if conv_size >= orig_size:
                bloat_diff = conv_size - orig_size
                bloat_mb = bloat_diff / (1024 * 1024)
                self._cleanup_failed()
                self._update_db_skipped_bloat(
                    orig_size, conv_size,
                    f"Original was already more compact than H.265 output (+{bloat_mb:.1f} MB bloat prevented). Kept original."
                )
                return True
            elif (orig_size - conv_size) < (orig_size * 0.03):
                saved_mb = (orig_size - conv_size) / (1024 * 1024)
                self._cleanup_failed()
                self._update_db_skipped_bloat(
                    orig_size, conv_size,
                    f"Negligible savings (<3%, only {saved_mb:.1f} MB). Discarded output to avoid generational quality loss."
                )
                return True

            saved_bytes = orig_size - conv_size
            self._update_db_complete(orig_size, conv_size, saved_bytes)
            return True

        except Exception as e:
            self._cleanup_failed()
            self._update_db_error(str(e))
            return False

    def _probe_duration(self) -> float:
        if not FFPROBE_PATH:
            return 0.0
        try:
            res = subprocess.run([
                FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(self.source_path)
            ], stdout=subprocess.PIPE, text=True, creationflags=CREATE_NO_WINDOW, timeout=5)
            return float(res.stdout.strip())
        except Exception:
            return 0.0

    def _verify_output(self) -> bool:
        if not self.output_path.exists() or self.output_path.stat().st_size < 1024:
            return False
        if not FFPROBE_PATH:
            return True
        try:
            res = subprocess.run([
                FFPROBE_PATH, "-v", "error", str(self.output_path)
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW, timeout=10)
            return res.returncode == 0
        except Exception:
            return True

    def _cleanup_failed(self):
        if self.output_path.exists():
            try:
                self.output_path.unlink()
            except Exception:
                pass

    def _update_progress(self, progress: float):
        with db_transaction() as tx:
            tx.execute("UPDATE transcodes SET progress = ? WHERE id = ?", (progress, self.transcode_id))
        if self.progress_cb:
            self.progress_cb({"id": self.transcode_id, "progress": progress})

    def _update_speed(self, speed: str):
        with db_transaction() as tx:
            tx.execute("UPDATE transcodes SET speed = ? WHERE id = ?", (speed, self.transcode_id))

    def _update_fps(self, fps: float):
        with db_transaction() as tx:
            tx.execute("UPDATE transcodes SET fps = ? WHERE id = ?", (fps, self.transcode_id))

    def _update_db_status(self, status: str):
        with db_transaction() as tx:
            tx.execute("UPDATE transcodes SET status = ?, started_at = datetime('now') WHERE id = ?", (status, self.transcode_id))

    def _update_db_complete(self, orig_size: int, conv_size: int, saved_bytes: int):
        with db_transaction() as tx:
            tx.execute("""
                UPDATE transcodes SET status = 'completed', progress = 100.0,
                original_size = ?, converted_size = ?, saved_bytes = ?, finished_at = datetime('now')
                WHERE id = ?
            """, (orig_size, conv_size, saved_bytes, self.transcode_id))

    def _update_db_skipped_bloat(self, orig_size: int, conv_size: int, reason: str):
        with db_transaction() as tx:
            tx.execute("""
                UPDATE transcodes SET status = 'already_optimal', progress = 100.0,
                original_size = ?, converted_size = ?, saved_bytes = 0, error_msg = ?, finished_at = datetime('now')
                WHERE id = ?
            """, (orig_size, conv_size, reason, self.transcode_id))

    def _update_db_error(self, err: str):
        with db_transaction() as tx:
            tx.execute("UPDATE transcodes SET status = 'failed', error_msg = ? WHERE id = ?", (err, self.transcode_id))

class TranscodeQueue:
    def __init__(self):
        self.jobs: Dict[int, TranscodeJob] = {}
        self.current_job: Optional[TranscodeJob] = None
        self.lock = threading.Lock()
        self.is_running = False
        self.perf_mode = "balanced"

    def set_performance_mode(self, mode: str):
        if mode in PERFORMANCE_MODES:
            self.perf_mode = mode

    def add_job(self, source_file_id: int, profile_key: str = "nvenc_hq_10bit", dest_dir: Optional[str] = None) -> int:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT abs_path, filename, size_bytes FROM files WHERE id = ?", (source_file_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError("File not found")

        src_p = Path(row["abs_path"])
        if dest_dir:
            out_p = Path(dest_dir) / f"{src_p.stem}_H265.mp4"
        else:
            out_p = src_p.parent / f"{src_p.stem}_H265.mp4"

        with db_transaction() as tx:
            tx_cur = tx.cursor()
            tx_cur.execute("""
                INSERT INTO transcodes (source_file_id, output_path, status, profile, original_size)
                VALUES (?, ?, 'pending', ?, ?)
            """, (source_file_id, str(out_p), profile_key, row["size_bytes"]))
            job_id = tx_cur.lastrowid

        self.start_worker_if_needed()
        return job_id

    def pause_current(self):
        with self.lock:
            if self.current_job:
                self.current_job.pause()

    def resume_current(self):
        with self.lock:
            if self.current_job:
                self.current_job.resume()

    def cancel_job(self, transcode_id: int):
        with self.lock:
            if self.current_job and self.current_job.transcode_id == transcode_id:
                self.current_job.cancel()
            else:
                with db_transaction() as tx:
                    tx.execute("UPDATE transcodes SET status = 'cancelled' WHERE id = ?", (transcode_id,))

    def start_worker_if_needed(self):
        with self.lock:
            if not self.is_running:
                self.is_running = True
                threading.Thread(target=self._worker_loop, daemon=True).start()

    def _worker_loop(self):
        while True:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT t.id, t.source_file_id, t.output_path, t.profile, f.abs_path
                FROM transcodes t
                JOIN files f ON t.source_file_id = f.id
                WHERE t.status = 'pending'
                ORDER BY t.id ASC LIMIT 1
            """)
            row = cursor.fetchone()
            if not row:
                with self.lock:
                    self.is_running = False
                    self.current_job = None
                break

            job = TranscodeJob(
                transcode_id=row["id"],
                source_path=row["abs_path"],
                output_path=row["output_path"],
                profile_key=row["profile"],
                perf_mode=self.perf_mode
            )
            with self.lock:
                self.current_job = job

            job.run()
            time.sleep(0.5)

transcode_queue = TranscodeQueue()
