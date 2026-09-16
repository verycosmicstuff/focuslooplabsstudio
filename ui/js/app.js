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

function switchTab(tabName) {
  const item = document.querySelector(`.nav-item[data-tab="${tabName}"]`);
  if (item && !item.classList.contains('active')) {
    item.click();
  }
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
      sync: 'Primary & Backup Directory Sync Matrix',
      organizer: 'Smart Media Organizer',
      proofing: 'Client Proofing, Watermarking & Selects'
    };
    document.getElementById('current-view-title').innerText = titles[currentTab] || 'SaveSpace Pro';
    refreshCurrentTab();

    if (typeof debouncedSaveSessionState === 'function') {
      debouncedSaveSessionState({ last_active_tab: currentTab });
    }
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
  else if (currentTab === 'proofing') loadProofing();
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
      const aliasCount = (s.alternate_paths && s.alternate_paths.length) || 0;
      const aliasBadge = aliasCount > 1
        ? ' <span class="brand-badge" style="background:rgba(99,102,241,0.2); color:#a5b4fc; font-size:11px;" title="Alternate Mounts (USB/NAS):\n' + s.alternate_paths.join('\n') + '">🔗 ' + aliasCount + ' Mounts</span>'
        : '';

      const isScanning = s.scan_status === 'scanning';
      const isPaused = s.scan_status === 'paused';
      
      let countHtml = (s.file_count || 0).toLocaleString();
      let scanButtonsHtml = '<button class="btn btn-primary btn-sm" onclick="scanSource(' + s.id + ')" style="margin-right:4px;">Scan Now</button>';
      
      if (isScanning) {
        const liveCnt = (s.live_scanned_count !== undefined && s.live_scanned_count !== null) ? s.live_scanned_count : (s.file_count || 0);
        countHtml = '<span style="color:var(--accent-cyan); font-weight:700;">' + Number(liveCnt).toLocaleString() + '</span> <span style="font-size:11px; color:var(--text-muted);">(scanning...)</span>';
        scanButtonsHtml = '<button class="btn btn-warning btn-sm" onclick="pauseSourceScan(' + s.id + ')" style="margin-right:4px; font-weight:600;" title="Pause Indexing">⏸️ Pause</button>'
          + '<button class="btn btn-secondary btn-sm" onclick="cancelSourceScan(' + s.id + ')" style="margin-right:4px;" title="Cancel Scan">⏹️</button>';
      } else if (isPaused) {
        const liveCnt = (s.live_scanned_count !== undefined && s.live_scanned_count !== null) ? s.live_scanned_count : (s.file_count || 0);
        countHtml = '<span style="color:var(--accent-amber); font-weight:700;">' + Number(liveCnt).toLocaleString() + '</span> <span style="font-size:11px; color:var(--accent-amber);">(⏸️ PAUSED)</span>';
        scanButtonsHtml = '<button class="btn btn-success btn-sm" onclick="resumeSourceScan(' + s.id + ')" style="margin-right:4px; font-weight:600;" title="Resume Indexing">▶️ Resume</button>'
          + '<button class="btn btn-secondary btn-sm" onclick="cancelSourceScan(' + s.id + ')" style="margin-right:4px;" title="Cancel Scan">⏹️</button>';
      }

      tr.id = 'source-row-' + s.id;
      tr.innerHTML = '<td style="font-weight:600;"><div style="display:flex; align-items:center; gap:6px;"><span>' + s.label + '</span><button class="btn btn-secondary btn-sm" onclick="openEditSourceModal(' + s.id + ')" title="Rename / Change Label" style="padding:1px 6px; font-size:11px; opacity:0.75;">✏️</button></div></td>'
        + '<td style="font-family:monospace; font-size:12px;">' + s.path + aliasBadge + excludedBadge + '</td>'
        + '<td><span class="brand-badge" style="cursor:pointer;" onclick="openEditSourceModal(' + s.id + ')" title="Click to change drive type">' + s.drive_type + '</span></td>'
        + '<td>' + onlineTag + '</td>'
        + '<td id="source-count-' + s.id + '">' + countHtml + '</td>'
        + '<td>' + formatBytes(s.total_media_size || 0) + '</td>'
        + '<td style="font-size:11px; color:var(--text-muted);">' + (s.last_scanned ? s.last_scanned.split('T')[0] : 'Never') + '</td>'
        + '<td style="white-space:nowrap;">'
        + '<button class="btn btn-secondary btn-sm" onclick="openEditSourceModal(' + s.id + ')" style="margin-right:4px;">✏️ Label</button>'
        + '<button class="btn btn-secondary btn-sm" onclick="openSubfoldersModal(' + s.id + ')" style="margin-right:4px;">📁 Folders' + (excludedCount > 0 ? ' (' + excludedCount + ')' : '') + '</button>'
        + '<span id="scan-actions-' + s.id + '">' + scanButtonsHtml + '</span>'
        + '<button class="btn btn-secondary btn-sm" onclick="deleteSource(' + s.id + ')">Remove</button>'
        + '</td>';
      tbody.appendChild(tr);

      if (isScanning || isPaused) {
        pollScanProgress(s.id);
      }
    });
  } catch (err) {
    console.error('Failed to load sources:', err);
  }
}

window.openEditSourceModal = function(sourceId) {
  const source = (sourcesData || []).find(s => s.id === sourceId);
  if (!source) return;

  document.getElementById('edit-source-id').value = source.id;
  document.getElementById('edit-source-path-display').innerText = source.path;
  document.getElementById('edit-source-label-input').value = source.label || '';
  document.getElementById('edit-source-type-select').value = source.drive_type || 'LOCAL';

  const modal = document.getElementById('modal-edit-source');
  if (modal) {
    modal.classList.add('active');
    setTimeout(() => {
      const inp = document.getElementById('edit-source-label-input');
      if (inp) { inp.focus(); inp.select(); }
    }, 50);
  }
};

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

let activeScanPollers = new Set();

function pollScanProgress(sourceId) {
  if (activeScanPollers.has(sourceId)) return;
  activeScanPollers.add(sourceId);

  const pollInterval = setInterval(async () => {
    try {
      const res = await fetch(API_BASE + '/api/sources/' + sourceId + '/scan_status');
      if (!res.ok) {
        clearInterval(pollInterval);
        activeScanPollers.delete(sourceId);
        return;
      }
      const data = await res.json();
      if (data.status === 'idle' || data.status === 'completed') {
        clearInterval(pollInterval);
        activeScanPollers.delete(sourceId);
        updateSourceScanControls(sourceId, 'idle', data.scanned || 0);
        showToast('Scan complete! ' + (data.scanned || 0).toLocaleString() + ' files indexed.', 'success');
        loadSources();
        loadOverview();
      } else if (data.status === 'cancelled') {
        clearInterval(pollInterval);
        activeScanPollers.delete(sourceId);
        updateSourceScanControls(sourceId, 'idle', data.scanned || 0);
        showToast('Scan cancelled for source ' + sourceId, 'info');
        loadSources();
      } else if (data.status === 'error') {
        clearInterval(pollInterval);
        activeScanPollers.delete(sourceId);
        updateSourceScanControls(sourceId, 'idle');
        showToast('Scan error: ' + (data.error || 'Unknown error'), 'error');
      } else if (data.status === 'paused') {
        updateSourceScanControls(sourceId, 'paused', data.scanned_count || data.scanned || 0);
      } else if (data.status === 'scanning') {
        updateSourceScanControls(sourceId, 'scanning', data.scanned_count || data.scanned || 0);
      }
    } catch (e) {
      clearInterval(pollInterval);
      activeScanPollers.delete(sourceId);
    }
  }, 2000);
}

function updateSourceScanControls(sourceId, status, count) {
  const countEl = document.getElementById('source-count-' + sourceId);
  const actionsEl = document.getElementById('scan-actions-' + sourceId);
  
  if (status === 'scanning') {
    if (countEl && count !== undefined) {
      countEl.innerHTML = '<span style="color:var(--accent-cyan); font-weight:700;">' + Number(count).toLocaleString() + '</span> <span style="font-size:11px; color:var(--text-muted);">(scanning...)</span>';
    }
    if (actionsEl) {
      actionsEl.innerHTML = '<button class="btn btn-warning btn-sm" onclick="pauseSourceScan(' + sourceId + ')" style="margin-right:4px; font-weight:600;" title="Pause Indexing">⏸️ Pause</button>'
        + '<button class="btn btn-secondary btn-sm" onclick="cancelSourceScan(' + sourceId + ')" style="margin-right:4px;" title="Cancel Scan">⏹️</button>';
    }
  } else if (status === 'paused') {
    if (countEl && count !== undefined) {
      countEl.innerHTML = '<span style="color:var(--accent-amber); font-weight:700;">' + Number(count).toLocaleString() + '</span> <span style="font-size:11px; color:var(--accent-amber);">(⏸️ PAUSED)</span>';
    }
    if (actionsEl) {
      actionsEl.innerHTML = '<button class="btn btn-success btn-sm" onclick="resumeSourceScan(' + sourceId + ')" style="margin-right:4px; font-weight:600;" title="Resume Indexing">▶️ Resume</button>'
        + '<button class="btn btn-secondary btn-sm" onclick="cancelSourceScan(' + sourceId + ')" style="margin-right:4px;" title="Cancel Scan">⏹️</button>';
    }
  } else {
    if (actionsEl) {
      actionsEl.innerHTML = '<button class="btn btn-primary btn-sm" onclick="scanSource(' + sourceId + ')" style="margin-right:4px;">Scan Now</button>';
    }
  }
}

window.pauseSourceScan = async function(id) {
  try {
    const res = await fetch(API_BASE + '/api/sources/' + id + '/pause', { method: 'POST' });
    if (res.ok) {
      showToast('Indexing paused.', 'info');
      updateSourceScanControls(id, 'paused');
    } else {
      const err = await res.json();
      showToast(err.detail || 'Could not pause scan', 'error');
    }
  } catch (e) {
    showToast('Failed to pause scan: ' + e, 'error');
  }
};

window.resumeSourceScan = async function(id) {
  try {
    const res = await fetch(API_BASE + '/api/sources/' + id + '/resume', { method: 'POST' });
    if (res.ok) {
      showToast('Indexing resumed!', 'success');
      updateSourceScanControls(id, 'scanning');
      pollScanProgress(id);
    } else {
      const err = await res.json();
      showToast(err.detail || 'Could not resume scan', 'error');
    }
  } catch (e) {
    showToast('Failed to resume scan: ' + e, 'error');
  }
};

window.cancelSourceScan = async function(id) {
  if (!confirm('Cancel the running scan for this drive? Files indexed so far will be kept.')) return;
  try {
    const res = await fetch(API_BASE + '/api/sources/' + id + '/cancel', { method: 'POST' });
    if (res.ok) {
      showToast('Indexing cancelled.', 'info');
      updateSourceScanControls(id, 'idle');
      loadSources();
    }
  } catch (e) {
    showToast('Failed to cancel scan: ' + e, 'error');
  }
};

window.scanSource = async function(id) {
  try {
    updateSourceScanControls(id, 'scanning');
    const res = await fetch(API_BASE + '/api/sources/' + id + '/scan', { method: 'POST' });
    if (res.ok) {
      showToast('Scan started in background! Indexing files live...', 'info');
      pollScanProgress(id);
    } else {
      const err = await res.json();
      showToast(err.detail || 'Failed to start scan', 'error');
      updateSourceScanControls(id, 'idle');
    }
  } catch (e) {
    showToast('Failed to start scan: ' + e, 'error');
    updateSourceScanControls(id, 'idle');
  }
};

const btnScanAll = document.getElementById('btn-scan-all');
if (btnScanAll) {
  btnScanAll.addEventListener('click', async () => {
    if (!sourcesData || sourcesData.length === 0) {
      showToast('No sources registered to scan.', 'info');
      return;
    }
    showToast('Scanning all online sources...', 'info');
    for (const s of sourcesData) {
      if (s.is_online) {
        try {
          await fetch(API_BASE + '/api/sources/' + s.id + '/scan', { method: 'POST' });
          pollScanProgress(s.id);
        } catch (e) {
          console.error(e);
        }
      }
    }
  });
}

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

const selCullFolder = document.getElementById('sel-cull-folder');
if (selCullFolder) {
  selCullFolder.addEventListener('change', () => {
    loadCuller();
  });
}

async function loadCullerFolders() {
  const sel = document.getElementById('sel-cull-folder');
  if (!sel) return;
  const currentVal = sel.value;
  try {
    const res = await fetch(API_BASE + '/api/culling/folders');
    const folders = await res.json();
    sel.innerHTML = '<option value="">All Scanned Folders</option>';
    folders.forEach(f => {
      const opt = document.createElement('option');
      opt.value = f.path;
      opt.textContent = f.name;
      opt.title = f.path;
      sel.appendChild(opt);
    });
    if (currentVal) sel.value = currentVal;
  } catch (e) {
    console.error('Failed to load culling folders', e);
  }
}

let cullOffset = 0;
const CULL_BATCH_SIZE = 80;

