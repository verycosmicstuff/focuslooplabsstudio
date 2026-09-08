import os
import io
import math
import time
import base64
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance

from src.config import RAW_EXTS, PHOTO_EXTS
from src.core.logger import get_logger
from src.core.session import record_last_task

logger = get_logger("watermarker")

def load_default_font(size: int) -> ImageFont.ImageFont:
    """Attempts to load a standard clean TrueType font on Windows, falling back gracefully."""
    font_candidates = [
        "arial.ttf",
        "segoeui.ttf",
        "calibri.ttf",
        "tahoma.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf"
    ]
    for candidate in font_candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None

def open_image_source(file_path: str) -> Optional[Image.Image]:
    """
    Opens an image safely, handling RAW files by extracting embedded preview,
    and automatically transposing EXIF orientation.
    """
    p = Path(file_path)
    if not p.exists():
        return None

    ext = p.suffix.lower()

    # RAW formats handling
    if ext in RAW_EXTS:
        try:
            import rawpy
            with rawpy.imread(file_path) as raw:
                try:
                    thumb = raw.extract_thumb()
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        img = Image.open(io.BytesIO(thumb.data))
                        img = ImageOps.exif_transpose(img)
                        return img.convert("RGBA")
                    elif thumb.format == rawpy.ThumbFormat.BITMAP:
                        img = Image.fromarray(thumb.data)
                        img = ImageOps.exif_transpose(img)
                        return img.convert("RGBA")
                except Exception:
                    pass
                # Fallback: rapid half-size decoding if embedded thumb missing
                try:
                    rgb = raw.postprocess(half_size=True, use_camera_wb=True)
                    return Image.fromarray(rgb).convert("RGBA")
                except Exception:
                    pass
        except Exception:
            pass

    # Standard formats
    try:
        img = Image.open(file_path)
        img = ImageOps.exif_transpose(img)
        return img.convert("RGBA")
    except Exception:
        return None

def apply_text_watermark(
    base_img: Image.Image,
    text: str,
    position: str = "diagonal_grid",
    opacity: float = 0.35,
    font_scale: float = 0.04,
    color_hex: str = "#FFFFFF",
    include_shadow: bool = True
) -> Image.Image:
    """
    Applies text watermark to an RGBA image.
    Supports positions: 'diagonal_grid', 'center', 'bottom-right', 'bottom-left', 'top-right', 'top-left'.
    """
    if not text:
        return base_img

    width, height = base_img.size
    overlay = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    # Calculate font size relative to image dimension
    min_dim = min(width, height)
    font_size = max(16, int(min_dim * font_scale))
    font = load_default_font(font_size)

    # Parse hex color
    hex_clean = color_hex.lstrip("#")
    if len(hex_clean) == 6:
        r = int(hex_clean[0:2], 16)
        g = int(hex_clean[2:4], 16)
        b = int(hex_clean[4:6], 16)
    else:
        r, g, b = 255, 255, 255

    alpha = int(max(0.0, min(1.0, opacity)) * 255)
    text_color = (r, g, b, alpha)
    shadow_color = (0, 0, 0, int(alpha * 0.75))

    # Helper to calculate text bounding box
    def get_text_dimensions(txt: str):
        try:
            bbox = font.getbbox(txt)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            return font_size * len(txt) * 0.6, font_size

    tw, th = get_text_dimensions(text)

    if position == "diagonal_grid":
        # Create a single rotated tile of text on a temporary canvas
        tile_w = int(tw * 2.2 + 80)
        tile_h = int(th * 4.0 + 80)
        tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
        tdraw = ImageDraw.Draw(tile)

        # Draw text at center of tile
        tx = (tile_w - tw) // 2
        ty = (tile_h - th) // 2
        if include_shadow:
            tdraw.text((tx + 2, ty + 2), text, font=font, fill=shadow_color)
        tdraw.text((tx, ty), text, font=font, fill=text_color)

        # Rotate tile -30 degrees
        rotated_tile = tile.rotate(30, resample=Image.Resampling.BICUBIC, expand=True)
        rt_w, rt_h = rotated_tile.size

        # Tile across overlay
        step_x = max(1, int(rt_w * 0.85))
        step_y = max(1, int(rt_h * 0.85))

        for y in range(-rt_h, height + rt_h, step_y):
            for x in range(-rt_w, width + rt_w, step_x):
                overlay.alpha_composite(rotated_tile, (x, y))

    else:
        margin_x = int(width * 0.04)
        margin_y = int(height * 0.04)

        if position == "center":
            x = (width - tw) // 2
            y = (height - th) // 2
        elif position == "top-center":
            x = (width - tw) // 2
            y = margin_y
        elif position == "bottom-center":
            x = (width - tw) // 2
            y = height - th - margin_y
        elif position == "top-left":
            x = margin_x
            y = margin_y
        elif position == "top-right":
            x = width - tw - margin_x
            y = margin_y
        elif position == "bottom-left":
            x = margin_x
            y = height - th - margin_y
        else:  # 'bottom-right' default
            x = width - tw - margin_x
            y = height - th - margin_y

        if include_shadow:
            draw.text((x + 2, y + 2), text, font=font, fill=shadow_color)
        draw.text((x, y), text, font=font, fill=text_color)

    # Composite overlay on top of base image
    return Image.alpha_composite(base_img, overlay)

