// CFU counter — frontend.
// Click model:
//   • Left click on empty plate → add a manual colony (default radius)
//   • Right click on a circle    → delete it
//   • Wheel → zoom (anchored at cursor)
//   • Cmd/Ctrl + drag → pan
//   • ← / →                       prev/next image
//   • Cmd/Ctrl-Z                  undo last action (server replays/inserts)

const $ = (id) => document.getElementById(id);

const PRESETS = {
  white:  { min_value: 200, max_saturation: 60,  min_circularity: 0.55 },
  cream:  { min_value: 180, max_saturation: 100, min_circularity: 0.55 },
  yellow: { min_value: 160, max_saturation: 200, min_circularity: 0.50 },
  any:    { min_value: 140, max_saturation: 255, min_circularity: 0.45 },
};

const state = {
  batch: null,
  imageName: null,
  imageList: [],
  detections: [],
  plate: null,
  img: null,
  view: { zoom: 1, ox: 0, oy: 0 },
  dragPan: null,
  history: [],              // for undo: list of { kind:'add'|'delete', det }
  maskPreview: null,        // HTMLImageElement when live preview is on
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
function imgURL(suffix) {
  return `/api/batch/${enc(state.batch)}/image/${enc(state.imageName)}${suffix}`;
}

// ── batches + image list ─────────────────────────────────────────────────

async function loadBatches() {
  const r = await fetch('/api/batches').then(r => r.json());
  const sel = $('batch-select');
  sel.innerHTML = '';
  for (const b of r.batches) {
    const opt = document.createElement('option');
    opt.value = b; opt.textContent = b;
    sel.appendChild(opt);
  }
  const want = r.default && r.batches.includes(r.default) ? r.default : r.batches[0];
  if (want) {
    sel.value = want;
    state.batch = want;
    await loadImages();
  }
}

async function loadImages() {
  if (!state.batch) return;
  const r = await fetch(`/api/batch/${enc(state.batch)}/images`).then(r => r.json());
  state.imageList = r.images;
  const list = $('image-list');
  list.innerHTML = '';
  for (const it of r.images) {
    const row = document.createElement('div');
    row.className = 'image-row';
    if (it.reviewed) row.classList.add('reviewed');
    if (it.low_confidence) row.classList.add('low-conf');
    if (it.notes) row.classList.add('has-notes');
    if (it.name === state.imageName) row.classList.add('selected');
    row.innerHTML = `
      <span class="row-flag"></span>
      <span class="row-name" title="${it.name}${it.notes ? ' — ' + it.notes : ''}">${it.name}</span>
      <span class="row-count">${it.processed ? it.count : '–'}</span>`;
    row.addEventListener('click', () => selectImage(it.name));
    list.appendChild(row);
  }
}

async function selectImage(name) {
  state.imageName = name;
  state.history = [];
  $('current-name').textContent = name;
  await loadImages();
  await loadDetections();
  $('notes-input').value = state.imageList.find(i => i.name === name)?.notes || '';
}

async function loadDetections() {
  if (!state.batch || !state.imageName) return;
  const r = await fetch(imgURL('/detections'));
  if (!r.ok) {
    state.detections = []; state.plate = null;
    await loadRawImage(); fitToCanvas(); draw();
    $('count-badge').textContent = '— (未计数)';
    $('meta-tag').textContent = '';
    return;
  }
  const data = await r.json();
  state.detections = data.detections;
  state.plate = data.plate;
  $('count-badge').textContent = `${data.detections.length} CFU`;
  const lc = data.diagnostics?.low_confidence ? ' · 低置信' : '';
  const rv = data.reviewed ? ' · 已复核' : '';
  $('meta-tag').textContent = `· ${data.method || 'cv'}${rv}${lc}`;
  await loadRawImage();
  fitToCanvas();
  draw();
}

async function loadRawImage() {
  if (!state.batch || !state.imageName) return;
  return new Promise(resolve => {
    const im = new Image();
    im.onload = () => { state.img = im; resolve(); };
    im.src = imgURL('/raw') + `?t=${Date.now()}`;
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
  // If we have a plate circle, fit the plate bbox; else fit the whole image.
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
  // center on cxImg, cyImg
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

  // Either show the raw photo, or the live mask preview (which already contains the image tinted green).
  const baseImg = state.maskPreview || state.img;
  if (state.maskPreview && state.plate) {
    // mask preview is cropped to plate bbox — draw it at the bbox origin
    const pad = 24;
    const x0 = state.plate.cx - state.plate.r - pad;
    const y0 = state.plate.cy - state.plate.r - pad;
    ctx.drawImage(baseImg, x0, y0);
  } else {
    ctx.drawImage(baseImg, 0, 0);
    // mask outside plate with neutral grey
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

  // plate ring
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
    const color = d.source === 'manual' ? '#28a0f0'
                : d.source === 'sam' ? '#c83cdc' : '#28dc28';
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(d.cx, d.cy, Math.max(d.r, 4), 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillText(String(d.id), d.cx + d.r + 4, d.cy - 4);
  }
  ctx.restore();
  $('count-badge').textContent = `${state.detections.length} CFU`;
}

// ── interactions ─────────────────────────────────────────────────────────

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

async function onMouseDownCanvas(evt) {
  // pan with cmd/ctrl
  if (evt.metaKey || evt.ctrlKey || evt.button === 1) {
    evt.preventDefault();
    state.dragPan = { sx: evt.clientX, sy: evt.clientY, ox: state.view.ox, oy: state.view.oy };
    return;
  }
  if (evt.button === 2) return; // right click handled separately
}

async function onClickCanvas(evt) {
  if (state.dragPan) return; // was a drag
  if (evt.metaKey || evt.ctrlKey) return;
  if (!state.batch || !state.imageName || !state.img) return;
  const rect = $('canvas').getBoundingClientRect();
  const sx = evt.clientX - rect.left, sy = evt.clientY - rect.top;
  const [ix, iy] = screenToImg(sx, sy);
  // ignore clicks outside the plate
  if (state.plate) {
    const dx = ix - state.plate.cx, dy = iy - state.plate.cy;
    if (dx * dx + dy * dy > state.plate.r * state.plate.r) return;
  }
  const hit = findHit(ix, iy);
  if (hit) return; // left click on an existing circle = no-op
  const r = parseFloat($('p-radius').value) || 40;
  const resp = await fetch(imgURL('/detections'), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ cx: ix, cy: iy, r }),
  }).then(r => r.json());
  state.history.push({ kind: 'add', id: resp.id });
  await loadDetections();
  loadImages();
}

async function onContextMenu(evt) {
  evt.preventDefault();
  if (!state.batch || !state.imageName || !state.img) return;
  const rect = $('canvas').getBoundingClientRect();
  const sx = evt.clientX - rect.left, sy = evt.clientY - rect.top;
  const [ix, iy] = screenToImg(sx, sy);
  const hit = findHit(ix, iy);
  if (!hit) return;
  state.history.push({ kind: 'delete', det: { ...hit } });
  await fetch(imgURL(`/detections/${hit.id}`), { method: 'DELETE' });
  await loadDetections();
  loadImages();
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
    await fetch(imgURL(`/detections/${last.id}`), { method: 'DELETE' });
  } else if (last.kind === 'delete') {
    await fetch(imgURL('/detections'), {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ cx: last.det.cx, cy: last.det.cy, r: last.det.r }),
    });
  }
  await loadDetections();
  loadImages();
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
  setStatus('导入中…');
  const r = await fetch('/api/ingest', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ paths: [p] }),
  }).then(r => r.json());
  setStatus(`已建链 ${r.linked} 个文件到批次 ${r.batch}`);
  await loadBatches();
  $('batch-select').value = r.batch;
  state.batch = r.batch;
  await loadImages();
}

