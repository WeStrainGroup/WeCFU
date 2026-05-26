// WeCFU — frontend (v0.1.1).
//
// Click model:
//   • Left click on empty plate area  → add a manual colony (instant, optimistic)
//   • Right click on a circle         → delete it             (instant, optimistic)
//   • Wheel                            → zoom (anchored at cursor)
//   • Cmd/Ctrl + drag                 → pan
//   • ← / →                            → prev/next image
//   • Space                            → mark reviewed
//   • Cmd/Ctrl-Z                      → undo last add/delete

const $ = (id) => document.getElementById(id);
const { t, applyI18n, setLang, getLang, LANG_NAMES } = window.WECFU_I18N;

const PRESETS = {
  white:  { min_value: 200, max_saturation: 60,  min_circularity: 0.55 },
  cream:  { min_value: 180, max_saturation: 100, min_circularity: 0.55 },
  yellow: { min_value: 160, max_saturation: 200, min_circularity: 0.50 },
  any:    { min_value: 140, max_saturation: 255, min_circularity: 0.45 },
};

const state = {
  batch: null,         // current internal storage key (auto-managed, not user-facing)
  imageName: null,
  imageList: [],
  detections: [],
  plate: null,
  img: null,
  imgUrl: null,
  view: { zoom: 1, ox: 0, oy: 0, ready: false },
  dragPan: null,
  history: [],
  maskPreview: null,
  saveDirHandle: null, // File System Access API directory handle (Chromium)
};

// ── helpers ─────────────────────────────────────────────────────────────

function setStatus(s) { $('status').textContent = s; }

function applyPreset(name) {
  const p = PRESETS[name];
  if (!p) return;
  $('p-min-value').value = p.min_value;
  $('p-max-sat').value = p.max_saturation;
  $('p-circ').value = p.min_circularity;
}

function paramsBody() {
  return {
    plate_inset: parseFloat($('p-inset').value),
    min_value: parseInt($('p-min-value').value, 10),
    max_saturation: parseInt($('p-max-sat').value, 10),
    min_circularity: parseFloat($('p-circ').value),
    min_area_frac: parseFloat($('p-min-area').value),
    peak_min_distance: parseInt($('p-peak').value, 10),
  };
}

const enc = encodeURIComponent;
function imgURL(suffix) { return `/api/batch/${enc(state.batch)}/image/${enc(state.imageName)}${suffix}`; }

// ── batches + image list ─────────────────────────────────────────────────

async function loadDefaultBatch() {
  try {
    const r = await fetch('/api/batches').then(r => r.json());
    if (r.batches && r.batches.length) {
      state.batch = r.batches.includes(r.default) ? r.default : r.batches[0];
      await loadImages();
    } else {
      // No batches yet — fresh install. Wait for the user to ingest.
      state.batch = null;
      state.imageList = [];
      renderImageList();
    }
  } catch (e) {
    console.warn('loadDefaultBatch failed (will retry after ingest):', e);
    state.batch = null;
    state.imageList = [];
  }
}

async function loadImages() {
  if (!state.batch) {
    state.imageList = [];
    renderImageList();
    return;
  }
  try {
    const resp = await fetch(`/api/batch/${enc(state.batch)}/images`);
    if (!resp.ok) {
      state.imageList = [];
      renderImageList();
      return;
    }
    const r = await resp.json();
    state.imageList = Array.isArray(r.images) ? r.images : [];
  } catch (e) {
    console.warn('loadImages failed:', e);
    state.imageList = [];
  }
  renderImageList();
}

function renderImageList() {
  const list = $('image-list');
  list.innerHTML = '';
  for (const it of state.imageList) {
    const row = document.createElement('div');
    row.className = 'image-row';
    // Three dot states (CSS picks the strongest one).
    if (it.processed) row.classList.add('counted');
    if (it.reviewed)  row.classList.add('reviewed');
    if (it.notes) row.classList.add('has-notes');
    if (it.name === state.imageName) row.classList.add('selected');

    const flagTitle = it.reviewed ? t('flagReviewed')
                     : it.processed ? t('flagCounted')
                     : t('flagUnprocessed');

    row.innerHTML = `
      <span class="row-flag" title="${flagTitle}"></span>
      <span class="row-name" title="${it.name}${it.notes ? ' — ' + it.notes : ''}">${it.name}</span>
      <span class="row-count">${it.processed ? it.count : '–'}</span>`;
    row.addEventListener('click', () => selectImage(it.name));
    list.appendChild(row);
  }
}

