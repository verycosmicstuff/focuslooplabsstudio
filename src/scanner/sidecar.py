import os
from pathlib import Path
from typing import Optional, List, Tuple
from src.config import RAW_EXTS, PHOTO_EXTS, SIDECAR_EXTS

def get_base_stem(path: Path) -> str:
    """Returns normalized stem stripped of raw/photo extensions."""
    name = path.name
    # Handle .RAF.xmp
    if name.lower().endswith(".xmp"):
        base = name[:-4]
        for ext in RAW_EXTS | PHOTO_EXTS:
            if base.lower().endswith(ext):
                return base[:-len(ext)].lower()
        return base.lower()
    
    return path.stem.lower()

def compute_pair_id(dir_path: Path, stem: str) -> str:
    """Generates canonical pair_id for media and its sidecar."""
    norm_dir = str(dir_path.resolve()).lower()
    return f"{norm_dir}::{stem.lower()}"

def find_sidecars_for_file(abs_path: str) -> List[str]:
    """Finds all existing sidecars and paired RAW/JPG for a given file."""
    p = Path(abs_path)
    if not p.parent.exists():
        return []

    stem = p.stem
    parent = p.parent
    sidecars = []

    # Check potential sidecar patterns
    patterns = [
        parent / f"{stem}.xmp",
        parent / f"{stem}.XMP",
        parent / f"{p.name}.xmp",
        parent / f"{p.name}.XMP",
    ]

    for cand in patterns:
        if cand.exists() and str(cand.resolve()).lower() != str(p.resolve()).lower():
            if str(cand.resolve()) not in sidecars:
                sidecars.append(str(cand.resolve()))

    return sidecars
