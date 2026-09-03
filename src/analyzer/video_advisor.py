"""
Video Compression Suitability Advisor
Analyzes video metadata (codec, resolution, bitrate, duration) to determine
whether transcoding will save space or risk inflating file size.
"""

from typing import Dict, Any, Optional

def format_bitrate(bps: int) -> str:
    """Formats bits-per-second into human-readable Mbps or kbps."""
    if not bps or bps <= 0:
        return "N/A"
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.1f} Mbps"
    return f"{bps / 1_000:.0f} kbps"

def analyze_video_suitability(
    codec: Optional[str],
    width: int,
    height: int,
    duration_sec: float,
    size_bytes: int,
    reported_bitrate: int = 0,
    fps: float = 0.0,
    profile_key: str = "nvenc_hq_10bit"
) -> Dict[str, Any]:
    """
    Evaluates whether a video file should be transcoded to H.265.
    
    Returns:
        Dict containing:
            - effective_bitrate: int
            - bitrate_formatted: str
            - suitability: 'high_savings' | 'moderate_savings' | 'already_compact' | 'already_hevc'
            - suitability_label: str
            - suitability_color: str
            - est_savings_pct: int (percentage 0 - 90)
            - est_savings_bytes: int
            - explanation: str
            - is_recommended: bool (True for high & moderate savings)
    """
    effective_bitrate = reported_bitrate or 0
    if effective_bitrate <= 0 and duration_sec > 0 and size_bytes > 0:
        effective_bitrate = int((size_bytes * 8) / duration_sec)

    norm_codec = (codec or "").lower().strip()
    norm_width = width or 1920
    norm_height = height or 1080
    pixels = norm_width * norm_height

    # Standard visually lossless H.265 (CQ 22 / CRF 22) bitrates
    if pixels >= 3840 * 1800 or norm_width >= 3200:
        res_label = "4K"
        target_bitrate = 18_000_000      # 18 Mbps
        bloat_threshold = 14_000_000     # <= 14 Mbps H.264 is already compressed
        high_savings_threshold = 40_000_000 # >= 40 Mbps has huge savings
    elif pixels >= 2560 * 1200 or norm_width >= 2400:
        res_label = "1440p"
        target_bitrate = 10_000_000      # 10 Mbps
        bloat_threshold = 8_000_000      # <= 8 Mbps
        high_savings_threshold = 22_000_000
    elif pixels >= 1600 * 900 or norm_width >= 1600:
        res_label = "1080p"
        target_bitrate = 5_000_000       # 5 Mbps
        bloat_threshold = 3_800_000      # <= 3.8 Mbps
        high_savings_threshold = 12_000_000
    elif pixels >= 1000 * 600 or norm_width >= 1000:
        res_label = "720p"
        target_bitrate = 2_500_000       # 2.5 Mbps
        bloat_threshold = 2_000_000      # <= 2 Mbps
        high_savings_threshold = 6_000_000
    else:
        res_label = "SD"
        target_bitrate = 1_200_000       # 1.2 Mbps
        bloat_threshold = 950_000        # <= 950 kbps
        high_savings_threshold = 3_000_000

    bitrate_str = format_bitrate(effective_bitrate)

    # Case A: Mezzanine / Camera Raw / Intra codecs (ProRes, DNxHD, MJPEG)
    if any(k in norm_codec for k in ["prores", "dnxhd", "mjpeg", "cineform", "raw"]):
        est_pct = 80
        est_saved_b = int(size_bytes * 0.80)
        return {
            "effective_bitrate": effective_bitrate,
            "bitrate_formatted": bitrate_str,
            "res_label": res_label,
            "suitability": "high_savings",
            "suitability_label": "High Savings (~80%)",
            "suitability_color": "var(--accent-emerald)",
            "est_savings_pct": est_pct,
            "est_savings_bytes": est_saved_b,
            "is_recommended": True,
            "explanation": "Uncompressed/ProRes footage. Converting to H.265 will reclaim ~80% space without visible quality loss."
        }

    # Case B: Already H.265 / HEVC / AV1 / VP9
    if any(k in norm_codec for k in ["hevc", "h265", "av1", "vp9"]):
        if effective_bitrate >= high_savings_threshold * 2:
            est_pct = min(85, max(30, int((1.0 - (target_bitrate / effective_bitrate)) * 100)))
            est_saved_b = int(size_bytes * (est_pct / 100.0))
            return {
                "effective_bitrate": effective_bitrate,
                "bitrate_formatted": bitrate_str,
                "res_label": res_label,
                "suitability": "high_savings",
                "suitability_label": f"Camera HEVC (~{est_pct}%)",
                "suitability_color": "var(--accent-emerald)",
                "est_savings_pct": est_pct,
                "est_savings_bytes": est_saved_b,
                "is_recommended": True,
                "explanation": f"High-bitrate camera HEVC ({bitrate_str}). Can be compressed to standard delivery HEVC."
            }
        else:
            return {
                "effective_bitrate": effective_bitrate,
                "bitrate_formatted": bitrate_str,
                "res_label": res_label,
                "suitability": "already_hevc",
                "suitability_label": "Already H.265",
                "suitability_color": "var(--accent-blue)",
                "est_savings_pct": 0,
                "est_savings_bytes": 0,
                "is_recommended": False,
                "explanation": f"File is already encoded with {norm_codec.upper()} at {bitrate_str}. Re-encoding will cause generational loss with no space savings."
            }

    # Case C: Low Bitrate H.264 (OBS recordings, web clips, screen captures) -> RISK OF BLOAT
    if 0 < effective_bitrate <= bloat_threshold:
        return {
            "effective_bitrate": effective_bitrate,
            "bitrate_formatted": bitrate_str,
            "res_label": res_label,
            "suitability": "already_compact",
            "suitability_label": "Already Compact (Bloat Risk)",
            "suitability_color": "var(--accent-rose)",
            "est_savings_pct": 0,
            "est_savings_bytes": 0,
            "is_recommended": False,
            "explanation": f"Current bitrate ({bitrate_str}) is already lower than target H.265 ({format_bitrate(target_bitrate)}). Re-encoding will likely INCREASE file size!"
        }

    # Case D: Moderate Bitrate H.264
    if 0 < effective_bitrate < high_savings_threshold:
        est_pct = min(50, max(20, int((1.0 - (target_bitrate / effective_bitrate)) * 100)))
        est_saved_b = int(size_bytes * (est_pct / 100.0))
        return {
            "effective_bitrate": effective_bitrate,
            "bitrate_formatted": bitrate_str,
            "res_label": res_label,
            "suitability": "moderate_savings",
            "suitability_label": f"Moderate (~{est_pct}%)",
            "suitability_color": "var(--accent-amber)",
            "est_savings_pct": est_pct,
            "est_savings_bytes": est_saved_b,
            "is_recommended": True,
            "explanation": f"Moderate bitrate {res_label} video ({bitrate_str}). Expected reduction: ~{est_pct}%."
        }

    # Case E: High Bitrate H.264 (Camera / DSLR / Drone)
    if effective_bitrate >= high_savings_threshold:
        est_pct = min(85, max(50, int((1.0 - (target_bitrate / effective_bitrate)) * 100)))
        est_saved_b = int(size_bytes * (est_pct / 100.0))
        return {
            "effective_bitrate": effective_bitrate,
            "bitrate_formatted": bitrate_str,
            "res_label": res_label,
            "suitability": "high_savings",
            "suitability_label": f"High Savings (~{est_pct}%)",
            "suitability_color": "var(--accent-emerald)",
            "est_savings_pct": est_pct,
            "est_savings_bytes": est_saved_b,
            "is_recommended": True,
            "explanation": f"High-bitrate camera footage ({bitrate_str}). Excellent candidate for {est_pct}% space reduction!"
        }

    # Fallback
    return {
        "effective_bitrate": 0,
        "bitrate_formatted": "Unknown",
        "res_label": res_label,
        "suitability": "moderate_savings",
        "suitability_label": "Standard (~40%)",
        "suitability_color": "var(--accent-amber)",
        "est_savings_pct": 40,
        "est_savings_bytes": int(size_bytes * 0.40),
        "is_recommended": True,
        "explanation": "Bitrate not available. Standard ~40% space savings estimated."
    }