async function selectImage(name) {
  if (state.imageName === name) return;
  state.imageName = name;
  state.history = [];
  state.view.ready = false; // force one-time refit when the image changes
  state.maskPreview = null; // clear any live-threshold preview from the previous image
  $('current-name').textContent = name;
  renderImageList();
  await loadDetections({ refit: true });
  $('notes-input').value = state.imageList.find(i => i.name === name)?.notes || '';
  // Opening an image auto-marks it as reviewed (green dot in the sidebar).
  // The button has been removed in v0.1.5 — review = "you have looked at this".
  if (state.batch) {
    fetch(imgURL('/reviewed?reviewed=true'), { method: 'POST' }).catch(() => {});
    const row = state.imageList.find(i => i.name === name);
    if (row && !row.reviewed) { row.reviewed = true; renderImageList(); }
  }
  // If the live-preview toggle is on, re-fetch for the new image (with the
  // currently-set thresholds) instead of showing the stale previous preview.
  if ($('p-preview').checked) refreshMaskPreview();
}

async function loadDetections({ refit = false } = {}) {
  if (!state.batch || !state.imageName) return;
  const r = await fetch(imgURL('/detections'));
  if (!r.ok) {
    state.detections = []; state.plate = null;
    await loadRawImage();
    if (refit || !state.view.ready) { fitToCanvas(); state.view.ready = true; }
    draw();
    $('count-badge').textContent = t('notProcessed');
    $('meta-tag').textContent = '';
    return;
  }
  const data = await r.json();
  state.detections = data.detections;
  state.plate = data.plate;
  updateCountBadge();
  $('meta-tag').textContent = '';
  await loadRawImage();
  if (refit || !state.view.ready) { fitToCanvas(); state.view.ready = true; }
  draw();
}

function updateCountBadge() {
  $('count-badge').textContent = `${state.detections.length} ${t('cfuSuffix')}`;
}

async function loadRawImage() {
  const url = imgURL('/raw');
  if (state.imgUrl === url && state.img) return; // already loaded
  return new Promise(resolve => {
    const im = new Image();
    im.onload = () => { state.img = im; state.imgUrl = url; resolve(); };
    im.src = url;
  });
}

// ── canvas ──────────────────────────────────────────────────────────────

function resizeCanvas() {
  const c = $('canvas');
  const ratio = window.devicePixelRatio || 1;
  const wrap = c.parentElement.getBoundingClientRect();
  c.width = Math.max(1, Math.floor(wrap.width * ratio));
  c.height = Math.max(1, Math.floor(wrap.height * ratio));
}

function fitToCanvas() {
  resizeCanvas();
  const c = $('canvas');
  if (!state.img) return;
  const ratio = window.devicePixelRatio || 1;
  let fitW = state.img.width, fitH = state.img.height, cxImg = state.img.width / 2, cyImg = state.img.height / 2;
  if (state.plate) {
    const pad = 24;
    fitW = (state.plate.r + pad) * 2;
    fitH = (state.plate.r + pad) * 2;
    cxImg = state.plate.cx;
    cyImg = state.plate.cy;
  }
  const scale = Math.min(c.width / fitW, c.height / fitH);
  state.view.zoom = scale / ratio;
  state.view.ox = (c.width / ratio) / 2 - cxImg * state.view.zoom;
  state.view.oy = (c.height / ratio) / 2 - cyImg * state.view.zoom;
}

function screenToImg(sx, sy) {
  return [(sx - state.view.ox) / state.view.zoom, (sy - state.view.oy) / state.view.zoom];
}

