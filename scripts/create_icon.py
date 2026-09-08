import os
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

def create_savespace_icon():
    size = 512
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Rounded squircle background
    pad = 20
    radius = 115
    
    # Shadow layer
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle(
        [pad + 8, pad + 14, size - pad - 8, size - pad],
        radius=radius,
        fill=(0, 0, 0, 160)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    img = Image.alpha_composite(shadow, img)
    draw = ImageDraw.Draw(img)

    # Base squircle card
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=radius,
        fill=(11, 17, 32, 255),
        outline=(30, 41, 59, 255),
        width=4
    )

    # Inner subtle glow edge
    draw.rounded_rectangle(
        [pad + 4, pad + 4, size - pad - 4, size - pad - 4],
        radius=radius - 4,
        outline=(15, 23, 42, 180),
        width=2
    )

    # 2. Cosmic storage disk / aperture rings (Cyan & Emerald)
    cx, cy = size // 2, size // 2
    r_outer = 175
    r_inner = 90
    r_hub = 38

    # Outer neon ring (gradient effect via layered concentric arcs)
    for i in range(12):
        w = 175 - i * 1.2
        alpha = int(220 - i * 14)
        # Left/top half cyan (#06b6d4: 6, 182, 212)
        draw.arc([cx - w, cy - w, cx + w, cy + w], start=135, end=315, fill=(6, 182, 212, alpha), width=3)
        # Right/bottom half emerald (#10b981: 16, 185, 129)
        draw.arc([cx - w, cy - w, cx + w, cy + w], start=-45, end=135, fill=(16, 185, 129, alpha), width=3)

    # Orbiting dots / space stars
    for angle_deg in [30, 75, 165, 210, 255, 330]:
        rad = math.radians(angle_deg)
        dot_r = 145
        dot_x = cx + dot_r * math.cos(rad)
        dot_y = cy + dot_r * math.sin(rad)
        d_size = 6 if angle_deg in [75, 255] else 4
        fill_col = (6, 182, 212, 230) if math.sin(rad) < 0 else (16, 185, 129, 230)
        draw.ellipse([dot_x - d_size, dot_y - d_size, dot_x + d_size, dot_y + d_size], fill=fill_col)

    # Inner disc track
    draw.ellipse([cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner], outline=(30, 41, 59, 255), width=3)

    # Bold stylized "S" monogram & storage drive read head
    s_width = 24
    
    # Upper S hook
    draw.arc([cx - 75, cy - 105, cx + 55, cy + 15], start=160, end=360, fill=(6, 182, 212, 255), width=s_width)
    # Middle diagonal spine
    draw.line([cx + 35, cy - 45, cx - 35, cy + 45], fill=(13, 198, 170, 255), width=s_width)
    # Lower S hook
    draw.arc([cx - 55, cy - 15, cx + 75, cy + 105], start=-20, end=180, fill=(16, 185, 129, 255), width=s_width)

    # Rounded caps on S ends
    draw.ellipse([cx - 75 - s_width // 2 + 12, cy - 50 - s_width // 2, cx - 75 + s_width // 2 + 12, cy - 50 + s_width // 2], fill=(6, 182, 212, 255))
    draw.ellipse([cx + 75 - s_width // 2 - 12, cy + 50 - s_width // 2, cx + 75 + s_width // 2 - 12, cy + 50 + s_width // 2], fill=(16, 185, 129, 255))

    # Center glowing hub
    draw.ellipse([cx - r_hub, cy - r_hub, cx + r_hub, cy + r_hub], fill=(15, 23, 42, 255), outline=(6, 182, 212, 220), width=3)
    draw.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], fill=(16, 185, 129, 255))
    draw.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=(255, 255, 255, 240))

    # Ensure icons folder exists
    icons_dir = Path("ui/icons")
    icons_dir.mkdir(parents=True, exist_ok=True)

    # Save 512x512 PNG
    png_path = icons_dir / "app_icon.png"
    img.save(str(png_path), "PNG")
    print(f"Saved PNG to {png_path}")

    # Generate multi-resolution .ico
    ico_path = icons_dir / "app_icon.ico"
    root_ico_path = Path("SaveSpace.ico")

    # Save icon with all standard Windows sizes
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    img.save(str(ico_path), format="ICO", sizes=sizes)
    img.save(str(root_ico_path), format="ICO", sizes=sizes)
    print(f"Saved ICO to {ico_path} and {root_ico_path}")

if __name__ == "__main__":
    create_savespace_icon()
