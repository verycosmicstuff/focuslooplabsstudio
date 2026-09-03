import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "savespace.db"
THUMBNAILS_DIR = DATA_DIR / "thumbnails"
THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)

QUARANTINE_DIR = DATA_DIR / "quarantine"
QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

# Media format groups
RAW_EXTS = {".raf", ".dng", ".cr2", ".cr3", ".arw", ".nef", ".rw2", ".orf"}
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".heic"}
VIDEO_EXTS = {".mov", ".mp4", ".mkv", ".avi", ".m4v", ".webm", ".prores"}
SIDECAR_EXTS = {".xmp"}

ALL_MEDIA_EXTS = RAW_EXTS | PHOTO_EXTS | VIDEO_EXTS | SIDECAR_EXTS

# Detection of external utilities
def _resolve_binary(name: str) -> str:
    choco_direct = Path(r"C:\ProgramData\chocolatey\lib\ffmpeg\tools\ffmpeg\bin") / f"{name}.exe"
    if choco_direct.is_file():
        return str(choco_direct)
    found = shutil.which(name)
    if found:
        return found
    fallback = Path(rf"C:\ProgramData\chocolatey\bin\{name}.exe")
    if fallback.is_file():
        return str(fallback)
    return ""

FFMPEG_PATH = _resolve_binary("ffmpeg")
FFPROBE_PATH = _resolve_binary("ffprobe")

HANDBRAKE_PATHS = [
    shutil.which("HandBrakeCLI") or "",
    r"C:\Program Files\HandBrake\HandBrakeCLI.exe",
    r"C:\Program Files\HandBrake\HandBrake.exe",
]
HANDBRAKE_PATH = next((p for p in HANDBRAKE_PATHS if p and os.path.isfile(p)), "")

# Server and GUI defaults
DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"

# Performance profiles for transcoding and background indexing
PERFORMANCE_MODES = {
    "stealth": {
        "name": "Stealth / Silent (Background)",
        "desc": "Ultra low CPU & GPU priority, 2 threads max. Computer stays cold and quiet while working.",
        "os_priority": "IDLE",
        "cpu_threads": 2,
        "max_concurrent_transcodes": 1,
    },
    "balanced": {
        "name": "Balanced (Recommended)",
        "desc": "Below-normal priority with NVENC GPU acceleration. Smooth desktop multitasking.",
        "os_priority": "BELOW_NORMAL",
        "cpu_threads": 4,
        "max_concurrent_transcodes": 1,
    },
    "turbo": {
        "name": "Turbo / Overnight",
        "desc": "Maximum GPU throughput & full CPU allocation for batch overnight rendering.",
        "os_priority": "NORMAL",
        "cpu_threads": 8,
        "max_concurrent_transcodes": 2,
    },
}
