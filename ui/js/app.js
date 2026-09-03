// SaveSpace Pro Desktop UI Controller
const API_BASE = window.location.origin;

let currentTab = 'overview';
let sourcesData = [];
let cullingItems = [];
let selectedCullIds = new Set();
let duplicatesData = [];
let selectedDupeIds = new Set();
let transcodeQueueData = [];
let syncMatrixData = null;
let currentPerfMode = 'balanced';
let isTranscodePaused = false;
let selectedTranscodeIds = new Set();
let currentCandidates = [];

function formatBytes(bytes, decimals = 1) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function escapeJs(str) {
  if (!str) return '';
  return String(str).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = 'toast toast-' + type;
  const icon = type === 'success' ? '✓' : (type === 'error' ? '✕' : 'ℹ');
  toast.innerHTML = `<span style="font-size:15px;">${icon}</span> <span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    toast.style.transition = 'all 0.25s ease';
    setTimeout(() => toast.remove(), 250);
  }, 2800);
}

async function openFileLocation(filePath, openFolder = false) {
  if (!filePath) return;
  try {
    showToast(openFolder ? 'Opening folder...' : 'Opening in File Explorer...', 'info');
    const res = await fetch(API_BASE + '/api/files/open-location', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: filePath, open_folder: openFolder })
    });
    const data = await res.json();
    if (!res.ok) {
      showToast('Could not open: ' + (data.detail || 'File not found'), 'error');
    } else {
      showToast(openFolder ? 'Folder opened in Explorer' : 'File revealed in Explorer', 'success');
    }
  } catch (err) {
    showToast('Failed to open location: ' + err, 'error');
  }
}

// Global Context Menu Management
let activeContextItem = null;

function setupContextMenu() {
  const menu = document.getElementById('custom-context-menu');
  if (!menu) return;

  const btnOpenFile = document.getElementById('ctx-open-file');
  if (btnOpenFile) {
    btnOpenFile.addEventListener('click', () => {
      if (activeContextItem && activeContextItem.abs_path) {
        openFileLocation(activeContextItem.abs_path, false);
      }
      hideContextMenu();
    });
  }

  const btnOpenFolder = document.getElementById('ctx-open-folder');
  if (btnOpenFolder) {
    btnOpenFolder.addEventListener('click', () => {
      if (activeContextItem) {
        const target = activeContextItem.folder_path || activeContextItem.abs_path;
        openFileLocation(target, true);
      }
      hideContextMenu();
    });
  }

  const btnCopyPath = document.getElementById('ctx-copy-path');
  if (btnCopyPath) {
    btnCopyPath.addEventListener('click', async () => {
      if (activeContextItem && activeContextItem.abs_path) {
        try {
          await navigator.clipboard.writeText(activeContextItem.abs_path);
          showToast('File path copied to clipboard!', 'success');
        } catch (e) {
          showToast('Failed to copy: ' + e, 'error');
        }
      }
      hideContextMenu();
    });
  }

  const btnCopyFolder = document.getElementById('ctx-copy-folder');
  if (btnCopyFolder) {
    btnCopyFolder.addEventListener('click', async () => {
      if (activeContextItem) {
        const target = activeContextItem.folder_path || '';
        try {
          await navigator.clipboard.writeText(target);
          showToast('Folder path copied to clipboard!', 'success');
        } catch (e) {
          showToast('Failed to copy: ' + e, 'error');
        }
      }
      hideContextMenu();
    });
  }

  const btnQueueItem = document.getElementById('ctx-queue-item');
  if (btnQueueItem) {
    btnQueueItem.addEventListener('click', () => {
      if (activeContextItem && activeContextItem.file_id) {
        queueSingleVideo(activeContextItem.file_id);
      }
      hideContextMenu();
    });
  }

  document.addEventListener('click', (e) => {
    if (!menu.contains(e.target)) {
      hideContextMenu();
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      hideContextMenu();
    }
  });
}

function showContextMenu(e, item) {
  e.preventDefault();
  e.stopPropagation();
  activeContextItem = item;
  const menu = document.getElementById('custom-context-menu');
  if (!menu) return;

  const titleEl = document.getElementById('ctx-file-title');
  if (titleEl) titleEl.innerText = item.filename || 'File';

  const queueBtn = document.getElementById('ctx-queue-item');
  const queueDiv = document.getElementById('ctx-queue-divider');
  if (queueBtn && queueDiv) {
    if (item.can_queue && item.file_id) {
      queueBtn.style.display = 'flex';
      queueDiv.style.display = 'block';
    } else {
      queueBtn.style.display = 'none';
      queueDiv.style.display = 'none';
    }
  }

  menu.style.display = 'block';

  const menuWidth = 240;
  const menuHeight = 220;
  let posX = e.clientX;
  let posY = e.clientY;

  if (posX + menuWidth > window.innerWidth) {
    posX = window.innerWidth - menuWidth - 10;
  }
  if (posY + menuHeight > window.innerHeight) {
    posY = window.innerHeight - menuHeight - 10;
  }

  menu.style.left = Math.max(10, posX) + 'px';
  menu.style.top = Math.max(10, posY) + 'px';
}

function hideContextMenu() {
  const menu = document.getElementById('custom-context-menu');
  if (menu) menu.style.display = 'none';
  activeContextItem = null;
}

document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(el => el.classList.remove('active'));
    
    item.classList.add('active');
    currentTab = item.dataset.tab;
    const targetPanel = document.getElementById('tab-' + currentTab);
    if (targetPanel) targetPanel.classList.add('active');

    const titles = {
      overview: 'Storage Overview & System Health',
      sources: 'Drives & Storage Sources',
      culler: 'Blur & Burst Photo Culler',
      duplicates: 'Duplicate Media Finder',
      transcoder: 'GPU-Accelerated H.265 Transcoder (NVENC)',
      sync: 'SSD & NAS Backup Sync Matrix',
      organizer: 'Smart Media Organizer'
    };
    document.getElementById('current-view-title').innerText = titles[currentTab] || 'SaveSpace Pro';
    refreshCurrentTab();
  });
});

document.querySelectorAll('.perf-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    document.querySelectorAll('.perf-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentPerfMode = btn.dataset.mode;
    document.getElementById('cur-perf-badge').innerText = currentPerfMode.toUpperCase();

    try {
      await fetch(API_BASE + '/api/transcodes/control?action=set_perf_mode&value=' + currentPerfMode, { method: 'POST' });
    } catch (e) {
      console.error(e);
    }
  });
});

const btnTranscodePause = document.getElementById('btn-transcode-pause');
btnTranscodePause.addEventListener('click', async () => {
  isTranscodePaused = !isTranscodePaused;
  const action = isTranscodePaused ? 'pause' : 'resume';
  btnTranscodePause.innerText = isTranscodePaused ? 'Resume Transcodes' : 'Pause Transcodes';
  btnTranscodePause.style.background = isTranscodePaused ? 'var(--accent-amber)' : '';

  try {
    await fetch(API_BASE + '/api/transcodes/control?action=' + action, { method: 'POST' });
  } catch (e) {
    console.error(e);
  }
});

document.getElementById('btn-refresh-all').addEventListener('click', () => {
  refreshCurrentTab();
});

function refreshCurrentTab() {
  if (currentTab === 'overview') loadOverview();
  else if (currentTab === 'sources') loadSources();
  else if (currentTab === 'culler') loadCuller();
  else if (currentTab === 'duplicates') loadDuplicates();
  else if (currentTab === 'transcoder') loadTranscoder();
  else if (currentTab === 'sync') loadSync();
  else if (currentTab === 'organizer') loadOrganizer();
}

async function loadOverview() {
  try {
    const [statsRes, sourcesRes] = await Promise.all([
      fetch(API_BASE + '/api/stats').then(r => r.json()),
      fetch(API_BASE + '/api/sources').then(r => r.json())
    ]);

    document.getElementById('stat-total-size').innerText = formatBytes(statsRes.media.total_size);
    document.getElementById('stat-total-files').innerText = (statsRes.media.total_files || 0).toLocaleString() + ' files indexed (' + (statsRes.media.raw_count || 0) + ' RAW, ' + (statsRes.media.video_count || 0) + ' Vids)';
    document.getElementById('stat-reclaimable').innerText = formatBytes(statsRes.total_potential_savings_bytes);
    document.getElementById('stat-blurry-size').innerText = formatBytes(statsRes.blurry.blurry_size);
    document.getElementById('stat-blurry-count').innerText = (statsRes.blurry.blurry_count || 0) + ' flagged blurry';
    document.getElementById('stat-dupes-size').innerText = formatBytes(statsRes.duplicate_savings_bytes);
    document.getElementById('stat-transcode-size').innerText = formatBytes(statsRes.transcode_savings_est_bytes);

    sourcesData = sourcesRes;
    const drivesContainer = document.getElementById('overview-drives-list');
    drivesContainer.innerHTML = '';

    sourcesRes.forEach(src => {
      const usedBytes = src.total_bytes - src.free_bytes;
      const pct = src.total_bytes > 0 ? Math.round((usedBytes / src.total_bytes) * 100) : 0;
      let barClass = '';
      if (pct > 90) barClass = 'danger';
      else if (pct > 75) barClass = 'warning';

      const card = document.createElement('div');
      card.className = 'drive-card';
      card.innerHTML = '<div class="drive-header"><div class="drive-name">' + src.label + '</div><div class="drive-badge">' + src.drive_type + '</div></div>'
        + '<div class="meter-bar"><div class="meter-fill ' + barClass + '" style="width:' + pct + '%"></div></div>'
        + '<div class="drive-info"><span>' + formatBytes(usedBytes) + ' used of ' + formatBytes(src.total_bytes) + '</span><span style="font-weight:600;">' + pct + '%</span></div>'
        + '<div style="font-size:11px; color:var(--text-muted); margin-top:8px; display:flex; justify-content:space-between;"><span>Path: ' + src.path + '</span><span>Indexed: ' + formatBytes(src.total_media_size) + '</span></div>';
      drivesContainer.appendChild(card);
    });
  } catch (err) {
    console.error('Failed to load overview:', err);
  }
}

async function loadSources() {
  try {
    const res = await fetch(API_BASE + '/api/sources');
    sourcesData = await res.json();
    const tbody = document.getElementById('sources-table-body');
    tbody.innerHTML = '';

    sourcesData.forEach(s => {
      const tr = document.createElement('tr');
      const onlineTag = s.is_online ? '<span style="color:var(--accent-emerald);">● Online</span>' : '<span style="color:var(--accent-rose);">○ Offline</span>';
      const excludedCount = (s.excluded_paths && s.excluded_paths.length) || 0;
      const excludedBadge = excludedCount > 0 
        ? ' <span class="brand-badge" style="background:rgba(245,158,11,0.2); color:var(--accent-amber); font-size:11px; cursor:pointer;" onclick="openSubfoldersModal(' + s.id + ')" title="' + excludedCount + ' subfolders deselected">' + excludedCount + ' deselected</span>'
        : '';

      tr.innerHTML = '<td style="font-weight:600;">' + s.label + '</td>'
        + '<td style="font-family:monospace; font-size:12px;">' + s.path + excludedBadge + '</td>'
        + '<td><span class="brand-badge">' + s.drive_type + '</span></td>'
        + '<td>' + onlineTag + '</td>'
        + '<td>' + (s.file_count || 0).toLocaleString() + '</td>'
        + '<td>' + formatBytes(s.total_media_size || 0) + '</td>'
        + '<td style="font-size:11px; color:var(--text-muted);">' + (s.last_scanned ? s.last_scanned.split('T')[0] : 'Never') + '</td>'
        + '<td style="white-space:nowrap;">'
        + '<button class="btn btn-secondary btn-sm" onclick="openSubfoldersModal(' + s.id + ')" style="margin-right:4px;">📁 Folders' + (excludedCount > 0 ? ' (' + excludedCount + ')' : '') + '</button>'
        + '<button class="btn btn-primary btn-sm" onclick="scanSource(' + s.id + ')" style="margin-right:4px;">Scan Now</button>'
        + '<button class="btn btn-secondary btn-sm" onclick="deleteSource(' + s.id + ')">Remove</button>'
        + '</td>';
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error('Failed to load sources:', err);
  }
}

let currentSubfolders = [];
let currentSubfolderSourceId = null;

window.openSubfoldersModal = async function(sourceId) {
  currentSubfolderSourceId = sourceId;
  const modal = document.getElementById('modal-manage-subfolders');
  const container = document.getElementById('subfolder-list-container');
  const titleSpan = document.getElementById('subfolder-modal-title');
  const txtFilter = document.getElementById('txt-subfolder-filter');
  if (txtFilter) txtFilter.value = '';

  container.innerHTML = '<p style="color:var(--text-muted); padding:16px;">Reading drive subfolders...</p>';
  modal.classList.add('active');

  try {
    const res = await fetch(API_BASE + '/api/sources/' + sourceId + '/subfolders');
    const data = await res.json();
    currentSubfolders = data.subfolders || [];
    titleSpan.textContent = (data.label || 'Drive') + ' (' + data.path + ')';

    renderSubfolderList(currentSubfolders);
  } catch (err) {
    container.innerHTML = '<p style="color:var(--accent-rose); padding:16px;">Failed to read subfolders: ' + err + '</p>';
  }
};

function renderSubfolderList(subfolders) {
  const container = document.getElementById('subfolder-list-container');
  container.innerHTML = '';

  if (subfolders.length === 0) {
    container.innerHTML = '<p style="color:var(--text-muted); padding:16px;">No subfolders found in this drive root.</p>';
    return;
  }

  subfolders.forEach(sub => {
    const row = document.createElement('div');
    row.className = 'subfolder-item-row';
    row.dataset.name = sub.name.toLowerCase();
    row.style.display = 'flex';
    row.style.alignItems = 'center';
    row.style.justifyContent = 'space-between';
    row.style.padding = '8px 10px';
    row.style.borderBottom = '1px solid rgba(255,255,255,0.05)';

    const isChecked = !sub.is_excluded;

    row.innerHTML = '<label style="display:flex; align-items:center; gap:10px; cursor:pointer; flex:1; font-size:13px; font-weight:500;">'
      + '<input type="checkbox" class="chk-subfolder" data-path="' + sub.rel_path + '" ' + (isChecked ? 'checked' : '') + ' style="cursor:pointer; width:16px; height:16px;">'
      + '<span>📁 ' + sub.name + '</span>'
      + '</label>'
      + '<span class="subfolder-status-badge ' + (isChecked ? 'badge-included' : 'badge-excluded') + '" style="font-size:11px; padding:2px 8px; border-radius:4px; font-weight:600;">'
      + (isChecked ? '✓ Included' : '✕ Deselected (Skip)')
      + '</span>';

    const chk = row.querySelector('.chk-subfolder');
    const badge = row.querySelector('.subfolder-status-badge');

    chk.addEventListener('change', () => {
      sub.is_excluded = !chk.checked;
      if (chk.checked) {
        badge.textContent = '✓ Included';
        badge.className = 'subfolder-status-badge badge-included';
      } else {
        badge.textContent = '✕ Deselected (Skip)';
        badge.className = 'subfolder-status-badge badge-excluded';
      }
    });

    container.appendChild(row);
  });
}

window.scanSource = async function(id) {
  try {
    await fetch(API_BASE + '/api/sources/' + id + '/scan', { method: 'POST' });
    alert('Scan started in background! You can continue using the app or your PC smoothly.');
  } catch (e) {
    alert('Failed to start scan: ' + e);
  }
};

window.deleteSource = async function(id) {
  if (!confirm('Are you sure you want to remove this source from indexing?')) return;
  try {
    await fetch(API_BASE + '/api/sources/' + id, { method: 'DELETE' });
    loadSources();
  } catch (e) {
    alert('Failed to delete source: ' + e);
  }
};

const sliderThreshold = document.getElementById('blur-threshold-slider');
const valThreshold = document.getElementById('blur-threshold-val');
sliderThreshold.addEventListener('input', (e) => {
  valThreshold.innerText = e.target.value;
});
sliderThreshold.addEventListener('change', () => {
  loadCuller();
});

document.getElementById('chk-burst-only').addEventListener('change', () => {
  loadCuller();
});

let cullOffset = 0;
const CULL_BATCH_SIZE = 80;

async function loadCuller(append = false) {
  const threshold = sliderThreshold.value;
  const burstOnly = document.getElementById('chk-burst-only').checked;
  const gallery = document.getElementById('culler-gallery');

  if (!append) {
    cullOffset = 0;
    cullingItems = [];
    selectedCullIds.clear();
    gallery.innerHTML = '<p style="color:var(--text-muted); padding:20px;">Loading media analysis...</p>';
  }

  const existingMore = document.getElementById('cull-load-more-box');
  if (existingMore) existingMore.remove();

  try {
    const res = await fetch(API_BASE + '/api/culling?threshold=' + threshold + '&burst_only=' + burstOnly + '&limit=' + CULL_BATCH_SIZE + '&offset=' + cullOffset);
    const newItems = await res.json();

    if (!append) {
      gallery.innerHTML = '';
    }

    if (newItems.length === 0 && !append) {
      gallery.innerHTML = '<p style="color:var(--text-muted); padding:20px;">No photos found matching criteria. Run a scan on your photo folders first!</p>';
      return;
    }

    cullingItems = cullingItems.concat(newItems);
    cullOffset += newItems.length;

    newItems.forEach(item => {
      const card = document.createElement('div');
      card.className = 'media-card';
      card.dataset.id = item.id;

      const isBlurry = item.blur_score < threshold;
      const blurBadgeClass = isBlurry ? 'blurry' : 'sharp';
      const blurBadgeText = 'Focus: ' + item.blur_score + '/100';

      let burstBadgeHtml = '';
      if (item.burst_group) {
        burstBadgeHtml = item.is_burst_best 
          ? '<div class="burst-badge" style="background:var(--accent-emerald);">★ Sharpest in Burst</div>'
          : '<div class="burst-badge">Burst Shot</div>';
      }

      card.innerHTML = '<div class="media-thumb-container">'
        + '<img class="media-thumb" src="' + API_BASE + '/api/thumbnail/' + item.id + '" loading="lazy" decoding="async" width="200" height="150" onerror="this.style.opacity=0.3">'
        + '<div class="blur-badge ' + blurBadgeClass + '">' + blurBadgeText + '</div>'
        + burstBadgeHtml
        + '</div>'
        + '<div class="media-meta-bar">'
        + '<div class="media-name" title="' + item.filename + '">' + item.filename + '</div>'
        + '<div class="media-details"><span>' + (item.camera_model || item.media_type.toUpperCase()) + '</span><span>' + formatBytes(item.size_bytes) + '</span></div>'
        + '</div>';

      card.addEventListener('click', () => {
        if (selectedCullIds.has(item.id)) {
          selectedCullIds.delete(item.id);
          card.classList.remove('selected');
        } else {
          selectedCullIds.add(item.id);
          card.classList.add('selected');
        }
      });

      card.addEventListener('contextmenu', (e) => {
        showContextMenu(e, {
          filename: item.filename,
          abs_path: item.abs_path,
          folder_path: item.abs_path ? item.abs_path.replace(/[/\\][^/\\]+$/, '') : '',
          file_id: item.id,
          can_queue: false
        });
      });

      gallery.appendChild(card);
    });

    if (newItems.length === CULL_BATCH_SIZE) {
      const moreBox = document.createElement('div');
      moreBox.id = 'cull-load-more-box';
      moreBox.style.gridColumn = '1 / -1';
      moreBox.style.textAlign = 'center';
      moreBox.style.padding = '24px 0';
      moreBox.innerHTML = '<button id="btn-load-more-cull" class="btn btn-secondary" style="padding:8px 24px; font-size:13px; font-weight:600;">Load Next ' + CULL_BATCH_SIZE + ' Photos ↓</button>';
      gallery.appendChild(moreBox);

      document.getElementById('btn-load-more-cull').addEventListener('click', () => {
        loadCuller(true);
      });
    }

  } catch (err) {
    if (!append) {
      gallery.innerHTML = '<p style="color:var(--accent-rose);">Failed to load culling gallery: ' + err + '</p>';
    }
  }
}

document.getElementById('btn-select-all-blurry').addEventListener('click', () => {
  const threshold = parseFloat(sliderThreshold.value);
  document.querySelectorAll('#culler-gallery .media-card').forEach(card => {
    const id = parseInt(card.dataset.id);
    const item = cullingItems.find(i => i.id === id);
    if (item && item.blur_score < threshold) {
      selectedCullIds.add(id);
      card.classList.add('selected');
    }
  });
});

async function executeCullingAction(action) {
  if (selectedCullIds.size === 0) {
    alert('Please select one or more photos first!');
    return;
  }
  const promptText = action === 'trash' 
    ? 'Send ' + selectedCullIds.size + ' photos and their paired XMP sidecars to the Windows Recycle Bin?'
    : 'Quarantine ' + selectedCullIds.size + ' photos safely?';

  if (!confirm(promptText)) return;

  try {
    const res = await fetch(API_BASE + '/api/culling/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file_ids: Array.from(selectedCullIds),
        action: action,
        include_sidecars: true
      })
    });
    const result = await res.json();
    alert('Success! Processed ' + result.processed_count + ' files (including sidecars).');
    loadCuller();
    loadOverview();
  } catch (e) {
    alert('Error: ' + e);
  }
}

document.getElementById('btn-cull-trash').addEventListener('click', () => executeCullingAction('trash'));
document.getElementById('btn-cull-quarantine').addEventListener('click', () => executeCullingAction('quarantine'));

async function loadDuplicates() {
  const crossOnly = document.getElementById('chk-cross-source').checked;
  const sameNameOnly = document.getElementById('chk-same-filename') ? document.getElementById('chk-same-filename').checked : true;
  const container = document.getElementById('duplicates-container');
  container.innerHTML = '<p style="color:var(--text-muted); padding:20px;">Scanning duplicate clusters...</p>';

  try {
    const res = await fetch(API_BASE + '/api/duplicates?cross_source_only=' + crossOnly + '&same_name_only=' + sameNameOnly);
    duplicatesData = await res.json();
    container.innerHTML = '';
    selectedDupeIds.clear();

    if (duplicatesData.length === 0) {
      container.innerHTML = '<p style="color:var(--text-muted); padding:20px;">No duplicate files found! Your drives are clean.</p>';
      return;
    }

    duplicatesData.forEach((group, idx) => {
      const card = document.createElement('div');
      card.style.background = 'var(--bg-card)';
      card.style.border = '1px solid var(--border-color)';
      card.style.borderRadius = '10px';
      card.style.padding = '16px';
      card.style.marginBottom = '16px';

      let filesHtml = '';
      const primaryName = (group.primary_filename || '').toLowerCase();

      group.files.forEach(f => {
        const isPrimary = f.id === group.primary_id;
        const isSameName = (f.filename.toLowerCase() === primaryName);

        let tag = '';
        if (isPrimary) {
          tag = '<span class="brand-badge" style="background:rgba(16,185,129,0.2); color:var(--accent-emerald);">KEEP (Primary)</span>';
        } else if (isSameName) {
          tag = '<span class="brand-badge" style="background:rgba(244,63,94,0.2); color:var(--accent-rose);">EXACT COPY</span>';
        } else {
          tag = '<span class="brand-badge" style="background:rgba(245,158,11,0.2); color:var(--accent-amber);" title="Content hash matches, but filename is different">DIFFERENT FILENAME</span>';
        }

        // Only pre-check if not primary AND has identical filename! Never pre-check different filenames!
        const shouldCheck = !isPrimary && isSameName;

        filesHtml += '<div class="dupe-file-row" data-path="' + escapeHtml(f.abs_path) + '" data-name="' + escapeHtml(f.filename) + '" style="display:flex; align-items:center; justify-content:space-between; padding:8px 0; border-bottom:1px solid rgba(255,255,255,0.05); cursor:context-menu;">'
          + '<div style="display:flex; align-items:center; gap:10px;">'
          + '<input type="checkbox" class="chk-dupe-item" data-id="' + f.id + '" data-same-name="' + isSameName + '" data-is-primary="' + isPrimary + '" ' + (shouldCheck ? 'checked' : '') + '>'
          + '<div>'
          + '<div style="font-weight:600; font-size:13px;">' + escapeHtml(f.filename) + ' ' + tag + '</div>'
          + '<div style="font-size:11px; color:var(--text-muted); font-family:monospace;">' + escapeHtml(f.abs_path) + '</div>'
          + '</div>'
          + '</div>'
          + '<div style="display:flex; align-items:center; gap:8px;">'
          + '<div style="font-size:12px; color:var(--text-muted);">' + escapeHtml(f.source_label) + ' (' + escapeHtml(f.drive_type) + ')</div>'
          + '<button class="btn btn-secondary btn-sm btn-open-dupe" title="Reveal in File Explorer" style="padding:2px 7px; font-size:11px;">📂</button>'
          + '</div>'
          + '</div>';
      });

      card.innerHTML = '<div style="display:flex; justify-content:space-between; margin-bottom:12px;">'
        + '<div><span style="font-weight:700; font-size:14px;">Duplicate Set #' + (idx + 1) + '</span><span style="font-size:12px; color:var(--text-muted); margin-left:10px;">' + group.count + ' identical copies (' + formatBytes(group.file_size) + ' each)</span></div>'
        + '<div style="color:var(--accent-amber); font-size:12px; font-weight:600;">Reclaimable: ' + formatBytes(group.potential_savings_bytes) + '</div>'
        + '</div>' + filesHtml;

      card.querySelectorAll('.dupe-file-row').forEach(row => {
        const filePath = row.dataset.path;
        const fileName = row.dataset.name;
        const btn = row.querySelector('.btn-open-dupe');
        if (btn) {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            openFileLocation(filePath, false);
          });
        }
        row.addEventListener('contextmenu', (e) => {
          showContextMenu(e, {
            filename: fileName,
            abs_path: filePath,
            folder_path: filePath ? filePath.replace(/[/\\][^/\\]+$/, '') : '',
            can_queue: false
          });
        });
      });

      container.appendChild(card);
    });
  } catch (err) {
    container.innerHTML = '<p style="color:var(--accent-rose);">Failed to load duplicates: ' + err + '</p>';
  }
}

document.getElementById('chk-cross-source').addEventListener('change', loadDuplicates);
const chkSameNameEl = document.getElementById('chk-same-filename');
if (chkSameNameEl) {
  chkSameNameEl.addEventListener('change', loadDuplicates);
}

const btnAutoSelectDupe = document.getElementById('btn-auto-select-redundant');
if (btnAutoSelectDupe) {
  btnAutoSelectDupe.addEventListener('click', () => {
    let count = 0;
    document.querySelectorAll('.chk-dupe-item').forEach(chk => {
      const isPrimary = chk.dataset.isPrimary === 'true';
      const isSameName = chk.dataset.sameName === 'true';
      if (!isPrimary && isSameName) {
        chk.checked = true;
        count++;
      } else {
        chk.checked = false;
      }
    });
    alert('Selected ' + count + ' exact redundant copies.');
  });
}

document.getElementById('btn-delete-selected-dupes').addEventListener('click', async () => {
  const idsToDelete = [];
  document.querySelectorAll('.chk-dupe-item:checked').forEach(chk => {
    idsToDelete.push(parseInt(chk.dataset.id));
  });

  if (idsToDelete.length === 0) {
    alert('No duplicate copies selected!');
    return;
  }

  if (!confirm('Safely send ' + idsToDelete.length + ' redundant duplicate files to Windows Recycle Bin?')) return;

  try {
    await fetch(API_BASE + '/api/duplicates/resolve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(idsToDelete)
    });
    alert('Cleaned ' + idsToDelete.length + ' duplicates!');
    loadDuplicates();
    loadOverview();
  } catch (e) {
    alert('Error: ' + e);
  }
});

const PROFILE_SAVINGS_RATIOS = {
  'nvenc_hq_10bit': 0.65, // ~65% reduction (CQ 22, 10-bit)
  'nvenc_lossless': 0.40, // ~40% reduction (CQ 18 ultra archival quality)
  'nvenc_compact': 0.80,  // ~80% reduction (CQ 26 max space saving)
  'cpu_x265_hq': 0.70     // ~70% reduction (CPU CRF 22)
};

function getProfileRatio() {
  const prof = document.getElementById('sel-transcode-profile')?.value || 'nvenc_hq_10bit';
  return PROFILE_SAVINGS_RATIOS[prof] || 0.65;
}

function updateCandidateSavingsCells() {
  const ratio = getProfileRatio();
  document.querySelectorAll('.cell-est-savings').forEach(cell => {
    const size = parseInt(cell.dataset.size || '0');
    const estSavings = Math.round(size * ratio);
    cell.innerText = '~' + formatBytes(estSavings);
  });
  updateTranscodeSelectionSummary();
}

let transcodeFiltersBound = false;

async function loadTranscoder() {
  try {
    // Populate drive selector if needed
    const selDrive = document.getElementById('sel-transcode-drive');
    if (selDrive && selDrive.children.length <= 1 && sourcesData.length > 0) {
      selDrive.innerHTML = '<option value="">All Drives</option>';
      sourcesData.forEach(s => {
        selDrive.innerHTML += '<option value="' + s.id + '">' + s.label + '</option>';
      });
    }

    const driveId = selDrive ? selDrive.value : '';
    const minSize = document.getElementById('sel-transcode-min-size') ? document.getElementById('sel-transcode-min-size').value : '50';
    const codec = document.getElementById('sel-transcode-codec') ? document.getElementById('sel-transcode-codec').value : '';
    const search = document.getElementById('txt-transcode-search') ? document.getElementById('txt-transcode-search').value.trim() : '';
    const suitability = document.getElementById('sel-transcode-suitability') ? document.getElementById('sel-transcode-suitability').value : 'recommended';

    const queryUrl = API_BASE + '/api/transcodes/candidates?min_size_mb=' + minSize
      + (driveId ? '&source_id=' + driveId : '')
      + (codec ? '&codec=' + encodeURIComponent(codec) : '')
      + (search ? '&search=' + encodeURIComponent(search) : '')
      + (suitability ? '&suitability=' + encodeURIComponent(suitability) : '');

    const [candidates, queueRes] = await Promise.all([
      fetch(queryUrl).then(r => r.json()),
      fetch(API_BASE + '/api/transcodes/queue').then(r => r.json())
    ]);

    currentCandidates = candidates;
    const summary = queueRes.summary;

    // 1. MASTER QUEUE MONITOR (DUAL PROGRESS)
    document.getElementById('queue-counter-badge').innerText = '(' + summary.completed_jobs + ' / ' + summary.total_jobs + ' completed)';
    document.getElementById('queue-savings-badge').innerText = 'Saved: ' + formatBytes(summary.total_saved_bytes);
    document.getElementById('queue-master-fill').style.width = summary.overall_progress + '%';
    document.getElementById('queue-progress-pct').innerText = summary.overall_progress + '%';

    const queueStatusText = document.getElementById('queue-status-text');
    if (summary.active_job) {
      queueStatusText.innerText = 'Processing ' + summary.active_job.filename + ' (' + (summary.completed_jobs + 1) + ' of ' + summary.total_jobs + ')';
    } else if (summary.total_jobs > 0 && summary.pending_jobs === 0) {
      queueStatusText.innerText = '✓ All ' + summary.total_jobs + ' queued transcodes completed!';
      queueStatusText.style.color = 'var(--accent-emerald)';
    } else if (summary.pending_jobs > 0) {
      queueStatusText.innerText = summary.pending_jobs + ' job(s) pending in queue.';
      queueStatusText.style.color = 'var(--text-muted)';
    } else {
      queueStatusText.innerText = 'Queue is idle. Select videos below to start transcoding.';
      queueStatusText.style.color = 'var(--text-muted)';
    }

    // 2. ACTIVE FILE INDIVIDUAL PROGRESS BAR
    const activeBox = document.getElementById('active-job-box');
    const activeTitle = document.getElementById('active-job-title');
    const activePct = document.getElementById('active-job-pct');
    const activeFill = document.getElementById('active-job-fill');
    const activeMetrics = document.getElementById('active-job-metrics');
    const activeSaved = document.getElementById('active-job-saved');

    if (summary.active_job) {
      activeBox.style.borderColor = 'var(--accent-cyan)';
      activeTitle.innerText = 'Currently Transcoding: ' + summary.active_job.filename;
      activePct.innerText = summary.active_job.progress + '%';
      activeFill.style.width = summary.active_job.progress + '%';
      activeMetrics.innerText = 'Speed: ' + (summary.active_job.speed || 'N/A') + ' | FPS: ' + (summary.active_job.fps || 0);
      const profileRatio = getProfileRatio();
      const estSaved = Math.round(summary.active_job.original_size * profileRatio);
      activeSaved.innerText = 'Original: ' + formatBytes(summary.active_job.original_size) + ' | Est. Saved: ' + formatBytes(estSaved);
    } else {
      activeBox.style.borderColor = 'var(--border-color)';
      activeTitle.innerText = 'Currently Transcoding: None';
      activePct.innerText = '0.0%';
      activeFill.style.width = '0%';
      activeMetrics.innerText = 'Speed: 0x | FPS: 0';
      activeSaved.innerText = 'Projected Savings: 0 B';
    }

    // 2.5 RENDER QUEUE BREAKDOWN TABLE
    const queueBox = document.getElementById('queue-details-box');
    const queueTbody = document.getElementById('queue-items-body');
    const queueBadge = document.getElementById('queue-breakdown-count');
    const queueItems = queueRes.items || [];

    if (queueBox && queueTbody) {
      if (queueItems.length > 0) {
        queueBox.style.display = 'block';
        if (queueBadge) queueBadge.innerText = queueItems.length + ' queued';
        queueTbody.innerHTML = '';

        queueItems.forEach(q => {
          const qtr = document.createElement('tr');
          qtr.style.cursor = 'context-menu';

          let statusBadge = '';
          if (q.status === 'completed') {
            statusBadge = '<span class="brand-badge" style="background:rgba(16,185,129,0.2); color:var(--accent-emerald);">✓ Done</span>';
          } else if (q.status === 'already_optimal') {
            statusBadge = '<span class="brand-badge" style="background:rgba(59,130,246,0.2); color:var(--accent-blue); cursor:help;" title="' + escapeHtml(q.error_msg || 'Original was already more compact than H.265') + '">🛡️ Kept Original (Optimal)</span>';
          } else if (q.status === 'transcoding') {
            statusBadge = '<span class="brand-badge" style="background:rgba(6,182,212,0.2); color:var(--accent-cyan);">Transcoding ' + (q.progress || 0) + '%</span>';
          } else if (q.status === 'pending') {
            statusBadge = '<span class="brand-badge" style="background:rgba(245,158,11,0.2); color:var(--accent-amber);">Pending</span>';
          } else if (q.status === 'cancelled') {
            statusBadge = '<span class="brand-badge" style="background:rgba(244,63,94,0.2); color:var(--accent-rose);">Cancelled</span>';
          } else {
            statusBadge = '<span class="brand-badge">' + (q.status || 'Queue') + '</span>';
          }

          const qFolderName = q.folder_name || 'Folder';
          const qSubLoc = q.source_label || (q.source_path ? q.source_path.substring(0, 20) + '...' : '');

          qtr.innerHTML = '<td style="font-weight:600;" title="' + escapeHtml(q.source_path) + '">' + escapeHtml(q.filename) + '</td>'
            + '<td>'
            +   '<div class="folder-cell" title="' + escapeHtml(q.source_path) + '">'
            +     '<div class="folder-title"><span class="folder-icon">📁</span>' + escapeHtml(qFolderName) + '</div>'
            +     '<div class="folder-sub">' + escapeHtml(qSubLoc) + '</div>'
            +   '</div>'
            + '</td>'
            + '<td><span style="font-size:11px; color:var(--text-muted);">' + (q.profile || 'NVENC') + '</span></td>'
            + '<td>' + formatBytes(q.original_size) + '</td>'
            + '<td>' + statusBadge + '</td>'
            + '<td style="text-align:center;">'
            +   '<button class="btn btn-secondary btn-sm btn-open-queue" title="Reveal in File Explorer" style="padding:3px 8px; font-size:11px;">📂 Open</button>'
            + '</td>';

          const btnOpenQ = qtr.querySelector('.btn-open-queue');
          if (btnOpenQ) {
            btnOpenQ.addEventListener('click', (e) => {
              e.stopPropagation();
              openFileLocation(q.source_path, false);
            });
          }

          qtr.addEventListener('contextmenu', (e) => {
            showContextMenu(e, {
              filename: q.filename,
              abs_path: q.source_path,
              folder_path: q.folder_path || '',
              file_id: q.source_file_id,
              can_queue: false
            });
          });

          queueTbody.appendChild(qtr);
        });
      } else {
        queueBox.style.display = 'none';
      }
    }

    // 3. CANDIDATES TABLE WITH SUITABILITY & BITRATE
    const tbody = document.getElementById('video-candidates-body');
    tbody.innerHTML = '';

    const ratio = getProfileRatio();

    if (candidates.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; color:var(--text-muted); padding:24px;">No videos match the current filters.</td></tr>';
    } else {
      candidates.forEach(v => {
        const tr = document.createElement('tr');
        tr.style.cursor = 'context-menu';
        const isChecked = selectedTranscodeIds.has(v.id);

        const folderName = v.folder_name || 'Folder';
        const subLocation = v.source_label || (v.abs_path ? v.abs_path.substring(0, 20) + '...' : '');
        const bitrateDisplay = v.bitrate_formatted || 'N/A';
        const codecDisplay = (v.video_codec ? v.video_codec.toUpperCase() : 'H.264');
        const resDisplay = v.res_label ? (v.res_label + (v.width ? ' (' + v.width + 'x' + v.height + ')' : '')) : (v.width ? v.width + 'x' + v.height : 'HD');

        // Savings estimation cell
        let savingsCellHtml = '';
        if (v.suitability === 'already_compact') {
          savingsCellHtml = '<span style="color:var(--accent-rose); font-size:11px; font-weight:600;">0 B (Bloat Risk)</span>';
        } else if (v.suitability === 'already_hevc') {
          savingsCellHtml = '<span style="color:var(--text-muted); font-size:11px;">0 B (Already H.265)</span>';
        } else {
          const estBytes = v.est_savings_bytes || Math.round(v.size_bytes * ratio);
          savingsCellHtml = '<span class="cell-est-savings" data-size="' + v.size_bytes + '" style="color:var(--accent-emerald); font-weight:600;">~' + formatBytes(estBytes) + '</span>';
        }

        // Efficiency / Suitability Badge
        let badgeBg = 'rgba(16,185,129,0.18)';
        let badgeColor = 'var(--accent-emerald)';
        if (v.suitability === 'already_compact') {
          badgeBg = 'rgba(244,63,94,0.18)';
          badgeColor = 'var(--accent-rose)';
        } else if (v.suitability === 'already_hevc') {
          badgeBg = 'rgba(59,130,246,0.18)';
          badgeColor = 'var(--accent-blue)';
        } else if (v.suitability === 'moderate_savings') {
          badgeBg = 'rgba(245,158,11,0.18)';
          badgeColor = 'var(--accent-amber)';
        }

        const efficiencyBadge = '<span class="brand-badge" style="background:' + badgeBg + '; color:' + badgeColor + '; font-size:11px; font-weight:600; cursor:help;" title="' + escapeHtml(v.explanation || '') + '">'
          + escapeHtml(v.suitability_label || 'Standard')
          + '</span>';

        tr.innerHTML = '<td style="text-align:center;"><input type="checkbox" class="chk-candidate-item" data-id="' + v.id + '" ' + (isChecked ? 'checked' : '') + '></td>'
          + '<td style="font-weight:600;" title="' + escapeHtml(v.abs_path) + '">' + escapeHtml(v.filename) + '</td>'
          + '<td>'
          +   '<div class="folder-cell" title="' + escapeHtml(v.abs_path) + '">'
          +     '<div class="folder-title"><span class="folder-icon">📁</span>' + escapeHtml(folderName) + '</div>'
          +     '<div class="folder-sub">' + escapeHtml(subLocation) + '</div>'
          +   '</div>'
          + '</td>'
          + '<td style="font-family:monospace; font-size:12px; font-weight:600; color:var(--text-main);">' + escapeHtml(bitrateDisplay) + '</td>'
          + '<td><span style="font-weight:500;">' + codecDisplay + '</span> <span style="font-size:11px; color:var(--text-muted);">' + resDisplay + '</span></td>'
          + '<td>' + formatBytes(v.size_bytes) + '</td>'
          + '<td>' + savingsCellHtml + '</td>'
          + '<td>' + efficiencyBadge + '</td>'
          + '<td>'
          +   '<div style="display:flex; gap:5px; align-items:center;">'
          +     '<button class="btn btn-secondary btn-sm btn-queue-single" data-id="' + v.id + '">Queue</button>'
          +     '<button class="btn btn-secondary btn-sm btn-open-cand" title="Reveal in File Explorer" style="padding:4px 8px; font-size:12px;">📂</button>'
          +   '</div>'
          + '</td>';

        const btnQ = tr.querySelector('.btn-queue-single');
        if (btnQ) {
          btnQ.addEventListener('click', (e) => {
            e.stopPropagation();
            if (v.suitability === 'already_compact') {
              if (!confirm('Warning: "' + v.filename + '" is already heavily compressed (' + bitrateDisplay + ').\n\nRe-encoding to H.265 may INCREASE its file size (bloat)!\n\nDo you still want to queue it?')) {
                return;
              }
            } else if (v.suitability === 'already_hevc') {
              if (!confirm('Notice: "' + v.filename + '" is already encoded in H.265/HEVC.\n\nRe-encoding will cause generational quality loss with little or no space gain.\n\nQueue anyway?')) {
                return;
              }
            }
            queueSingleVideo(v.id);
          });
        }

        const btnOpen = tr.querySelector('.btn-open-cand');
        if (btnOpen) {
          btnOpen.addEventListener('click', (e) => {
            e.stopPropagation();
            openFileLocation(v.abs_path, false);
          });
        }

        tr.addEventListener('contextmenu', (e) => {
          showContextMenu(e, {
            filename: v.filename,
            abs_path: v.abs_path,
            folder_path: v.folder_path || '',
            file_id: v.id,
            can_queue: true
          });
        });

        tbody.appendChild(tr);
      });
    }

    // Update selection summary
    updateTranscodeSelectionSummary();

    // Bind filters & listeners once
    if (!transcodeFiltersBound) {
      transcodeFiltersBound = true;
      bindTranscodeControls();
    }

  } catch (err) {
    console.error('Failed to load transcoder:', err);
  }
}

function updateTranscodeSelectionSummary() {
  const summaryEl = document.getElementById('transcode-selection-summary');
  const btnQueueSelected = document.getElementById('btn-queue-selected');
  const ratio = getProfileRatio();

  let totalSelBytes = 0;
  selectedTranscodeIds.forEach(id => {
    const item = currentCandidates.find(c => c.id === id);
    if (item) totalSelBytes += item.size_bytes;
  });

  const projectedSavings = Math.round(totalSelBytes * ratio);

  if (summaryEl) {
    if (selectedTranscodeIds.size > 0) {
      summaryEl.innerHTML = '<strong>' + selectedTranscodeIds.size + '</strong> selected (' + formatBytes(totalSelBytes) + ') → Est. Saved: <span style="color:var(--accent-emerald)">~' + formatBytes(projectedSavings) + '</span>';
    } else {
      summaryEl.innerText = '0 selected';
    }
  }
  if (btnQueueSelected) {
    btnQueueSelected.innerText = 'Queue Selected (' + selectedTranscodeIds.size + ')';
  }
}

function bindTranscodeControls() {
  // Profile change dynamically updates all estimated savings
  const selProfile = document.getElementById('sel-transcode-profile');
  if (selProfile) {
    selProfile.addEventListener('change', () => {
      updateCandidateSavingsCells();
    });
  }
  // Filter triggers
  ['sel-transcode-drive', 'sel-transcode-min-size', 'sel-transcode-codec', 'sel-transcode-suitability'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', () => loadTranscoder());
  });

  const searchEl = document.getElementById('txt-transcode-search');
  if (searchEl) {
    searchEl.addEventListener('input', () => loadTranscoder());
  }

  // Checkbox select all
  const chkAll = document.getElementById('chk-candidate-all');
  if (chkAll) {
    chkAll.addEventListener('change', (e) => {
      const checked = e.target.checked;
      document.querySelectorAll('.chk-candidate-item').forEach(chk => {
        chk.checked = checked;
        const fid = parseInt(chk.dataset.id);
        if (checked) selectedTranscodeIds.add(fid);
        else selectedTranscodeIds.delete(fid);
      });
      updateTranscodeSelectionSummary();
    });
  }

  // Row checkbox delegator
  document.getElementById('video-candidates-body').addEventListener('change', (e) => {
    if (e.target.classList.contains('chk-candidate-item')) {
      const fid = parseInt(e.target.dataset.id);
      if (e.target.checked) selectedTranscodeIds.add(fid);
      else selectedTranscodeIds.delete(fid);
      updateTranscodeSelectionSummary();
    }
  });

  // Queue selected button
  document.getElementById('btn-queue-selected').addEventListener('click', async () => {
    if (selectedTranscodeIds.size === 0) {
      alert('Please select one or more videos to queue!');
      return;
    }

    const selectedItems = currentCandidates.filter(c => selectedTranscodeIds.has(c.id));
    const bloatRiskItems = selectedItems.filter(c => c.suitability === 'already_compact');
    if (bloatRiskItems.length > 0) {
      if (!confirm(`Warning: ${bloatRiskItems.length} of your selected videos are already heavily compressed and at risk of increasing in size (bloat)!\n\nQueue all ${selectedTranscodeIds.size} videos anyway?`)) {
        return;
      }
    }

    const profile = document.getElementById('sel-transcode-profile').value;
    try {
      const res = await fetch(API_BASE + '/api/transcodes/queue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_ids: Array.from(selectedTranscodeIds), profile: profile })
      });
      const data = await res.json();
      alert('Queued ' + data.count + ' videos for H.265 transcoding!');
      selectedTranscodeIds.clear();
      loadTranscoder();
    } catch (e) {
      alert('Failed to queue: ' + e);
    }
  });

  // Queue all filtered button
  document.getElementById('btn-queue-all-filtered').addEventListener('click', async () => {
    if (currentCandidates.length === 0) {
      alert('No videos match current filter to queue!');
      return;
    }
    const eligibleIds = currentCandidates
      .filter(c => c.transcode_status !== 'completed' && c.transcode_status !== 'already_optimal')
      .map(c => c.id);

    if (eligibleIds.length === 0) {
      alert('All currently filtered videos are already transcoded or in queue!');
      return;
    }

    const bloatRiskCount = currentCandidates.filter(c => c.suitability === 'already_compact').length;
    let promptMsg = 'Queue all ' + eligibleIds.length + ' filtered videos for H.265 conversion?';
    if (bloatRiskCount > 0) {
      promptMsg = `Warning: ${bloatRiskCount} of the filtered videos are already compact and may INCREASE in size if transcoded.\n\nAre you sure you want to queue all ${eligibleIds.length} videos?`;
    }

    if (!confirm(promptMsg)) return;

    const profile = document.getElementById('sel-transcode-profile').value;
    try {
      const res = await fetch(API_BASE + '/api/transcodes/queue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_ids: eligibleIds, profile: profile })
      });
      const data = await res.json();
      alert('Queued ' + data.count + ' videos!');
      loadTranscoder();
    } catch (e) {
      alert('Failed to queue: ' + e);
    }
  });

  // Master queue controls
  document.getElementById('btn-start-queue').addEventListener('click', async () => {
    try {
      await fetch(API_BASE + '/api/transcodes/control?action=start', { method: 'POST' });
      loadTranscoder();
    } catch (e) {
      console.error(e);
    }
  });

  document.getElementById('btn-pause-queue').addEventListener('click', async () => {
    try {
      const action = isTranscodePaused ? 'resume' : 'pause';
      isTranscodePaused = !isTranscodePaused;
      document.getElementById('btn-pause-queue').innerText = isTranscodePaused ? '▶ Resume' : '⏸ Pause';
      await fetch(API_BASE + '/api/transcodes/control?action=' + action, { method: 'POST' });
      loadTranscoder();
    } catch (e) {
      console.error(e);
    }
  });

  document.getElementById('btn-clear-completed-queue').addEventListener('click', async () => {
    try {
      await fetch(API_BASE + '/api/transcodes/control?action=clear_completed', { method: 'POST' });
      loadTranscoder();
    } catch (e) {
      console.error(e);
    }
  });
}

window.queueSingleVideo = async function(fid) {
  const profile = document.getElementById('sel-transcode-profile').value;
  try {
    await fetch(API_BASE + '/api/transcodes/queue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_ids: [fid], profile: profile })
    });
    loadTranscoder();
  } catch (e) {
    alert('Failed to queue video: ' + e);
  }
};

async function loadSync() {
  if (sourcesData.length === 0) {
    const res = await fetch(API_BASE + '/api/sources');
    sourcesData = await res.json();
  }
  const selWorking = document.getElementById('sel-sync-working');
  const selBackup = document.getElementById('sel-sync-backup');
  selWorking.innerHTML = '';
  selBackup.innerHTML = '';

  sourcesData.forEach(s => {
    selWorking.innerHTML += '<option value="' + s.id + '">' + s.label + ' (' + s.path + ')</option>';
    selBackup.innerHTML += '<option value="' + s.id + '">' + s.label + ' (' + s.path + ')</option>';
  });

  if (sourcesData.length > 1) {
    selBackup.selectedIndex = 1;
  }
}

document.getElementById('btn-compare-sync').addEventListener('click', async () => {
  const wId = document.getElementById('sel-sync-working').value;
  const bId = document.getElementById('sel-sync-backup').value;
  if (wId === bId) {
    alert('Please choose two different drives to compare (e.g. Working SSD vs NAS Backup)!');
    return;
  }

  try {
    const res = await fetch(API_BASE + '/api/sync/matrix?working_source_id=' + wId + '&backup_source_id=' + bId);
    syncMatrixData = await res.json();

    document.getElementById('sync-summary-card').style.display = 'block';
    document.getElementById('sync-reclaimable-size').innerText = formatBytes(syncMatrixData.safe_reclaimable_bytes);

    const syncedContainer = document.getElementById('synced-safe-list');
    syncedContainer.innerHTML = '';
    if (syncMatrixData.synced_safe.length === 0) {
      syncedContainer.innerHTML = '<p style="color:var(--text-muted); font-size:13px;">No matching verified backups found on target drive.</p>';
    } else {
      syncMatrixData.synced_safe.forEach(f => {
        syncedContainer.innerHTML += '<div style="font-size:12px; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.05); display:flex; justify-content:space-between;">'
          + '<span>✓ ' + f.filename + '</span>'
          + '<span style="color:var(--text-muted);">' + formatBytes(f.size_bytes) + '</span>'
          + '</div>';
      });
    }

    const unbackedContainer = document.getElementById('unbacked-up-list');
    unbackedContainer.innerHTML = '';
    if (syncMatrixData.unbacked_up.length === 0) {
      unbackedContainer.innerHTML = '<p style="color:var(--accent-emerald); font-size:13px;">All files on working drive are safely backed up!</p>';
    } else {
      syncMatrixData.unbacked_up.forEach(f => {
        unbackedContainer.innerHTML += '<div style="font-size:12px; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.05); display:flex; justify-content:space-between;">'
          + '<span style="color:var(--accent-rose);">⚠️ ' + f.filename + '</span>'
          + '<span style="color:var(--text-muted);">' + formatBytes(f.size_bytes) + '</span>'
          + '</div>';
      });
    }
  } catch (e) {
    alert('Failed to compare drives: ' + e);
  }
});

document.getElementById('btn-reclaim-safe-ssd').addEventListener('click', async () => {
  if (!syncMatrixData || syncMatrixData.synced_safe.length === 0) {
    alert('No verified safe files to reclaim. Compare drives first!');
    return;
  }

  const count = syncMatrixData.synced_safe.length;
  const size = formatBytes(syncMatrixData.safe_reclaimable_bytes);

  if (!confirm('Reclaim ' + size + ' on your SSD by recycling ' + count + ' files that are cryptographically verified on your backup drive? (XMP sidecars will be safely handled)')) return;

  try {
    const fileIds = syncMatrixData.synced_safe.map(f => f.id);
    const res = await fetch(API_BASE + '/api/sync/reclaim', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fileIds)
    });
    const result = await res.json();
    alert('Successfully reclaimed space! Recycled ' + result.reclaimed_count + ' local files.');
    loadOverview();
  } catch (e) {
    alert('Error: ' + e);
  }
});

async function loadOrganizer() {
  if (sourcesData.length === 0) {
    const res = await fetch(API_BASE + '/api/sources');
    sourcesData = await res.json();
  }
  const selOrg = document.getElementById('sel-org-source');
  selOrg.innerHTML = '';
  sourcesData.forEach(s => {
    selOrg.innerHTML += '<option value="' + s.id + '">' + s.label + ' (' + s.path + ')</option>';
  });
}

document.getElementById('btn-org-preview').addEventListener('click', async () => {
  const sourceId = document.getElementById('sel-org-source').value;
  const destRoot = document.getElementById('txt-org-dest').value.trim();
  const pattern = document.getElementById('txt-org-pattern').value.trim();
  const container = document.getElementById('org-preview-container');

  if (!destRoot) {
    alert('Please specify a target folder destination (e.g. F:\\OrganizedPhotos)!');
    return;
  }

  container.innerHTML = '<p style="color:var(--text-muted); font-size:13px;">Generating organization plan...</p>';

  try {
    const res = await fetch(API_BASE + '/api/organize/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_id: parseInt(sourceId),
        destination_root: destRoot,
        pattern: pattern,
        dry_run: true
      })
    });
    const plan = await res.json();
    container.innerHTML = '';

    if (plan.length === 0) {
      container.innerHTML = '<p style="color:var(--text-muted); font-size:13px;">No files found in source drive to organize.</p>';
      return;
    }

    plan.slice(0, 50).forEach(p => {
      const sidecarInfo = p.sidecars.length > 0 
        ? '<div style="color:var(--accent-cyan); font-size:11px;">+ ' + p.sidecars.length + ' XMP sidecar(s) atomically locked</div>'
        : '';
      container.innerHTML += '<div style="font-size:12px; padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.05);">'
        + '<div><strong>From:</strong> ' + p.source_path + '</div>'
        + '<div style="color:var(--accent-emerald);"><strong>To:</strong> ' + p.dest_path + '</div>'
        + sidecarInfo
        + '</div>';
    });
    if (plan.length > 50) {
      container.innerHTML += '<p style="color:var(--text-muted); font-size:12px; margin-top:8px;">... and ' + (plan.length - 50) + ' more files.</p>';
    }
  } catch (e) {
    alert('Failed to preview: ' + e);
  }
});

document.getElementById('btn-org-execute').addEventListener('click', async () => {
  const sourceId = document.getElementById('sel-org-source').value;
  const destRoot = document.getElementById('txt-org-dest').value.trim();
  const pattern = document.getElementById('txt-org-pattern').value.trim();

  if (!destRoot) {
    alert('Please specify a target folder destination!');
    return;
  }

  if (!confirm('Execute file organization to ' + destRoot + '? Files and their XMP sidecars will be moved into the organized date/camera structure.')) return;

  try {
    const res = await fetch(API_BASE + '/api/organize/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_id: parseInt(sourceId),
        destination_root: destRoot,
        pattern: pattern,
        dry_run: false
      })
    });
    const result = await res.json();
    alert('Organized ' + result.success_count + ' files successfully!');
    loadOverview();
  } catch (e) {
    alert('Error: ' + e);
  }
});

const modalAddSource = document.getElementById('modal-add-source');
document.getElementById('btn-add-source-modal').addEventListener('click', () => {
  modalAddSource.classList.add('active');
  const sec = document.getElementById('add-source-subfolder-section');
  if (sec) sec.style.display = 'none';
});

// Universal modal close handler
document.querySelectorAll('.modal-close').forEach(b => {
  b.addEventListener('click', (e) => {
    const modal = e.target.closest('.modal-overlay');
    if (modal) modal.classList.remove('active');
  });
});

// Manage Subfolders Modal Controls
const txtSubFilter = document.getElementById('txt-subfolder-filter');
if (txtSubFilter) {
  txtSubFilter.addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase().trim();
    document.querySelectorAll('#subfolder-list-container .subfolder-item-row').forEach(row => {
      row.style.display = row.dataset.name.includes(q) ? 'flex' : 'none';
    });
  });
}

const btnSubSelectAll = document.getElementById('btn-subfolder-select-all');
if (btnSubSelectAll) {
  btnSubSelectAll.addEventListener('click', () => {
    document.querySelectorAll('#subfolder-list-container .chk-subfolder').forEach(chk => {
      chk.checked = true;
      chk.dispatchEvent(new Event('change'));
    });
  });
}

const btnSubDeselectAll = document.getElementById('btn-subfolder-deselect-all');
if (btnSubDeselectAll) {
  btnSubDeselectAll.addEventListener('click', () => {
    document.querySelectorAll('#subfolder-list-container .chk-subfolder').forEach(chk => {
      chk.checked = false;
      chk.dispatchEvent(new Event('change'));
    });
  });
}

const btnSaveSubExclusions = document.getElementById('btn-save-subfolder-exclusions');
if (btnSaveSubExclusions) {
  btnSaveSubExclusions.addEventListener('click', async () => {
    if (!currentSubfolderSourceId) return;

    // Any unchecked box is an excluded path
    const excluded = [];
    document.querySelectorAll('#subfolder-list-container .chk-subfolder').forEach(chk => {
      if (!chk.checked) {
        excluded.push(chk.dataset.path);
      }
    });

    const purge = document.getElementById('chk-purge-deselected').checked;
    btnSaveSubExclusions.disabled = true;
    btnSaveSubExclusions.textContent = 'Saving & Applying...';

    try {
      const res = await fetch(API_BASE + '/api/sources/' + currentSubfolderSourceId + '/exclusions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ excluded_paths: excluded, purge_indexed: purge })
      });
      const result = await res.json();
      alert(result.message || 'Exclusions saved successfully!');
      document.getElementById('modal-manage-subfolders').classList.remove('active');
      loadSources();
      loadOverview();
    } catch (err) {
      alert('Failed to save exclusions: ' + err);
    } finally {
      btnSaveSubExclusions.disabled = false;
      btnSaveSubExclusions.textContent = 'Save & Apply Exclusions';
    }
  });
}

// Check subfolders for new source registration
async function checkNewSourceSubfolders(dirPath) {
  const sec = document.getElementById('add-source-subfolder-section');
  const list = document.getElementById('add-source-subfolder-list');
  if (!dirPath || dirPath.length < 2) {
    if (sec) sec.style.display = 'none';
    return;
  }
  try {
    const res = await fetch(API_BASE + '/api/utils/list_subfolders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: dirPath })
    });
    const data = await res.json();
    const subs = data.subfolders || [];
    if (subs.length > 0) {
      sec.style.display = 'block';
      list.innerHTML = '';
      subs.forEach(s => {
        const label = document.createElement('label');
        label.style.display = 'flex';
        label.style.alignItems = 'center';
        label.style.gap = '8px';
        label.style.padding = '4px 0';
        label.style.cursor = 'pointer';
        label.innerHTML = '<input type="checkbox" class="chk-add-sub" data-path="' + s.rel_path + '" checked> <span>📁 ' + s.name + '</span>';
        list.appendChild(label);
      });
    } else {
      sec.style.display = 'none';
    }
  } catch (e) {
    if (sec) sec.style.display = 'none';
  }
}

const inputSourcePath = document.getElementById('modal-source-path');
if (inputSourcePath) {
  inputSourcePath.addEventListener('change', () => {
    checkNewSourceSubfolders(inputSourcePath.value.trim());
  });
}

const btnAddSubAll = document.getElementById('btn-add-subfolder-all');
if (btnAddSubAll) {
  btnAddSubAll.addEventListener('click', () => {
    document.querySelectorAll('#add-source-subfolder-list .chk-add-sub').forEach(c => c.checked = true);
  });
}

const btnAddSubNone = document.getElementById('btn-add-subfolder-none');
if (btnAddSubNone) {
  btnAddSubNone.addEventListener('click', () => {
    document.querySelectorAll('#add-source-subfolder-list .chk-add-sub').forEach(c => c.checked = false);
  });
}

document.getElementById('modal-btn-save-source').addEventListener('click', async () => {
  const path = document.getElementById('modal-source-path').value.trim();
  const label = document.getElementById('modal-source-label').value.trim();
  const type = document.getElementById('modal-source-type').value;

  if (!path || !label) {
    alert('Please provide both a directory path and a label!');
    return;
  }

  // Collect any deselected subfolders
  const excluded = [];
  document.querySelectorAll('#add-source-subfolder-list .chk-add-sub').forEach(chk => {
    if (!chk.checked) {
      excluded.push(chk.dataset.path);
    }
  });

  try {
    await fetch(API_BASE + '/api/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: path, label: label, drive_type: type, excluded_paths: excluded })
    });
    modalAddSource.classList.remove('active');
    loadOverview();
    loadSources();
  } catch (e) {
    alert('Failed to add source: ' + e);
  }
});

// Native Windows Folder Picker Triggers
const btnBrowseSource = document.getElementById('btn-browse-source');
if (btnBrowseSource) {
  btnBrowseSource.addEventListener('click', async () => {
    try {
      const res = await fetch(API_BASE + '/api/utils/pick_folder', { method: 'POST' });
      const data = await res.json();
      if (data.selected && data.path) {
        document.getElementById('modal-source-path').value = data.path;
        if (!document.getElementById('modal-source-label').value.trim()) {
          document.getElementById('modal-source-label').value = data.label;
        }
        checkNewSourceSubfolders(data.path);
      }
    } catch (e) {
      console.error('Folder picker error:', e);
    }
  });
}

const btnBrowseOrg = document.getElementById('btn-browse-org');
if (btnBrowseOrg) {
  btnBrowseOrg.addEventListener('click', async () => {
    try {
      const res = await fetch(API_BASE + '/api/utils/pick_folder', { method: 'POST' });
      const data = await res.json();
      if (data.selected && data.path) {
        document.getElementById('txt-org-dest').value = data.path;
      }
    } catch (e) {
      console.error('Folder picker error:', e);
    }
  });
}

setupContextMenu();
loadOverview();

setInterval(() => {
  if (currentTab === 'transcoder') {
    loadTranscoder();
  }
}, 3000);
