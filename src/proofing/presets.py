import json
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional

from src.config import DATA_DIR
from src.core.logger import get_logger

logger = get_logger("presets")
PRESETS_FILE = DATA_DIR / "watermark_presets.json"

BUILTIN_PRESETS: List[Dict[str, Any]] = [
    {
        "id": "builtin_diagonal_text",
        "name": "Default: Diagonal Repeating Grid",
        "is_builtin": True,
        "config": {
            "watermark_type": "text",
            "text": "PROOF ONLY — DO NOT COPY",
            "position": "diagonal_grid",
            "opacity": 0.35,
            "font_scale": 0.04,
            "color_hex": "#FFFFFF",
            "shadow": True,
            "logo_path": "",
            "logo_position": "bottom-right",
            "logo_opacity": 0.8,
            "logo_scale": 0.18,
            "max_dimension": 2048,
            "is_original_res": False,
            "quality": 80,
            "output_mode": "original_subfolder",
            "subfolder_name": "_proofs",
            "subfolder_type": "suffix",
            "suffix": "_proof"
        }
    },
    {
        "id": "builtin_bottom_center_text",
        "name": "Bottom Center Proof (Subtle Text)",
        "is_builtin": True,
        "config": {
            "watermark_type": "text",
            "text": "PROOF ONLY",
            "position": "bottom-center",
            "opacity": 0.45,
            "font_scale": 0.035,
            "color_hex": "#FFFFFF",
            "shadow": True,
            "logo_path": "",
            "logo_position": "bottom-right",
            "logo_opacity": 0.8,
            "logo_scale": 0.18,
            "max_dimension": 2048,
            "is_original_res": False,
            "quality": 85,
            "output_mode": "original_subfolder",
            "subfolder_name": "_proofs",
            "subfolder_type": "suffix",
            "suffix": "_proof"
        }
    },
    {
        "id": "builtin_logo_bottom_right",
        "name": "PNG Logo (Bottom Right)",
        "is_builtin": True,
        "config": {
            "watermark_type": "logo",
            "text": "PROOF ONLY",
            "position": "diagonal_grid",
            "opacity": 0.35,
            "font_scale": 0.04,
            "color_hex": "#FFFFFF",
            "shadow": True,
            "logo_path": "",
            "logo_position": "bottom-right",
            "logo_opacity": 0.85,
            "logo_scale": 0.18,
            "max_dimension": 2048,
            "is_original_res": False,
            "quality": 85,
            "output_mode": "original_subfolder",
            "subfolder_name": "_proofs",
            "subfolder_type": "suffix",
            "suffix": "_proof"
        }
    },
    {
        "id": "builtin_logo_text_both",
        "name": "Grid Protection + Corner Logo",
        "is_builtin": True,
        "config": {
            "watermark_type": "both",
            "text": "PROOF ONLY",
            "position": "diagonal_grid",
            "opacity": 0.25,
            "font_scale": 0.035,
            "color_hex": "#FFFFFF",
            "shadow": True,
            "logo_path": "",
            "logo_position": "bottom-right",
            "logo_opacity": 0.85,
            "logo_scale": 0.15,
            "max_dimension": 2048,
            "is_original_res": False,
            "quality": 82,
            "output_mode": "original_subfolder",
            "subfolder_name": "_proofs",
            "subfolder_type": "suffix",
            "suffix": "_proof"
        }
    },
    {
        "id": "builtin_fullres_subtle",
        "name": "Full-Res Original + Subtle Logo",
        "is_builtin": True,
        "config": {
            "watermark_type": "logo",
            "text": "PROOF ONLY",
            "position": "bottom-center",
            "opacity": 0.35,
            "font_scale": 0.03,
            "color_hex": "#FFFFFF",
            "shadow": True,
            "logo_path": "",
            "logo_position": "bottom-right",
            "logo_opacity": 0.75,
            "logo_scale": 0.12,
            "max_dimension": 0,
            "is_original_res": True,
            "quality": 92,
            "output_mode": "original_subfolder",
            "subfolder_name": "_proofs",
            "subfolder_type": "suffix",
            "suffix": "_proof"
        }
    },
    {
        "id": "builtin_web_quick",
        "name": "Web Proof Fast Share (1600px)",
        "is_builtin": True,
        "config": {
            "watermark_type": "text",
            "text": "SAMPLE FOR REVIEW",
            "position": "diagonal_grid",
            "opacity": 0.35,
            "font_scale": 0.04,
            "color_hex": "#FFFFFF",
            "shadow": True,
            "logo_path": "",
            "logo_position": "bottom-right",
            "logo_opacity": 0.8,
            "logo_scale": 0.18,
            "max_dimension": 1600,
            "is_original_res": False,
            "quality": 75,
            "output_mode": "original_subfolder",
            "subfolder_name": "_proofs",
            "subfolder_type": "suffix",
            "suffix": "_proof"
        }
    }
]