async function uploadFiles(fileList) {
  const batch = 'upload_' + new Date().toISOString().replace(/[:.]/g, '-');
  const fd = new FormData();
  fd.append('batch', batch);
  for (const f of fileList) fd.append('files', f);
  setStatus(`上传 ${fileList.length} 个文件…`);
  await fetch('/api/upload', { method: 'POST', body: fd });
  setStatus(`已上传到批次 ${batch}`);
  await loadBatches();
  $('batch-select').value = batch;
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

// ── wiring ──────────────────────────────────────────────────────────────

window.addEventListener('DOMContentLoaded', async () => {
  await loadBatches();

  $('batch-select').addEventListener('change', async e => {
    state.batch = e.target.value;
    state.imageName = null;
    await loadImages();
  });

  $('btn-ingest').addEventListener('click', async () => {
    const p = $('path-input').value.trim();
    if (p) await ingestPath(p);
  });

  $('btn-run').addEventListener('click', async () => {
    if (!state.batch) return;
    setStatus('计数批次中…');
    const r = await fetch(`/api/batch/${enc(state.batch)}/run?force=false`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(paramsBody()),
    }).then(r => r.json());
    setStatus(`完成 ${r.processed} 张`);
    await loadImages();
    if (state.imageName) await loadDetections();
  });

  $('btn-rerun').addEventListener('click', async () => {
    if (!state.batch || !state.imageName) return;
    setStatus('重跑当前图…');
    await fetch(imgURL('/run'), {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(paramsBody()),
    });
    setStatus('完成');
    await loadDetections(); loadImages();
  });

  $('btn-sam').addEventListener('click', async () => {
    if (!state.batch || !state.imageName) return;
    setStatus('SAM 运行中 (CPU 大约 30s)…');
    const r = await fetch(imgURL('/sam'), { method: 'POST' });
    if (!r.ok) { alert('SAM 失败:\n' + await r.text()); setStatus('SAM 不可用'); return; }
    setStatus('SAM 完成');
    await loadDetections(); loadImages();
  });

  $('btn-mark-reviewed').addEventListener('click', async () => {
    if (!state.batch || !state.imageName) return;
    await fetch(imgURL('/reviewed?reviewed=true'), { method: 'POST' });
    loadImages();
  });

  $('btn-apply-params').addEventListener('click', () => $('btn-rerun').click());

  $('btn-export-csv').addEventListener('click', () => {
    if (!state.batch) return;
    window.location = `/api/batch/${enc(state.batch)}/export.csv`;
  });

  $('btn-export-zip').addEventListener('click', () => {
    if (!state.batch) return;
    window.location = `/api/batch/${enc(state.batch)}/export.zip`;
  });

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
    // skip typing in inputs
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return;
    if ((e.metaKey || e.ctrlKey) && e.key === 'z') { e.preventDefault(); undo(); return; }
    if (e.key === 'ArrowRight' || e.key === 'j') moveSelection(1);
    else if (e.key === 'ArrowLeft' || e.key === 'k') moveSelection(-1);
    else if (e.key === ' ') {
      e.preventDefault();
      if (state.batch && state.imageName) $('btn-mark-reviewed').click();
    }
  });

  // dropzone
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
});
