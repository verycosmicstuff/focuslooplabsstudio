import os
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
from src.config import HANDBRAKE_PATH

class HandBrakeBridge:
    @staticmethod
    def is_available() -> bool:
        return bool(HANDBRAKE_PATH and os.path.isfile(HANDBRAKE_PATH))

    @staticmethod
    def get_info() -> Dict[str, Any]:
        return {
            "available": HandBrakeBridge.is_available(),
            "path": HANDBRAKE_PATH,
            "type": "CLI" if "cli" in HANDBRAKE_PATH.lower() else "GUI"
        }

    @staticmethod
    def transcode_file(source_path: str, dest_path: str, preset: str = "Production Max") -> bool:
        """Runs HandBrakeCLI if CLI is present."""
        if not HandBrakeBridge.is_available() or "cli" not in HANDBRAKE_PATH.lower():
            return False

        cmd = [
            HANDBRAKE_PATH,
            "-i", source_path,
            "-o", dest_path,
            "-e", "nvenc_h265",
            "-q", "22",
            "--encoder-preset", "slow",
            "--all-audio",
            "--all-subtitles"
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=3600)
            return res.returncode == 0
        except Exception:
            return False
