from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class SourceCreate(BaseModel):
    path: str
    label: str
    drive_type: Optional[str] = "LOCAL"

class SourceResponse(BaseModel):
    id: int
    path: str
    label: str
    drive_type: str
    total_bytes: int
    free_bytes: int
    is_online: bool
    last_scanned: Optional[str] = None
    file_count: Optional[int] = 0
    total_media_size: Optional[int] = 0

class FileItem(BaseModel):
    id: int
    source_id: int
    rel_path: str
    abs_path: str
    filename: str
    ext: str
    size_bytes: int
    media_type: str
    fast_hash: Optional[str] = None
    full_hash: Optional[str] = None
    pair_id: Optional[str] = None
    has_sidecar: Optional[bool] = False
    sidecar_path: Optional[str] = None
    blur_score: Optional[float] = None
    is_blurry: Optional[bool] = None
    burst_group: Optional[str] = None
    is_burst_best: Optional[bool] = None
    disposition: Optional[str] = "review"

class TranscodeRequest(BaseModel):
    file_ids: List[int]
    profile: str = "nvenc_hq_10bit"
    mode: str = "parallel" # parallel, replace_backup, in_place
    output_dir: Optional[str] = None

class CullingAction(BaseModel):
    file_ids: List[int]
    action: str # "trash", "quarantine", "keep", "review"
    include_sidecars: bool = True

class OrganizeRule(BaseModel):
    source_id: int
    destination_root: str
    pattern: str = "{year}/{year}-{month}/{date}_{camera}/{filename}"
    dry_run: bool = True