function draw() {
  const c = $('canvas');
  const ctx = c.getContext('2d');
  ctx.fillStyle = '#0a0b0e';
  ctx.fillRect(0, 0, c.width, c.height);
  if (!state.img) return;
  const ratio = window.devicePixelRatio || 1;
  ctx.save();
  ctx.scale(ratio, ratio);
  ctx.translate(state.view.ox, state.view.oy);
  ctx.scale(state.view.zoom, state.view.zoom);

  const baseImg = state.maskPreview || state.img;
  if (state.maskPreview && state.plate) {
    const pad = 24;
    const x0 = state.plate.cx - state.plate.r - pad;
    const y0 = state.plate.cy - state.plate.r - pad;
    ctx.drawImage(baseImg, x0, y0);
  } else {
    ctx.drawImage(baseImg, 0, 0);
    if (state.plate) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, state.img.width, state.img.height);
      ctx.arc(state.plate.cx, state.plate.cy, state.plate.r, 0, Math.PI * 2, true);
      ctx.fillStyle = 'rgba(20,22,26,0.92)';
      ctx.fill('evenodd');
      ctx.restore();
    }
  }

  if (state.plate) {
    ctx.strokeStyle = 'rgba(170,170,170,0.9)';
    ctx.lineWidth = 2 / state.view.zoom;
    ctx.beginPath();
    ctx.arc(state.plate.cx, state.plate.cy, state.plate.r, 0, Math.PI * 2);
    ctx.stroke();
  }

  ctx.lineWidth = 3 / state.view.zoom;
  ctx.font = `${Math.max(11, 16 / state.view.zoom)}px sans-serif`;
  for (const d of state.detections) {
    // Match overlay.py colors and CSS legend dots:
    // machine-detected = blue, manually-added = green.
    const color = d.source === 'manual' ? '#54d486' : '#4a9fef';
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(d.cx, d.cy, Math.max(d.r, 4), 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillText(String(d.id), d.cx + d.r + 4, d.cy - 4);
  }
  ctx.restore();
  updateCountBadge();
}

// ── interactions (optimistic) ────────────────────────────────────────────

function findHit(ix, iy) {
  let best = null, bestArea = Infinity;
  for (const d of state.detections) {
    const dx = ix - d.cx, dy = iy - d.cy;
    if (dx * dx + dy * dy <= d.r * d.r) {
      const a = d.r * d.r;
      if (a < bestArea) { bestArea = a; best = d; }
    }
  }
  return best;
}

function localNextId() {
  return state.detections.reduce((m, d) => Math.max(m, d.id), 0) + 1;
}

let _imgListDirty = false;
function debouncedImageListRefresh() {
  if (_imgListDirty) return;
  _imgListDirty = true;
  setTimeout(() => { _imgListDirty = false; loadImages(); }, 400);
}

async function onMouseDownCanvas(evt) {
  if (evt.metaKey || evt.ctrlKey || evt.button === 1) {
    evt.preventDefault();
    state.dragPan = { sx: evt.clientX, sy: evt.clientY, ox: state.view.ox, oy: state.view.oy };
  }
}

async function onClickCanvas(evt) {
  if (state.dragPan) return;
  if (evt.metaKey || evt.ctrlKey) return;
  if (!state.batch || !state.imageName || !state.img) return;

  const rect = $('canvas').getBoundingClientRect();
  const sx = evt.clientX - rect.left, sy = evt.clientY - rect.top;
  const [ix, iy] = screenToImg(sx, sy);

  if (state.plate) {
    const dx = ix - state.plate.cx, dy = iy - state.plate.cy;
    if (dx * dx + dy * dy > state.plate.r * state.plate.r) return;
  }
  if (findHit(ix, iy)) return; // left click on existing circle = no-op

  // Optimistic add: paint immediately, sync to server in background.
  const r = parseFloat($('p-radius').value) || 40;
  const tempId = -Date.now();
  const optimisticDet = { id: tempId, cx: ix, cy: iy, r, score: 1, accepted: true, source: 'manual' };
  state.detections.push(optimisticDet);
  draw();
  state.history.push({ kind: 'add', tempId });

  fetch(imgURL('/detections'), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ cx: ix, cy: iy, r }),
  }).then(r => r.json()).then(resp => {
    const d = state.detections.find(x => x.id === tempId);
    if (d) d.id = resp.id;
    // history entry: replace tempId with real id
    const h = state.history.find(h => h.kind === 'add' && h.tempId === tempId);
    if (h) h.id = resp.id;
    draw();
    debouncedImageListRefresh();
  }).catch(() => { /* swallow; UI is optimistic */ });
}