async function loadCuller(append = false) {
  const threshold = sliderThreshold.value;
  const burstOnly = document.getElementById('chk-burst-only').checked;
  const folderFilter = document.getElementById('sel-cull-folder')?.value || '';
  const gallery = document.getElementById('culler-gallery');

  if (!append) {
    loadCullerFolders();
    cullOffset = 0;
    cullingItems = [];
    selectedCullIds.clear();
    gallery.innerHTML = '<p style="color:var(--text-muted); padding:20px;">Loading media analysis...</p>';
  }

  const existingMore = document.getElementById('cull-load-more-box');
  if (existingMore) existingMore.remove();

  try {
    let url = API_BASE + '/api/culling?threshold=' + threshold + '&burst_only=' + burstOnly + '&limit=' + CULL_BATCH_SIZE + '&offset=' + cullOffset;
    if (folderFilter) {
      url += '&folder=' + encodeURIComponent(folderFilter);
    }
    const res = await fetch(url);
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
        + '<button class="btn-cull-card-keep" title="Mark as intentional / keep" style="position:absolute; top:6px; right:6px; z-index:5; background:rgba(15,23,42,0.85); border:1px solid rgba(255,255,255,0.25); color:#fbbf24; border-radius:4px; font-size:10px; font-weight:700; padding:2px 7px; cursor:pointer;">⭐ Keep</button>'
        + '</div>'
        + '<div class="media-meta-bar">'
        + '<div class="media-name" title="' + item.filename + '">' + item.filename + '</div>'
        + '<div class="media-details"><span>' + (item.camera_model || item.media_type.toUpperCase()) + '</span><span>' + formatBytes(item.size_bytes) + '</span></div>'
        + '</div>';

      const keepBtn = card.querySelector('.btn-cull-card-keep');
      if (keepBtn) {
        keepBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          try {
            await fetch(API_BASE + '/api/culling/action', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ file_ids: [item.id], action: 'keep', include_sidecars: false })
            });
            showToast(`Marked "${item.filename}" as intentional keep!`, 'success');
            card.style.opacity = '0';
            card.style.transform = 'scale(0.9)';
            card.style.transition = 'all 0.2s ease';
            setTimeout(() => card.remove(), 200);
            cullingItems = cullingItems.filter(i => i.id !== item.id);
          } catch (err) {
            showToast('Failed to keep photo: ' + err, 'error');
          }
        });
      }

      card.addEventListener('click', () => {
        if (selectedCullIds.has(item.id)) {
          selectedCullIds.delete(item.id);
          card.classList.remove('selected');
        } else {
          selectedCullIds.add(item.id);
          card.classList.add('selected');
        }
      });

      card.addEventListener('dblclick', () => {
        const curIdx = cullingItems.findIndex(ci => ci.id === item.id);
        if (curIdx >= 0) {
          openUniversalPreviewModal({ items: cullingItems, currentIndex: curIdx, fromCuller: true });
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

let dupeFilterDebounce = null;

function createDuplicateSetCard(group, idx) {
  const card = document.createElement('div');
  card.className = 'dupe-set-card';
  card.style.background = 'var(--bg-card)';
  card.style.border = '1px solid var(--border-color)';
  card.style.borderRadius = '8px';
  card.style.padding = '12px 14px';
  card.style.marginBottom = '12px';

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

    const shouldCheck = !isPrimary && isSameName;

    filesHtml += '<div class="dupe-file-row" data-path="' + escapeHtml(f.abs_path) + '" data-name="' + escapeHtml(f.filename) + '" data-folder="' + escapeHtml(f.folder_path || '') + '" style="display:flex; align-items:center; justify-content:space-between; padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.04);">'
      + '<div style="display:flex; align-items:center; gap:10px;">'
      + '<input type="checkbox" class="chk-dupe-item" data-id="' + f.id + '" data-same-name="' + isSameName + '" data-is-primary="' + isPrimary + '" ' + (shouldCheck ? 'checked' : '') + '>'
      + '<div>'
      + '<div style="font-weight:600; font-size:12px;">' + escapeHtml(f.filename) + ' ' + tag + '</div>'
      + '<div style="font-size:11px; color:var(--text-muted); font-family:monospace;">' + escapeHtml(f.abs_path) + '</div>'
      + '</div>'
      + '</div>'
      + '<div style="display:flex; align-items:center; gap:8px;">'
      + '<div style="font-size:11px; color:var(--text-muted);">' + escapeHtml(f.source_label || '') + ' (' + escapeHtml(f.drive_type || '') + ')</div>'
      + '<button class="btn btn-secondary btn-sm btn-open-dupe" title="Reveal in File Explorer" style="padding:2px 6px; font-size:11px;">📂</button>'
      + '</div>'
      + '</div>';
  });

  card.innerHTML = '<div style="display:flex; justify-content:space-between; margin-bottom:8px;">'
    + '<div><span style="font-weight:700; font-size:13px;">Duplicate Set #' + (idx + 1) + '</span><span style="font-size:11px; color:var(--text-muted); margin-left:8px;">' + group.count + ' identical copies (' + formatBytes(group.file_size) + ' each)</span></div>'
    + '<div style="color:var(--accent-amber); font-size:11px; font-weight:600;">Reclaimable: ' + formatBytes(group.potential_savings_bytes) + '</div>'
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

  return card;
}

function renderDuplicates() {
  const container = document.getElementById('duplicates-container');
  if (!container) return;
  container.innerHTML = '';

  if (!duplicatesData || duplicatesData.length === 0) {
    container.innerHTML = '<p style="color:var(--text-muted); padding:20px; text-align:center;">No duplicate files found! Your drives are clean.</p>';
    return;
  }

  const query = (document.getElementById('txt-dupe-filter')?.value || '').trim().toLowerCase();
  const groupMode = document.getElementById('sel-dupe-group-mode')?.value || 'folder';

  // 1. Filter duplicate sets
  const filteredSets = duplicatesData.filter(g => {
    if (!query) return true;
    if (g.folder_pair_label && g.folder_pair_label.toLowerCase().includes(query)) return true;
    if (g.primary_filename && g.primary_filename.toLowerCase().includes(query)) return true;
    return g.files.some(f => (f.abs_path && f.abs_path.toLowerCase().includes(query)) || (f.filename && f.filename.toLowerCase().includes(query)));
  });

  if (filteredSets.length === 0) {
    container.innerHTML = '<p style="color:var(--text-muted); padding:20px; text-align:center;">No duplicates match your filter criteria.</p>';
    return;
  }

  // 2. Render either Folder Groups or Flat List
  if (groupMode === 'folder') {
    const folderGroups = {};
    filteredSets.forEach((g, idx) => {
      let key = g.folder_pair_key;
      let label = g.folder_pair_label;
      let paths = g.folder_paths;

      if (!key) {
        paths = Array.from(new Set(g.files.map(f => {
          if (f.folder_path) return f.folder_path;
          return f.abs_path ? f.abs_path.replace(/[/\\][^/\\]+$/, '') : 'Folder';
        }))).sort();
        key = paths.join(' ::: ');
        const names = paths.map(p => p.split(/[/\\]/).pop() || p);
        label = names.length === 1 ? `${names[0]} (Internal Folder Copies)` : names.join(' ⟷ ');
      }

      if (!folderGroups[key]) {
        folderGroups[key] = {
          key: key,
          label: label,
          folderPaths: paths || [],
          sets: [],
          totalSavings: 0,
          totalCopies: 0
        };
      }
      folderGroups[key].sets.push({ group: g, origIndex: idx });
      folderGroups[key].totalSavings += (g.potential_savings_bytes || 0);
      folderGroups[key].totalCopies += (g.count || g.files.length);
    });

    const sortedGroups = Object.values(folderGroups).sort((a, b) => b.totalSavings - a.totalSavings);

    sortedGroups.forEach(fg => {
      const groupWrapper = document.createElement('div');
      groupWrapper.className = 'dupe-folder-group-wrapper';
      groupWrapper.style.background = 'rgba(15, 23, 42, 0.4)';
      groupWrapper.style.border = '1px solid rgba(6, 182, 212, 0.25)';
      groupWrapper.style.borderRadius = '10px';
      groupWrapper.style.marginBottom = '20px';
      groupWrapper.style.padding = '14px 16px';

      // Header actions
      let batchButtonsHtml = '';
      if (fg.folderPaths.length === 2) {
        const name0 = fg.folderPaths[0].split(/[/\\]/).pop() || fg.folderPaths[0];
        const name1 = fg.folderPaths[1].split(/[/\\]/).pop() || fg.folderPaths[1];
        batchButtonsHtml += `<button class="btn btn-secondary btn-xs btn-group-pick-folder" data-folder="${escapeHtml(fg.folderPaths[1])}" style="font-size:11px; padding:3px 8px;" title="Select all duplicates in ${escapeHtml(name1)}">Check all in "${escapeHtml(name1)}"</button>`;
        batchButtonsHtml += `<button class="btn btn-secondary btn-xs btn-group-pick-folder" data-folder="${escapeHtml(fg.folderPaths[0])}" style="font-size:11px; padding:3px 8px;" title="Select all duplicates in ${escapeHtml(name0)}">Check all in "${escapeHtml(name0)}"</button>`;
      }
      batchButtonsHtml += `<button class="btn btn-secondary btn-xs btn-group-uncheck-all" style="font-size:11px; padding:3px 8px;">Deselect Folder</button>`;
      batchButtonsHtml += `<button class="btn btn-secondary btn-xs btn-group-omit-pair" data-pair-key="${escapeHtml(fg.key)}" style="font-size:11px; padding:3px 8px; color:var(--accent-rose);" title="Omit this folder pair from duplicates (e.g. intentional picks or mirrors)">🚫 Omit this Pair</button>`;

      const headerDiv = document.createElement('div');
      headerDiv.style.display = 'flex';
      headerDiv.style.justifyContent = 'space-between';
      headerDiv.style.alignItems = 'flex-start';
      headerDiv.style.flexWrap = 'wrap';
      headerDiv.style.gap = '10px';
      headerDiv.style.marginBottom = '14px';
      headerDiv.style.borderBottom = '1px solid rgba(255, 255, 255, 0.06)';
      headerDiv.style.paddingBottom = '10px';

      headerDiv.innerHTML = `
        <div>
          <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
            <span style="font-size:16px;">📁</span>
            <span style="font-size:14px; font-weight:700; color:var(--accent-cyan);">${escapeHtml(fg.label)}</span>
            <span class="brand-badge" style="font-size:11px;">${fg.sets.length} duplicate sets</span>
            <span style="color:var(--accent-amber); font-size:12px; font-weight:600;">Reclaimable: ${formatBytes(fg.totalSavings)}</span>
          </div>
          <div style="font-size:11px; color:var(--text-muted); font-family:monospace; margin-top:4px;">
            ${escapeHtml(fg.folderPaths.join('  ⟷  '))}
          </div>
        </div>
        <div style="display:flex; gap:6px; flex-wrap:wrap;">
          ${batchButtonsHtml}
        </div>
      `;

      groupWrapper.appendChild(headerDiv);

      fg.sets.forEach(item => {
        const setCard = createDuplicateSetCard(item.group, item.origIndex);
        groupWrapper.appendChild(setCard);
      });

      groupWrapper.querySelectorAll('.btn-group-pick-folder').forEach(btn => {
        btn.addEventListener('click', () => {
          const targetFolder = (btn.dataset.folder || '').toLowerCase();
          let picked = 0;
          groupWrapper.querySelectorAll('.dupe-file-row').forEach(row => {
            const p = (row.dataset.path || '').toLowerCase();
            const chk = row.querySelector('.chk-dupe-item');
            if (chk) {
              if (p.startsWith(targetFolder)) {
                chk.checked = true;
                picked++;
              } else {
                chk.checked = false;
              }
            }
          });
          showToast(`Checked ${picked} copies in ${btn.innerText.replace('Check all in ', '')}`, 'info');
        });
      });

      groupWrapper.querySelectorAll('.btn-group-uncheck-all').forEach(btn => {
        btn.addEventListener('click', () => {
          groupWrapper.querySelectorAll('.chk-dupe-item').forEach(chk => {
            chk.checked = false;
          });
          showToast('Deselected this folder group.', 'info');
        });
      });

      groupWrapper.querySelectorAll('.btn-group-omit-pair').forEach(btn => {
        btn.addEventListener('click', async () => {
          const pairKey = btn.dataset.pairKey;
          if (!pairKey) return;
          try {
            const res = await fetch(API_BASE + '/api/duplicates/omit_pair', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ pair_key: pairKey })
            });
            if (res.ok) {
              showToast('Folder pair omitted from duplicates view.', 'info');
              await updateIgnoredDupesBadge();
              await loadDuplicates();
            }
          } catch (e) {
            showToast('Failed to omit pair: ' + e, 'error');
          }
        });
      });

      container.appendChild(groupWrapper);
    });
  } else {
    // Flat List
    filteredSets.forEach((group, idx) => {
      const card = createDuplicateSetCard(group, idx);
      container.appendChild(card);
    });
  }
}

async function loadDuplicates() {
  const crossOnly = document.getElementById('chk-cross-source').checked;
  const sameNameOnly = document.getElementById('chk-same-filename') ? document.getElementById('chk-same-filename').checked : true;
  const container = document.getElementById('duplicates-container');
  container.innerHTML = '<p style="color:var(--text-muted); padding:20px; text-align:center;">Scanning duplicate clusters...</p>';

  updateIgnoredDupesBadge();

  try {
    const res = await fetch(API_BASE + '/api/duplicates?cross_source_only=' + crossOnly + '&same_name_only=' + sameNameOnly);
    duplicatesData = await res.json();
    selectedDupeIds.clear();
    renderDuplicates();
  } catch (err) {
    container.innerHTML = '<p style="color:var(--accent-rose); padding:20px;">Failed to load duplicates: ' + err + '</p>';
  }
}

document.getElementById('chk-cross-source').addEventListener('change', loadDuplicates);
const chkSameNameEl = document.getElementById('chk-same-filename');
if (chkSameNameEl) {
  chkSameNameEl.addEventListener('change', loadDuplicates);
}

const selDupeGroupMode = document.getElementById('sel-dupe-group-mode');
if (selDupeGroupMode) {
  selDupeGroupMode.addEventListener('change', () => {
    renderDuplicates();
  });
}

const txtDupeFilter = document.getElementById('txt-dupe-filter');
if (txtDupeFilter) {
  txtDupeFilter.addEventListener('input', () => {
    clearTimeout(dupeFilterDebounce);
    dupeFilterDebounce = setTimeout(() => {
      renderDuplicates();
    }, 180);
  });
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
    showToast('Auto-selected ' + count + ' exact redundant copies.', 'info');
  });
}

const btnDupeSelectNone = document.getElementById('btn-dupe-select-none');
if (btnDupeSelectNone) {
  btnDupeSelectNone.addEventListener('click', () => {
    document.querySelectorAll('.chk-dupe-item').forEach(chk => {
      chk.checked = false;
    });
    showToast('Cleared all duplicate selections.', 'info');
  });
}

async function updateIgnoredDupesBadge() {
  try {
    const res = await fetch(API_BASE + '/api/duplicates/ignored');
    if (res.ok) {
      const data = await res.json();
      const countEl = document.getElementById('lbl-ignored-dupe-count');
      if (countEl) countEl.innerText = (data.ignored_pairs || []).length;
    }
  } catch (e) {}
}

async function openIgnoredDupesModal() {
  const modal = document.getElementById('modal-ignored-dupes');
  const listEl = document.getElementById('ignored-dupes-list');
  if (!modal || !listEl) return;

  listEl.innerHTML = '<p style="color:var(--text-muted); font-size:12px;">Loading omitted pairs...</p>';
  modal.classList.add('active');

  try {
    const res = await fetch(API_BASE + '/api/duplicates/ignored');
    const data = await res.json();
    const pairs = data.ignored_pairs || [];
    if (pairs.length === 0) {
      listEl.innerHTML = '<p style="color:var(--text-muted); font-size:12px; padding:12px 0;">No folder pairs are currently omitted.</p>';
      return;
    }

    listEl.innerHTML = '';
    pairs.forEach(pairKey => {
      const row = document.createElement('div');
      row.style.display = 'flex';
      row.style.justifyContent = 'space-between';
      row.style.alignItems = 'center';
      row.style.background = 'rgba(255, 255, 255, 0.04)';
      row.style.padding = '8px 12px';
      row.style.borderRadius = '6px';
      row.style.gap = '12px';

      const label = pairKey.replace(/ ::: /g, '  ⟷  ');
      row.innerHTML = `
        <span style="font-family:monospace; font-size:12px; color:var(--text-main); word-break:break-all;">${escapeHtml(label)}</span>
        <button class="btn btn-secondary btn-xs btn-restore-ignored-pair" data-pair-key="${escapeHtml(pairKey)}" style="font-size:11px; white-space:nowrap;">Restore</button>
      `;
      listEl.appendChild(row);
    });

    listEl.querySelectorAll('.btn-restore-ignored-pair').forEach(btn => {
      btn.addEventListener('click', async () => {
        const pk = btn.dataset.pairKey;
        try {
          const r = await fetch(API_BASE + '/api/duplicates/restore_pair', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pair_key: pk })
          });
          if (r.ok) {
            showToast('Restored folder pair to duplicates.', 'success');
            await updateIgnoredDupesBadge();
            openIgnoredDupesModal();
            loadDuplicates();
          }
        } catch (e) {
          showToast('Failed to restore pair: ' + e, 'error');
        }
      });
    });
  } catch (err) {
    listEl.innerHTML = '<p style="color:var(--accent-rose); font-size:12px;">Failed to load omitted pairs.</p>';
  }
}

