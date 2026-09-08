import os
import re
import io
import json
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from PIL import Image

from src.config import RAW_EXTS, PHOTO_EXTS
from src.proofing.watermarker import open_image_source, resize_for_web_proof, apply_text_watermark, apply_logo_watermark
from src.core.db import get_db

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>__PROJECT_TITLE__ — Client Contact Sheet & Selects</title>
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: #151d30;
      --card-border: #24304f;
      --accent: #06b6d4;
      --accent-hover: #0891b2;
      --accent-pink: #ec4899;
      --text: #f1f5f9;
      --text-muted: #94a3b8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background: var(--bg); color: var(--text); padding-bottom: 100px; min-height: 100vh; }
    
    header {
      background: #0f172a;
      border-bottom: 1px solid var(--card-border);
      padding: 24px 32px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 16px;
      position: sticky;
      top: 0;
      z-index: 50;
    }
    .title-area h1 { font-size: 22px; font-weight: 700; color: #fff; margin-bottom: 4px; }
    .title-area p { font-size: 13px; color: var(--text-muted); }

    .toolbar {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .search-input {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: #fff;
      padding: 8px 14px;
      border-radius: 8px;
      font-size: 13px;
      outline: none;
      width: 180px;
    }
    .filter-btn {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text);
      padding: 8px 14px;
      border-radius: 8px;
      font-size: 13px;
      cursor: pointer;
      font-weight: 600;
      transition: all 0.2s;
    }
    .filter-btn.active { background: var(--accent); color: #042f2e; border-color: var(--accent); }

    .instructions-box {
      margin: 20px 32px 0 32px;
      padding: 14px 20px;
      background: rgba(6, 182, 212, 0.08);
      border: 1px solid rgba(6, 182, 212, 0.25);
      border-radius: 10px;
      font-size: 13px;
      color: #cbd5e1;
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .gallery-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
      gap: 18px;
      padding: 24px 32px;
    }

    .card {
      background: var(--card-bg);
      border: 2px solid var(--card-border);
      border-radius: 12px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      position: relative;
      transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;
      cursor: pointer;
    }
    .card:hover { transform: translateY(-3px); border-color: #38bdf8; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5); }
    .card.selected { border-color: var(--accent-pink); background: #1c1a2e; }

    .thumb-wrap {
      width: 100%;
      height: 200px;
      background: #020617;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      position: relative;
    }
    .thumb-wrap img {
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
      transition: transform 0.3s;
    }
    .card:hover .thumb-wrap img { transform: scale(1.03); }

    .idx-badge {
      position: absolute;
      top: 8px;
      left: 8px;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(4px);
      padding: 3px 8px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 700;
      color: #94a3b8;
    }

    .select-toggle {
      position: absolute;
      top: 8px;
      right: 8px;
      background: rgba(0, 0, 0, 0.75);
      border: 1px solid var(--card-border);
      width: 34px;
      height: 34px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: all 0.2s;
      color: #64748b;
      font-size: 16px;
      z-index: 10;
    }
    .select-toggle:hover { transform: scale(1.15); color: #fff; }
    .card.selected .select-toggle {
      background: var(--accent-pink);
      border-color: var(--accent-pink);
      color: #fff;
    }

    .card-footer {
      padding: 10px 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-top: 1px solid var(--card-border);
      background: rgba(0, 0, 0, 0.15);
    }
    .filename {
      font-size: 12px;
      font-weight: 600;
      color: #cbd5e1;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 160px;
    }

    /* Sticky Bottom Action Bar */
    .action-bar {
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      background: rgba(15, 23, 42, 0.95);
      backdrop-filter: blur(12px);
      border-top: 1px solid var(--card-border);
      padding: 16px 32px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      z-index: 100;
      box-shadow: 0 -10px 30px rgba(0, 0, 0, 0.6);
    }
    .counter-text {
      font-size: 15px;
      font-weight: 700;
      color: #fff;
    }
    .counter-text span { color: var(--accent-pink); font-size: 18px; }

    .btn {
      padding: 10px 18px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      border: none;
      transition: all 0.2s;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .btn-primary { background: var(--accent-pink); color: #fff; }
    .btn-primary:hover { background: #db2777; transform: translateY(-1px); }
    .btn-secondary { background: #334155; color: #fff; }
    .btn-secondary:hover { background: #475569; }

    /* Lightbox Modal */
    .lightbox-modal {
      display: none;
      position: fixed;
      top: 0; left: 0; width: 100%; height: 100%;
      background: rgba(0, 0, 0, 0.94);
      backdrop-filter: blur(8px);
      z-index: 200;
      align-items: center;
      justify-content: center;
      flex-direction: column;
    }
    .lightbox-modal.open { display: flex; }
    .lightbox-img-wrap {
      max-width: 90vw;
      max-height: 80vh;
      display: flex;
      align-items: center;
      justify-content: center;
      position: relative;
    }
    .lightbox-img-wrap img {
      max-width: 100%;
      max-height: 80vh;
      object-fit: contain;
      border-radius: 8px;
      box-shadow: 0 15px 50px rgba(0,0,0,0.8);
    }
    .lightbox-info {
      margin-top: 14px;
      font-size: 14px;
      color: #cbd5e1;
      display: flex;
      gap: 20px;
      align-items: center;
    }
    .lb-close {
      position: absolute;
      top: 20px;
      right: 28px;
      background: none;
      border: none;
      color: #fff;
      font-size: 32px;
      cursor: pointer;
    }
    .lb-nav {
      position: absolute;
      top: 50%;
      transform: translateY(-50%);
      background: rgba(255, 255, 255, 0.1);
      border: none;
      color: #fff;
      width: 48px;
      height: 48px;
      border-radius: 50%;
      font-size: 20px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.2s;
    }
    .lb-nav:hover { background: rgba(255, 255, 255, 0.25); }
    .lb-prev { left: 24px; }
    .lb-next { right: 24px; }

    /* Toast */
    .toast {
      position: fixed;
      bottom: 90px;
      right: 32px;
      background: #10b981;
      color: #fff;
      padding: 12px 20px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      box-shadow: 0 10px 25px rgba(0,0,0,0.4);
      display: none;
      z-index: 300;
    }
  </style>
</head>
<body>

  <header>
    <div class="title-area">
      <h1>__PROJECT_TITLE__</h1>
      <p>Client: <strong>__CLIENT_NAME__</strong> &bull; Date: __DATE_STR__ &bull; Total Images: __TOTAL_COUNT__</p>
    </div>
    <div class="toolbar">
      <input type="text" id="searchInput" class="search-input" placeholder="Search filename...">
      <button id="btnFilterAll" class="filter-btn active">All (__TOTAL_COUNT__)</button>
      <button id="btnFilterSelected" class="filter-btn">Selected (<span id="filterCount">0</span>)</button>
    </div>
  </header>

  <div class="instructions-box">
    <span>💡</span>
    <span>__INSTRUCTIONS__</span>
  </div>

  <main class="gallery-grid" id="galleryGrid">
    __CARDS_HTML__
  </main>

  <footer class="action-bar">
    <div class="counter-text">
      Selected: <span id="selectedCount">0</span> of __TOTAL_COUNT__ photos
    </div>
    <div style="display: flex; gap: 10px;">
      <button id="btnCopyPicks" class="btn btn-primary">
        📋 Copy Selected Filenames
      </button>
      <button id="btnDownloadTxt" class="btn btn-secondary">
        💾 Download .TXT List
      </button>
      <button id="btnDownloadJson" class="btn btn-secondary">
        📦 Download .JSON
      </button>
    </div>
  </footer>

  <!-- Lightbox Modal -->
  <div id="lightbox" class="lightbox-modal">
    <button class="lb-close" id="lbClose">&times;</button>
    <button class="lb-nav lb-prev" id="lbPrev">&#10094;</button>
    <div class="lightbox-img-wrap">
      <img id="lbImg" src="" alt="Preview">
    </div>
    <button class="lb-nav lb-next" id="lbNext">&#10095;</button>
    <div class="lightbox-info">
      <span id="lbFilename" style="font-weight: 700;"></span>
      <button id="lbToggleSelect" class="btn btn-primary btn-sm" style="padding: 6px 14px;">Toggle Select</button>
    </div>
  </div>

  <div id="toast" class="toast">Selections copied to clipboard!</div>

  <script>
    const itemsData = __ITEMS_JSON__;
    const selectedSet = new Set();
    let currentFilter = 'all';
    let currentSearch = '';
    let currentLbIdx = 0;

    const cards = document.querySelectorAll('.card');
    const selectedCountEl = document.getElementById('selectedCount');
    const filterCountEl = document.getElementById('filterCount');
    const toast = document.getElementById('toast');

    function updateUi() {
      selectedCountEl.textContent = selectedSet.size;
      filterCountEl.textContent = selectedSet.size;

      cards.forEach((c) => {
        const fn = c.dataset.filename;
        const isSel = selectedSet.has(fn);
        c.classList.toggle('selected', isSel);

        const matchesSearch = fn.toLowerCase().includes(currentSearch);
        const matchesFilter = currentFilter === 'all' || (currentFilter === 'selected' && isSel);

        c.style.display = (matchesSearch && matchesFilter) ? 'flex' : 'none';
      });
    }

    function toggleSelect(fn) {
      if (selectedSet.has(fn)) {
        selectedSet.delete(fn);
      } else {
        selectedSet.add(fn);
      }
      updateUi();
    }

    cards.forEach((c, idx) => {
      const fn = c.dataset.filename;
      const btn = c.querySelector('.select-toggle');

      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleSelect(fn);
      });

      c.addEventListener('click', () => {
        openLightbox(idx);
      });
    });

    // Filtering & Searching
    document.getElementById('searchInput').addEventListener('input', (e) => {
      currentSearch = e.target.value.toLowerCase().trim();
      updateUi();
    });

    const btnAll = document.getElementById('btnFilterAll');
    const btnSel = document.getElementById('btnFilterSelected');

    btnAll.addEventListener('click', () => {
      currentFilter = 'all';
      btnAll.classList.add('active');
      btnSel.classList.remove('active');
      updateUi();
    });

    btnSel.addEventListener('click', () => {
      currentFilter = 'selected';
      btnSel.classList.add('active');
      btnAll.classList.remove('active');
      updateUi();
    });

    // Lightbox
    const lb = document.getElementById('lightbox');
    const lbImg = document.getElementById('lbImg');
    const lbFilename = document.getElementById('lbFilename');
    const lbToggleBtn = document.getElementById('lbToggleSelect');

    function openLightbox(idx) {
      currentLbIdx = idx;
      const item = itemsData[idx];
      lbImg.src = item.thumb;
      lbFilename.textContent = item.filename;
      lb.classList.add('open');
      updateLbBtn();
    }

    function updateLbBtn() {
      const fn = itemsData[currentLbIdx].filename;
      if (selectedSet.has(fn)) {
        lbToggleBtn.textContent = '★ Selected (Click to Remove)';
        lbToggleBtn.style.background = '#ec4899';
      } else {
        lbToggleBtn.textContent = '☆ Select Photo';
        lbToggleBtn.style.background = '#06b6d4';
      }
    }

    lbToggleBtn.addEventListener('click', () => {
      const fn = itemsData[currentLbIdx].filename;
      toggleSelect(fn);
      updateLbBtn();
    });

    document.getElementById('lbClose').addEventListener('click', () => lb.classList.remove('open'));
    document.getElementById('lbPrev').addEventListener('click', () => {
      currentLbIdx = (currentLbIdx - 1 + itemsData.length) % itemsData.length;
      openLightbox(currentLbIdx);
    });
    document.getElementById('lbNext').addEventListener('click', () => {
      currentLbIdx = (currentLbIdx + 1) % itemsData.length;
      openLightbox(currentLbIdx);
    });

    window.addEventListener('keydown', (e) => {
      if (!lb.classList.contains('open')) return;
      if (e.key === 'Escape') lb.classList.remove('open');
      if (e.key === 'ArrowLeft') document.getElementById('lbPrev').click();
      if (e.key === 'ArrowRight') document.getElementById('lbNext').click();
      if (e.key === ' ') { e.preventDefault(); lbToggleBtn.click(); }
    });

    function showToast(msg) {
      toast.textContent = msg;
      toast.style.display = 'block';
      setTimeout(() => { toast.style.display = 'none'; }, 3000);
    }

    // Export buttons
    document.getElementById('btnCopyPicks').addEventListener('click', () => {
      if (selectedSet.size === 0) {
        alert('Please select at least one photo first!');
        return;
      }
      const list = Array.from(selectedSet).join(', ');
      navigator.clipboard.writeText(list).then(() => {
        showToast(`Copied ${selectedSet.size} filenames to clipboard!`);
      });
    });

    document.getElementById('btnDownloadTxt').addEventListener('click', () => {
      if (selectedSet.size === 0) {
        alert('Please select at least one photo first!');
        return;
      }
      const content = Array.from(selectedSet).join('\\n');
      const blob = new Blob([content], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${itemsData[0]?.filename.split('.')[0] || 'Client'}_Selects.txt`;
      a.click();
    });

    document.getElementById('btnDownloadJson').addEventListener('click', () => {
      if (selectedSet.size === 0) {
        alert('Please select at least one photo first!');
        return;
      }
      const payload = {
        client: "__CLIENT_NAME__",
        project: "__PROJECT_TITLE__",
        export_date: new Date().toISOString(),
        count: selectedSet.size,
        selections: Array.from(selectedSet)
      };
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `Selections_${Date.now()}.json`;
      a.click();
    });
  </script>
</body>
</html>
"""

def generate_contact_sheet_package(
    files: List[Dict[str, Any]],
    output_dir: str,
    project_title: str = "Client Proofing Gallery",
    client_name: str = "Valued Client",
    instructions: str = "Click the heart icon on your favorite photos, then click 'Copy Selected Filenames' below to send us your picks.",
    watermark_text: Optional[str] = "PROOF ONLY",
    max_thumb_size: int = 800
) -> Dict[str, Any]:
    """
    Generates a complete standalone Client Contact Sheet package:
    - Creates `output_dir / "thumbnails"` containing optimized web-friendly JPEGs (with optional proof watermark).
    - Creates `output_dir / "index.html"` containing responsive lightbox gallery with interactive selects picker.
    """
    out_root = Path(output_dir)
    thumbs_dir = out_root / "thumbnails"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    items_data = []
    cards_html_list = []

    for idx, f in enumerate(files):
        src_path = f.get("abs_path") or f.get("path")
        if not src_path or not os.path.isfile(src_path):
            continue

        p = Path(src_path)
        filename = p.name
        stem = p.stem
        thumb_filename = f"{stem}_thumb.jpg"
        thumb_dest = thumbs_dir / thumb_filename

        # Generate thumb if not already there
        if not thumb_dest.exists():
            img = open_image_source(src_path)
            if img:
                img = resize_for_web_proof(img, max_thumb_size)
                if watermark_text:
                    img = apply_text_watermark(img, watermark_text, position="diagonal_grid", opacity=0.30, font_scale=0.035)
                rgb_img = img.convert("RGB")
                rgb_img.save(str(thumb_dest), "JPEG", quality=75, optimize=True)

        rel_thumb_url = f"thumbnails/{thumb_filename}"
        items_data.append({
            "index": idx + 1,
            "filename": filename,
            "stem": stem,
            "thumb": rel_thumb_url
        })

        card_html = f"""
        <div class="card" data-filename="{filename}">
          <div class="thumb-wrap">
            <span class="idx-badge">#{idx + 1}</span>
            <button class="select-toggle" title="Mark as select">❤</button>
            <img src="{rel_thumb_url}" alt="{filename}" loading="lazy">
          </div>
          <div class="card-footer">
            <span class="filename" title="{filename}">{filename}</span>
            <span style="font-size: 11px; color: var(--text-muted);">#{idx + 1}</span>
          </div>
        </div>
        """
        cards_html_list.append(card_html)

    now_str = datetime.now().strftime("%B %d, %Y")
    rendered_html = (
        HTML_TEMPLATE
        .replace("__PROJECT_TITLE__", project_title)
        .replace("__CLIENT_NAME__", client_name)
        .replace("__DATE_STR__", now_str)
        .replace("__TOTAL_COUNT__", str(len(items_data)))
        .replace("__INSTRUCTIONS__", instructions)
        .replace("__CARDS_HTML__", "\n".join(cards_html_list))
        .replace("__ITEMS_JSON__", json.dumps(items_data))
    )

    html_path = out_root / "index.html"
    with open(html_path, "w", encoding="utf-8") as hf:
        hf.write(rendered_html)

    return {
        "html_path": str(html_path),
        "total_images": len(items_data),
        "thumbnails_dir": str(thumbs_dir),
        "status": "ready"
    }

def parse_client_selects(raw_input: str) -> List[str]:
    """
    Intelligently parses messy client selection input:
    - Comma-separated: "DSCF1001, DSCF1002"
    - Newline-separated lists or bullet points
    - JSON manifests
    - Bare frame numbers: "1001, 1002, 1005"
    """
    if not raw_input:
        return []

    # Check if input is JSON
    trimmed = raw_input.strip()
    if trimmed.startswith("{") and "selections" in trimmed:
        try:
            data = json.loads(trimmed)
            if isinstance(data.get("selections"), list):
                return [str(x).strip() for x in data["selections"] if str(x).strip()]
        except Exception:
            pass

    # Split by commas, semicolons, newlines, tabs
    tokens = re.split(r'[,;\n\r\t]+', raw_input)
    cleaned = []
    seen = set()

    for t in tokens:
        # Strip bullets, quotes, leading #
        item = re.sub(r'^[•\-\*\#\s]+', '', t).strip().strip('"\'')
        if item and item.lower() not in seen:
            seen.add(item.lower())
            cleaned.append(item)

    return cleaned

def resolve_selects_against_directory_or_db(
    queries: List[str],
    source_dir: Optional[str] = None,
    source_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Resolves a list of query items (filenames, stems, or frame numbers)
    against either a filesystem directory or an indexed source in SQLite.
    Also automatically identifies accompanying .xmp sidecars.
    """
    file_map = {} # norm_name -> { abs_path, filename, size, ext }

    # 1. Gather candidate files
    if source_dir and os.path.isdir(source_dir):
        p = Path(source_dir)
        for entry in p.rglob("*"):
            if entry.is_file():
                ext = entry.suffix.lower()
                if ext in PHOTO_EXTS or ext in RAW_EXTS:
                    file_map[entry.name.lower()] = {
                        "abs_path": str(entry.resolve()),
                        "filename": entry.name,
                        "stem": entry.stem.lower(),
                        "size_bytes": entry.stat().st_size,
                        "ext": ext
                    }
    elif source_id:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, abs_path, filename, size_bytes FROM files WHERE source_id = ? AND status = 'active'", (source_id,))
        for r in cursor.fetchall():
            fn = r["filename"]
            p = Path(fn)
            file_map[fn.lower()] = {
                "id": r["id"],
                "abs_path": r["abs_path"],
                "filename": fn,
                "stem": p.stem.lower(),
                "size_bytes": r["size_bytes"],
                "ext": p.suffix.lower()
            }
    else:
        # Query all active files in DB
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, abs_path, filename, size_bytes FROM files WHERE status = 'active'")
        for r in cursor.fetchall():
            fn = r["filename"]
            p = Path(fn)
            file_map[fn.lower()] = {
                "id": r["id"],
                "abs_path": r["abs_path"],
                "filename": fn,
                "stem": p.stem.lower(),
                "size_bytes": r["size_bytes"],
                "ext": p.suffix.lower()
            }

    matched = []
    unmatched = []
    matched_paths = set()

    for q in queries:
        q_clean = q.strip()
        q_lower = q_clean.lower()
        found_file = None

        # Strategy A: Exact filename match (e.g. "DSCF1001.JPG")
        if q_lower in file_map:
            found_file = file_map[q_lower]

        # Strategy B: Stem match without extension (e.g. "DSCF1001")
        if not found_file:
            for item in file_map.values():
                if item["stem"] == q_lower:
                    found_file = item
                    break

        # Strategy C: Frame number substring match (e.g. "1001" or "#1001" matches "DSCF1001.RAF")
        if not found_file and q_clean.isdigit():
            q_num = q_clean
            for item in file_map.values():
                # Check if stem ends with this number or contains it
                if item["stem"].endswith(q_num) or f"_{q_num}" in item["stem"]:
                    found_file = item
                    break

        if found_file and found_file["abs_path"] not in matched_paths:
            matched_paths.add(found_file["abs_path"])

            # Check for sidecar .xmp
            src_p = Path(found_file["abs_path"])
            sidecar_p = src_p.with_suffix(".xmp")
            sidecar_path = str(sidecar_p) if sidecar_p.exists() else None

            matched.append({
                "id": found_file.get("id"),
                "query": q_clean,
                "abs_path": found_file["abs_path"],
                "filename": found_file["filename"],
                "size_bytes": found_file["size_bytes"],
                "sidecar_path": sidecar_path
            })
        else:
            unmatched.append(q_clean)

    total_queries = len(queries)
    match_rate = round((len(matched) / max(1, total_queries)) * 100, 1)

    return {
        "matched": matched,
        "unmatched": unmatched,
        "total_queries": total_queries,
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "match_rate_pct": match_rate
    }

def execute_selects_export(
    items: List[Dict[str, Any]],
    destination_dir: str,
    action: str = "copy" # "copy" or "move"
) -> Dict[str, Any]:
    """
    Copies or moves matched client select files (and any accompanying .xmp sidecars)
    into the designated target edit directory.
    """
    dest_root = Path(destination_dir)
    dest_root.mkdir(parents=True, exist_ok=True)

    success_count = 0
    errors = []
    total_bytes = 0

    for it in items:
        main_path = it.get("abs_path")
        if not main_path or not os.path.isfile(main_path):
            continue

        p = Path(main_path)
        dest_main = dest_root / p.name

        try:
            if action == "move":
                shutil.move(str(p), str(dest_main))
            else:
                shutil.copy2(str(p), str(dest_main))

            total_bytes += dest_main.stat().st_size
            success_count += 1

            # Handle sidecar if present
            sidecar = it.get("sidecar_path")
            if sidecar and os.path.isfile(sidecar):
                sc_p = Path(sidecar)
                dest_sc = dest_root / sc_p.name
                if action == "move":
                    shutil.move(str(sc_p), str(dest_sc))
                else:
                    shutil.copy2(str(sc_p), str(dest_sc))
                total_bytes += dest_sc.stat().st_size

        except Exception as e:
            errors.append(f"{p.name}: {str(e)}")

    return {
        "action": action,
        "destination": str(dest_root),
        "processed_count": success_count,
        "total_bytes": total_bytes,
        "errors": errors
    }
