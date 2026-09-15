import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

def _resolve_data_dir() -> Path:
    custom = os.environ.get("FOCUSLOOP_DATA_DIR") or os.environ.get("SAVESAPCE_DATA_DIR")
    if custom:
        p = Path(custom)
        p.mkdir(parents=True, exist_ok=True)
        return p
    
    # Check if local app directory is writable (preferred for portable zero-install mode)
    local_data = BASE_DIR / "data"
    try:
        local_data.mkdir(parents=True, exist_ok=True)
        test_file = local_data / ".perm_check"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        return local_data
    except Exception:
        # Fall back to user Application Support on macOS or AppData on Windows
        if sys.platform == "darwin":
            fallback = Path.home() / "Library" / "Application Support" / "FocusloopLabs" / "data"
        else:
            appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
            fallback = Path(appdata) / "FocusloopLabs" / "data"
            if not fallback.exists() and (Path(appdata) / "SaveSpace" / "data").exists():
                fallback = Path(appdata) / "SaveSpace" / "data"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

def _resolve_logs_dir(data_dir: Path) -> Path:
    custom = os.environ.get("FOCUSLOOP_LOGS_DIR") or os.environ.get("SAVESAPCE_LOGS_DIR")
    if custom:
        p = Path(custom)
        p.mkdir(parents=True, exist_ok=True)
        return p
    if data_dir.parent == BASE_DIR:
        local_logs = BASE_DIR / "logs"
        try:
            local_logs.mkdir(parents=True, exist_ok=True)
            return local_logs
        except Exception:
            pass
    if sys.platform == "darwin":
        fallback_logs = Path.home() / "Library" / "Logs" / "FocusloopLabs"
    else:
        fallback_logs = data_dir.parent / "logs"
    fallback_logs.mkdir(parents=True, exist_ok=True)
    return fallback_logs

DATA_DIR = _resolve_data_dir()
LOGS_DIR = _resolve_logs_dir(DATA_DIR)

# Database path resolution: use focusloop.db, or use existing savespace.db if present
if (DATA_DIR / "focusloop.db").exists():
    DB_PATH = DATA_DIR / "focusloop.db"
elif (DATA_DIR / "savespace.db").exists():
    DB_PATH = DATA_DIR / "savespace.db"
else:
    DB_PATH = DATA_DIR / "focusloop.db"
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
    # 1. Bundled local bin folder inside app (portable / installed distribution)
    for candidate in [BASE_DIR / "bin" / name, BASE_DIR / "bin" / f"{name}.exe"]:
        if candidate.is_file():
            return str(candidate)
    
    # 2. System PATH
    found = shutil.which(name)
    if found:
        return found

    # 3. macOS Homebrew & standard UNIX paths
    mac_paths = [
        Path(f"/opt/homebrew/bin/{name}"),     # Apple Silicon Homebrew
        Path(f"/usr/local/bin/{name}"),        # Intel Homebrew / MacPorts
        Path(f"/usr/bin/{name}"),              # Standard system
    ]
    for mp in mac_paths:
        if mp.is_file():
            return str(mp)

    # 4. Windows Chocolatey paths
    choco_direct = Path(r"C:\ProgramData\chocolatey\lib\ffmpeg\tools\ffmpeg\bin") / f"{name}.exe"
    if choco_direct.is_file():
        return str(choco_direct)
    fallback = Path(rf"C:\ProgramData\chocolatey\bin\{name}.exe")
    if fallback.is_file():
        return str(fallback)

    # 5. Windows WinGet paths
    winget_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if winget_base.is_dir():
        try:
            matches = list(winget_base.glob(f"**/{name}.exe"))
            if matches:
                return str(matches[0])
        except Exception:
            pass

    return ""

FFMPEG_PATH = _resolve_binary("ffmpeg")
FFPROBE_PATH = _resolve_binary("ffprobe")

HANDBRAKE_PATHS = [
    str(BASE_DIR / "bin" / "HandBrakeCLI"),
    str(BASE_DIR / "bin" / "HandBrakeCLI.exe"),
    shutil.which("HandBrakeCLI") or "",
    "/opt/homebrew/bin/HandBrakeCLI",
    "/usr/local/bin/HandBrakeCLI",
    "/Applications/HandBrake.app/Contents/MacOS/HandBrakeCLI",
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