const btnManageIgnoredDupes = document.getElementById('btn-manage-ignored-dupes');
if (btnManageIgnoredDupes) {
  btnManageIgnoredDupes.addEventListener('click', openIgnoredDupesModal);
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

window.filterTranscodeByFolder = function(folderName) {
  const searchInput = document.getElementById('txt-transcode-search');
  if (searchInput) {
    searchInput.value = folderName;
    loadTranscoder();
  }
};

async function loadTranscoder() {
  try {
    // Ensure sourcesData is loaded
    if (!sourcesData || sourcesData.length === 0) {
      try {
        const sRes = await fetch(API_BASE + '/api/sources');
        sourcesData = await sRes.json();
      } catch (e) {
        console.error('Failed to load sources for transcoder:', e);
      }
    }

    // Always keep drive/folder selector in sync with latest sourcesData
    const selDrive = document.getElementById('sel-transcode-drive');
    if (selDrive && sourcesData && sourcesData.length > 0) {
      const prevVal = selDrive.value;
      const newHtml = '<option value="">All Drives & Folders</option>' + sourcesData.map(s => {
        const pathSuffix = s.path && s.path !== s.label ? ' (' + s.path + ')' : '';
        return '<option value="' + s.id + '">' + escapeHtml(s.label + pathSuffix) + '</option>';
      }).join('');

      if (selDrive.innerHTML !== newHtml) {
        selDrive.innerHTML = newHtml;
        if (prevVal) {
          selDrive.value = prevVal;
        }
      }
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
          +   '<div class="folder-cell" title="Click to filter by folder: ' + escapeHtml(folderName) + '" onclick="filterTranscodeByFolder(\'' + escapeJs(folderName) + '\')" style="cursor:pointer;">'
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
    alert('Please choose two different directories to compare (Primary Working Directory vs Backup Directory)!');
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
      syncedContainer.innerHTML = '<p style="color:var(--text-muted); font-size:13px;">No matching verified backups found in Backup Directory.</p>';
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
      unbackedContainer.innerHTML = '<p style="color:var(--accent-emerald); font-size:13px;">All files in Primary Working Directory are safely backed up!</p>';
    } else {
      syncMatrixData.unbacked_up.forEach(f => {
        unbackedContainer.innerHTML += '<div style="font-size:12px; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.05); display:flex; justify-content:space-between;">'
          + '<span style="color:var(--accent-rose);">⚠️ ' + f.filename + '</span>'
          + '<span style="color:var(--text-muted);">' + formatBytes(f.size_bytes) + '</span>'
          + '</div>';
      });
    }
  } catch (e) {
    alert('Failed to compare directories: ' + e);
  }
});

document.getElementById('btn-reclaim-safe-ssd').addEventListener('click', async () => {
  if (!syncMatrixData || syncMatrixData.synced_safe.length === 0) {
    alert('No verified safe files to reclaim. Compare directories first!');
    return;
  }

  const count = syncMatrixData.synced_safe.length;
  const size = formatBytes(syncMatrixData.safe_reclaimable_bytes);

  if (!confirm('Reclaim ' + size + ' in your Primary Working Directory by recycling ' + count + ' files that are cryptographically verified in your Backup Directory? (XMP sidecars will be safely handled)')) return;

  try {
    const fileIds = syncMatrixData.synced_safe.map(f => f.id);
    const res = await fetch(API_BASE + '/api/sync/reclaim', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fileIds)
    });
    const result = await res.json();
    alert('Successfully reclaimed space! Recycled ' + result.reclaimed_count + ' files from Primary Working Directory.');
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
    showToast('Please provide both a directory path and a label!', 'error');
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
    const res = await fetch(API_BASE + '/api/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: path, label: label, drive_type: type, excluded_paths: excluded })
    });
    const resData = await res.json();
    if (!res.ok) {
      showToast(resData.detail || 'Failed to add source', 'error');
      return;
    }
    modalAddSource.classList.remove('active');
    if (resData.status === 'alias_linked') {
      showToast(resData.message || 'Volume recognized! Linked as alternate mount path.', 'success');
    } else {
      showToast(`Source "${label}" registered! Scan started.`, 'success');
    }
    loadOverview();
    loadSources();

    if (resData.id) {
      window.scanSource(resData.id);
    }
  } catch (e) {
    showToast('Failed to add source: ' + e, 'error');
  }
});

// Edit Source Details Save Handler
const btnConfirmSaveSourceLabel = document.getElementById('btn-confirm-save-source-label');
if (btnConfirmSaveSourceLabel) {
  btnConfirmSaveSourceLabel.addEventListener('click', async () => {
    const sourceId = document.getElementById('edit-source-id').value;
    const newLabel = document.getElementById('edit-source-label-input').value.trim();
    const newType = document.getElementById('edit-source-type-select').value;

    if (!newLabel) {
      showToast('Please enter a valid label.', 'error');
      return;
    }

    try {
      const res = await fetch(API_BASE + '/api/sources/' + sourceId, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label: newLabel, drive_type: newType })
      });
      const data = await res.json();
      if (!res.ok) {
        showToast(data.detail || 'Failed to update label', 'error');
        return;
      }
      const modal = document.getElementById('modal-edit-source');
      if (modal) modal.classList.remove('active');
      showToast('Updated: "' + newLabel + '"', 'success');
      loadSources();
      loadOverview();
    } catch (e) {
      showToast('Error updating source: ' + e, 'error');
    }
  });

  const txtEditLabel = document.getElementById('edit-source-label-input');
  if (txtEditLabel) {
    txtEditLabel.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        btnConfirmSaveSourceLabel.click();
      }
    });
  }
}

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

// ============================================================================
// 8. CLIENT PROOFING, BULK WATERMARKING & SELECTS PICKER
// ============================================================================

let proofingPhotos = [];
let selectedProofingPaths = new Set();
let activePreviewPhotoPath = null;
let watermarkBatchInterval = null;
let previewDebounceTimer = null;
let lastGeneratedContactSheetHtml = null;
let lastResolvedSelects = null;

// Subview Pills Switching
const pillWatermark = document.getElementById('pill-watermark');
const pillContact = document.getElementById('pill-contact');
const pillSelects = document.getElementById('pill-selects');

const subviewWatermark = document.getElementById('subview-watermark');
const subviewContact = document.getElementById('subview-contact');
const subviewSelects = document.getElementById('subview-selects');

let currentProofingSubview = 'watermark';

function switchProofingSubview(viewName) {
  currentProofingSubview = viewName;
  if (pillWatermark) pillWatermark.className = 'btn btn-sm ' + (viewName === 'watermark' ? 'btn-primary' : 'btn-secondary');
  if (pillContact) pillContact.className = 'btn btn-sm ' + (viewName === 'contact' ? 'btn-primary' : 'btn-secondary');
  if (pillSelects) pillSelects.className = 'btn btn-sm ' + (viewName === 'selects' ? 'btn-primary' : 'btn-secondary');

  if (subviewWatermark) subviewWatermark.style.display = (viewName === 'watermark' ? 'block' : 'none');
  if (subviewContact) subviewContact.style.display = (viewName === 'contact' ? 'block' : 'none');
  if (subviewSelects) subviewSelects.style.display = (viewName === 'selects' ? 'block' : 'none');

  if (viewName === 'contact') {
    const summaryEl = document.getElementById('lbl-contact-photos-summary');
    if (summaryEl) {
      const count = selectedProofingPaths.size > 0 ? selectedProofingPaths.size : proofingPhotos.length;
      summaryEl.innerText = `${count} photos ready to generate contact sheet`;
    }
  }

  if (typeof debouncedSaveSessionState === 'function') {
    debouncedSaveSessionState({ last_proofing_subview: viewName });
  }
}

if (pillWatermark) pillWatermark.addEventListener('click', () => switchProofingSubview('watermark'));
if (pillContact) pillContact.addEventListener('click', () => switchProofingSubview('contact'));
if (pillSelects) pillSelects.addEventListener('click', () => switchProofingSubview('selects'));

// Mode Switcher (Text vs Logo vs Both)
const selWatermarkMode = document.getElementById('sel-watermark-mode');
const boxWatermarkText = document.getElementById('box-watermark-text');
const boxWatermarkLogo = document.getElementById('box-watermark-logo');

if (selWatermarkMode) {
  selWatermarkMode.addEventListener('change', () => {
    const val = selWatermarkMode.value;
    if (boxWatermarkText) boxWatermarkText.style.display = (val === 'text' || val === 'both') ? 'flex' : 'none';
    if (boxWatermarkLogo) boxWatermarkLogo.style.display = (val === 'logo' || val === 'both') ? 'flex' : 'none';
    debouncedTriggerPreview();
  });
}

// Sliders live values
const rngOpacity = document.getElementById('rng-watermark-opacity');
const lblValOpacity = document.getElementById('lbl-val-opacity');
if (rngOpacity && lblValOpacity) {
  rngOpacity.addEventListener('input', () => {
    lblValOpacity.innerText = rngOpacity.value + '%';
    debouncedTriggerPreview();
  });
}

const rngFontScale = document.getElementById('rng-watermark-fontscale');
const lblValFontScale = document.getElementById('lbl-val-fontscale');
if (rngFontScale && lblValFontScale) {
  rngFontScale.addEventListener('input', () => {
    lblValFontScale.innerText = rngFontScale.value + '%';
    debouncedTriggerPreview();
  });
}

const rngQuality = document.getElementById('rng-watermark-quality');
const lblValQuality = document.getElementById('lbl-val-quality');
if (rngQuality && lblValQuality) {
  rngQuality.addEventListener('input', () => {
    lblValQuality.innerText = rngQuality.value + '%';
  });
}

// Long Edge Resolution Slider & Preset Buttons
const rngRes = document.getElementById('rng-watermark-res');
const lblValRes = document.getElementById('lbl-val-res');
const chkOrigRes = document.getElementById('chk-watermark-orig-res');
const hiddenRes = document.getElementById('sel-watermark-res');
const resPresetButtons = document.querySelectorAll('.btn-res-preset');

function getResLabelText(val) {
  val = parseInt(val);
  if (val === 1080) return '1080 px (Social / HD)';
  if (val === 1200) return '1200 px (Compact Proof)';
  if (val === 1600) return '1600 px (Medium Proof)';
  if (val === 1920) return '1920 px (Full HD)';
  if (val === 2048) return '2048 px (Standard Web Proof)';
  if (val === 2560) return '2560 px (2K QHD)';
  if (val === 3840) return '3840 px (4K UHD)';
  return `${val} px`;
}

function updateResUI(val, isOriginal = false) {
  if (isOriginal) {
    if (chkOrigRes) chkOrigRes.checked = true;
    if (rngRes) rngRes.disabled = true;
    if (lblValRes) lblValRes.innerText = 'Original Resolution (No Downscale)';
    if (hiddenRes) hiddenRes.value = '0';
    resPresetButtons.forEach(b => b.className = 'btn btn-secondary btn-sm btn-res-preset');
  } else {
    val = parseInt(val) || 2048;
    if (chkOrigRes) chkOrigRes.checked = false;
    if (rngRes) {
      rngRes.disabled = false;
      rngRes.value = val;
    }
    if (lblValRes) lblValRes.innerText = getResLabelText(val);
    if (hiddenRes) hiddenRes.value = val.toString();

    resPresetButtons.forEach(b => {
      const bVal = parseInt(b.dataset.res);
      b.className = (bVal === val)
        ? 'btn btn-primary btn-sm btn-res-preset'
        : 'btn btn-secondary btn-sm btn-res-preset';
    });
  }
}

if (rngRes) {
  rngRes.addEventListener('input', () => {
    updateResUI(rngRes.value, false);
  });
}

if (chkOrigRes) {
  chkOrigRes.addEventListener('change', () => {
    if (chkOrigRes.checked) {
      updateResUI(0, true);
    } else {
      updateResUI(rngRes ? rngRes.value : 2048, false);
    }
  });
}

resPresetButtons.forEach(btn => {
  btn.addEventListener('click', () => {
    const r = btn.dataset.res;
    updateResUI(r, false);
  });
});

const rngLogoOpacity = document.getElementById('rng-watermark-logo-opacity');
const lblValLogoOpacity = document.getElementById('lbl-val-logo-opacity');
if (rngLogoOpacity && lblValLogoOpacity) {
  rngLogoOpacity.addEventListener('input', () => {
    lblValLogoOpacity.innerText = rngLogoOpacity.value + '%';
    debouncedTriggerPreview();
  });
}

const rngLogoScale = document.getElementById('rng-watermark-logo-scale');
const lblValLogoScale = document.getElementById('lbl-val-logo-scale');
if (rngLogoScale && lblValLogoScale) {
  rngLogoScale.addEventListener('input', () => {
    lblValLogoScale.innerText = rngLogoScale.value + '%';
    debouncedTriggerPreview();
  });
}

// Preview change triggers
['txt-watermark-string', 'sel-watermark-pos', 'col-watermark-color', 'chk-watermark-shadow', 'sel-watermark-logo-pos'].forEach(id => {
  const el = document.getElementById(id);
  if (el) {
    el.addEventListener('input', () => debouncedTriggerPreview());
    el.addEventListener('change', () => debouncedTriggerPreview());
  }
});

function debouncedTriggerPreview() {
  clearTimeout(previewDebounceTimer);
  previewDebounceTimer = setTimeout(() => {
    triggerWatermarkPreview();
  }, 320);
}

// ============================================================================
// WATERMARK PRESETS ENGINE
// ============================================================================
let watermarkPresets = [];
let activePresetId = null;

const selWatermarkPreset = document.getElementById('sel-watermark-preset');
const btnPresetSaveNew = document.getElementById('btn-preset-save-new');
const btnPresetUpdate = document.getElementById('btn-preset-update');
const btnPresetDelete = document.getElementById('btn-preset-delete');
const modalSavePreset = document.getElementById('modal-save-preset');
const txtPresetNameInput = document.getElementById('txt-preset-name-input');
const btnModalConfirmSavePreset = document.getElementById('btn-modal-confirm-save-preset');