def _read_presets_file() -> List[Dict[str, Any]]:
    """Reads custom presets from PRESETS_FILE."""
    if not PRESETS_FILE.exists():
        return []
    try:
        data = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        logger.error(f"Failed to read presets file: {e}")
        return []

def _write_presets_file(presets: List[Dict[str, Any]]):
    """Saves custom presets atomically to PRESETS_FILE."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temp_p = PRESETS_FILE.with_suffix(".tmp")
        temp_p.write_text(json.dumps(presets, indent=2), encoding="utf-8")
        temp_p.replace(PRESETS_FILE)
    except Exception as e:
        logger.error(f"Failed to write presets file: {e}")

def get_all_presets() -> List[Dict[str, Any]]:
    """Returns all presets: built-in presets followed by user custom presets."""
    custom_list = _read_presets_file()
    custom_filtered = [p for p in custom_list if not p.get("is_builtin")]
    return BUILTIN_PRESETS + custom_filtered

def get_preset_by_id(preset_id: str) -> Optional[Dict[str, Any]]:
    """Finds a preset by its unique ID."""
    for p in get_all_presets():
        if p.get("id") == preset_id:
            return p
    return None

def save_preset(name: str, config: Dict[str, Any], preset_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Creates a new custom preset or updates an existing custom preset.
    Built-in presets cannot be overwritten; a clone will be created instead.
    """
    clean_name = (name or "Untitled Preset").strip()
    custom_presets = _read_presets_file()

    norm_config = dict(config)
    if "opacity" in norm_config:
        norm_config["opacity"] = float(norm_config["opacity"])
    if "logo_opacity" in norm_config:
        norm_config["logo_opacity"] = float(norm_config["logo_opacity"])
    if "font_scale" in norm_config:
        norm_config["font_scale"] = float(norm_config["font_scale"])
    if "logo_scale" in norm_config:
        norm_config["logo_scale"] = float(norm_config["logo_scale"])
    if "max_dimension" in norm_config:
        norm_config["max_dimension"] = int(norm_config["max_dimension"])
    if "quality" in norm_config:
        norm_config["quality"] = int(norm_config["quality"])
    norm_config["is_original_res"] = bool(norm_config.get("is_original_res", False))

    target_id = preset_id

    existing_idx = -1
    if target_id and not target_id.startswith("builtin_"):
        for idx, cp in enumerate(custom_presets):
            if cp.get("id") == target_id:
                existing_idx = idx
                break

    if existing_idx >= 0:
        custom_presets[existing_idx]["name"] = clean_name
        custom_presets[existing_idx]["config"] = norm_config
        custom_presets[existing_idx]["updated_at"] = int(time.time())
        preset_item = custom_presets[existing_idx]
    else:
        new_id = f"custom_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        preset_item = {
            "id": new_id,
            "name": clean_name,
            "is_builtin": False,
            "config": norm_config,
            "created_at": int(time.time()),
            "updated_at": int(time.time())
        }
        custom_presets.append(preset_item)

    _write_presets_file(custom_presets)
    logger.info(f"Saved watermark preset '{clean_name}' (ID: {preset_item['id']})")
    return preset_item

def delete_preset(preset_id: str) -> bool:
    """Deletes a custom preset. Built-in presets are protected."""
    if not preset_id or preset_id.startswith("builtin_"):
        logger.warning(f"Cannot delete built-in preset '{preset_id}'")
        return False

    custom_presets = _read_presets_file()
    initial_len = len(custom_presets)
    custom_presets = [p for p in custom_presets if p.get("id") != preset_id]

    if len(custom_presets) < initial_len:
        _write_presets_file(custom_presets)
        logger.info(f"Deleted watermark preset (ID: {preset_id})")
        return True

    return False
