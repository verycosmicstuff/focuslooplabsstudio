import os
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional

from src.config import DATA_DIR
from src.core.logger import get_logger

logger = get_logger("session")

SESSION_FILE = DATA_DIR / "session_state.json"

DEFAULT_SESSION_STATE: Dict[str, Any] = {
    "version": "1.0",
    "last_updated": 0,
    "last_active_tab": "proofing",
    "last_proofing_subview": "watermark",
    "custom_folders": [],
    "watermark_settings": {
        "mode": "text",
        "text": "PROOF ONLY — DO NOT COPY",
        "position": "diagonal_grid",
        "opacity": 35,
        "font_scale": 4,
        "color_hex": "#FFFFFF",
        "shadow": True,
        "logo_path": "",
        "logo_position": "bottom-right",
        "logo_opacity": 80,
        "logo_scale": 18,
        "resolution": 2048,
        "is_original_res": False,
        "quality": 80,
        "output_mode": "original_subfolder",
        "subfolder_name": "_proofs",
        "subfolder_type": "suffix",
        "suffix": "_proof"
    },
    "contact_sheet_settings": {
        "title": "Client Proofing Gallery",
        "client": "Valued Client",
        "instructions": "Click the heart icon on your favorite photos, then click 'Copy Selected Filenames' below to send us your picks.",
        "watermark_text": "PROOF ONLY",
        "dest_dir": ""
    },
    "selects_settings": {
        "input": "",
        "source_dir": "",
        "dest_dir": "",
        "action": "copy"
    },
    "last_task": {
        "task_type": "none",
        "summary": "No previous tasks recorded yet",
        "timestamp": 0,
        "formatted_time": "",
        "details": {}
    }
}

def get_session_state() -> Dict[str, Any]:
    """Reads saved session state from data/session_state.json or returns default."""
    if not SESSION_FILE.exists():
        return dict(DEFAULT_SESSION_STATE)

    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        # Merge with defaults to ensure missing keys are populated
        merged = dict(DEFAULT_SESSION_STATE)
        for k, v in data.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k] = {**merged[k], **v}
            else:
                merged[k] = v
        return merged
    except Exception as e:
        logger.warning(f"Could not read session state: {e}. Using defaults.")
        return dict(DEFAULT_SESSION_STATE)

def save_session_state(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Updates and safely saves session state to data/session_state.json."""
    current = get_session_state()

    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(current.get(k), dict):
            current[k] = {**current[k], **v}
        else:
            current[k] = v

    current["last_updated"] = int(time.time())

    try:
        temp_file = SESSION_FILE.with_suffix(".tmp")
        temp_file.write_text(json.dumps(current, indent=2), encoding="utf-8")
        temp_file.replace(SESSION_FILE)
    except Exception as e:
        logger.error(f"Failed to write session state: {e}")

    return current

def record_last_task(task_type: str, summary: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Records a completed task into session state and logs it to savespace.log."""
    now = time.time()
    formatted = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
    task_data = {
        "task_type": task_type,
        "summary": summary,
        "timestamp": now,
        "formatted_time": formatted,
        "details": details or {}
    }
    logger.info(f"[TaskTracker] Completed task: {summary} ({formatted})")
    return save_session_state({"last_task": task_data})