def apply_logo_watermark(
    base_img: Image.Image,
    logo_path: str,
    position: str = "bottom-right",
    opacity: float = 0.8,
    scale_pct: float = 0.18
) -> Image.Image:
    """Applies a PNG logo with transparency to the base image."""
    if not logo_path or not os.path.isfile(logo_path):
        return base_img

    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception:
        return base_img

    bw, bh = base_img.size
    target_w = max(40, int(bw * max(0.05, min(0.8, scale_pct))))
    aspect = logo.size[1] / max(1, logo.size[0])
    target_h = max(20, int(target_w * aspect))

    logo_resized = logo.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # Adjust opacity
    alpha_mult = max(0.0, min(1.0, opacity))
    if alpha_mult < 1.0:
        r, g, b, a = logo_resized.split()
        a = a.point(lambda p: int(p * alpha_mult))
        logo_resized.putalpha(a)

    margin_x = int(bw * 0.04)
    margin_y = int(bh * 0.04)

    if position == "center":
        x = (bw - target_w) // 2
        y = (bh - target_h) // 2
    elif position == "top-center":
        x = (bw - target_w) // 2
        y = margin_y
    elif position == "bottom-center":
        x = (bw - target_w) // 2
        y = bh - target_h - margin_y
    elif position == "top-left":
        x = margin_x
        y = margin_y
    elif position == "top-right":
        x = bw - target_w - margin_x
        y = margin_y
    elif position == "bottom-left":
        x = margin_x
        y = bh - target_h - margin_y
    else:  # bottom-right
        x = bw - target_w - margin_x
        y = bh - target_h - margin_y

    overlay = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    overlay.paste(logo_resized, (x, y), logo_resized)
    return Image.alpha_composite(base_img, overlay)

def resize_for_web_proof(img: Image.Image, max_dimension: int = 2048) -> Image.Image:
    """Downscales image so its long edge does not exceed max_dimension."""
    if max_dimension <= 0:
        return img

    w, h = img.size
    long_edge = max(w, h)
    if long_edge <= max_dimension:
        return img

    ratio = max_dimension / float(long_edge)
    new_w = max(1, int(w * ratio))
    new_h = max(1, int(h * ratio))

    return img.resize((new_w, new_h), Image.Resampling.LANCZOS)

