import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def build_full_circle_icon(variant="dark"):
    # Render at 4x (2048x2048) for ultra-sharp Lanczos antialiasing
    S = 2048
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = S // 2, S // 2
    # Full size circle: radius 990 (diameter 1980 / 2048 = 96.7% of canvas)
    R = 990

    if variant == "dark":
        disc_fill = (11, 17, 32, 255) # Deep navy/obsidian
        disc_border = (30, 58, 138, 200) # Subtle deep blue rim
        cycle_color1 = (34, 211, 238, 255) # Cyan
        cycle_color2 = (59, 130, 246, 255) # Blue
        text_color = (255, 255, 255, 255)
        reticle_color = (34, 211, 238, 190)
    elif variant == "solid_cyan":
        disc_fill = (6, 182, 212, 255) # Rich cyan
        disc_border = (8, 145, 178, 255)
        cycle_color1 = (255, 255, 255, 255)
        cycle_color2 = (255, 255, 255, 255)
        text_color = (15, 23, 42, 255)
        reticle_color = (15, 23, 42, 180)
    else: # ring_only (transparent inside & outside)
        disc_fill = (11, 17, 32, 230)
        disc_border = (56, 189, 248, 100)
        cycle_color1 = (34, 211, 238, 255)
        cycle_color2 = (99, 102, 241, 255)
        text_color = (255, 255, 255, 255)
        reticle_color = (34, 211, 238, 200)

    # 1. Base Full-Size Circle Disc
    draw.ellipse([cx - R, cy - R, cx + R, cy + R], fill=disc_fill, outline=disc_border, width=16)

    # 2. Cycle Arrows Ring (diameter ~800, thickness ~90)
    r_cycle = 780
    thick = 85

    # Top arc: from angle 195 deg to 345 deg (counter-clockwise in draw.arc: start 195, end 345)
    draw.arc([cx - r_cycle, cy - r_cycle, cx + r_cycle, cy + r_cycle], start=195, end=345, fill=cycle_color1, width=thick)

    # Top Arrowhead at angle ~348 deg (near top-right)
    # Arrowhead geometry pointing clockwise
    a_top = math.radians(-12)
    tx = cx + r_cycle * math.cos(a_top)
    ty = cy + r_cycle * math.sin(a_top)
    # Tangent vector: angle + 90 deg
    tan_x = -math.sin(a_top)
    tan_y = math.cos(a_top)
    norm_x = -tan_y
    norm_y = tan_x
    arrow_len = 160
    arrow_w = 120

    tip_t = (tx + tan_x * arrow_len * 0.7, ty + tan_y * arrow_len * 0.7)
    base_left_t = (tx - tan_x * arrow_len * 0.3 + norm_x * arrow_w * 0.6, ty - tan_y * arrow_len * 0.3 + norm_y * arrow_w * 0.6)
    base_right_t = (tx - tan_x * arrow_len * 0.3 - norm_x * arrow_w * 0.6, ty - tan_y * arrow_len * 0.3 - norm_y * arrow_w * 0.6)
    draw.polygon([tip_t, base_left_t, base_right_t], fill=cycle_color1)

    # Bottom arc: from angle 15 deg to 165 deg
    draw.arc([cx - r_cycle, cy - r_cycle, cx + r_cycle, cy + r_cycle], start=15, end=165, fill=cycle_color2, width=thick)

    # Bottom Arrowhead at angle ~168 deg (near bottom-left)
    a_bot = math.radians(168)
    bx = cx + r_cycle * math.cos(a_bot)
    by = cy + r_cycle * math.sin(a_bot)
    tan_bx = -math.sin(a_bot)
    tan_by = math.cos(a_bot)
    norm_bx = -tan_by
    norm_by = tan_bx

    tip_b = (bx + tan_bx * arrow_len * 0.7, by + tan_by * arrow_len * 0.7)
    base_left_b = (bx - tan_bx * arrow_len * 0.3 + norm_bx * arrow_w * 0.6, by - tan_by * arrow_len * 0.3 + norm_by * arrow_w * 0.6)
    base_right_b = (bx - tan_bx * arrow_len * 0.3 - norm_bx * arrow_w * 0.6, by - tan_by * arrow_len * 0.3 - norm_by * arrow_w * 0.6)
    draw.polygon([tip_b, base_left_b, base_right_b], fill=cycle_color2)

    # 3. Autofocus Viewfinder Corner Brackets [ + ]
    ret_w = 460
    ret_h = 320
    ret_arm = 80
    ret_th = 28
    
    rx1, rx2 = cx - ret_w, cx + ret_w
    ry1, ry2 = cy - ret_h, cy + ret_h

    # Top-Left [
    draw.line([(rx1, ry1 + ret_arm), (rx1, ry1), (rx1 + ret_arm, ry1)], fill=reticle_color, width=ret_th)
    # Top-Right ]
    draw.line([(rx2 - ret_arm, ry1), (rx2, ry1), (rx2, ry1 + ret_arm)], fill=reticle_color, width=ret_th)
    # Bottom-Left [
    draw.line([(rx1, ry2 - ret_arm), (rx1, ry2), (rx1 + ret_arm, ry2)], fill=reticle_color, width=ret_th)
    # Bottom-Right ]
    draw.line([(rx2 - ret_arm, ry2), (rx2, ry2), (rx2 - ret_arm, ry2)], fill=reticle_color, width=ret_th)

    # 4. Bold Centered 'FLS' Typography
    font_path = "C:/Windows/Fonts/segoeuib.ttf"
    if not Path(font_path).exists():
        font_path = "C:/Windows/Fonts/arialbd.ttf"
    
    font_size = 380
    font = ImageFont.truetype(font_path, font_size)
    text = "FLS"

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    
    # Visual optical center adjustment
    tx_pos = cx - tw // 2 - bbox[0]
    ty_pos = cy - th // 2 - bbox[1] - 15
    draw.text((tx_pos, ty_pos), text, font=font, fill=text_color)

    # Downsample to 512x512 with high-quality Lanczos filter
    final_img = img.resize((512, 512), Image.Resampling.LANCZOS)
    return final_img

if __name__ == "__main__":
    out_dir = Path("ui/icons")
    
    # 1. Build variants
    dark_icon = build_full_circle_icon("dark")
    dark_icon.save(out_dir / "fls_full_circle_dark.png", "PNG")
    
    cyan_icon = build_full_circle_icon("solid_cyan")
    cyan_icon.save(out_dir / "fls_full_circle_cyan.png", "PNG")

    # 2. Save primary app_icon.png and multi-size ICO
    dark_icon.save(out_dir / "app_icon.png", "PNG")
    
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    dark_icon.save(out_dir / "app_icon.ico", format="ICO", sizes=ico_sizes)
    dark_icon.save("FocusloopLabs.ico", format="ICO", sizes=ico_sizes)
    
    print("Successfully created full-size circular icon with transparent background!")