function collectCurrentPresetConfig() {
  const mode = document.getElementById('sel-watermark-mode')?.value || 'text';
  const textStr = document.getElementById('txt-watermark-string')?.value || 'PROOF ONLY';
  const pos = document.getElementById('sel-watermark-pos')?.value || 'diagonal_grid';
  const opacity = (parseFloat(document.getElementById('rng-watermark-opacity')?.value || '35')) / 100;
  const fontScale = (parseFloat(document.getElementById('rng-watermark-fontscale')?.value || '4')) / 100;
  const colorHex = document.getElementById('col-watermark-color')?.value || '#FFFFFF';
  const shadow = !!document.getElementById('chk-watermark-shadow')?.checked;

  const logoPath = document.getElementById('txt-watermark-logo-path')?.value || '';
  const logoPos = document.getElementById('sel-watermark-logo-pos')?.value || 'bottom-right';
  const logoOpacity = (parseFloat(document.getElementById('rng-watermark-logo-opacity')?.value || '80')) / 100;
  const logoScale = (parseFloat(document.getElementById('rng-watermark-logo-scale')?.value || '18')) / 100;

  const maxDim = parseInt(document.getElementById('sel-watermark-res')?.value || '2048');
  const isOrigRes = !!document.getElementById('chk-watermark-orig-res')?.checked;
  const quality = parseInt(document.getElementById('rng-watermark-quality')?.value || '80');

  const outMode = document.getElementById('sel-watermark-out-mode')?.value || 'original_subfolder';
  const subfolderType = document.getElementById('sel-watermark-subfolder-type')?.value || 'suffix';
  const subfolderName = document.getElementById('txt-watermark-subfolder-name')?.value.trim() || '_proofs';
  const suffix = document.getElementById('txt-watermark-suffix')?.value || '_proof';

  return {
    watermark_type: mode,
    text: textStr,
    position: pos,
    opacity: opacity,
    font_scale: fontScale,
    color_hex: colorHex,
    shadow: shadow,
    logo_path: logoPath,
    logo_position: logoPos,
    logo_opacity: logoOpacity,
    logo_scale: logoScale,
    max_dimension: isOrigRes ? 0 : maxDim,
    is_original_res: isOrigRes,
    quality: quality,
    output_mode: outMode,
    subfolder_type: subfolderType,
    subfolder_name: subfolderName,
    suffix: suffix
  };
}

async function loadWatermarkPresets(targetPresetIdToSelect = null) {
  try {
    const res = await fetch(API_BASE + '/api/proofing/presets');
    if (!res.ok) return;
    const data = await res.json();
    watermarkPresets = data.presets || [];

    if (!selWatermarkPreset) return;
    selWatermarkPreset.innerHTML = '';

    const builtins = watermarkPresets.filter(p => p.is_builtin);
    const customs = watermarkPresets.filter(p => !p.is_builtin);

    if (builtins.length > 0) {
      const grpBuiltin = document.createElement('optgroup');
      grpBuiltin.label = '✨ Built-in Presets';
      builtins.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.innerText = p.name;
        grpBuiltin.appendChild(opt);
      });
      selWatermarkPreset.appendChild(grpBuiltin);
    }

    if (customs.length > 0) {
      const grpCustom = document.createElement('optgroup');
      grpCustom.label = '👤 Custom Saved Presets';
      customs.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.innerText = p.name;
        grpCustom.appendChild(opt);
      });
      selWatermarkPreset.appendChild(grpCustom);
    }

    const selectId = targetPresetIdToSelect || activePresetId || watermarkPresets[0]?.id;
    if (selectId && watermarkPresets.some(p => p.id === selectId)) {
      selWatermarkPreset.value = selectId;
      activePresetId = selectId;
    } else if (watermarkPresets.length > 0) {
      selWatermarkPreset.value = watermarkPresets[0].id;
      activePresetId = watermarkPresets[0].id;
    }

    updatePresetButtonsUI();
  } catch (e) {
    console.error('Failed to load presets:', e);
  }
}

function updatePresetButtonsUI() {
  const curPreset = watermarkPresets.find(p => p.id === activePresetId);
  const isCustom = curPreset && !curPreset.is_builtin;

  if (btnPresetUpdate) btnPresetUpdate.style.display = isCustom ? 'inline-block' : 'none';
  if (btnPresetDelete) btnPresetDelete.style.display = isCustom ? 'inline-block' : 'none';
}

function applyWatermarkPreset(preset, notify = true) {
  if (!preset || !preset.config) return;
  const cfg = preset.config;
  activePresetId = preset.id;

  // 1. Watermark Mode
  const mode = cfg.watermark_type || 'text';
  if (selWatermarkMode) {
    selWatermarkMode.value = mode;
    if (boxWatermarkText) boxWatermarkText.style.display = (mode === 'text' || mode === 'both') ? 'flex' : 'none';
    if (boxWatermarkLogo) boxWatermarkLogo.style.display = (mode === 'logo' || mode === 'both') ? 'flex' : 'none';
  }

  // 2. Text Watermark Settings
  if (cfg.text !== undefined && document.getElementById('txt-watermark-string')) {
    document.getElementById('txt-watermark-string').value = cfg.text;
  }
  if (cfg.position && document.getElementById('sel-watermark-pos')) {
    document.getElementById('sel-watermark-pos').value = cfg.position;
  }
  if (cfg.opacity !== undefined && rngOpacity && lblValOpacity) {
    const opVal = cfg.opacity <= 1.0 ? Math.round(cfg.opacity * 100) : cfg.opacity;
    rngOpacity.value = opVal;
    lblValOpacity.innerText = opVal + '%';
  }
  if (cfg.font_scale !== undefined && rngFontScale && lblValFontScale) {
    const fsVal = cfg.font_scale <= 0.2 ? Math.round(cfg.font_scale * 100) : cfg.font_scale;
    rngFontScale.value = fsVal;
    lblValFontScale.innerText = fsVal + '%';
  }
  if (cfg.color_hex && document.getElementById('col-watermark-color')) {
    document.getElementById('col-watermark-color').value = cfg.color_hex;
  }
  if (cfg.shadow !== undefined && document.getElementById('chk-watermark-shadow')) {
    document.getElementById('chk-watermark-shadow').checked = !!cfg.shadow;
  }

  // 3. Logo Watermark Settings
  if (cfg.logo_path !== undefined && document.getElementById('txt-watermark-logo-path')) {
    document.getElementById('txt-watermark-logo-path').value = cfg.logo_path;
  }
  if (cfg.logo_position && document.getElementById('sel-watermark-logo-pos')) {
    document.getElementById('sel-watermark-logo-pos').value = cfg.logo_position;
  }
  if (cfg.logo_opacity !== undefined && rngLogoOpacity && lblValLogoOpacity) {
    const lopVal = cfg.logo_opacity <= 1.0 ? Math.round(cfg.logo_opacity * 100) : cfg.logo_opacity;
    rngLogoOpacity.value = lopVal;
    lblValLogoOpacity.innerText = lopVal + '%';
  }
  if (cfg.logo_scale !== undefined && rngLogoScale && lblValLogoScale) {
    const lscVal = cfg.logo_scale <= 1.0 ? Math.round(cfg.logo_scale * 100) : cfg.logo_scale;
    rngLogoScale.value = lscVal;
    lblValLogoScale.innerText = lscVal + '%';
  }

  // 4. Resolution & Quality
  const isOrig = !!cfg.is_original_res;
  const resVal = cfg.max_dimension > 0 ? cfg.max_dimension : 2048;
  updateResUI(resVal, isOrig);

  if (cfg.quality !== undefined && rngQuality && lblValQuality) {
    rngQuality.value = cfg.quality;
    lblValQuality.innerText = cfg.quality + '%';
  }

  // 5. Destination & Subfolder
  if (cfg.output_mode && selWatermarkOutMode) {
    selWatermarkOutMode.value = cfg.output_mode;
  }
  if (cfg.subfolder_type && selWatermarkSubfolderType) {
    selWatermarkSubfolderType.value = cfg.subfolder_type;
  }
  if (cfg.subfolder_name && txtSubfolderName) {
    txtSubfolderName.value = cfg.subfolder_name;
  }
  if (cfg.suffix && document.getElementById('txt-watermark-suffix')) {
    document.getElementById('txt-watermark-suffix').value = cfg.suffix;
  }

  updateDestModeUI();
  updatePresetButtonsUI();
  debouncedTriggerPreview();

  if (typeof debouncedSaveSessionState === 'function') {
    debouncedSaveSessionState({ watermark_settings: { active_preset_id: preset.id } });
  }

  if (notify) {
    showToast(`Applied preset: ${preset.name}`, 'info');
  }
}

if (selWatermarkPreset) {
  selWatermarkPreset.addEventListener('change', () => {
    const pId = selWatermarkPreset.value;
    const found = watermarkPresets.find(p => p.id === pId);
    if (found) {
      applyWatermarkPreset(found, true);
    }
  });
}

if (btnPresetSaveNew) {
  btnPresetSaveNew.addEventListener('click', () => {
    if (modalSavePreset) {
      if (txtPresetNameInput) {
        txtPresetNameInput.value = 'My Custom Preset';
      }
      modalSavePreset.classList.add('active');
      setTimeout(() => txtPresetNameInput?.focus(), 150);
    }
  });
}

if (btnModalConfirmSavePreset) {
  btnModalConfirmSavePreset.addEventListener('click', async () => {
    const name = txtPresetNameInput?.value.trim() || 'Custom Preset';
    const config = collectCurrentPresetConfig();

    try {
      const res = await fetch(API_BASE + '/api/proofing/presets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, config: config })
      });
      if (res.ok) {
        const saved = await res.json();
        modalSavePreset?.classList.remove('active');
        await loadWatermarkPresets(saved.id);
        showToast(`Preset "${saved.name}" saved!`, 'success');
      } else {
        const err = await res.json().catch(() => ({}));
        showToast('Error saving preset: ' + (err.detail || 'Failed'), 'error');
      }
    } catch (e) {
      console.error(e);
      showToast('Error saving preset: ' + e, 'error');
    }
  });
}

if (btnPresetUpdate) {
  btnPresetUpdate.addEventListener('click', async () => {
    const curPreset = watermarkPresets.find(p => p.id === activePresetId);
    if (!curPreset || curPreset.is_builtin) {
      showToast('Built-in presets cannot be overwritten. Click "+ Save Preset" instead.', 'warning');
      return;
    }

    const config = collectCurrentPresetConfig();
    try {
      const res = await fetch(API_BASE + '/api/proofing/presets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: curPreset.id, name: curPreset.name, config: config })
      });
      if (res.ok) {
        const updated = await res.json();
        await loadWatermarkPresets(updated.id);
        showToast(`Updated preset "${updated.name}"!`, 'success');
      } else {
        showToast('Error updating preset', 'error');
      }
    } catch (e) {
      console.error(e);
      showToast('Error updating preset: ' + e, 'error');
    }
  });
}