def process_single_image(
    input_path: str,
    output_path: str,
    config: Dict[str, Any]
) -> bool:
    """
    Loads an image, applies watermark, resizes for web proofing, and saves as JPEG.
    """
    img = open_image_source(input_path)
    if not img:
        return False

    mode = config.get("watermark_type", "text") # "text", "logo", or "both"

    if mode in ("text", "both"):
        text = config.get("text", "PROOF ONLY")
        position = config.get("position", "diagonal_grid")
        opacity = float(config.get("opacity", 0.35))
        font_scale = float(config.get("font_scale", 0.04))
        color_hex = config.get("color_hex", "#FFFFFF")
        shadow = bool(config.get("shadow", True))
        img = apply_text_watermark(img, text, position, opacity, font_scale, color_hex, shadow)

    if mode in ("logo", "both"):
        logo_path = config.get("logo_path", "")
        logo_pos = config.get("logo_position", "bottom-right")
        logo_opacity = float(config.get("logo_opacity", 0.8))
        logo_scale = float(config.get("logo_scale", 0.18))
        img = apply_logo_watermark(img, logo_path, logo_pos, logo_opacity, logo_scale)

    # Web proof resize
    max_dim = int(config.get("max_dimension", 2048))
    img = resize_for_web_proof(img, max_dim)

    # Convert to RGB JPEG
    rgb_img = img.convert("RGB")
    quality = int(config.get("quality", 80))

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    rgb_img.save(str(out_p), "JPEG", quality=quality, optimize=True)
    return True

def generate_watermark_preview(
    input_path: str,
    config: Dict[str, Any],
    preview_size: int = 900
) -> Optional[str]:
    """
    Generates a fast base64 data-URI JPEG preview with watermarks applied
    for instantaneous display in the web UI.
    """
    img = open_image_source(input_path)
    if not img:
        return None

    # Downscale first for lightning-fast preview responsiveness
    img = resize_for_web_proof(img, preview_size)

    mode = config.get("watermark_type", "text")
    if mode in ("text", "both"):
        text = config.get("text", "PROOF ONLY")
        position = config.get("position", "diagonal_grid")
        opacity = float(config.get("opacity", 0.35))
        font_scale = float(config.get("font_scale", 0.04))
        color_hex = config.get("color_hex", "#FFFFFF")
        shadow = bool(config.get("shadow", True))
        img = apply_text_watermark(img, text, position, opacity, font_scale, color_hex, shadow)

    if mode in ("logo", "both"):
        logo_path = config.get("logo_path", "")
        logo_pos = config.get("logo_position", "bottom-right")
        logo_opacity = float(config.get("logo_opacity", 0.8))
        logo_scale = float(config.get("logo_scale", 0.18))
        img = apply_logo_watermark(img, logo_path, logo_pos, logo_opacity, logo_scale)

    rgb_img = img.convert("RGB")
    buf = io.BytesIO()
    rgb_img.save(buf, "JPEG", quality=82, optimize=True)
    buf.seek(0)
    b64_str = base64.b64encode(buf.read()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64_str}"