async function onContextMenu(evt) {
  evt.preventDefault();
  if (!state.batch || !state.imageName || !state.img) return;
  const rect = $('canvas').getBoundingClientRect();
  const sx = evt.clientX - rect.left, sy = evt.clientY - rect.top;
  const [ix, iy] = screenToImg(sx, sy);
  const hit = findHit(ix, iy);
  if (!hit) return;

  // Optimistic delete
  const snapshot = { ...hit };
  state.detections = state.detections.filter(d => d.id !== hit.id);
  draw();
  state.history.push({ kind: 'delete', det: snapshot });

  fetch(imgURL(`/detections/${hit.id}`), { method: 'DELETE' })
    .then(() => debouncedImageListRefresh())
    .catch(() => { /* swallow */ });
}

function onWheel(evt) {
  evt.preventDefault();
  if (!state.img) return;
  const rect = $('canvas').getBoundingClientRect();
  const sx = evt.clientX - rect.left, sy = evt.clientY - rect.top;
  const [ix, iy] = screenToImg(sx, sy);
  const factor = evt.deltaY < 0 ? 1.15 : 1 / 1.15;
  state.view.zoom *= factor;
  state.view.ox = sx - ix * state.view.zoom;
  state.view.oy = sy - iy * state.view.zoom;
  draw();
}

function onMouseMove(evt) {
  if (!state.dragPan) return;
  state.view.ox = state.dragPan.ox + (evt.clientX - state.dragPan.sx);
  state.view.oy = state.dragPan.oy + (evt.clientY - state.dragPan.sy);
  draw();
}

function onMouseUp() { setTimeout(() => { state.dragPan = null; }, 50); }

async function undo() {
  const last = state.history.pop();
  if (!last) return;
  if (last.kind === 'add') {
    const id = last.id ?? last.tempId;
    state.detections = state.detections.filter(d => d.id !== id);
    draw();
    if (last.id) fetch(imgURL(`/detections/${last.id}`), { method: 'DELETE' });
  } else if (last.kind === 'delete') {
    const tempId = -Date.now();
    state.detections.push({ ...last.det, id: tempId });
    draw();
    fetch(imgURL('/detections'), {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ cx: last.det.cx, cy: last.det.cy, r: last.det.r }),
    }).then(r => r.json()).then(resp => {
      const d = state.detections.find(x => x.id === tempId);
      if (d) d.id = resp.id;
      draw();
    });
  }
  debouncedImageListRefresh();
}

function moveSelection(delta) {
  if (!state.imageList.length) return;
  const idx = state.imageList.findIndex(i => i.name === state.imageName);
  const j = Math.max(0, Math.min(state.imageList.length - 1, (idx < 0 ? 0 : idx) + delta));
  if (state.imageList[j]) selectImage(state.imageList[j].name);
}

// ── live mask preview ────────────────────────────────────────────────────

let _previewTimer = null;
async function refreshMaskPreview() {
  if (!$('p-preview').checked || !state.batch || !state.imageName) {
    state.maskPreview = null; draw(); return;
  }
  clearTimeout(_previewTimer);
  _previewTimer = setTimeout(async () => {
    const r = await fetch(imgURL('/mask_preview.png'), {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(paramsBody()),
    });
    if (!r.ok) return;
    const blob = await r.blob();
    const im = new Image();
    im.onload = () => { state.maskPreview = im; draw(); };
    im.src = URL.createObjectURL(blob);
  }, 200);
}

// ── ingestion ───────────────────────────────────────────────────────────

async function ingestPath(p) {
  setStatus(t('statusIngesting'));
  const r = await fetch('/api/ingest', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ paths: [p] }),
  }).then(r => r.json());
  setStatus('');
  state.batch = r.batch;
  await loadImages();
}

async function uploadFiles(fileList) {
  const batch = 'upload_' + new Date().toISOString().replace(/[:.]/g, '-');
  const fd = new FormData();
  fd.append('batch', batch);
  for (const f of fileList) fd.append('files', f);
  setStatus(t('statusUploading'));
  await fetch('/api/upload', { method: 'POST', body: fd });
  setStatus('');
  state.batch = batch;
  await loadImages();
}

