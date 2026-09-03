import os
import io
import json
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from PIL import Image, ExifTags
from src.config import FFMPEG_PATH, FFPROBE_PATH, THUMBNAILS_DIR, RAW_EXTS, VIDEO_EXTS

def extract_image_meta(file_path: str) -> Dict[str, Any]:
    meta = {
        "width": 0,
        "height": 0,
        "camera_make": None,
        "camera_model": None,
        "lens": None,
        "iso": None,
        "shutter": None,
        "aperture": None,
        "capture_date": None,
    }
    ext = Path(file_path).suffix.lower()

    if ext in RAW_EXTS:
        try:
            import exifread
            with open(file_path, "rb") as f:
                tags = exifread.process_file(f, details=False)
                if "Image Make" in tags:
                    meta["camera_make"] = str(tags["Image Make"]).strip()
                if "Image Model" in tags:
                    meta["camera_model"] = str(tags["Image Model"]).strip()
                if "EXIF LensModel" in tags:
                    meta["lens"] = str(tags["EXIF LensModel"]).strip()
                if "EXIF ISOSpeedRatings" in tags:
                    try:
                        meta["iso"] = int(str(tags["EXIF ISOSpeedRatings"]))
                    except:
                        pass
                if "EXIF ExposureTime" in tags:
                    meta["shutter"] = str(tags["EXIF ExposureTime"])
                if "EXIF FNumber" in tags:
                    try:
                        val = tags["EXIF FNumber"].values[0]
                        meta["aperture"] = round(float(val), 1)
                    except:
                        pass
                if "EXIF DateTimeOriginal" in tags:
                    meta["capture_date"] = str(tags["EXIF DateTimeOriginal"]).strip()
                elif "Image DateTime" in tags:
                    meta["capture_date"] = str(tags["Image DateTime"]).strip()
        except Exception:
            pass

    # Standard images or fallback
    if not meta["capture_date"]:
        try:
            with Image.open(file_path) as img:
                meta["width"], meta["height"] = img.size
                exif = img.getexif()
                if exif:
                    for tag_id, val in exif.items():
                        tag = ExifTags.TAGS.get(tag_id, tag_id)
                        if tag == "Make" and not meta["camera_make"]:
                            meta["camera_make"] = str(val).strip()
                        elif tag == "Model" and not meta["camera_model"]:
                            meta["camera_model"] = str(val).strip()
                        elif tag == "DateTimeOriginal" or tag == "DateTime":
                            meta["capture_date"] = str(val).strip()
        except Exception:
            pass

    return meta

def extract_video_meta(file_path: str) -> Dict[str, Any]:
    meta = {
        "width": 0,
        "height": 0,
        "duration_sec": 0.0,
        "video_codec": None,
        "audio_codec": None,
        "bitrate": 0,
        "fps": 0.0,
        "capture_date": None,
        "camera_make": None,
        "camera_model": None,
    }
    if not FFPROBE_PATH or not os.path.isfile(FFPROBE_PATH):
        return meta

    cmd = [
        FFPROBE_PATH,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        file_path
    ]
    try:
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0

        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, startupinfo=startupinfo, timeout=15)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            fmt = data.get("format", {})
            meta["duration_sec"] = float(fmt.get("duration", 0.0))
            meta["bitrate"] = int(fmt.get("bit_rate", 0))

            tags = fmt.get("tags", {})
            meta["capture_date"] = tags.get("creation_time") or tags.get("date")

            for stream in data.get("streams", []):
                codec_type = stream.get("codec_type")
                if codec_type == "video" and not meta["video_codec"]:
                    meta["video_codec"] = stream.get("codec_name")
                    meta["width"] = int(stream.get("width", 0))
                    meta["height"] = int(stream.get("height", 0))
                    # Frame rate
                    r_fps = stream.get("r_frame_rate", "0/1")
                    if "/" in r_fps:
                        num, den = r_fps.split("/")
                        if float(den) > 0:
                            meta["fps"] = round(float(num) / float(den), 2)
                elif codec_type == "audio" and not meta["audio_codec"]:
                    meta["audio_codec"] = stream.get("codec_name")
    except Exception:
        pass

    return meta

def generate_thumbnail(file_path: str, file_id: int) -> Optional[str]:
    """Generates an optimized thumbnail JPEG and saves in THUMBNAILS_DIR."""
    thumb_path = THUMBNAILS_DIR / f"{file_id}.jpg"
    if thumb_path.exists():
        return str(thumb_path)

    ext = Path(file_path).suffix.lower()

    # 1. RAW formats (Fuji .RAF, Sony .ARW, Canon .CR3, etc.)
    if ext in RAW_EXTS:
        try:
            import rawpy
            with rawpy.imread(file_path) as raw:
                try:
                    thumb = raw.extract_thumb()
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        # Downscale embedded high-res preview to true lightweight thumbnail
                        with Image.open(io.BytesIO(thumb.data)) as img:
                            img = img.convert("RGB")
                            img.thumbnail((380, 380), Image.Resampling.BILINEAR)
                            img.save(thumb_path, "JPEG", quality=80, optimize=True)
                        return str(thumb_path)
                    elif thumb.format == rawpy.ThumbFormat.BITMAP:
                        img = Image.fromarray(thumb.data)
                        img.thumbnail((380, 380), Image.Resampling.BILINEAR)
                        img.save(thumb_path, "JPEG", quality=80, optimize=True)
                        return str(thumb_path)
                except Exception:
                    pass
        except Exception:
            pass

    # 2. Standard Photos
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif"}:
        try:
            with Image.open(file_path) as img:
                img = img.convert("RGB")
                img.thumbnail((380, 380), Image.Resampling.BILINEAR)
                img.save(thumb_path, "JPEG", quality=80, optimize=True)
                return str(thumb_path)
        except Exception:
            pass

    # 3. Videos (extract frame via ffmpeg)
    if ext in VIDEO_EXTS and FFMPEG_PATH:
        cmd = [
            FFMPEG_PATH,
            "-ss", "00:00:01",
            "-i", file_path,
            "-vframes", "1",
            "-vf", "scale='min(380,iw)':-1",
            "-q:v", "4",
            "-y",
            str(thumb_path)
        ]
        try:
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo, timeout=10)
            if thumb_path.exists():
                return str(thumb_path)
        except Exception:
            pass

    return None