class WatermarkBatchManager:
    """Manages background batch watermark export with progress tracking."""
    def __init__(self):
        self._lock = threading.Lock()
        self.is_running = False
        self.cancel_requested = False
        self.total = 0
        self.completed = 0
        self.failed = 0
        self.current_file = ""
        self.destination_dir = ""
        self.errors = []
        self.start_time = 0.0

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            elapsed = time.time() - self.start_time if self.is_running else 0.0
            pct = round((self.completed / max(1, self.total)) * 100, 1) if self.total > 0 else 0.0
            return {
                "is_running": self.is_running,
                "total": self.total,
                "completed": self.completed,
                "failed": self.failed,
                "percent": pct,
                "current_file": self.current_file,
                "destination_dir": self.destination_dir,
                "elapsed_sec": round(elapsed, 1),
                "errors": self.errors[-10:] # last 10 errors
            }

    def cancel(self):
        with self._lock:
            if self.is_running:
                self.cancel_requested = True

    def start_batch(
        self,
        files: List[Dict[str, Any]],
        output_dir: Optional[str],
        config: Dict[str, Any],
        suffix: str = "_proof",
        output_mode: str = "custom_dir",
        subfolder_name: str = "_proofs",
        subfolder_type: str = "suffix"
    ) -> bool:
        with self._lock:
            if self.is_running:
                return False
            self.is_running = True
            self.cancel_requested = False
            self.total = len(files)
            self.completed = 0
            self.failed = 0
            self.current_file = ""
            self.destination_dir = output_dir if output_mode == "custom_dir" else f"Respective Original Folders ({output_mode})"
            self.errors = []
            self.start_time = time.time()

        thread = threading.Thread(
            target=self._run_batch,
            args=(files, output_dir, config, suffix, output_mode, subfolder_name, subfolder_type),
            daemon=True
        )
        logger.info(f"Starting batch watermark export: {len(files)} items, mode={output_mode}, dest={self.destination_dir}")
        thread.start()
        return True

    def _run_batch(
        self,
        files: List[Dict[str, Any]],
        output_dir: Optional[str],
        config: Dict[str, Any],
        suffix: str,
        output_mode: str,
        subfolder_name: str,
        subfolder_type: str = "suffix"
    ):
        if output_mode == "custom_dir":
            if not output_dir:
                with self._lock:
                    self.errors.append("Output directory not specified for custom_dir mode")
                    self.is_running = False
                logger.error("Watermark batch cancelled: No output directory specified for custom_dir mode")
                return
            out_root = Path(output_dir)
            try:
                out_root.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                with self._lock:
                    self.errors.append(f"Failed to create output directory: {str(e)}")
                    self.is_running = False
                logger.error(f"Watermark batch failed: Could not create output directory: {e}")
                return

        for item in files:
            with self._lock:
                if self.cancel_requested:
                    self.is_running = False
                    logger.info("Watermark batch cancelled by user request")
                    break

            file_path = item.get("abs_path") or item.get("path")
            if not file_path or not os.path.isfile(file_path):
                with self._lock:
                    self.failed += 1
                    self.completed += 1
                continue

            p = Path(file_path)
            stem = p.stem
            out_filename = f"{stem}{suffix}.jpg"

            if output_mode == "original_folder":
                target_dir = p.parent
            elif output_mode == "original_subfolder":
                clean_val = (subfolder_name or "_proofs").strip().strip("/\\")
                parent_name = p.parent.name
                if subfolder_type == "prefix":
                    sep = "" if clean_val.endswith(("_", "-", " ")) else "_"
                    resolved_folder_name = f"{clean_val}{sep}{parent_name}"
                elif subfolder_type == "suffix":
                    sep = "" if clean_val.startswith(("_", "-", " ")) else "_"
                    resolved_folder_name = f"{parent_name}{sep}{clean_val}"
                else:  # "custom" exact name
                    resolved_folder_name = clean_val or "_proofs"
                target_dir = p.parent / resolved_folder_name
            else:
                target_dir = Path(output_dir)

            try:
                target_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                with self._lock:
                    self.failed += 1
                    self.completed += 1
                    self.errors.append(f"Folder create failed for {p.name}: {str(e)}")
                continue

            out_path = target_dir / out_filename

            with self._lock:
                self.current_file = p.name

            try:
                success = process_single_image(str(p), str(out_path), config)
                with self._lock:
                    if success:
                        self.completed += 1
                    else:
                        self.failed += 1
                        self.completed += 1
                        self.errors.append(f"Could not process: {p.name}")
            except Exception as e:
                with self._lock:
                    self.failed += 1
                    self.completed += 1
                    self.errors.append(f"{p.name}: {str(e)}")

        with self._lock:
            self.is_running = False
            self.current_file = ""
            final_completed = self.completed
            final_failed = self.failed
            was_cancelled = self.cancel_requested

        summary = f"Watermarked {final_completed} photos ({final_failed} failed) to {output_mode}"
        if was_cancelled:
            summary += " [Cancelled]"
        logger.info(f"Batch watermark completed: {summary}")
        record_last_task(
            task_type="watermark_batch",
            summary=summary,
            details={
                "total": len(files),
                "completed": final_completed,
                "failed": final_failed,
                "output_mode": output_mode,
                "destination": self.destination_dir,
                "cancelled": was_cancelled
            }
        )

# Global instance
watermark_manager = WatermarkBatchManager()