async function walkDir(entry, out) {
  const reader = entry.createReader();
  await new Promise(resolve => {
    const read = () => reader.readEntries(async entries => {
      if (!entries.length) { resolve(); return; }
      for (const e of entries) {
        if (e.isFile) await new Promise(res => e.file(f => { out.push(f); res(); }));
        else if (e.isDirectory) await walkDir(e, out);
      }
      read();
    });
    read();
  });
}

// ── export modal ────────────────────────────────────────────────────────

let _exportFormat = 'csv';

function openExportModal(format) {
  _exportFormat = format;
  // Default filename: input image name if exactly one image, else session label
  let base;
  if (state.imageList.length === 1) {
    base = state.imageList[0].name.replace(/\.[^.]+$/, '');
  } else if (state.imageName) {
    base = `wecfu_${state.batch}`;
  } else {
    base = `wecfu_${state.batch}`;
  }
  const ext = format === 'csv' ? '.csv' : '.zip';
  $('export-filename').value = base + ext;
  $('export-backdrop').hidden = false;
  $('export-format-row').hidden = true; // we know format from which button was clicked
  $('export-filename').focus();
  $('export-filename').select();
}

async function pickSaveLocation() {
  // Chrome / Edge support showDirectoryPicker; Safari / Firefox do not.
  if (!window.showDirectoryPicker) {
    alert(t('exportSaveLocationDefault'));
    return;
  }
  try {
    state.saveDirHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
    $('export-location-btn').textContent = state.saveDirHandle.name + '/';
  } catch (_) { /* cancelled */ }
}

async function doExport() {
  const fname = $('export-filename').value.trim() || `wecfu_${state.batch}.${_exportFormat}`;
  const ext = _exportFormat === 'csv' ? '.csv' : '.zip';
  const finalName = fname.toLowerCase().endsWith(ext) ? fname : fname + ext;
  const url = `/api/batch/${enc(state.batch)}/export.${_exportFormat}?filename=${enc(finalName)}`;

  setStatus(t('statusProcessing'));
  const resp = await fetch(url);
  if (!resp.ok) { alert('Export failed'); setStatus(''); return; }
  const blob = await resp.blob();

  if (state.saveDirHandle && window.showDirectoryPicker) {
    try {
      const fh = await state.saveDirHandle.getFileHandle(finalName, { create: true });
      const w = await fh.createWritable();
      await w.write(blob); await w.close();
      setStatus(t('statusDone'));
      $('export-backdrop').hidden = true;
      return;
    } catch (e) {
      console.warn('save to directory failed, falling back to download', e);
    }
  }

  // Fallback: regular browser download
  const u = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = u; a.download = finalName;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(u);
  setStatus(t('statusDone'));
  $('export-backdrop').hidden = true;
}

// ── help modal ──────────────────────────────────────────────────────────

function openHelp() {
  $('help-body').innerHTML = t('helpBody');
  $('modal-backdrop').hidden = false;
}
function closeHelp() { $('modal-backdrop').hidden = true; }

// ── language switcher ──────────────────────────────────────────────────

function populateLangSelect() {
  const sel = $('lang-select');
  sel.innerHTML = '';
  for (const [code, name] of Object.entries(LANG_NAMES)) {
    const opt = document.createElement('option');
    opt.value = code; opt.textContent = name;
    sel.appendChild(opt);
  }
  sel.value = getLang();
  sel.addEventListener('change', e => {
    setLang(e.target.value);
    // re-render anything that has translated text in JS
    renderImageList();
    updateCountBadge();
    if ($('help-body').innerHTML) $('help-body').innerHTML = t('helpBody');
  });
}

// ── wiring ──────────────────────────────────────────────────────────────