if (btnPresetDelete) {
  btnPresetDelete.addEventListener('click', async () => {
    const curPreset = watermarkPresets.find(p => p.id === activePresetId);
    if (!curPreset || curPreset.is_builtin) return;

    if (!confirm(`Are you sure you want to delete preset "${curPreset.name}"?`)) return;

    try {
      const res = await fetch(API_BASE + `/api/proofing/presets/${curPreset.id}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        showToast(`Deleted preset "${curPreset.name}"`, 'success');
        await loadWatermarkPresets();
        if (watermarkPresets.length > 0) {
          applyWatermarkPreset(watermarkPresets[0], true);
        }
      } else {
        showToast('Could not delete preset', 'error');
      }
    } catch (e) {
      console.error(e);
      showToast('Error deleting preset: ' + e, 'error');
    }
  });
}

// Native Folder Pickers for Proofing
function setupFolderPicker(btnId, inputId, onSelectedCallback) {
  const btn = document.getElementById(btnId);
  const input = document.getElementById(inputId);
  if (!btn || !input) return;

  btn.addEventListener('click', async () => {
    try {
      const res = await fetch(API_BASE + '/api/utils/pick_folder', { method: 'POST' });
      const data = await res.json();
      if (data.selected && data.path) {
        input.value = data.path;
        if (onSelectedCallback) onSelectedCallback(data.path);
      }
    } catch (e) {
      console.error('Folder picker error:', e);
    }
  });
}

// Native Folder Pickers for Proofing
function setupFolderPicker(btnId, inputId, onSelectedCallback) {
  const btn = document.getElementById(btnId);
  const input = document.getElementById(inputId);
  if (!btn || !input) return;

  btn.addEventListener('click', async () => {
    try {
      const res = await fetch(API_BASE + '/api/utils/pick_folder', { method: 'POST' });
      const data = await res.json();
      if (data.selected && data.path) {
        input.value = data.path;
        if (onSelectedCallback) onSelectedCallback(data.path);
      }
    } catch (e) {
      console.error('Folder picker error:', e);
    }
  });
}

// Multi-folder management state
let customProofingFolders = []; // array of { path: string, label: string, checked: boolean, recursive?: boolean }
let pendingSubfolderSelection = null; // holds { parentPath, parentLabel, subfolders, directCount }

function addFolderToProofingList(pNorm, label, doRenderAndLoad = true, recursive = true) {
  const existing = customProofingFolders.find(f => f.path.toLowerCase() === pNorm.toLowerCase() && f.recursive === recursive);
  if (!existing) {
    customProofingFolders.push({
      path: pNorm,
      label: label,
      checked: true,
      recursive: recursive
    });
    if (doRenderAndLoad) {
      renderCustomFoldersList();
      loadPhotosFromActiveFolders();
      showToast(`Added folder: ${label}`, 'success');
      if (typeof debouncedSaveSessionState === 'function') {
        debouncedSaveSessionState();
      }
    }
    return true;
  }
  return false;
}

const btnAddWatermarkFolder = document.getElementById('btn-browse-watermark-src');
if (btnAddWatermarkFolder) {
  btnAddWatermarkFolder.addEventListener('click', async () => {
    try {
      const res = await fetch(API_BASE + '/api/utils/pick_folder', { method: 'POST' });
      const data = await res.json();
      if (data.selected && data.path) {
        const pNorm = data.path.trim();

        // Check if this folder has subfolders
        try {
          const subRes = await fetch(API_BASE + '/api/utils/list_subfolders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: pNorm, include_counts: true })
          });
          const subData = await subRes.json();
          const subs = subData.subfolders || [];
          const directCount = subData.direct_photo_count || 0;

          if (subs.length === 0) {
            // No subfolders, add directly
            addFolderToProofingList(pNorm, data.label || subData.folder_name || pNorm, true, true);
          } else {
            // Subfolders detected! Prompt user with modal
            openSubfolderPickerModal({
              parentPath: pNorm,
              parentLabel: data.label || subData.folder_name || pNorm,
              subfolders: subs,
              directCount: directCount
            });
          }
        } catch (e) {
          addFolderToProofingList(pNorm, data.label || pNorm, true, true);
        }
      }
    } catch (e) {
      console.error('Folder picker error:', e);
    }
  });
}

function openSubfolderPickerModal(data) {
  pendingSubfolderSelection = data;
  const modal = document.getElementById('modal-proofing-subfolder-picker');
  const lblName = document.getElementById('lbl-proofing-modal-folder-name');
  const lblPath = document.getElementById('lbl-proofing-modal-folder-path');
  const listContainer = document.getElementById('proofing-subfolder-list');

  if (!modal) return;

  if (lblName) lblName.innerText = `📁 ${data.parentLabel}`;
  if (lblPath) lblPath.innerText = data.parentPath;
  if (listContainer) listContainer.innerHTML = '';

  // 1. Direct files in root if any
  if (data.directCount > 0) {
    const rootRow = createSubfolderRowItem({
      path: data.parentPath,
      name: `${data.parentLabel} (Direct Files in Root)`,
      photo_count: data.directCount,
      is_root: true
    });
    listContainer.appendChild(rootRow);
  }

  // 2. Add each subfolder
  data.subfolders.forEach(sub => {
    const subRow = createSubfolderRowItem({
      path: sub.path,
      name: sub.name,
      photo_count: sub.photo_count || 0,
      is_root: false
    });
    listContainer.appendChild(subRow);
  });

  updateCheckedSubsCountButton();
  modal.classList.add('active');
}

function createSubfolderRowItem(item) {
  const row = document.createElement('div');
  row.className = 'proofing-sub-row';
  row.style.display = 'flex';
  row.style.alignItems = 'center';
  row.style.justifyContent = 'space-between';
  row.style.gap = '8px';
  row.style.background = 'rgba(6, 182, 212, 0.1)';
  row.style.border = '1px solid rgba(6, 182, 212, 0.25)';
  row.style.borderRadius = '6px';
  row.style.padding = '6px 10px';
  row.style.cursor = 'pointer';

  const left = document.createElement('label');
  left.style.display = 'flex';
  left.style.alignItems = 'center';
  left.style.gap = '8px';
  left.style.flex = '1';
  left.style.cursor = 'pointer';

  const chk = document.createElement('input');
  chk.type = 'checkbox';
  chk.className = 'chk-proofing-sub-item';
  chk.checked = true;
  chk.dataset.path = item.path;
  chk.dataset.name = item.name;
  chk.dataset.isRoot = item.is_root ? '1' : '0';

  chk.addEventListener('change', () => {
    row.style.background = chk.checked ? 'rgba(6, 182, 212, 0.12)' : 'rgba(255,255,255,0.02)';
    row.style.borderColor = chk.checked ? 'rgba(6, 182, 212, 0.3)' : 'var(--border-color)';
    updateCheckedSubsCountButton();
  });

  const icon = document.createElement('span');
  icon.innerText = item.is_root ? '📂' : '📁';

  const nameSpan = document.createElement('span');
  nameSpan.style.fontSize = '12px';
  nameSpan.style.fontWeight = '600';
  nameSpan.style.color = 'var(--text-main)';
  nameSpan.innerText = item.name;

  left.appendChild(chk);
  left.appendChild(icon);
  left.appendChild(nameSpan);

  const countBadge = document.createElement('span');
  countBadge.className = 'brand-badge';
  countBadge.style.fontSize = '10px';
  countBadge.style.background = item.photo_count > 0 ? 'rgba(16, 185, 129, 0.2)' : 'rgba(255,255,255,0.05)';
  countBadge.style.color = item.photo_count > 0 ? 'var(--accent-emerald)' : 'var(--text-muted)';
  countBadge.innerText = item.photo_count > 0 ? `${item.photo_count} photos` : 'empty';

  row.appendChild(left);
  row.appendChild(countBadge);

  row.addEventListener('click', (e) => {
    if (e.target !== chk) {
      chk.checked = !chk.checked;
      chk.dispatchEvent(new Event('change'));
    }
  });

  return row;
}

function updateCheckedSubsCountButton() {
  const btn = document.getElementById('btn-proofing-add-checked-subs');
  if (!btn) return;
  const checked = document.querySelectorAll('#proofing-subfolder-list .chk-proofing-sub-item:checked');
  btn.innerText = `Add Checked Folders (${checked.length})`;
  btn.disabled = checked.length === 0;
}

const btnAddEntireRecursive = document.getElementById('btn-proofing-add-entire-recursive');
if (btnAddEntireRecursive) {
  btnAddEntireRecursive.addEventListener('click', () => {
    if (!pendingSubfolderSelection) return;
    addFolderToProofingList(
      pendingSubfolderSelection.parentPath,
      `${pendingSubfolderSelection.parentLabel} (All Subfolders)`,
      true,
      true
    );
    document.getElementById('modal-proofing-subfolder-picker')?.classList.remove('active');
  });
}

const btnAddCheckedSubs = document.getElementById('btn-proofing-add-checked-subs');
if (btnAddCheckedSubs) {
  btnAddCheckedSubs.addEventListener('click', () => {
    const checkedBoxes = Array.from(document.querySelectorAll('#proofing-subfolder-list .chk-proofing-sub-item:checked'));
    if (checkedBoxes.length === 0) return;

    let addedCount = 0;
    checkedBoxes.forEach(chk => {
      const p = chk.dataset.path;
      const name = chk.dataset.name;
      const isRoot = chk.dataset.isRoot === '1';
      const added = addFolderToProofingList(p, name, false, !isRoot);
      if (added) addedCount++;
    });

    document.getElementById('modal-proofing-subfolder-picker')?.classList.remove('active');
    renderCustomFoldersList();
    loadPhotosFromActiveFolders();
    showToast(`Added ${addedCount} folder(s) to checklist!`, 'success');
  });
}

const btnProofingSubAll = document.getElementById('btn-proofing-sub-all');
if (btnProofingSubAll) {
  btnProofingSubAll.addEventListener('click', () => {
    document.querySelectorAll('#proofing-subfolder-list .chk-proofing-sub-item').forEach(c => {
      c.checked = true;
      c.dispatchEvent(new Event('change'));
    });
  });
}

const btnProofingSubNone = document.getElementById('btn-proofing-sub-none');
if (btnProofingSubNone) {
  btnProofingSubNone.addEventListener('click', () => {
    document.querySelectorAll('#proofing-subfolder-list .chk-proofing-sub-item').forEach(c => {
      c.checked = false;
      c.dispatchEvent(new Event('change'));
    });
  });
}

function renderCustomFoldersList() {
  const container = document.getElementById('box-watermark-folders-list');
  if (!container) return;

  if (customProofingFolders.length === 0) {
    container.innerHTML = '<span style="color:var(--text-muted); font-size:11px; font-style:italic;">No custom folders added yet. Click "+ Add Folder" or choose a drive above.</span>';
    return;
  }

  container.innerHTML = '';
  customProofingFolders.forEach((f, idx) => {
    const row = document.createElement('div');
    row.style.display = 'flex';
    row.style.alignItems = 'center';
    row.style.justifyContent = 'space-between';
    row.style.gap = '6px';
    row.style.background = f.checked ? 'rgba(6, 182, 212, 0.12)' : 'rgba(255, 255, 255, 0.02)';
    row.style.border = f.checked ? '1px solid rgba(6, 182, 212, 0.3)' : '1px solid var(--border-color)';
    row.style.borderRadius = '4px';
    row.style.padding = '3px 6px';
    row.style.fontSize = '11px';

    const left = document.createElement('label');
    left.style.display = 'flex';
    left.style.alignItems = 'center';
    left.style.gap = '6px';
    left.style.flex = '1';
    left.style.cursor = 'pointer';
    left.style.overflow = 'hidden';

    const chk = document.createElement('input');
    chk.type = 'checkbox';
    chk.checked = f.checked;
    chk.addEventListener('change', () => {
      f.checked = chk.checked;
      renderCustomFoldersList();
      loadPhotosFromActiveFolders();
      if (typeof debouncedSaveSessionState === 'function') {
        debouncedSaveSessionState();
      }
    });

    const labelSpan = document.createElement('span');
    labelSpan.style.fontWeight = '600';
    labelSpan.style.color = f.checked ? 'var(--accent-cyan)' : 'var(--text-muted)';
    labelSpan.style.whiteSpace = 'nowrap';
    labelSpan.style.overflow = 'hidden';
    labelSpan.style.textOverflow = 'ellipsis';
    labelSpan.title = f.path;
    const badgeText = f.recursive ? '⚡ ' : '📁 ';
    labelSpan.innerText = `${badgeText}${f.label}`;

    left.appendChild(chk);
    left.appendChild(labelSpan);

    const btnRemove = document.createElement('button');
    btnRemove.type = 'button';
    btnRemove.innerHTML = '&times;';
    btnRemove.title = 'Remove folder from checklist';
    btnRemove.style.background = 'none';
    btnRemove.style.border = 'none';
    btnRemove.style.color = 'var(--text-muted)';
    btnRemove.style.cursor = 'pointer';
    btnRemove.style.fontSize = '14px';
    btnRemove.style.padding = '0 4px';
    btnRemove.addEventListener('click', (e) => {
      e.stopPropagation();
      customProofingFolders.splice(idx, 1);
      renderCustomFoldersList();
      loadPhotosFromActiveFolders();
      if (typeof debouncedSaveSessionState === 'function') {
        debouncedSaveSessionState();
      }
    });

    row.appendChild(left);
    row.appendChild(btnRemove);
    container.appendChild(row);
  });
}

setupFolderPicker('btn-browse-watermark-dest', 'txt-watermark-dest');
setupFolderPicker('btn-browse-contact-dest', 'txt-contact-dest');
setupFolderPicker('btn-browse-selects-src', 'txt-selects-source-dir');
setupFolderPicker('btn-browse-selects-dest', 'txt-selects-dest-dir');

// Native File Picker for PNG Logo (Replaces old text prompt)
const btnBrowseLogo = document.getElementById('btn-browse-logo');
if (btnBrowseLogo) {
  btnBrowseLogo.addEventListener('click', async () => {
    try {
      const res = await fetch(API_BASE + '/api/utils/pick_file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: 'Select PNG Logo / Watermark Image',
          type: 'logo'
        })
      });
      const data = await res.json();
      if (data.selected && data.path) {
        const logoInput = document.getElementById('txt-watermark-logo-path');
        if (logoInput) {
          logoInput.value = data.path;
          debouncedTriggerPreview();
          showToast(`Selected logo: ${data.filename}`, 'success');
        }
      }
    } catch (e) {
      console.error('File picker error:', e);
      showToast('Could not open file picker: ' + e, 'error');
    }
  });
}

// Load Proofing Overview
async function loadProofing() {
  try {
    const sourcesRes = await fetch(API_BASE + '/api/sources').then(r => r.json());
    sourcesData = sourcesRes;

    const selSrc = document.getElementById('sel-watermark-source');
    if (selSrc) {
      const curVal = selSrc.value;
      selSrc.innerHTML = '<option value="">-- Choose Drive or Indexed Folder --</option>';
      sourcesRes.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.id;
        opt.innerText = `${s.label} (${s.file_count || 0} files)`;
        selSrc.appendChild(opt);
      });
      if (curVal) selSrc.value = curVal;
    }

    if (proofingPhotos.length === 0 && customProofingFolders.length === 0 && sourcesRes.length > 0) {
      const firstSrc = sourcesRes[0];
      if (selSrc) selSrc.value = firstSrc.id;
      loadPhotosFromActiveFolders(firstSrc.id);
    }

    if (watermarkPresets.length === 0) {
      loadWatermarkPresets();
    }
  } catch (e) {
    console.error('Failed to load proofing sources:', e);
  }
}

const selWatermarkSrc = document.getElementById('sel-watermark-source');
if (selWatermarkSrc) {
  selWatermarkSrc.addEventListener('change', () => {
    const srcId = selWatermarkSrc.value;
    if (srcId) {
      loadPhotosFromActiveFolders(srcId);
    }
  });
}

// Load photos from checked custom folders or selected drive
async function loadPhotosFromActiveFolders(forceSourceId) {
  const listEl = document.getElementById('watermark-photos-list');
  const countEl = document.getElementById('lbl-watermark-count');
  if (!listEl) return;

  listEl.innerHTML = '<p style="color:var(--text-muted); font-size:12px; text-align:center; padding:20px;">Scanning photos...</p>';
  proofingPhotos = [];
  selectedProofingPaths.clear();

  const activeFolders = customProofingFolders.filter(f => f.checked);
  const sourceId = forceSourceId || document.getElementById('sel-watermark-source')?.value || null;

  try {
    if (activeFolders.length > 0) {
      const res = await fetch(API_BASE + '/api/utils/list_photos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          folder_items: activeFolders.map(f => ({ path: f.path, recursive: f.recursive !== false })),
          paths: activeFolders.map(f => f.path)
        })
      });
      const data = await res.json();
      proofingPhotos = data.photos || [];
    } else if (sourceId) {
      const res = await fetch(API_BASE + `/api/sources/${sourceId}/photos`).then(r => r.json());
      proofingPhotos = res.photos || [];
    }

    renderWatermarkPhotoList();

    if (countEl) countEl.innerText = `${proofingPhotos.length} photos found`;

    // Automatically set sample for preview
    if (proofingPhotos.length > 0) {
      activePreviewPhotoPath = proofingPhotos[0].abs_path;
      proofingPhotos.forEach(p => selectedProofingPaths.add(p.abs_path));
      updateWatermarkSelectCounts();
      triggerWatermarkPreview();
    }
  } catch (err) {
    listEl.innerHTML = `<p style="color:var(--accent-rose); font-size:12px; padding:10px;">Failed to load photos: ${err}</p>`;
  }
}

function renderWatermarkPhotoList() {
  const listEl = document.getElementById('watermark-photos-list');
  const filterVal = (document.getElementById('txt-watermark-filter')?.value || '').toLowerCase();
  if (!listEl) return;

  listEl.innerHTML = '';
  if (proofingPhotos.length === 0) {
    listEl.innerHTML = '<p style="color:var(--text-muted); font-size:12px; text-align:center; padding:20px;">No photos found in this source.</p>';
    return;
  }

  const fragment = document.createDocumentFragment();

  proofingPhotos.forEach(item => {
    if (filterVal && !item.filename.toLowerCase().includes(filterVal)) {
      return;
    }

    const row = document.createElement('div');
    const isChecked = selectedProofingPaths.has(item.abs_path);
    const isPreviewing = (activePreviewPhotoPath === item.abs_path);

    row.style.display = 'flex';
    row.style.alignItems = 'center';
    row.style.gap = '8px';
    row.style.padding = '6px 8px';
    row.style.borderRadius = '6px';
    row.style.cursor = 'pointer';
    row.style.background = isPreviewing ? 'rgba(6, 182, 212, 0.15)' : 'rgba(255,255,255,0.02)';
    row.style.border = isPreviewing ? '1px solid var(--accent-cyan)' : '1px solid transparent';
    row.style.transition = 'all 0.15s';

    const chk = document.createElement('input');
    chk.type = 'checkbox';
    chk.checked = isChecked;
    chk.addEventListener('change', (e) => {
      e.stopPropagation();
      if (chk.checked) {
        selectedProofingPaths.add(item.abs_path);
      } else {
        selectedProofingPaths.delete(item.abs_path);
      }
      updateWatermarkSelectCounts();
    });

    const label = document.createElement('div');
    label.style.flex = '1';
    label.style.overflow = 'hidden';
    label.style.textOverflow = 'ellipsis';
    label.style.whiteSpace = 'nowrap';
    label.style.fontSize = '12px';
    label.innerText = item.filename;

    const sizeSpan = document.createElement('span');
    sizeSpan.style.fontSize = '10px';
    sizeSpan.style.color = 'var(--text-muted)';
    sizeSpan.innerText = formatBytes(item.size_bytes);

    row.appendChild(chk);
    row.appendChild(label);
    row.appendChild(sizeSpan);

    row.addEventListener('click', () => {
      activePreviewPhotoPath = item.abs_path;
      renderWatermarkPhotoList();
      triggerWatermarkPreview();
    });

    fragment.appendChild(row);
  });

  listEl.appendChild(fragment);
  updateWatermarkSelectCounts();
}

function updateWatermarkSelectCounts() {
  const countEl = document.getElementById('lbl-watermark-count');
  if (countEl) {
    countEl.innerText = `${selectedProofingPaths.size} of ${proofingPhotos.length} selected`;
  }
}

// Select All / None & Filter
const btnWatermarkSelAll = document.getElementById('btn-watermark-sel-all');
if (btnWatermarkSelAll) {
  btnWatermarkSelAll.addEventListener('click', () => {
    proofingPhotos.forEach(p => selectedProofingPaths.add(p.abs_path));
    renderWatermarkPhotoList();
  });
}

const btnWatermarkSelNone = document.getElementById('btn-watermark-sel-none');
if (btnWatermarkSelNone) {
  btnWatermarkSelNone.addEventListener('click', () => {
    selectedProofingPaths.clear();
    renderWatermarkPhotoList();
  });
}

const txtWatermarkFilter = document.getElementById('txt-watermark-filter');
if (txtWatermarkFilter) {
  txtWatermarkFilter.addEventListener('input', () => {
    renderWatermarkPhotoList();
  });
}

// Live Interactive Watermark Preview
async function triggerWatermarkPreview(targetPath) {
  const filePath = targetPath || activePreviewPhotoPath;
  if (!filePath) return;

  const previewImg = document.getElementById('img-watermark-live');
  const placeholder = document.getElementById('preview-placeholder');
  const sampleName = document.getElementById('lbl-preview-sample-name');

  if (sampleName) {
    const pParts = filePath.replace(/\\/g, '/').split('/');
    sampleName.innerText = pParts[pParts.length - 1];
  }

  const mode = document.getElementById('sel-watermark-mode')?.value || 'text';
  const textStr = document.getElementById('txt-watermark-string')?.value || 'PROOF ONLY';
  const pos = document.getElementById('sel-watermark-pos')?.value || 'diagonal_grid';
  const opacity = (parseFloat(document.getElementById('rng-watermark-opacity')?.value || '35')) / 100;
  const fontScale = (parseFloat(document.getElementById('rng-watermark-fontscale')?.value || '4')) / 100;
  const colorHex = document.getElementById('col-watermark-color')?.value || '#FFFFFF';
  const shadow = !!document.getElementById('chk-watermark-shadow')?.checked;

  const logoPath = document.getElementById('txt-watermark-logo-path')?.value || '';
  const logoPos = document.getElementById('sel-watermark-logo-pos')?.value || 'bottom-right';
  const logoOpacity = (parseFloat(document.getElementById('rng-watermark-logo-opacity')?.value || '80')) / 100;
  const logoScale = (parseFloat(document.getElementById('rng-watermark-logo-scale')?.value || '18')) / 100;

  const config = {
    watermark_type: mode,
    text: textStr,
    position: pos,
    opacity: opacity,
    font_scale: fontScale,
    color_hex: colorHex,
    shadow: shadow,
    logo_path: logoPath,
    logo_position: logoPos,
    logo_opacity: logoOpacity,
    logo_scale: logoScale
  };

  try {
    const res = await fetch(API_BASE + '/api/proofing/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_path: filePath, config: config })
    });
    const data = await res.json();
    if (res.ok && data.preview_data_url) {
      if (previewImg) {
        previewImg.src = data.preview_data_url;
        previewImg.style.display = 'block';
      }
      if (placeholder) placeholder.style.display = 'none';
    } else {
      if (placeholder) {
        placeholder.innerText = 'Preview error: ' + (data.detail || 'Could not generate');
        placeholder.style.display = 'block';
      }
      if (previewImg) previewImg.style.display = 'none';
    }
  } catch (err) {
    if (placeholder) {
      placeholder.innerText = 'Preview failed: ' + err;
      placeholder.style.display = 'block';
    }
  }
}

const btnPreviewRefresh = document.getElementById('btn-preview-refresh');
if (btnPreviewRefresh) {
  btnPreviewRefresh.addEventListener('click', () => triggerWatermarkPreview());
}

const previewImgEl = document.getElementById('img-watermark-live');
if (previewImgEl) {
  previewImgEl.style.cursor = 'zoom-in';
  previewImgEl.title = 'Click to open full-screen preview lightbox';
  previewImgEl.addEventListener('click', () => {
    if (activePreviewPhotoPath) {
      openUniversalPreviewModal({
        items: proofingPhotos.length > 0 ? proofingPhotos : [{ abs_path: activePreviewPhotoPath, filename: activePreviewPhotoPath.split(/[/\\]/).pop() }],
        currentIndex: Math.max(0, proofingPhotos.findIndex(p => p.abs_path === activePreviewPhotoPath))
      });
    }
  });
}

// Destination Mode Switcher Controls
const selWatermarkOutMode = document.getElementById('sel-watermark-out-mode');
const boxSubfolderName = document.getElementById('box-subfolder-name');
const selWatermarkSubfolderType = document.getElementById('sel-watermark-subfolder-type');
const lblSubfolderNameLabel = document.getElementById('lbl-subfolder-name-label');
const boxWatermarkCustomDest = document.getElementById('box-watermark-custom-dest');
const txtSubfolderName = document.getElementById('txt-watermark-subfolder-name');
const lblDestHint = document.getElementById('lbl-dest-hint');

function computeSubfolderName(rawName, folderType, parentName = 'foldername') {
  const clean = (rawName || '_proofs').trim().replace(/^[/\\]+|[/\\]+$/g, '');
  if (folderType === 'prefix') {
    const sep = (clean.endsWith('_') || clean.endsWith('-') || clean.endsWith(' ')) ? '' : '_';
    return `${clean}${sep}${parentName}`;
  } else if (folderType === 'suffix') {
    const sep = (clean.startsWith('_') || clean.startsWith('-') || clean.startsWith(' ')) ? '' : '_';
    return `${parentName}${sep}${clean}`;
  } else {
    return clean || '_proofs';
  }
}

function updateDestModeUI() {
  if (!selWatermarkOutMode) return;
  const mode = selWatermarkOutMode.value;
  const subType = selWatermarkSubfolderType?.value || 'suffix';
  const subName = (txtSubfolderName?.value || '_proofs').trim();

  if (lblSubfolderNameLabel) {
    if (subType === 'prefix') lblSubfolderNameLabel.innerText = 'Folder Prefix:';
    else if (subType === 'suffix') lblSubfolderNameLabel.innerText = 'Folder Postfix:';
    else lblSubfolderNameLabel.innerText = 'Exact Name:';
  }

  if (mode === 'original_subfolder') {
    if (boxSubfolderName) boxSubfolderName.style.display = 'flex';
    if (boxWatermarkCustomDest) boxWatermarkCustomDest.style.display = 'none';

    const sampleFolder = (customProofingFolders.length > 0 && customProofingFolders[0].label) ? customProofingFolders[0].label : 'foldername';
    const previewName = computeSubfolderName(subName, subType, sampleFolder);

    if (lblDestHint) {
      if (subType === 'prefix') {
        lblDestHint.innerHTML = `💡 Each photo will be saved in a prefixed subfolder: <code>${escapeHtml(previewName)}/</code> inside its respective original folder.`;
      } else if (subType === 'suffix') {
        lblDestHint.innerHTML = `💡 Each photo will be saved in a postfixed subfolder: <code>${escapeHtml(previewName)}/</code> inside its respective original folder.`;
      } else {
        lblDestHint.innerHTML = `💡 Each photo will be saved in an exact subfolder: <code>${escapeHtml(previewName)}/</code> inside its respective original folder.`;
      }
    }
  } else if (mode === 'original_folder') {
    if (boxSubfolderName) boxSubfolderName.style.display = 'none';
    if (boxWatermarkCustomDest) boxWatermarkCustomDest.style.display = 'none';
    if (lblDestHint) lblDestHint.innerHTML = '💡 Each photo will be saved directly alongside its original file with suffix (e.g. <code>photo_proof.jpg</code>).';
  } else if (mode === 'custom_dir') {
    if (boxSubfolderName) boxSubfolderName.style.display = 'none';
    if (boxWatermarkCustomDest) boxWatermarkCustomDest.style.display = 'flex';
    if (lblDestHint) lblDestHint.innerHTML = '💡 All photos will be saved into the single custom destination folder selected above.';
  }
}

if (selWatermarkOutMode) {
  selWatermarkOutMode.addEventListener('change', updateDestModeUI);
}
if (selWatermarkSubfolderType) {
  selWatermarkSubfolderType.addEventListener('change', updateDestModeUI);
}
if (txtSubfolderName) {
  txtSubfolderName.addEventListener('input', updateDestModeUI);
}

// Start Batch Watermark Export
const btnStartWatermarkBatch = document.getElementById('btn-start-watermark-batch');
if (btnStartWatermarkBatch) {
  btnStartWatermarkBatch.addEventListener('click', async () => {
    const outMode = document.getElementById('sel-watermark-out-mode')?.value || 'original_subfolder';
    const subfolderName = document.getElementById('txt-watermark-subfolder-name')?.value.trim() || '_proofs';
    const subfolderType = document.getElementById('sel-watermark-subfolder-type')?.value || 'suffix';
    const destDir = document.getElementById('txt-watermark-dest')?.value.trim();

    if (outMode === 'custom_dir' && !destDir) {
      showToast('Please specify a destination folder for watermarked proofs!', 'error');
      document.getElementById('txt-watermark-dest')?.focus();
      return;
    }

    const filesToWatermark = proofingPhotos.filter(p => selectedProofingPaths.has(p.abs_path));
    if (filesToWatermark.length === 0) {
      showToast('Please select at least 1 photo to watermark!', 'error');
      return;
    }

    const mode = document.getElementById('sel-watermark-mode')?.value || 'text';
    const textStr = document.getElementById('txt-watermark-string')?.value || 'PROOF ONLY';
    const pos = document.getElementById('sel-watermark-pos')?.value || 'diagonal_grid';
    const opacity = (parseFloat(document.getElementById('rng-watermark-opacity')?.value || '35')) / 100;
    const fontScale = (parseFloat(document.getElementById('rng-watermark-fontscale')?.value || '4')) / 100;
    const colorHex = document.getElementById('col-watermark-color')?.value || '#FFFFFF';
    const shadow = !!document.getElementById('chk-watermark-shadow')?.checked;

    const logoPath = document.getElementById('txt-watermark-logo-path')?.value || '';
    const logoPos = document.getElementById('sel-watermark-logo-pos')?.value || 'bottom-right';
    const logoOpacity = (parseFloat(document.getElementById('rng-watermark-logo-opacity')?.value || '80')) / 100;
    const logoScale = (parseFloat(document.getElementById('rng-watermark-logo-scale')?.value || '18')) / 100;

    const maxDim = parseInt(document.getElementById('sel-watermark-res')?.value || '2048');
    const quality = parseInt(document.getElementById('rng-watermark-quality')?.value || '80');
    const suffix = document.getElementById('txt-watermark-suffix')?.value || '_proof';

    const config = {
      watermark_type: mode,
      text: textStr,
      position: pos,
      opacity: opacity,
      font_scale: fontScale,
      color_hex: colorHex,
      shadow: shadow,
      logo_path: logoPath,
      logo_position: logoPos,
      logo_opacity: logoOpacity,
      logo_scale: logoScale,
      max_dimension: maxDim,
      quality: quality
    };

    try {
      showToast(`Starting watermark export for ${filesToWatermark.length} photos...`, 'info');
      const res = await fetch(API_BASE + '/api/proofing/batch_watermark', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_ids: filesToWatermark.map(f => f.id).filter(Boolean),
          file_paths: filesToWatermark.map(f => f.abs_path),
          output_dir: outMode === 'custom_dir' ? destDir : null,
          output_mode: outMode,
          subfolder_name: subfolderName,
          subfolder_type: subfolderType,
          suffix: suffix,
          config: config
        })
      });
      let data = {};
      try {
        data = await res.json();
      } catch (e) {
        data = { detail: res.statusText || 'Server error' };
      }
      if (!res.ok) {
        showToast('Error starting batch: ' + (data.detail || 'Failed'), 'error');
        return;
      }

      // Show progress box
      const progBox = document.getElementById('box-watermark-progress');
      if (progBox) progBox.style.display = 'block';

      startWatermarkProgressPolling(outMode, destDir, filesToWatermark[0]?.abs_path, subfolderName, subfolderType);
    } catch (e) {
      showToast('Batch error: ' + e, 'error');
    }
  });
}

function startWatermarkProgressPolling(outMode, destDir, sampleFilePath, subfolderName, subfolderType = 'suffix') {
  clearInterval(watermarkBatchInterval);
  watermarkBatchInterval = setInterval(async () => {
    try {
      const statusRes = await fetch(API_BASE + '/api/proofing/batch_status').then(r => r.json());
      const bar = document.getElementById('bar-watermark-prog-fill');
      const pct = document.getElementById('lbl-batch-prog-pct');
      const curFile = document.getElementById('lbl-batch-prog-current');
      const counter = document.getElementById('lbl-batch-prog-counter');
      const title = document.getElementById('lbl-batch-prog-title');

      if (bar) bar.style.width = statusRes.percent + '%';
      if (pct) pct.innerText = statusRes.percent + '%';
      if (curFile) curFile.innerText = statusRes.current_file || 'Processing...';
      if (counter) counter.innerText = `${statusRes.completed} / ${statusRes.total}`;

      if (!statusRes.is_running) {
        clearInterval(watermarkBatchInterval);
        if (title) title.innerText = 'Batch Completed!';
        showToast(`Watermarking finished! ${statusRes.completed} photos exported.`, 'success');
        setTimeout(() => {
          if (outMode === 'custom_dir' && destDir) {
            openFileLocation(destDir, true);
          } else if (sampleFilePath) {
            const parts = sampleFilePath.replace(/\\/g, '/').split('/');
            parts.pop(); // remove photo filename
            const parentName = parts[parts.length - 1] || 'folder';
            const baseDir = parts.join('/');
            let targetOpenDir = baseDir;
            if (outMode === 'original_subfolder') {
              const actualSub = computeSubfolderName(subfolderName, subfolderType, parentName);
              targetOpenDir = `${baseDir}/${actualSub}`;
            }
            openFileLocation(targetOpenDir, true);
          }
        }, 1200);
      }
    } catch (e) {
      console.error('Polling status error:', e);
    }
  }, 600);
}

const btnCancelWatermarkBatch = document.getElementById('btn-cancel-watermark-batch');
if (btnCancelWatermarkBatch) {
  btnCancelWatermarkBatch.addEventListener('click', async () => {
    try {
      await fetch(API_BASE + '/api/proofing/cancel_batch', { method: 'POST' });
      showToast('Cancelling watermark batch...', 'info');
    } catch (e) {
      console.error(e);
    }
  });
}

// Generate Client Contact Sheet
const btnGenContactSheet = document.getElementById('btn-generate-contact-sheet');
if (btnGenContactSheet) {
  btnGenContactSheet.addEventListener('click', async () => {
    const destDir = document.getElementById('txt-contact-dest')?.value.trim();
    if (!destDir) {
      showToast('Please specify an output folder for the Contact Sheet package!', 'error');
      document.getElementById('txt-contact-dest')?.focus();
      return;
    }

    const title = document.getElementById('txt-contact-title')?.value.trim() || 'Client Proofing Gallery';
    const client = document.getElementById('txt-contact-client')?.value.trim() || 'Valued Client';
    const instructions = document.getElementById('txt-contact-instructions')?.value.trim();
    const watermarkText = document.getElementById('txt-contact-watermark')?.value.trim() || 'PROOF ONLY';

    const files = proofingPhotos.filter(p => selectedProofingPaths.has(p.abs_path));
    const targetFiles = files.length > 0 ? files : proofingPhotos;

    if (targetFiles.length === 0) {
      showToast('Please select photos or load a shoot folder first in Tab 1!', 'error');
      return;
    }

    try {
      showToast(`Generating client contact sheet package for ${targetFiles.length} photos...`, 'info');
      btnGenContactSheet.disabled = true;
      btnGenContactSheet.innerText = '⏳ Building Contact Sheet Package...';

      const res = await fetch(API_BASE + '/api/proofing/generate_contact_sheet', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_ids: targetFiles.map(f => f.id).filter(Boolean),
          file_paths: targetFiles.map(f => f.abs_path),
          source_dir: targetFiles.every(f => !f.id) ? document.getElementById('txt-watermark-custom-dir')?.value : null,
          output_dir: destDir,
          project_title: title,
          client_name: client,
          instructions: instructions,
          watermark_text: watermarkText
        })
      });
      const data = await res.json();
      btnGenContactSheet.disabled = false;
      btnGenContactSheet.innerText = '📑 Generate Standalone Client Contact Sheet';

      if (!res.ok) {
        showToast('Error: ' + (data.detail || 'Failed to generate contact sheet'), 'error');
        return;
      }

      lastGeneratedContactSheetHtml = data.html_path;
      const resBox = document.getElementById('box-contact-result');
      const resPath = document.getElementById('lbl-contact-result-path');
      if (resBox) resBox.style.display = 'block';
      if (resPath) resPath.innerText = data.html_path;

      showToast('🎉 Standalone client gallery generated successfully!', 'success');
    } catch (e) {
      btnGenContactSheet.disabled = false;
      btnGenContactSheet.innerText = '📑 Generate Standalone Client Contact Sheet';
      showToast('Failed to generate contact sheet: ' + e, 'error');
    }
  });
}

const btnOpenContactBrowser = document.getElementById('btn-open-contact-browser');
if (btnOpenContactBrowser) {
  btnOpenContactBrowser.addEventListener('click', () => {
    if (lastGeneratedContactSheetHtml) {
      openFileLocation(lastGeneratedContactSheetHtml, false);
    }
  });
}

const btnRevealContactExplorer = document.getElementById('btn-reveal-contact-explorer');
if (btnRevealContactExplorer) {
  btnRevealContactExplorer.addEventListener('click', () => {
    const destDir = document.getElementById('txt-contact-dest')?.value.trim();
    if (destDir) {
      openFileLocation(destDir, true);
    }
  });
}

// Client Selects Resolver & Exporter
const btnResolveSelects = document.getElementById('btn-resolve-selects');
if (btnResolveSelects) {
  btnResolveSelects.addEventListener('click', async () => {
    const inputStr = document.getElementById('txt-selects-input')?.value.trim();
    if (!inputStr) {
      showToast('Please paste the client\'s selections list first!', 'error');
      return;
    }

    const srcDir = document.getElementById('txt-selects-source-dir')?.value.trim() || document.getElementById('txt-watermark-custom-dir')?.value.trim();
    const selSrcId = document.getElementById('sel-watermark-source')?.value || null;

    try {
      showToast('Resolving selections against shoot files...', 'info');
      const res = await fetch(API_BASE + '/api/proofing/resolve_selects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_input: inputStr,
          source_dir: srcDir || null,
          source_id: selSrcId ? parseInt(selSrcId) : null
        })
      });
      const data = await res.json();
      lastResolvedSelects = data;

      // Stats
      const statsBox = document.getElementById('box-selects-stats');
      if (statsBox) {
        statsBox.innerHTML = `<span style="color:var(--accent-emerald);">Matched: ${data.matched_count}</span> | <span style="color:${data.unmatched_count > 0 ? 'var(--accent-rose)' : 'var(--text-muted)'};">Missing: ${data.unmatched_count}</span> | Match Rate: <strong style="color:var(--accent-cyan);">${data.match_rate_pct}%</strong>`;
      }

      // Unmatched warning
      const warnBox = document.getElementById('box-selects-unmatched');
      if (warnBox) {
        if (data.unmatched_count > 0) {
          warnBox.style.display = 'block';
          warnBox.innerHTML = `<strong>⚠️ ${data.unmatched_count} items not found in source folder:</strong> ${escapeHtml(data.unmatched.join(', '))}`;
        } else {
          warnBox.style.display = 'none';
        }
      }

      // Matched Grid
      const grid = document.getElementById('selects-matched-grid');
      if (grid) {
        grid.innerHTML = '';
        if (data.matched.length === 0) {
          grid.innerHTML = '<p style="grid-column: 1/-1; text-align: center; color: var(--accent-rose); font-size: 13px; margin-top: 40px;">No matching photos found for these entries.</p>';
        } else {
          data.matched.forEach((m, idx) => {
            const card = document.createElement('div');
            card.className = 'selects-card';
            card.style.background = 'var(--bg-secondary)';
            card.style.border = '1px solid var(--border-color)';
            card.style.borderRadius = '8px';
            card.style.overflow = 'hidden';
            card.style.display = 'flex';
            card.style.flexDirection = 'column';
            card.style.cursor = 'pointer';
            card.style.position = 'relative';
            card.style.transition = 'transform 0.15s, border-color 0.15s, box-shadow 0.15s';

            const thumbUrl = API_BASE + '/api/thumbnail_by_path?path=' + encodeURIComponent(m.abs_path);
            const badgeSidecar = m.sidecar_path ? '<span style="background:rgba(16,185,129,0.3); color:var(--accent-emerald); font-size:9px; font-weight:700; padding:2px 5px; border-radius:3px;">+XMP</span>' : '';

            card.innerHTML = `
              <div class="selects-thumb-wrap" style="position:relative; width:100%; height:130px; background:#070b14; overflow:hidden; display:flex; align-items:center; justify-content:center;">
                <img src="${thumbUrl}" alt="${escapeHtml(m.filename)}" loading="lazy" decoding="async" style="width:100%; height:100%; object-fit:cover; transition:transform 0.2s;" onerror="this.onerror=null; this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><rect width=%22100%22 height=%22100%22 fill=%22%231e293b%22/><text x=%2250%22 y=%2255%22 font-size=%2211%22 fill=%22%2394a3b8%22 text-anchor=%22middle%22>PHOTO</text></svg>';">
                <div class="thumb-hover-overlay" style="position:absolute; inset:0; background:rgba(0,0,0,0.45); opacity:0; transition:opacity 0.2s; display:flex; align-items:center; justify-content:center; gap:6px;">
                  <span style="background:rgba(6,182,212,0.9); color:#000; font-size:11px; font-weight:700; padding:4px 9px; border-radius:4px;">🔍 Preview</span>
                </div>
                <div style="position:absolute; top:6px; left:6px; background:rgba(0,0,0,0.7); color:#fff; font-size:10px; font-weight:700; padding:2px 6px; border-radius:4px;">
                  #${idx + 1}
                </div>
                ${badgeSidecar ? `<div style="position:absolute; top:6px; right:6px;">${badgeSidecar}</div>` : ''}
              </div>
              <div style="padding:8px; display:flex; flex-direction:column; gap:4px;">
                <div style="font-size:11px; font-weight:700; color:var(--text-main); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${escapeHtml(m.filename)}">
                  ${escapeHtml(m.filename)}
                </div>
                <div style="font-size:10px; color:var(--text-muted); display:flex; justify-content:space-between; align-items:center;">
                  <span>${formatBytes(m.size_bytes)}</span>
                  <span style="color:var(--accent-cyan); font-family:monospace;">Query: ${escapeHtml(m.query)}</span>
                </div>
              </div>
            `;

            card.addEventListener('mouseenter', () => {
              card.style.borderColor = 'var(--accent-cyan)';
              const ov = card.querySelector('.thumb-hover-overlay');
              if (ov) ov.style.opacity = '1';
            });
            card.addEventListener('mouseleave', () => {
              card.style.borderColor = 'var(--border-color)';
              const ov = card.querySelector('.thumb-hover-overlay');
              if (ov) ov.style.opacity = '0';
            });

            card.addEventListener('click', () => {
              openUniversalPreviewModal({
                items: data.matched,
                currentIndex: idx
              });
            });

            grid.appendChild(card);
          });
        }
      }

      // Actions Box
      const actionsBox = document.getElementById('box-selects-actions');
      if (actionsBox) {
        actionsBox.style.display = data.matched.length > 0 ? 'flex' : 'none';
      }
    } catch (e) {
      showToast('Failed to resolve selections: ' + e, 'error');
    }
  });
}

const btnExportSelectsAction = document.getElementById('btn-execute-selects-export');
if (btnExportSelectsAction) {
  btnExportSelectsAction.addEventListener('click', async () => {
    if (!lastResolvedSelects || !lastResolvedSelects.matched || lastResolvedSelects.matched.length === 0) {
      showToast('No matched selections to export!', 'error');
      return;
    }

    const destDir = document.getElementById('txt-selects-dest-dir')?.value.trim();
    if (!destDir) {
      showToast('Please specify a destination edit folder!', 'error');
      document.getElementById('txt-selects-dest-dir')?.focus();
      return;
    }

    const action = document.querySelector('input[name="rad-selects-action"]:checked')?.value || 'copy';

    try {
      showToast(`Exporting ${lastResolvedSelects.matched.length} selects...`, 'info');
      const res = await fetch(API_BASE + '/api/proofing/export_selects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          matched_items: lastResolvedSelects.matched,
          destination_dir: destDir,
          action: action
        })
      });
      const data = await res.json();
      if (!res.ok) {
        showToast('Export error: ' + (data.detail || 'Failed to export'), 'error');
        return;
      }

      showToast(`Successfully transferred ${data.processed_count} files (${formatBytes(data.total_bytes)}) to edit folder!`, 'success');
      setTimeout(() => openFileLocation(destDir, true), 800);
    } catch (e) {
      showToast('Export failed: ' + e, 'error');
    }
  });
}

const btnCopySelectsFilenames = document.getElementById('btn-copy-selects-filenames');
if (btnCopySelectsFilenames) {
  btnCopySelectsFilenames.addEventListener('click', () => {
    if (!lastResolvedSelects || !lastResolvedSelects.matched || lastResolvedSelects.matched.length === 0) {
      showToast('No resolved selections to copy!', 'error');
      return;
    }
    const list = lastResolvedSelects.matched.map(m => m.filename).join(', ');
    navigator.clipboard.writeText(list).then(() => {
      showToast(`Copied ${lastResolvedSelects.matched.length} filenames to clipboard!`, 'success');
    });
  });
}

// Global initialization
setupContextMenu();
loadOverview();
restoreSessionState();

setInterval(() => {
  if (currentTab === 'transcoder') {
    loadTranscoder();
  }
}, 3000);

// ----------------- SESSION PERSISTENCE & RESTORATION -----------------
let sessionSaveDebounceTimer = null;
let isRestoringSession = false;

function collectCurrentSessionState() {
  const mode = document.getElementById('sel-watermark-mode')?.value || 'text';
  const textStr = document.getElementById('txt-watermark-string')?.value || 'PROOF ONLY';
  const pos = document.getElementById('sel-watermark-pos')?.value || 'diagonal_grid';
  const opacity = parseInt(document.getElementById('rng-watermark-opacity')?.value || '35');
  const fontScale = parseInt(document.getElementById('rng-watermark-fontscale')?.value || '4');
  const colorHex = document.getElementById('col-watermark-color')?.value || '#FFFFFF';
  const shadow = !!document.getElementById('chk-watermark-shadow')?.checked;

  const logoPath = document.getElementById('txt-watermark-logo-path')?.value || '';
  const logoPos = document.getElementById('sel-watermark-logo-pos')?.value || 'bottom-right';
  const logoOpacity = parseInt(document.getElementById('rng-watermark-logo-opacity')?.value || '80');
  const logoScale = parseInt(document.getElementById('rng-watermark-logo-scale')?.value || '18');

  const resolution = parseInt(document.getElementById('rng-watermark-res')?.value || '2048');
  const isOrigRes = !!document.getElementById('chk-watermark-orig-res')?.checked;
  const quality = parseInt(document.getElementById('rng-watermark-quality')?.value || '80');
  const outMode = document.getElementById('sel-watermark-out-mode')?.value || 'original_subfolder';
  const subfolderName = document.getElementById('txt-watermark-subfolder-name')?.value || '_proofs';
  const customDest = document.getElementById('txt-watermark-dest')?.value || '';
  const suffix = document.getElementById('txt-watermark-suffix')?.value || '_proof';

  return {
    last_active_tab: currentTab,
    last_proofing_subview: currentProofingSubview,
    custom_folders: customProofingFolders.map(f => ({
      path: f.path,
      label: f.label,
      checked: !!f.checked,
      recursive: f.recursive !== false
    })),
    watermark_settings: {
      mode: mode,
      text: textStr,
      position: pos,
      opacity: opacity,
      font_scale: fontScale,
      color_hex: colorHex,
      shadow: shadow,
      logo_path: logoPath,
      logo_position: logoPos,
      logo_opacity: logoOpacity,
      logo_scale: logoScale,
      resolution: resolution,
      is_original_res: isOrigRes,
      quality: quality,
      output_mode: outMode,
      subfolder_name: subfolderName,
      subfolder_type: document.getElementById('sel-watermark-subfolder-type')?.value || 'suffix',
      custom_dest: customDest,
      suffix: suffix,
      active_preset_id: activePresetId || 'builtin_diagonal_text'
    },
    contact_sheet_settings: {
      title: document.getElementById('txt-contact-title')?.value || '',
      client: document.getElementById('txt-contact-client')?.value || '',
      instructions: document.getElementById('txt-contact-instructions')?.value || '',
      watermark_text: document.getElementById('txt-contact-watermark')?.value || '',
      dest_dir: document.getElementById('txt-contact-dest')?.value || ''
    },
    selects_settings: {
      input: document.getElementById('txt-selects-input')?.value || '',
      source_dir: document.getElementById('txt-selects-source-dir')?.value || '',
      dest_dir: document.getElementById('txt-selects-dest-dir')?.value || '',
      action: document.querySelector('input[name="rad-selects-action"]:checked')?.value || 'copy'
    }
  };
}

function debouncedSaveSessionState(extraOverrides = {}) {
  if (isRestoringSession) return;
  clearTimeout(sessionSaveDebounceTimer);
  sessionSaveDebounceTimer = setTimeout(async () => {
    try {
      const state = { ...collectCurrentSessionState(), ...extraOverrides };
      await fetch(API_BASE + '/api/session/state', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(state)
      });
    } catch (e) {
      console.warn('Could not save session state:', e);
    }
  }, 400);
}

async function restoreSessionState() {
  isRestoringSession = true;
  try {
    const res = await fetch(API_BASE + '/api/session/state');
    if (!res.ok) return;
    const state = await res.json();
    if (!state) return;

    // 1. Watermark settings
    if (state.watermark_settings) {
      const ws = state.watermark_settings;
      const elMode = document.getElementById('sel-watermark-mode');
      if (elMode && ws.mode) {
        elMode.value = ws.mode;
        const boxText = document.getElementById('box-watermark-text');
        const boxLogo = document.getElementById('box-watermark-logo');
        if (boxText) boxText.style.display = (ws.mode === 'text' || ws.mode === 'both') ? 'flex' : 'none';
        if (boxLogo) boxLogo.style.display = (ws.mode === 'logo' || ws.mode === 'both') ? 'flex' : 'none';
      }
      if (ws.text !== undefined && document.getElementById('txt-watermark-string')) {
        document.getElementById('txt-watermark-string').value = ws.text;
      }
      if (ws.position && document.getElementById('sel-watermark-pos')) {
        document.getElementById('sel-watermark-pos').value = ws.position;
      }
      if (ws.opacity !== undefined && document.getElementById('rng-watermark-opacity')) {
        document.getElementById('rng-watermark-opacity').value = ws.opacity;
        if (lblValOpacity) lblValOpacity.innerText = ws.opacity + '%';
      }
      if (ws.font_scale !== undefined && document.getElementById('rng-watermark-fontscale')) {
        document.getElementById('rng-watermark-fontscale').value = ws.font_scale;
        if (lblValFontScale) lblValFontScale.innerText = ws.font_scale + '%';
      }
      if (ws.color_hex && document.getElementById('col-watermark-color')) {
        document.getElementById('col-watermark-color').value = ws.color_hex;
      }
      if (ws.shadow !== undefined && document.getElementById('chk-watermark-shadow')) {
        document.getElementById('chk-watermark-shadow').checked = !!ws.shadow;
      }
      if (ws.logo_path !== undefined && document.getElementById('txt-watermark-logo-path')) {
        document.getElementById('txt-watermark-logo-path').value = ws.logo_path;
      }
      if (ws.logo_position && document.getElementById('sel-watermark-logo-pos')) {
        document.getElementById('sel-watermark-logo-pos').value = ws.logo_position;
      }
      if (ws.logo_opacity !== undefined && document.getElementById('rng-watermark-logo-opacity')) {
        document.getElementById('rng-watermark-logo-opacity').value = ws.logo_opacity;
        if (lblValLogoOpacity) lblValLogoOpacity.innerText = ws.logo_opacity + '%';
      }
      if (ws.logo_scale !== undefined && document.getElementById('rng-watermark-logo-scale')) {
        document.getElementById('rng-watermark-logo-scale').value = ws.logo_scale;
        if (lblValLogoScale) lblValLogoScale.innerText = ws.logo_scale + '%';
      }
      if (ws.quality !== undefined && document.getElementById('rng-watermark-quality')) {
        document.getElementById('rng-watermark-quality').value = ws.quality;
        if (lblValQuality) lblValQuality.innerText = ws.quality + '%';
      }
      if (ws.output_mode && document.getElementById('sel-watermark-out-mode')) {
        document.getElementById('sel-watermark-out-mode').value = ws.output_mode;
      }
      if (ws.subfolder_name !== undefined && document.getElementById('txt-watermark-subfolder-name')) {
        document.getElementById('txt-watermark-subfolder-name').value = ws.subfolder_name;
      }
      if (ws.subfolder_type !== undefined && document.getElementById('sel-watermark-subfolder-type')) {
        document.getElementById('sel-watermark-subfolder-type').value = ws.subfolder_type;
      }
      if (ws.custom_dest !== undefined && document.getElementById('txt-watermark-dest')) {
        document.getElementById('txt-watermark-dest').value = ws.custom_dest;
      }
      if (ws.suffix !== undefined && document.getElementById('txt-watermark-suffix')) {
        document.getElementById('txt-watermark-suffix').value = ws.suffix;
      }

      // Resolution & Slider
      updateResUI(ws.resolution || 2048, !!ws.is_original_res);
      updateDestModeUI();

      if (ws.active_preset_id) {
        await loadWatermarkPresets(ws.active_preset_id);
      } else {
        await loadWatermarkPresets();
      }
    }

    // 2. Custom Folders Checklist
    if (Array.isArray(state.custom_folders) && state.custom_folders.length > 0) {
      customProofingFolders = state.custom_folders;
      renderCustomFoldersList();
      loadPhotosFromActiveFolders();
    }

    // 3. Contact Sheet Settings
    if (state.contact_sheet_settings) {
      const cs = state.contact_sheet_settings;
      if (cs.title && document.getElementById('txt-contact-title')) document.getElementById('txt-contact-title').value = cs.title;
      if (cs.client && document.getElementById('txt-contact-client')) document.getElementById('txt-contact-client').value = cs.client;
      if (cs.instructions && document.getElementById('txt-contact-instructions')) document.getElementById('txt-contact-instructions').value = cs.instructions;
      if (cs.watermark_text && document.getElementById('txt-contact-watermark')) document.getElementById('txt-contact-watermark').value = cs.watermark_text;
      if (cs.dest_dir && document.getElementById('txt-contact-dest')) document.getElementById('txt-contact-dest').value = cs.dest_dir;
    }

    // 4. Selects Settings
    if (state.selects_settings) {
      const ss = state.selects_settings;
      if (ss.input && document.getElementById('txt-selects-input')) document.getElementById('txt-selects-input').value = ss.input;
      if (ss.source_dir && document.getElementById('txt-selects-source-dir')) document.getElementById('txt-selects-source-dir').value = ss.source_dir;
      if (ss.dest_dir && document.getElementById('txt-selects-dest-dir')) document.getElementById('txt-selects-dest-dir').value = ss.dest_dir;
      if (ss.action) {
        const rad = document.querySelector(`input[name="rad-selects-action"][value="${ss.action}"]`);
        if (rad) rad.checked = true;
      }
    }

    // 5. Last Task Banner
    if (state.last_task && state.last_task.task_type && state.last_task.task_type !== 'none') {
      const banner = document.getElementById('session-last-task-banner');
      const textEl = document.getElementById('session-last-task-text');
      if (banner && textEl) {
        banner.style.display = 'inline-flex';
        const formatted = state.last_task.formatted_time ? ` (${state.last_task.formatted_time})` : '';
        textEl.innerText = `${state.last_task.summary}${formatted}`;
        textEl.title = `${state.last_task.summary}${formatted}`;
      }
    }

    // 6. Active Tab & Subview
    if (state.last_active_tab && state.last_active_tab !== 'overview') {
      switchTab(state.last_active_tab);
    }
    if (state.last_proofing_subview) {
      switchProofingSubview(state.last_proofing_subview);
    }
  } catch (err) {
    console.warn('Failed restoring session state:', err);
  } finally {
    isRestoringSession = false;
  }
}

// ----------------- APPLICATION LOGS VIEWER -----------------
const modalAppLogs = document.getElementById('modal-app-logs');
const btnShowLogsModal = document.getElementById('btn-show-logs-modal');
const btnRefreshLogs = document.getElementById('btn-refresh-logs');
const btnOpenLogsFolder = document.getElementById('btn-open-logs-folder');
const preLogsContent = document.getElementById('pre-logs-content');
const lblLogsPath = document.getElementById('lbl-logs-path');
const lblLogsSize = document.getElementById('lbl-logs-size');

async function fetchAndDisplayRecentLogs() {
  if (!preLogsContent) return;
  try {
    preLogsContent.textContent = 'Loading logs from server...';
    const res = await fetch(API_BASE + '/api/logs/recent?lines=200');
    const data = await res.json();
    if (lblLogsPath && data.path) lblLogsPath.textContent = data.path;
    if (lblLogsSize) lblLogsSize.textContent = formatBytes(data.size_bytes || 0);

    if (data.lines && data.lines.length > 0) {
      preLogsContent.textContent = data.lines.join('\n');
    } else {
      preLogsContent.textContent = 'Log file is empty.';
    }
    preLogsContent.scrollTop = preLogsContent.scrollHeight;
  } catch (err) {
    preLogsContent.textContent = 'Error fetching logs: ' + err;
  }
}

if (btnShowLogsModal) {
  btnShowLogsModal.addEventListener('click', () => {
    if (modalAppLogs) {
      modalAppLogs.classList.add('active');
      fetchAndDisplayRecentLogs();
    }
  });
}

if (btnRefreshLogs) {
  btnRefreshLogs.addEventListener('click', fetchAndDisplayRecentLogs);
}

if (btnOpenLogsFolder) {
  btnOpenLogsFolder.addEventListener('click', async () => {
    try {
      showToast('Opening logs folder in File Explorer...', 'info');
      const res = await fetch(API_BASE + '/api/logs/open', { method: 'POST' });
      if (res.ok) {
        showToast('Logs folder opened in Explorer', 'success');
      } else {
        showToast('Could not open logs folder', 'error');
      }
    } catch (e) {
      showToast('Error opening logs: ' + e, 'error');
    }
  });
}

// Attach auto-save listeners to all proofing inputs
[
  'txt-watermark-string', 'sel-watermark-pos', 'rng-watermark-opacity',
  'rng-watermark-fontscale', 'col-watermark-color', 'chk-watermark-shadow',
  'txt-watermark-logo-path', 'sel-watermark-logo-pos', 'rng-watermark-logo-opacity',
  'rng-watermark-logo-scale', 'sel-watermark-mode', 'rng-watermark-res',
  'chk-watermark-orig-res', 'rng-watermark-quality', 'sel-watermark-out-mode',
  'sel-watermark-subfolder-type', 'txt-watermark-subfolder-name', 'txt-watermark-dest', 'txt-watermark-suffix',
  'txt-contact-title', 'txt-contact-client', 'txt-contact-instructions',
  'txt-contact-watermark', 'txt-contact-dest', 'txt-selects-input',
  'txt-selects-source-dir', 'txt-selects-dest-dir'
].forEach(id => {
  const el = document.getElementById(id);
  if (el) {
    el.addEventListener('input', () => debouncedSaveSessionState());
    el.addEventListener('change', () => debouncedSaveSessionState());
  }
});
document.querySelectorAll('input[name="rad-selects-action"]').forEach(rad => {
  rad.addEventListener('change', () => debouncedSaveSessionState());
});

// ----------------- UNIVERSAL PHOTO PREVIEW LIGHTBOX MODAL -----------------
let previewModalState = {
  items: [],
  currentIndex: 0,
  fromCuller: false
};

window.openUniversalPreviewModal = function({ items, currentIndex = 0, fromCuller = false }) {
  const modal = document.getElementById('modal-photo-preview');
  if (!modal || !items || items.length === 0) return;

  previewModalState.items = items;
  previewModalState.currentIndex = Math.max(0, Math.min(currentIndex, items.length - 1));
  previewModalState.fromCuller = !!fromCuller;

  renderPreviewModalCurrentItem();
  modal.classList.add('active');
};

function renderPreviewModalCurrentItem() {
  const { items, currentIndex } = previewModalState;
  if (!items || items.length === 0) return;

  const item = items[currentIndex];
  const absPath = item.abs_path || item.path || '';
  const filename = item.filename || (absPath ? absPath.split(/[/\\]/).pop() : 'Photo');
  const sizeBytes = item.size_bytes || 0;

  const counterEl = document.getElementById('preview-modal-counter');
  const titleEl = document.getElementById('preview-modal-filename');
  const sizeEl = document.getElementById('preview-modal-size');
  const pathEl = document.getElementById('preview-modal-path');
  const imgEl = document.getElementById('preview-modal-img');
  const loaderEl = document.getElementById('preview-modal-loader');
  const prevBtn = document.getElementById('btn-preview-modal-prev');
  const nextBtn = document.getElementById('btn-preview-modal-next');
  const keepBtn = document.getElementById('btn-preview-modal-keep');

  if (counterEl) counterEl.innerText = `${currentIndex + 1} / ${items.length}`;
  if (titleEl) {
    titleEl.innerText = filename;
    titleEl.title = filename;
  }
  if (sizeEl) sizeEl.innerText = sizeBytes > 0 ? `(${formatBytes(sizeBytes)})` : '';
  if (pathEl) {
    pathEl.innerText = absPath;
    pathEl.title = absPath;
  }

  if (keepBtn) {
    keepBtn.style.display = previewModalState.fromCuller ? 'inline-block' : 'none';
  }

  if (prevBtn) prevBtn.style.opacity = items.length > 1 ? '1' : '0.3';
  if (nextBtn) nextBtn.style.opacity = items.length > 1 ? '1' : '0.3';

  if (imgEl && loaderEl) {
    loaderEl.style.display = 'block';
    imgEl.style.opacity = '0.2';

    // Fetch high-res preview
    const previewUrl = API_BASE + '/api/preview_by_path?path=' + encodeURIComponent(absPath) + '&max_dim=1800';
    imgEl.onload = () => {
      loaderEl.style.display = 'none';
      imgEl.style.opacity = '1';
    };
    imgEl.onerror = () => {
      // Fallback to thumbnail URL if preview fails
      const fallbackUrl = API_BASE + '/api/thumbnail_by_path?path=' + encodeURIComponent(absPath);
      imgEl.onerror = null;
      imgEl.src = fallbackUrl;
      loaderEl.style.display = 'none';
      imgEl.style.opacity = '1';
    };
    imgEl.src = previewUrl;
  }
}

const btnPrevModalPrev = document.getElementById('btn-preview-modal-prev');
const btnPrevModalNext = document.getElementById('btn-preview-modal-next');
const btnPrevModalReveal = document.getElementById('btn-preview-modal-reveal');
const btnPrevModalKeep = document.getElementById('btn-preview-modal-keep');

if (btnPrevModalKeep) {
  btnPrevModalKeep.addEventListener('click', async () => {
    const item = previewModalState.items[previewModalState.currentIndex];
    if (!item || !item.id) return;
    try {
      const res = await fetch(API_BASE + '/api/culling/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_ids: [item.id], action: 'keep', include_sidecars: false })
      });
      if (res.ok) {
        showToast(`Marked "${item.filename}" as intentional keep!`, 'success');
        previewModalState.items.splice(previewModalState.currentIndex, 1);
        if (previewModalState.items.length === 0) {
          document.getElementById('modal-photo-preview')?.classList.remove('active');
        } else {
          if (previewModalState.currentIndex >= previewModalState.items.length) {
            previewModalState.currentIndex = previewModalState.items.length - 1;
          }
          renderPreviewModalCurrentItem();
        }
        loadCuller();
      }
    } catch (err) {
      showToast('Failed to mark photo keep: ' + err, 'error');
    }
  });
}

if (btnPrevModalPrev) {
  btnPrevModalPrev.addEventListener('click', () => {
    if (previewModalState.items.length <= 1) return;
    previewModalState.currentIndex = (previewModalState.currentIndex - 1 + previewModalState.items.length) % previewModalState.items.length;
    renderPreviewModalCurrentItem();
  });
}

if (btnPrevModalNext) {
  btnPrevModalNext.addEventListener('click', () => {
    if (previewModalState.items.length <= 1) return;
    previewModalState.currentIndex = (previewModalState.currentIndex + 1) % previewModalState.items.length;
    renderPreviewModalCurrentItem();
  });
}

if (btnPrevModalReveal) {
  btnPrevModalReveal.addEventListener('click', () => {
    const item = previewModalState.items[previewModalState.currentIndex];
    const p = item?.abs_path || item?.path;
    if (p) {
      openFileLocation(p, false);
    }
  });
}

window.addEventListener('keydown', (e) => {
  const modal = document.getElementById('modal-photo-preview');
  if (!modal || !modal.classList.contains('active')) return;

  if (e.key === 'ArrowLeft') {
    e.preventDefault();
    btnPrevModalPrev?.click();
  } else if (e.key === 'ArrowRight') {
    e.preventDefault();
    btnPrevModalNext?.click();
  } else if (e.key === 'Escape') {
    modal.classList.remove('active');
  }
});