function wireUpHandlers() {
  $('btn-ingest').addEventListener('click', async () => {
    const p = $('path-input').value.trim();
    if (p) await ingestPath(p);
  });

  $('btn-run').addEventListener('click', async () => {
    if (!state.batch) return;
    setStatus(t('statusProcessing'));
    await fetch(`/api/batch/${enc(state.batch)}/run?force=false`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(paramsBody()),
    });
    setStatus(t('statusDone'));
    await loadImages();
    if (state.imageName) await loadDetections();
  });

  $('btn-rerun').addEventListener('click', async () => {
    if (!state.batch || !state.imageName) return;
    setStatus(t('statusProcessing'));
    await fetch(imgURL('/run'), {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(paramsBody()),
    });
    setStatus(t('statusDone'));
    await loadDetections(); loadImages();
  });

  $('btn-apply-params').addEventListener('click', () => $('btn-rerun').click());

  $('btn-export-csv').addEventListener('click', () => state.batch && openExportModal('csv'));
  $('btn-export-zip').addEventListener('click', () => state.batch && openExportModal('zip'));
  $('btn-export-cancel').addEventListener('click', () => { $('export-backdrop').hidden = true; });
  $('btn-export-confirm').addEventListener('click', doExport);
  $('export-location-btn').addEventListener('click', pickSaveLocation);

  $('btn-help').addEventListener('click', openHelp);
  $('btn-help-close').addEventListener('click', closeHelp);
  $('modal-backdrop').addEventListener('click', e => { if (e.target.id === 'modal-backdrop') closeHelp(); });
  $('export-backdrop').addEventListener('click', e => { if (e.target.id === 'export-backdrop') $('export-backdrop').hidden = true; });

  $('btn-undo').addEventListener('click', undo);

  $('preset-select').addEventListener('change', e => {
    if (e.target.value !== 'custom') applyPreset(e.target.value);
    refreshMaskPreview();
  });

  for (const id of ['p-min-value', 'p-max-sat', 'p-inset', 'p-circ', 'p-min-area', 'p-peak']) {
    $(id).addEventListener('input', () => {
      $('preset-select').value = 'custom';
      refreshMaskPreview();
    });
  }
  $('p-preview').addEventListener('change', refreshMaskPreview);

  $('notes-input').addEventListener('change', async () => {
    if (!state.batch || !state.imageName) return;
    await fetch(imgURL('/notes'), {
      method: 'PUT', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ notes: $('notes-input').value }),
    });
    loadImages();
  });

  const c = $('canvas');
  c.addEventListener('mousedown', onMouseDownCanvas);
  c.addEventListener('click', onClickCanvas);
  c.addEventListener('contextmenu', onContextMenu);
  c.addEventListener('wheel', onWheel, { passive: false });
  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('mouseup', onMouseUp);
  window.addEventListener('resize', () => { fitToCanvas(); draw(); });

  window.addEventListener('keydown', e => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return;
    if ((e.metaKey || e.ctrlKey) && e.key === 'z') { e.preventDefault(); undo(); return; }
    if (e.key === 'Escape') { closeHelp(); $('export-backdrop').hidden = true; return; }
    if (e.key === 'ArrowRight' || e.key === 'j') moveSelection(1);
    else if (e.key === 'ArrowLeft' || e.key === 'k') moveSelection(-1);
  });

  const dz = $('dropzone');
  dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('dragging'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('dragging'));
  dz.addEventListener('drop', async e => {
    e.preventDefault();
    dz.classList.remove('dragging');
    const files = [];
    for (const it of e.dataTransfer.items) {
      const entry = it.webkitGetAsEntry?.();
      if (entry?.isFile) files.push(it.getAsFile());
      else if (entry?.isDirectory) await walkDir(entry, files);
      else if (it.kind === 'file') files.push(it.getAsFile());
    }
    if (files.length) await uploadFiles(files);
  });
}

// Bootstrap: wire up handlers FIRST so buttons work even if the initial
// data fetch fails (e.g. fresh install with no batches yet). Then load.
window.addEventListener('DOMContentLoaded', async () => {
  try { applyI18n(); } catch (e) { console.warn('applyI18n failed:', e); }
  try { populateLangSelect(); } catch (e) { console.warn('populateLangSelect failed:', e); }
  try { wireUpHandlers(); } catch (e) { console.error('wireUpHandlers failed:', e); }
  try { await loadDefaultBatch(); } catch (e) { console.warn('loadDefaultBatch failed:', e); }
});
