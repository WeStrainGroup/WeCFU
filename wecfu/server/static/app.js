// Internal WeCFU: instant local edits, serialized snapshot saves and bounded rendering.
'use strict';
const $ = id => document.getElementById(id);
const {t, applyI18n, setLang, getLang, LANG_NAMES} = window.WECFU_I18N;
const paramControls = window.WECFU_PARAM_CONTROLS;
const referenceHelpers = window.WECFU_REFERENCE_CONTROLS;
const modelHelpers = window.WECFU_MODEL_PREVIEW_CONTROLS;
const reviewHelpers = window.WECFU_REVIEW_QUEUE_CONTROLS;
const workflowHelpers = window.WECFU_WORKFLOW_CONTROLS;
const MODEL_ENGINE = 'cfucounter_onnx_author_v1';
const SAM_ENGINE = 'sam2_local_v1';
const FUSION_ENGINE = 'sam_dino_fusion_local_v1';
const FUSION_V2_ENGINE = 'sam_dino_fusion_local_v2';
const ASSISTED_ENGINE = 'sam2_cv_frozen_v1';
const ENHANCED_ENGINE = 'component_watershed_v1';
const LEGACY_DEFAULTS = {plate_inset: 0.82, min_value: 200, max_saturation: 60,
  min_circularity: 0.55, min_area_frac: 0.0001, peak_min_distance: 15};
const DEFAULTS = {...LEGACY_DEFAULTS, plate_inset: 0.95, max_saturation: 100};
const PRESETS = {
  white: {...DEFAULTS},
  legacy: {...LEGACY_DEFAULTS},
  cream: {...LEGACY_DEFAULTS, min_value: 180, max_saturation: 100},
  yellow: {...LEGACY_DEFAULTS, min_value: 160, max_saturation: 200, min_circularity: 0.50},
  any: {...LEGACY_DEFAULTS, min_value: 140, max_saturation: 255, min_circularity: 0.45},
};
const PARAM_IDS = {plate_inset: 'p-inset', min_value: 'p-min-value', max_saturation: 'p-max-sat',
  min_circularity: 'p-circ', min_area_frac: 'p-min-area', peak_min_distance: 'p-peak'};
const pointerSelects = new WeakSet();
const state = {
  batch: null, imageName: null, imageList: [], doc: null, detections: [], plate: null,
  img: null, display: null, imgUrl: null, view: {zoom: 1, ox: 0, oy: 0, fitted: true},
  canvasSize: {width: 0, height: 0, ratio: 1},
  history: [], loading: false, busy: false, navToken: 0, gesture: null, crop: null,
  paramsDirty: false, preview: null, previewToken: 0, previewController: null, previewStatus: '',
  saveQueues: new Map(), saveDirHandle: null, cancelRun: false, frame: null, backdrop: null,
  backdropDirty: true, imageSourceHash: null,
  reference: {key: null, envelope: null, loading: false, error: '', geometry: null, token: 0, controller: null},
  batchRun: {active: false, report: null},
  bulkSelection: {enabled: false, batch: null, names: new Set()},
  modelPreview: {candidate: null, signature: null, token: 0, controller: null, timer: null,
    loading: false, error: '', message: '', pendingApply: null, engine: null},
  review: {requested: false, id: null, queue: null, signature: null, loading: false, error: '',
    refreshing: null, statuses: new Map()},
  workflow: {enabled: false, kind: 'default', customParams: null, appliedCustomParams: null, adjustmentsOpen: false},
};
const enc = encodeURIComponent;
const clone = value => JSON.parse(JSON.stringify(value));
const keyFor = (batch = state.batch, name = state.imageName) => `${batch}\n${name}`;
const imageURL = (suffix = '', batch = state.batch, name = state.imageName) =>
  `/api/batch/${enc(batch)}/image/${enc(name)}${suffix}`;
function setStatus(message, error = false) {
  $('status').textContent = message;
  $('status').classList.toggle('error', error);
}
async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try { const body = await response.json(); message = body.detail || message; } catch (_) { /* no JSON */ }
    const error = new Error(typeof message === 'string' ? message : JSON.stringify(message));
    error.status = response.status; throw error;
  }
  return response;
}
async function jsonRequest(url, method = 'GET', body) {
  return (await request(url, {method, ...(body !== undefined ? {
    headers: {'content-type': 'application/json'}, body: JSON.stringify(body)} : {})})).json();
}
function handleError(error) { console.error(error); setStatus(`${t('actionFailed')}: ${error.message}`, true); }
function safeAction(fn) { return (...args) => {
  try { return Promise.resolve(fn(...args)).catch(handleError); } catch (error) { handleError(error); }
}; }
function applyPending() { return Boolean(state.modelPreview.pendingApply); }
function reviewMode() { return state.review.requested; }
function manualOnlyReview() { return reviewMode() && state.review.queue?.annotation_mode === 'manual_only'; }
function assistedFrozenReview() { return reviewMode() && state.review.queue?.annotation_mode === 'assisted_frozen'; }
function restrictedReview() { return manualOnlyReview() || assistedFrozenReview(); }
function normalWorkflow() { return state.workflow.enabled && !reviewMode(); }
function customWorkflow() { return normalWorkflow() && state.workflow.kind === 'custom'; }
function workflowBuiltinEngine() { return builtinEngines().includes(ENHANCED_ENGINE) ? ENHANCED_ENGINE : defaultBuiltinEngine(); }
function workflowDefaultEngine() {
  // Profile labels have one meaning on every host; missing SAM must never masquerade as Lite.
  return state.workflow.kind === 'classical' ? workflowBuiltinEngine() : SAM_ENGINE;
}
function syncWorkflowRoute() {
  if (!normalWorkflow()) return;
  $('method-select').value = customWorkflow() ? workflowBuiltinEngine()
    : state.modelPreview.engine || workflowDefaultEngine();
}
function workflowParams() {
  return customWorkflow() ? state.workflow.customParams || DEFAULTS : DEFAULTS;
}
function appliedCustomParams() { return {...(state.workflow.appliedCustomParams || DEFAULTS)}; }
function customDraftPending() {
  const draft = state.workflow.customParams || DEFAULTS, applied = appliedCustomParams();
  return Object.keys(DEFAULTS).some(key => Number(draft[key]) !== Number(applied[key]));
}
function applyCustomSettings() {
  if (!customWorkflow() || state.loading || state.busy || state.crop || previewActive()) return;
  // Commit a number being edited before capturing the recipe. This never changes image state.
  for (const [key, spec] of Object.entries(paramControls.SPECS)) {
    if (key === 'radius') continue;
    const input = $(`v-${spec.id}`);
    if (input.dataset.edited === '1') commitSliderValue(key);
    if (input.getAttribute('aria-invalid') === 'true') { setStatus(t('normalizedValueInvalid'), true); return; }
  }
  state.workflow.customParams = {...paramsBody()};
  state.workflow.appliedCustomParams = {...state.workflow.customParams};
  state.workflow.adjustmentsOpen = false;
  clearPreview(); updateControls(); draw(); focusCanvas(); setStatus(t('customSettingsApplied'));
}
function toggleAdjustmentPanel() {
  if (!customWorkflow() || state.loading || state.busy || state.crop || previewActive()) return;
  state.workflow.adjustmentsOpen = !state.workflow.adjustmentsOpen;
  if (state.workflow.adjustmentsOpen) { $('custom-settings').open = true; fillParams(workflowParams()); }
  else clearPreview();
  updateControls(); draw(); refreshMaskPreview(); focusCanvas();
}
function modalOpen() { return !$('modal-backdrop').hidden || !$('export-backdrop').hidden; }
function focusCanvas({preserveEditing = false} = {}) {
  if (modalOpen()) return;
  if (preserveEditing && workflowHelpers?.ownsArrowKeys(document.activeElement)) return;
  const canvas = $('canvas'); canvas.tabIndex = 0;
  canvas.focus?.({preventScroll: true});
}
function focusAfterSelect(select) {
  if (!pointerSelects.has(select)) return; // Native keyboard option navigation must remain continuous.
  pointerSelects.delete(select); focusCanvas();
}
function revealSelectedRow() {
  const list = $('image-list');
  if (list.hidden) return;
  const row = Array.from(list.children).find(item => item.dataset.name === state.imageName);
  if (!row || !workflowHelpers || !list.getBoundingClientRect || !row.getBoundingClientRect) return;
  const bounds = list.getBoundingClientRect(), item = row.getBoundingClientRect();
  // scrollIntoView can move the page and canvas; adjust only this list's viewport.
  list.scrollTop = workflowHelpers.visibleScrollTop({scrollTop: list.scrollTop, clientHeight: list.clientHeight,
    scrollHeight: list.scrollHeight, viewportTop: bounds.top + (list.clientTop || 0), rowTop: item.top, rowBottom: item.bottom});
}
function updateSelectedRows({reveal = false} = {}) {
  for (const row of $('image-list').children) {
    const current = row.dataset.name === state.imageName;
    row.classList.toggle('selected', current);
    if (current) row.setAttribute?.('aria-current', 'true'); else row.removeAttribute?.('aria-current');
  }
  if (reveal) revealSelectedRow();
}
function validateReviewState(doc) {
  if (manualOnlyReview()) reviewHelpers.validateManualState(doc);
  if (assistedFrozenReview()) reviewHelpers.validateAssistedState(doc);
}
function reviewBlocked() { return reviewMode() && (state.review.loading || state.review.error || !state.review.queue); }
function builtinEngines() {
  const supplied = state.config?.builtin_algorithms;
  return Array.isArray(supplied) && supplied.includes(ENHANCED_ENGINE) ? ['baseline', ENHANCED_ENGINE] : ['baseline'];
}
function defaultBuiltinEngine() {
  return builtinEngines().includes(state.config?.default_count_engine) ? state.config.default_count_engine : 'baseline';
}
function selectedBuiltinEngine() {
  const selected = $('method-select').value;
  return builtinEngines().includes(selected) ? selected : defaultBuiltinEngine();
}
function methodForDocument(doc) {
  const hasSavedCount = doc.counted || (doc.counted === undefined && (doc.machine_count_initial > 0 || doc.detections?.length));
  if (!hasSavedCount) return defaultBuiltinEngine();
  const saved = doc.count_engine || 'baseline';
  if (builtinEngines().includes(saved)) return saved;
  if (modelHelpers?.isModelEngine?.(saved) && !reviewMode() && modelCapability(saved).enabled) return saved;
  return defaultBuiltinEngine();
}
function selectedModelEngine() {
  const engine = normalWorkflow() && !customWorkflow() && state.modelPreview.engine
    ? state.modelPreview.engine : $('method-select').value;
  return modelHelpers?.isModelEngine?.(engine) ? engine : null;
}
function previewActive() {
  const trial = state.modelPreview;
  return Boolean(trial.engine || trial.candidate || trial.loading || trial.pendingApply);
}
function modelCapability(engine = selectedModelEngine()) {
  return modelHelpers?.capability?.(state.config, engine) || {enabled: false, available: false};
}
function modelMethod() { return !reviewMode() && selectedModelEngine() !== null; }
function samMethod() { return modelMethod() && selectedModelEngine() === SAM_ENGINE; }
function fusionMethod() { return modelMethod() && [FUSION_ENGINE, FUSION_V2_ENGINE].includes(selectedModelEngine()); }
function fixedRecipeMethod() { return samMethod() || fusionMethod(); }
function modelInset() { return fixedRecipeMethod() ? modelHelpers.SAM_INSET : Number($('p-inset').value); }
function editable() { return Boolean(state.doc && state.img && !state.loading && !state.busy && !state.crop && !applyPending() && !reviewBlocked()); }
function snapshot() {
  validateReviewState({...state.doc, detections: state.detections});
  return {detections: clone(state.detections), plate: clone(state.plate),
    mode: state.doc.mode || 'auto', machine_count_initial: state.doc.machine_count_initial || 0,
    notes: state.doc.notes || '', plate_manual: Boolean(state.doc.plate_manual),
    reviewed: Boolean(state.doc.reviewed), params: clone(state.doc.params || DEFAULTS),
    counted: Boolean(state.doc.counted), count_params: state.doc.count_params ? clone(state.doc.count_params) : null,
    count_engine: state.doc.count_engine === undefined ? (manualOnlyReview() ? null : 'baseline') : state.doc.count_engine,
    count_model: state.doc.count_model ? clone(state.doc.count_model) : null};
}
function paramsDiffer() {
  if (state.doc?.mode === 'manual' || state.doc?.count_engine === ASSISTED_ENGINE || state.doc?.count_engine === SAM_ENGINE || [FUSION_ENGINE, FUSION_V2_ENGINE].includes(state.doc?.count_engine)) return false;
  if (state.doc?.count_engine === MODEL_ENGINE) {
    // Only the adopted model ROI affects this count; HSV settings belong to the traditional method.
    const adoptedInset = Number(state.doc.count_model?.plate_inset);
    return Number.isFinite(adoptedInset) && Number(state.doc.params?.plate_inset ?? DEFAULTS.plate_inset) !== adoptedInset;
  }
  const last = state.doc?.count_params || DEFAULTS;
  return state.doc?.mode !== 'manual' && Object.keys(DEFAULTS).some(key => Number(state.doc?.params?.[key] ?? DEFAULTS[key]) !== Number(last[key] ?? DEFAULTS[key]));
}
function adopt(data, {syncParams = true} = {}) {
  validateReviewState(data);
  state.doc = clone(data);
  state.detections = state.doc.detections || [];
  state.plate = state.doc.plate;
  state.doc.mode = state.doc.mode || 'auto';
  state.doc.machine_count_initial ??= state.detections.filter(d => d.source !== 'manual').length;
  // Older saved counts predate the counted flag; preserve their provenance on the next ordinary save.
  if (state.doc.counted === undefined) {
    state.doc.counted = state.doc.mode !== 'manual' && (state.doc.machine_count_initial > 0 || state.detections.length > 0);
  }
  $('mode-select').value = state.doc.mode;
  $('notes-input').value = state.doc.notes || '';
  if (normalWorkflow()) syncWorkflowRoute();
  else $('method-select').value = methodForDocument(state.doc);
  if (syncParams) { fillParams(normalWorkflow() ? workflowParams() : state.doc.params); state.paramsDirty = paramsDiffer(); }
  invalidateBackground();
  updateCurrentRow();
  updateControls();
}
function remember() {
  state.history.push(snapshot());
  if (state.history.length > 80) state.history.shift();
}
function changed({recordEdit = true} = {}) {
  clearModelPreview();
  if (reviewMode() && reviewItemStatus(state.imageName) === 'verified') state.review.statuses.set(state.imageName, 'stale');
  state.doc.detections = state.detections;
  state.doc.plate = state.plate;
  // This legacy flag protects edited work from batch recounting; it is not a human attestation.
  // Undo preserves the exact earlier flag, rather than recording another edit.
  if (recordEdit) state.doc.reviewed = true;
  queueSave();
  updateCurrentRow();
  updateControls();
  draw();
}
function hasCount() {
  return Boolean(state.doc && (state.doc.mode === 'manual' || state.doc.counted || state.detections.length || state.doc.machine_count_initial > 0));
}
function imageFlagKey(item) {
  return item.viewed || item.reviewed || Boolean(item.notes?.trim()) ? 'flagViewed'
    : item.mode === 'manual' || item.counted || Number(item.count) > 0 || (item.counted === undefined && item.processed)
      ? 'flagCounted' : 'flagUnprocessed';
}
// UI activity has its own source-bound metadata, never a detection edit or attestation.
async function recordViewed(batch, name, sourceHash, token) {
  if (!sourceHash || token !== state.navToken || batch !== state.batch || name !== state.imageName || !state.img) return;
  try {
    const receipt = await jsonRequest(imageURL('/viewed', batch, name), 'POST', {source_sha256: sourceHash});
    if (receipt.viewed !== true || receipt.source_sha256 !== sourceHash) throw new Error(t('viewStatusFailed'));
    if (batch !== state.batch || token !== state.navToken || name !== state.imageName || sourceHash !== state.imageSourceHash) return;
    const row = state.imageList.find(item => item.name === name);
    if (row) row.viewed = true;
    updateCurrentRow();
  } catch (error) {
    if (token === state.navToken && batch === state.batch && name === state.imageName) setStatus(t('viewStatusFailed'), true);
    console.warn('Photo view status could not be saved:', error);
  }
}
function updateCurrentRow() {
  updateSelectedRows();
  const row = state.imageList.find(item => item.name === state.imageName);
  if (!row || !state.doc) return;
  Object.assign(row, {count: state.detections.length, processed: hasCount(), counted: Boolean(state.doc.counted),
    reviewed: Boolean(state.doc.reviewed), notes: state.doc.notes || '', mode: state.doc.mode});
  // A colony edit only changes one row; avoid rebuilding the entire batch list.
  for (const element of $('image-list').children) {
    if (element.dataset.name !== state.imageName) continue;
    element.classList.toggle('counted', Boolean(row.processed));
    element.classList.toggle('reviewed', Boolean(row.reviewed || row.notes?.trim()));
    element.classList.toggle('visited', Boolean(row.viewed));
    element.classList.toggle('has-notes', Boolean(row.notes));
    element.querySelector('.row-count').textContent = row.processed ? row.count : '–';
    element.querySelector('.row-flag').title = t(imageFlagKey(row));
    element.querySelector('.row-name').title = `${row.name}${row.notes ? ` — ${row.notes}` : ''}`;
  }
}
function updateSaveStatus() {
  const queue = state.saveQueues.get(keyFor());
  const key = applyPending() ? 'modelSavePending' : !state.doc ? '' : queue?.error ? 'saveFailed' : queue?.pending || queue?.saving ? 'saving' : 'saved';
  $('save-status').textContent = key ? t(key) : '';
  $('save-status').classList.toggle('error', Boolean(queue?.error || applyPending()));
  $('save-status').title = queue?.error?.message || '';
  $('btn-save-retry').hidden = applyPending() || !queue?.error;
}
function queueSave() {
  if (!state.doc) return;
  const key = keyFor();
  let queue = state.saveQueues.get(key);
  if (!queue) {
    queue = {url: imageURL('/state'), pending: null, saving: null, timer: null, error: null, revision: state.doc.revision};
    state.saveQueues.set(key, queue);
  }
  queue.pending = snapshot(); // capture image and all values now, never in the async callback
  clearTimeout(queue.timer);
  queue.timer = setTimeout(() => drainQueue(queue).catch(() => {}), 300);
  updateSaveStatus();
}
async function drainQueue(queue) {
  clearTimeout(queue.timer);
  if (queue.saving) return queue.saving;
  if (!queue.pending) return;
  queue.error = null;
  queue.saving = (async () => {
    while (queue.pending) {
      const pending = queue.pending;
      try {
        const result = await jsonRequest(queue.url, 'PUT', {...pending, ...(queue.revision !== undefined ? {expected_revision: queue.revision} : {})});
        queue.revision = result.revision;
        if (queue.pending === pending) queue.pending = null;
      } catch (error) {
        queue.error = error; // retain latest snapshot for retry; never claim a failed edit was saved
        throw error;
      }
    }
  })();
  updateSaveStatus();
  try { await queue.saving; } finally { queue.saving = null; updateSaveStatus(); }
}
function trackRevision(data) {
  const queue = state.saveQueues.get(keyFor());
  if (queue) queue.revision = data.revision;
  else state.saveQueues.set(keyFor(), {url: imageURL('/state'), pending: null, saving: null, timer: null, error: null, revision: data.revision});
}
async function flushEdits() {
  for (const queue of state.saveQueues.values()) {
    clearTimeout(queue.timer);
    await drainQueue(queue);
  }
}
function updateControls() {
  const blocked = state.loading || state.busy || applyPending() || reviewBlocked();
  const active = Boolean(state.doc && state.img);
  const locked = blocked || Boolean(state.crop);
  for (const id of ['btn-clear', 'btn-fit', 'btn-crop', 'btn-remove-image', 'notes-input']) $(id).disabled = !active || locked;
  $('btn-undo').disabled = !active || locked || !state.history.length;
  $('current-source-view').disabled = !active || locked;
  $('source-view-metadata').hidden = normalWorkflow();
  $('btn-rerun').disabled = restrictedReview() || !active || locked || state.doc?.mode === 'manual' || modelMethod();
  $('btn-apply-params').disabled = $('btn-rerun').disabled;
  if (restrictedReview()) $('mode-select').value = manualOnlyReview() ? 'manual' : 'auto';
  $('mode-select').disabled = locked || restrictedReview();
  for (const id of [...Object.values(PARAM_IDS), ...Object.values(paramControls.SPECS).map(spec => `s-${spec.id}`), 'preset-select', 'p-radius', 'p-preview', 'btn-defaults']) $(id).disabled = locked;
  for (const id of ['btn-add-images', 'btn-ingest']) $(id).disabled = locked;
  $('btn-run').disabled = locked || !state.imageList.length || $('mode-select').value === 'manual' || modelMethod();
  $('p-preview').disabled = locked;
  for (const id of ['btn-export-csv', 'btn-export-zip']) $(id).disabled = locked || !state.imageList.length;
  const index = state.imageList.findIndex(row => row.name === state.imageName);
  $('btn-prev').disabled = locked || index <= 0;
  $('btn-next').disabled = locked || !state.imageList.length || index >= state.imageList.length - 1;
  const displayedCandidate = displayedModelCandidate();
  $('count-badge').textContent = displayedCandidate
    ? `${t(samMethod() ? 'samPreview' : 'modelTemporary')} · ${displayedCandidate.candidate_count}`
    : manualOnlyReview() ? `${state.detections.length} ${t('manualMarksSuffix')}`
    : hasCount() ? `${state.detections.length} ${t('cfuSuffix')}` : t('notProcessed');
  $('count-source').hidden = manualOnlyReview();
  $('count-source').textContent = state.doc?.counted ? t(state.doc.count_engine === ASSISTED_ENGINE ? 'assistedSavedSource' : state.doc.count_engine === SAM_ENGINE ? 'samSavedSource' : state.doc.count_engine === FUSION_V2_ENGINE ? 'fusionV2SavedSource' : state.doc.count_engine === FUSION_ENGINE ? 'fusionSavedSource' : state.doc.count_engine === MODEL_ENGINE ? 'modelSavedSource' : state.doc.count_engine === ENHANCED_ENGINE ? 'enhancedSavedSource' : 'modelBaselineSource') : '';
  $('machine-count-initial').hidden = !assistedFrozenReview() || !state.doc;
  $('machine-count-initial').textContent = assistedFrozenReview() && state.doc ? `${t('initialMachineCount')}: ${state.doc.machine_count_initial}` : '';
  const methodPending = !restrictedReview() && state.doc?.counted && state.doc.mode !== 'manual' && !modelMethod()
    && selectedBuiltinEngine() !== (state.doc.count_engine || 'baseline');
  $('method-hint').textContent = methodPending ? t('builtinMethodPending') : '';
  $('method-hint').hidden = !methodPending;
  $('mode-hint').textContent = assistedFrozenReview() ? t('assistedFrozenHint') : t(state.doc?.mode === 'manual' || (!state.doc && $('mode-select').value === 'manual')
    ? modelMethod() || manualOnlyReview() ? 'modelManualHint' : 'manualHint' : modelMethod() ? 'modelModeHint' : 'autoHint');
  const modelRoiChanged = state.paramsDirty && state.doc?.count_engine === MODEL_ENGINE;
  $('params-hint').textContent = state.paramsDirty && !modelRoiChanged ? t('paramsChanged') : '';
  $('model-params-hint').hidden = !modelRoiChanged;
  $('model-params-hint').textContent = modelRoiChanged ? t('modelRoiChanged') : '';
  $('crop-tools').hidden = !state.crop;
  $('canvas-message').hidden = Boolean(state.img && !state.loading);
  $('canvas-message').textContent = t(state.loading ? 'loadingImage' : 'selectAnImage');
  $('boundary-hint').textContent = t(assistedFrozenReview() ? 'frozenBoundaryHint' : 'boundaryViewHint');
  $('boundary-hint').hidden = !reviewMode();
  updateSaveStatus();
  setPreviewStatus(state.previewStatus);
  updateModelControls();
  updateReferenceControls();
  updateReviewControls();
  updateWorkflowControls();
  updateBulkSelectionControls();
  for (const spec of Object.values(paramControls.SPECS)) $(`v-${spec.id}`).disabled = $(`s-${spec.id}`).disabled;
}
function updateWorkflowControls() {
  if (!state.workflow.enabled) return;
  const normal = normalWorkflow(), custom = customWorkflow();
  const defaultSam = !custom && workflowDefaultEngine() === SAM_ENGINE;
  const defaultCapability = modelCapability(SAM_ENGINE);
  const defaultUnavailable = defaultSam && (!defaultCapability.enabled || !defaultCapability.available);
  // Keep actions disabled while capability is unknown, without calling it a runtime failure.
  const showUnavailable = Boolean(state.config) && defaultUnavailable;
  const locked = state.loading || state.busy || Boolean(state.crop) || applyPending() || reviewBlocked();
  $('profile-option-default').textContent = t('profileDefault');
  $('profile-option-classical').hidden = false;
  $('recognition-profile-control').hidden = !normal;
  $('recognition-profile').value = state.workflow.kind;
  $('recognition-profile').disabled = locked || previewActive();
  $('viewer').classList.toggle('workflow-default', normal && !custom);
  $('viewer').classList.toggle('workflow-custom', custom);
  $('custom-settings').hidden = normal && !custom;
  $('btn-recognize-all').hidden = !normal;
  $('btn-recognize-all').disabled = locked || previewActive() || !state.imageList.length
    || $('mode-select').value === 'manual' || defaultUnavailable;
  $('batch-hint').textContent = showUnavailable ? t('modelUnavailable') : '';
  $('batch-hint').hidden = !showUnavailable;
  $('btn-adjustments-toggle').hidden = !custom;
  $('btn-adjustments-toggle').disabled = locked || previewActive();
  $('btn-adjustments-toggle').textContent = t(state.workflow.adjustmentsOpen ? 'collapseAdjustments' : customDraftPending() ? 'adjustmentsPending' : 'openAdjustments');
  $('btn-adjustments-toggle').setAttribute('aria-expanded', String(custom && state.workflow.adjustmentsOpen));
  if (custom) $('btn-apply-params').disabled = locked || previewActive();
  $('btn-recognize-current').hidden = !normal;
  $('btn-recognize-current').disabled = !editable() || previewActive() || state.doc?.mode === 'manual' || defaultUnavailable;
  $('recognition-route').hidden = true;
  $('recognition-mode-info').hidden = !normal;
  $('mode-info-title').textContent = t(custom ? 'profileCustom' : defaultSam ? 'profileDefault' : 'profileClassical');
  $('mode-info-description').textContent = t(custom ? 'modeInfoCustom' : defaultSam ? 'modeInfoUltra' : 'modeInfoLite');
  $('recognition-route').textContent = t(custom ? 'customRoute' : defaultSam ? 'defaultRoute' : 'classicalRoute');
  $('recognition-route').title = t(custom ? 'customRouteHint' : defaultSam ? 'defaultRouteHint' : 'classicalRouteHint');
  $('saved-source-visible').hidden = !normal || !state.doc?.counted;
  $('saved-source-visible').textContent = state.doc?.counted
    ? `${t('currentSavedSource')}${$('count-source').textContent}` : '';
  $('btn-custom-run-all').hidden = true;
  $('btn-custom-run-all').disabled = !custom || locked || !state.imageList.length || $('mode-select').value === 'manual';
  $('mode-hint').hidden = normal && (state.doc?.mode || $('mode-select').value) !== 'manual';
  const presetLabel = $('preset-select').closest('label');
  if (presetLabel) presetLabel.hidden = normal;
  if (normal) {
    $('method-hint').hidden = true;
    $('method-control').hidden = true; // Keep the route selector internal; saved provenance is displayed separately.
    $('btn-run').hidden = true;
    $('btn-model-preview').hidden = true;
    $('params-hint').textContent = custom ? t('customDraftHint') : '';
  }
  if ($('workflow-hint')) { $('workflow-hint').textContent = ''; $('workflow-hint').hidden = normal; }
  updateAdjustmentPanel();
}
function updateAdjustmentPanel() {
  const custom = customWorkflow();
  const settings = $('custom-settings'), destination = custom ? $('adjustments-body') : $('params');
  // Reuse controls and draft; the photo list remains visible alongside adjustments.
  if (settings.parentElement && settings.parentElement !== destination) {
    if (custom) destination.appendChild(settings);
    else destination.insertBefore(settings, $('reference-panel'));
  }
  const expanded = custom && state.workflow.adjustmentsOpen;
  $('adjustments-panel').hidden = !expanded;
  $('viewer').classList.toggle('adjustments-open', Boolean(expanded));
  $('dropzone').hidden = reviewMode();
  $('image-list').hidden = false;
}
function initializeWorkflow() {
  state.workflow.enabled = Boolean(workflowHelpers && $('recognition-profile'));
  if (!state.workflow.enabled) return;
  state.workflow.kind = 'default';
  if (reviewMode()) {
    $('custom-settings').open = true;
    $('review-boundary-tools').appendChild($('btn-crop'));
  }
  syncWorkflowRoute();
}
function changeRecognitionProfile() {
  if (!normalWorkflow() || state.busy || state.loading || state.crop || previewActive()) return;
  clearModelPreview(); clearPreview(); clearReferenceConfirmation();
  $('recognition-mode-info').open = false;
  state.workflow.kind = ['custom', 'classical'].includes($('recognition-profile').value) ? $('recognition-profile').value : 'default';
  state.workflow.customParams ||= {...DEFAULTS};
  state.workflow.appliedCustomParams ||= {...DEFAULTS};
  syncWorkflowRoute(); fillParams(workflowParams());
  state.workflow.adjustmentsOpen = customWorkflow();
  if (customWorkflow()) $('custom-settings').open = true;
  updateControls(); draw(); refreshMaskPreview();
}
async function recognizeCurrent() {
  if (!normalWorkflow() || !editable() || previewActive() || state.doc.mode === 'manual') return;
  syncWorkflowRoute();
  if (selectedModelEngine() === SAM_ENGINE) {
    // New images use the same protected, serial adoption path as Recognize all.
    // Existing work gets a preview and explicit adoption instead of silent replacement.
    if (!window.WECFU_DEFAULT_BATCH.protection(state.doc)) return countDefaultBatch({onlyCurrent: true});
    return runModelPreview({engine: SAM_ENGINE});
  }
  return recount();
}
function syncSliders() {
  let outside = false;
  for (const [key, spec] of Object.entries(paramControls.SPECS)) {
    const rawInput = $(`p-${spec.id}`);
    const raw = rawInput.value === '' ? NaN : Number(rawInput.value);
    const normalized = paramControls.toNormalized(key, raw);
    const slider = $(`s-${spec.id}`), output = $(`v-${spec.id}`);
    const outOfRange = paramControls.outsideSliderRange(key, raw);
    outside ||= outOfRange;
    if (normalized !== null) slider.value = normalized;
    output.value = normalized === null ? '' : normalized.toFixed(2);
    output.dataset.edited = '';
    output.classList.toggle('outside-range', outOfRange);
    output.setAttribute('aria-label', `${slider.labels?.[0]?.textContent || key} · ${t('normalizedScale')}`);
    output.title = outOfRange ? t('sliderRangeWarning') : t('normalizedScale');
    slider.setAttribute('aria-valuetext', `${output.value}${outOfRange ? '*' : ''}`);
    slider.style.setProperty('--slider-fill', `${(normalized ?? 0) * 100}%`);
  }
  $('slider-range-warning').hidden = !outside;
}
function sliderChanged(key, keyboardRawValue = null) {
  if (applyPending()) return;
  if (key !== 'radius') clearModelPreview();
  const spec = paramControls.SPECS[key];
  // Only the edited raw field changes. Rendering sliders must never quantize saved values.
  $(`p-${spec.id}`).value = keyboardRawValue ?? paramControls.fromNormalized(key, Number($(`s-${spec.id}`).value));
  $(`v-${spec.id}`).removeAttribute('aria-invalid');
  syncSliders();
  if (key !== 'radius') { $('preset-select').value = 'custom'; parametersChanged(key); }
  else updateControls();
}
function commitSliderValue(key) {
  const spec = paramControls.SPECS[key], input = $(`v-${spec.id}`);
  if (input.dataset.edited !== '1') return;
  const parsed = paramControls.parseNormalizedInput(input.value);
  input.dataset.edited = '';
  if (input.disabled || $(`s-${spec.id}`).disabled || applyPending()) { syncSliders(); return; }
  if (!parsed.valid) {
    syncSliders(); input.setAttribute('aria-invalid', 'true');
    setStatus(t('normalizedValueInvalid'), true); return;
  }
  input.removeAttribute('aria-invalid');
  // Enter/blur changes the same one raw parameter as a pointer slider edit.
  $(`s-${spec.id}`).value = parsed.value;
  sliderChanged(key);
}
function sliderKeyDown(key, event) {
  const spec = paramControls.SPECS[key];
  const direction = {ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1}[event.key];
  if (!spec.integer || !direction || event.defaultPrevented || event.isComposing
      || event.ctrlKey || event.metaKey || event.altKey || modalOpen()
      || $(`s-${spec.id}`).disabled || applyPending()) return;
  const raw = Number($(`p-${spec.id}`).value);
  if (!Number.isFinite(raw)) return;
  event.preventDefault();
  // Normalized steps can round back to the same integer (especially on log ranges).
  // Keep keyboard edits exact; pointer input still follows the normalized slider.
  const next = Math.min(spec.max, Math.max(spec.min, Math.round(raw) + direction * (spec.inverse ? -1 : 1)));
  sliderChanged(key, next);
}
function fillParams(params = DEFAULTS) {
  const values = {...DEFAULTS, ...params};
  for (const [key, id] of Object.entries(PARAM_IDS)) {
    $(id).value = values[key];
    $(`v-${id.slice(2)}`).removeAttribute('aria-invalid');
  }
  $('preset-select').value = Object.keys(PRESETS).find(name =>
    Object.keys(DEFAULTS).every(key => Number(values[key]) === PRESETS[name][key])) || 'custom';
  syncSliders();
}
function paramsBody() {
  const values = {};
  for (const [key, id] of Object.entries(PARAM_IDS)) {
    if (!$(id).checkValidity() || $(id).value === '') throw new Error(t('invalidParams'));
    values[key] = Number($(id).value);
    if ((key === 'plate_inset' || key === 'min_area_frac') && values[key] <= 0) throw new Error(t('invalidParams'));
  }
  return values;
}
function parametersChanged(changedKey = null) {
  if (restrictedReview() || applyPending()) return;
  clearModelPreview();
  try {
    const params = paramsBody();
    if (customWorkflow()) state.workflow.customParams = {...params};
    else if (normalWorkflow()) return; // Hidden defaults are not persisted by incidental input events.
    else if (state.doc) { state.doc.params = {...state.doc.params, ...params}; state.paramsDirty = paramsDiffer(); queueSave(); }
    updateControls();
    if (modelMethod()) draw(); // The model ROI is a live reference line, not an inference request.
    else if (changedKey === null || paramControls.SPECS[changedKey]?.preview) refreshMaskPreview();
  } catch (_) {
    $('params-hint').textContent = t('invalidParams');
    if (modelMethod()) { state.modelPreview.error = t('invalidParams'); updateControls(); draw(); }
  }
}
function applyPreset(name) {
  if (restrictedReview() || !PRESETS[name]) return;
  fillParams(PRESETS[name]);
  parametersChanged();
}
function resetDefaults() {
  if (restrictedReview()) return;
  if (normalWorkflow()) syncWorkflowRoute();
  else $('method-select').value = defaultBuiltinEngine();
  fillParams(DEFAULTS);
  // Manual marker size is independent of recognition presets.
  syncSliders();
  parametersChanged();
}

// A review URL is an explicit membership boundary, never a hint to open the full batch.
function configureReviewMode() {
  const search = window.location?.search || '';
  if (!new URLSearchParams(search).has('review')) return;
  state.review.requested = true;
  $('method-select').value = 'baseline'; $('reference-panel').open = true;
  try { state.review.id = reviewHelpers.queueId(search); }
  catch (error) { failReviewQueue(error); }
}
function reviewItemStatus(name) {
  return state.review.statuses.get(name) || state.review.queue?.items.find(item => item.name === name)?.reference_status;
}
function updateReviewControls() {
  const active = reviewMode(), review = state.review;
  $('review-summary').hidden = !active;
  $('sidebar').classList.toggle('review-sidebar', active);
  $('viewer').classList.toggle('review-mode', active);
  $('viewer').classList.toggle('restricted-review', restrictedReview());
  $('sidebar').classList.toggle('manual-only-review', manualOnlyReview());
  $('btn-review-params').hidden = !active || restrictedReview();
  if (!active) return;
  $('reference-purpose').textContent = t('reviewReferencePurpose');
  for (const id of ['dropzone', 'btn-remove-image', 'btn-run', 'btn-stop-run', 'btn-export-csv', 'btn-export-zip', 'btn-reference-export']) $(id).hidden = true;
  const queue = review.queue, progress = reviewHelpers.progress(queue, review.statuses);
  $('review-title').textContent = queue?.title || t('reviewTitle');
  const index = queue?.items.findIndex(item => item.name === state.imageName) ?? -1;
  $('review-position').textContent = queue ? `${t('reviewPosition')} ${index + 1}/${progress.total}` : '';
  $('review-progress').textContent = review.error ? '—' : queue ? `${t('reviewVerifiedProgress')} ${progress.verified}/${progress.total}` : '';
  $('review-policy').textContent = queue?.policy || '';
  const context = queue?.items.find(item => item.name === state.imageName)?.context || '';
  $('review-context').textContent = context; $('review-context').hidden = !context;
  if (restrictedReview()) {
    $('mode-select').value = manualOnlyReview() ? 'manual' : 'auto';
    $('btn-rerun').hidden = true; $('btn-apply-params').hidden = true; $('method-control').hidden = true;
    $('p-preview').disabled = true;
  }
  $('review-message').textContent = review.error ? `${t('reviewUnavailable')} ${review.error}` : review.loading ? t('reviewLoading') : '';
  $('btn-review-refresh').textContent = t(review.error ? 'reviewReload' : 'reviewRefresh');
  $('btn-review-refresh').disabled = Boolean(state.loading || state.busy || state.crop || review.loading || applyPending());
  const labels = {verified: 'reviewVerified', missing: 'reviewMissing', stale: 'reviewStale', withdrawn: 'reviewWithdrawn'};
  for (const row of $('image-list').children) {
    const status = reviewItemStatus(row.dataset.name) || 'missing';
    // The dot indicates browsing/editing; verification remains a separate text status.
    for (const name of reviewHelpers.STATUSES) row.classList.toggle(`review-${name}`, name === status);
    const flag = row.querySelector('.row-flag'), label = row.querySelector('.review-item-status');
    if (flag) flag.title = `${t(imageFlagKey(state.imageList.find(item => item.name === row.dataset.name) || {}))} · ${t(labels[status])}`;
    if (label) label.textContent = t(labels[status]);
  }
}
function failReviewQueue(error) {
  state.review.error = error.message || String(error); state.review.loading = false;
  state.loading = false; state.imageList = [];
  emptyViewer();
  setStatus(t('reviewUnavailable'), true);
}
async function refreshReviewQueue({preserveReference = false} = {}) {
  if (!reviewMode() || state.review.error) throw new Error(state.review.error || t('reviewUnavailable'));
  if (state.review.refreshing) return state.review.refreshing;
  const review = state.review;
  review.loading = true; updateControls();
  review.refreshing = (async () => {
    let readingQueue = false;
    try {
      await flushEdits();
      readingQueue = true;
      if (state.config?.web_mode) throw new Error(t('reviewUnavailable'));
      const queue = reviewHelpers.validate(await jsonRequest(`/api/review-queues/${enc(review.id)}`), review.id);
      const signature = reviewHelpers.signature(queue);
      if (review.signature && review.signature !== signature) throw new Error(t('reviewChanged'));
      const data = await jsonRequest(`/api/batch/${enc(queue.batch)}/images`);
      const rows = reviewHelpers.filterImages(queue, data.images);
      if (!review.signature && ['manual_only', 'assisted_frozen'].includes(queue.annotation_mode)) $('reference-panel').open = false;
      review.queue = queue; review.signature = signature; review.statuses.clear();
      state.batch = queue.batch; state.imageList = rows;
      const current = queue.items.find(item => item.name === state.imageName);
      if (!preserveReference && current && state.reference.envelope && state.reference.envelope.status !== current.reference_status) resetReferenceContext(keyFor());
      renderImageList();
      return queue;
    } catch (error) {
      if (readingQueue) failReviewQueue(error);
      throw error;
    } finally { review.loading = false; review.refreshing = null; updateControls(); }
  })();
  return review.refreshing;
}
async function refreshReviewProgress() {
  if (!reviewMode() || state.loading || state.busy || state.crop || state.review.loading) return;
  if (state.review.error) { window.location.reload(); return; }
  await refreshReviewQueue();
}
function fillReviewGroup() {
  if (!reviewMode() || $('reference-group').value) return;
  const group = state.review.queue?.items.find(item => item.name === state.imageName)?.group_id;
  if (group) $('reference-group').value = group;
}

// List rows use textContent so filenames and notes remain plain text.
function renderImageList() {
  const fragment = document.createDocumentFragment();
  for (const item of state.imageList) {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'image-row'; row.dataset.name = item.name;
    row.classList.toggle('selected', item.name === state.imageName);
    const counted = item.mode === 'manual' || item.counted || Number(item.count) > 0 || (item.counted === undefined && item.processed);
    row.classList.toggle('counted', Boolean(counted));
    row.classList.toggle('reviewed', Boolean(item.reviewed || item.notes?.trim()));
    row.classList.toggle('visited', Boolean(item.viewed));
    row.classList.toggle('has-notes', Boolean(item.notes));
    const check = document.createElement('span'); check.className = 'row-select-check'; check.setAttribute('aria-hidden', 'true');
    row.appendChild(check);
    const flag = document.createElement('span'); flag.className = 'row-flag';
    flag.title = t(imageFlagKey(item));
    const name = document.createElement('span'); name.className = 'row-name';
    name.textContent = item.name; name.title = `${item.name}${item.notes ? ` — ${item.notes}` : ''}`;
    const count = document.createElement('span'); count.className = 'row-count';
    count.textContent = manualOnlyReview() ? '' : counted ? item.count : '–';
    row.append(flag, name, count);
    if (reviewMode()) { const status = document.createElement('span'); status.className = 'review-item-status'; row.append(status); }
    row.addEventListener('click', safeAction(() => state.bulkSelection.enabled ? toggleBulkImage(item.name) : selectImage(item.name)));
    fragment.appendChild(row);
  }
  $('image-list').replaceChildren(fragment);
  updateSelectedRows({reveal: true});
  updateReviewControls();
  updateBulkSelectionControls();
}
async function loadImages() {
  if (reviewMode()) { await refreshReviewQueue(); return; }
  const batch = state.batch;
  if (!batch) { state.imageList = []; renderImageList(); return; }
  const data = await jsonRequest(`/api/batch/${enc(batch)}/images`);
  if (batch !== state.batch) return;
  state.imageList = Array.isArray(data.images) ? data.images : [];
  renderImageList();
  updateControls();
}
async function loadDefaultBatch() {
  if (reviewMode()) {
    const queue = await refreshReviewQueue();
    if (!restrictedReview()) $('reference-panel').open = true;
    await selectImage(reviewHelpers.firstUnverified(queue), {queueValidated: true});
    return;
  }
  const data = await jsonRequest('/api/batches');
  state.batch = data.batches?.includes(data.default) ? data.default : data.batches?.[0] || null;
  await loadImages();
}
function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(t('imageLoadFailed')));
    image.src = url;
  });
}
function boundedImage(image) {
  const maxSide = 2400;
  if (Math.max(image.width, image.height) <= maxSide) return image;
  const scale = maxSide / Math.max(image.width, image.height);
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(image.width * scale); canvas.height = Math.round(image.height * scale);
  canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
  return canvas;
}
async function loadPlateImage(url, referenceContext = false, signal) {
  // The hash and rendered pixels come from the very same response, never a later metadata request.
  const response = await request(`${url}?${referenceContext ? 'reference_context' : 'display_context'}=true`, {signal, cache: 'no-store'});
  const sourceHash = response.headers.get('X-WeCFU-Source-SHA256');
  if (!sourceHash) throw new Error(t('referenceMissingImageHash'));
  const objectURL = URL.createObjectURL(await response.blob());
  try { return {image: await loadImage(objectURL), sourceHash}; }
  finally { URL.revokeObjectURL(objectURL); }
}
async function selectImage(name, {force = false, queueValidated = false} = {}) {
  if (state.loading || state.busy || state.crop || applyPending() || reviewBlocked() || (name === state.imageName && !force)) return;
  if (reviewMode() && !state.review.queue.items.some(item => item.name === name)) return;
  clearModelPreview();
  state.loading = true; updateControls();
  const token = ++state.navToken;
  try {
    await flushEdits();
    if (reviewMode()) {
      if (!queueValidated) await refreshReviewQueue();
      if (!restrictedReview()) $('reference-panel').open = true;
    }
    clearPreview();
    cancelGesture();
    const batch = state.batch;
    const mode = manualOnlyReview() ? 'manual' : assistedFrozenReview() ? 'auto' : $('mode-select').value;
    const [data, photo, declaredView] = await Promise.all([
      jsonRequest(imageURL('/initialize', batch, name), 'POST', {mode}),
      loadPlateImage(imageURL('/raw', batch, name), !state.config?.web_mode && ($('reference-panel').open || modelMethod())),
      jsonRequest(imageURL('/source_view', batch, name)),
    ]);
    if (token !== state.navToken || batch !== state.batch) return;
    if (restrictedReview()) {
      try { validateReviewState(data); }
      catch (error) { failReviewQueue(error); throw error; }
    }
    state.imageName = name; state.img = photo.image; state.display = boundedImage(photo.image);
    state.imageSourceHash = photo.sourceHash;
    state.sourceView = declaredView.source_sha256 === photo.sourceHash && declaredView.declared ? declaredView.view : 'unknown';
    $('current-source-view').value = state.sourceView;
    state.imgUrl = imageURL('/raw', batch, name); state.history = [];
    trackRevision(data); adopt(data);
    updateSelectedRows({reveal: true});
    $('current-name').textContent = name;
    // Browsing records only separate UI activity; saved marks and verification stay unchanged.
    fitToCanvas();
    setStatus('');
    focusCanvas({preserveEditing: true});
    void recordViewed(batch, name, photo.sourceHash, token);
    if ($('p-preview').checked) refreshMaskPreview();
  } catch (error) {
    if (restrictedReview() && !state.review.error) failReviewQueue(error);
    throw error;
  } finally { if (token === state.navToken) { state.loading = false; updateControls(); draw(); } }
}
function moveSelection(delta) {
  const index = state.imageList.findIndex(item => item.name === state.imageName);
  const target = index < 0 ? 0 : index + delta;
  if (state.imageList[target]) return selectImage(state.imageList[target].name);
}
async function changeSourceView() {
  if (!editable() || state.busy || state.loading || state.crop || applyPending()) return;
  clearModelPreview();
  const previous = state.sourceView || 'unknown';
  const view = $('current-source-view').value;
  state.busy = true; updateControls();
  try {
    const result = await jsonRequest(imageURL('/source_view'), 'POST', {source_sha256: state.imageSourceHash, view});
    if (result.source_sha256 !== state.imageSourceHash) throw new Error(t('referenceMissingImageHash'));
    state.sourceView = result.view;
    $('current-source-view').value = result.view;
    setStatus(t('sourceViewSaved'));
  } catch (error) { $('current-source-view').value = previous; throw error; }
  finally { state.busy = false; updateControls(); }
}
function emptyViewer() {
  clearModelPreview();
  clearPreview(); cancelGesture(); ++state.navToken;
  Object.assign(state, {imageName: null, doc: null, detections: [], plate: null, img: null,
    display: null, imgUrl: null, imageSourceHash: null, history: [], crop: null, paramsDirty: false});
  $('current-name').textContent = t('selectAnImage'); $('notes-input').value = '';
  invalidateBackground(); updateControls(); renderImageList();
}

// Optional human-reference workflow. No ordinary view/edit action creates a reference.
function clearReferenceConfirmation() {
  $('reference-confirmed').checked = false;
  $('reference-crop-confirmed').checked = false;
}
function resetReferenceContext(key) {
  const reference = state.reference;
  reference.controller?.abort();
  Object.assign(reference, {key, envelope: null, loading: false, error: '', geometry: null,
    token: reference.token + 1, controller: null});
  clearReferenceConfirmation();
  $('reference-group').value = '';
}
function updateReferenceControls() {
  $('reference-panel').hidden = !reviewMode() || Boolean(state.config?.web_mode);
  const key = state.imageName ? keyFor() : null;
  if (state.reference.key !== key) resetReferenceContext(key);
  const reference = state.reference;
  if (restrictedReview() && !$('reference-panel').open) clearReferenceConfirmation();
  $('reference-expand-hint').hidden = !restrictedReview() || $('reference-panel').open;
  const geometry = state.doc ? referenceHelpers.geometrySignature(state.plate, state.detections) : null;
  if (geometry !== reference.geometry) {
    clearReferenceConfirmation();
    reference.geometry = geometry;
  }
  const active = Boolean(state.doc && state.img), locked = state.busy || state.loading || Boolean(state.crop) || applyPending() || reviewBlocked();
  const trialVisible = Boolean(state.modelPreview.candidate || state.modelPreview.loading || applyPending());
  const status = referenceHelpers.displayStatus(reference.envelope, state.plate, state.detections, state.imageSourceHash);
  if (reviewMode() && status !== 'unloaded' && state.review.queue?.items.some(item => item.name === state.imageName)) {
    state.review.statuses.set(state.imageName, status);
    updateReviewControls();
  }
  const statusKeys = {verified: 'referenceVerified', missing: 'referenceMissing', stale: 'referenceStale', withdrawn: 'referenceWithdrawn', unloaded: 'referenceOptional'};
  const summaryStatus = restrictedReview() && status === 'unloaded' ? reviewItemStatus(state.imageName) || status : status;
  $('reference-summary-status').textContent = t(statusKeys[summaryStatus] || 'referenceOptional');
  $('reference-summary-status').className = `reference-status reference-${summaryStatus}`;
  $('reference-annotator').disabled = locked || reference.loading;
  $('reference-group').disabled = locked || reference.loading || !active;
  $('reference-confirmed').disabled = locked || reference.loading || trialVisible || !active || !state.imageSourceHash;
  $('reference-crop-confirmed').disabled = $('reference-confirmed').disabled;
  $('btn-reference-save').disabled = locked || reference.loading || !active || !reference.envelope || Boolean(reference.error)
    || trialVisible || !state.imageSourceHash || !$('reference-confirmed').checked || !$('reference-annotator').value.trim();
  $('btn-reference-refresh').disabled = locked || reference.loading || !active;
  const record = reference.envelope?.reference;
  const cropStatus = !reference.envelope ? 'unknown' : referenceHelpers.plateStatus(reference.envelope, state.plate, state.imageSourceHash);
  const cropStatusKeys = {unknown: 'referenceCropUnknown', legacy: 'referenceScopeLegacy', unreviewed: 'referenceCropUnreviewed',
    verified: 'referenceCropVerified', stale: 'referenceCropStale', withdrawn: 'referenceCropWithdrawn'};
  $('reference-crop-status').textContent = t(cropStatusKeys[cropStatus]);
  $('reference-crop-status').className = `reference-status reference-${cropStatus === 'verified' ? 'verified' : 'stale'}`;
  $('reference-crop-status').hidden = !active;
  $('btn-reference-withdraw').hidden = !record;
  $('btn-reference-withdraw').disabled = locked || reference.loading || !record || reference.envelope?.status === 'withdrawn';
  $('btn-reference-export').disabled = locked || reference.loading || !state.batch || !state.imageList.length;
  $('reference-empty-warning').hidden = !active || state.detections.length !== 0;
  $('reference-record-info').textContent = record
    ? `${t('referenceLastRecord')}: ${record.annotator} · ${record.count} CFU · ${new Date(record.verified_at_utc).toLocaleString(getLang())}${record.group_id ? ` · ${t('referenceGroup')}: ${record.group_id}` : ''}` : '';
  $('reference-message').textContent = reference.error || (trialVisible ? t('modelReferenceBlocked') : reference.loading ? t('referenceLoading')
    : !active ? t('selectAnImage') : status === 'stale' ? t('referenceStaleHint') : status === 'verified' ? t('referenceVerifiedHint') : '');
  $('reference-message').classList.toggle('error', Boolean(reference.error));
  if (!$('reference-panel').hidden && $('reference-panel').open && active && !locked && !trialVisible && !state.modelPreview.error && !reference.loading && !reference.envelope && !reference.error) {
    // Only an expanded panel loads verification context, including after switching images.
    queueMicrotask(() => refreshReference().catch(handleError));
  }
}
async function refreshReference({reloadImage = false} = {}) {
  if ($('reference-panel').hidden || !$('reference-panel').open || !state.doc || !state.img || state.busy || state.loading || state.crop || state.reference.loading || applyPending() || reviewBlocked()) return;
  clearModelPreview();
  const reference = state.reference, key = keyFor(), token = ++reference.token;
  const controller = new AbortController(); reference.controller = controller;
  reference.loading = true; reference.error = ''; clearReferenceConfirmation();
  state.busy = true; updateControls();
  try {
    await flushEdits();
    const [envelope, photo] = await Promise.all([
      jsonRequest(imageURL('/reference')),
      reloadImage || !state.imageSourceHash ? loadPlateImage(imageURL('/raw'), true, controller.signal) : Promise.resolve(null),
    ]);
    if (key !== keyFor() || token !== reference.token) return;
    if (photo) {
      const dimensionsChanged = state.img.width !== photo.image.width || state.img.height !== photo.image.height;
      state.img = photo.image; state.display = boundedImage(photo.image); state.imageSourceHash = photo.sourceHash;
      clearPreview(); invalidateBackground(); if (dimensionsChanged) fitToCanvas();
    }
    reference.envelope = envelope;
    if (!$('reference-group').value && envelope.reference?.group_id) $('reference-group').value = envelope.reference.group_id;
    fillReviewGroup();
  } catch (error) {
    if (key === keyFor() && token === reference.token && error.name !== 'AbortError') reference.error = `${t('referenceFailed')}: ${error.message}`;
  } finally {
    if (token === reference.token) { reference.loading = false; reference.controller = null; }
    state.busy = false; updateControls(); refreshMaskPreview();
  }
}
async function saveHumanReference() {
  if (restrictedReview() && !$('reference-panel').open) return;
  if (reviewBlocked() || $('btn-reference-save').disabled || state.modelPreview.candidate || state.modelPreview.loading || applyPending()) return;
  const key = keyFor(), reference = state.reference;
  const annotator = $('reference-annotator').value.trim(), group = $('reference-group').value.trim();
  const displayedSourceHash = state.imageSourceHash;
  if (!$('reference-confirmed').checked || !annotator || !displayedSourceHash) return;
  const reviewScope = {colony_count_reviewed: true, colony_center_points_reviewed: true,
    plate_crop_reviewed: $('reference-crop-confirmed').checked};
  let saved = false;
  state.busy = true; reference.error = ''; updateControls(); setStatus(t('referenceSaving'));
  try {
    await flushEdits();
    if (reviewMode()) await refreshReviewQueue({preserveReference: true});
    const revision = state.saveQueues.get(key)?.revision;
    if (!Number.isInteger(revision)) throw new Error(t('referenceMissingRevision'));
    const envelope = await jsonRequest(imageURL('/reference'), 'POST', {
      expected_revision: revision, expected_image_sha256: displayedSourceHash,
      human_confirmed: true, annotator, group_id: group || null,
      review_scope: reviewScope,
    });
    if (key === keyFor()) reference.envelope = envelope;
    saved = true; setStatus(t('referenceSaved'));
  } catch (error) {
    reference.error = `${t('referenceFailed')}: ${error.message}`;
    setStatus(t('referenceFailed'), true);
    if (error.status === 409 && reference.envelope?.status === 'verified') reference.envelope = {...reference.envelope, status: 'stale'};
  } finally {
    clearReferenceConfirmation();
    state.busy = false; updateControls();
  }
  if (saved && reviewMode()) await refreshReviewQueue().catch(handleError);
}
async function withdrawHumanReference() {
  const reference = state.reference, record = reference.envelope?.reference;
  if (reviewBlocked() || $('btn-reference-withdraw').disabled || !record) return;
  let withdrawn = false;
  state.busy = true; reference.error = ''; updateControls(); setStatus('');
  try {
    await flushEdits();
    if (reviewMode()) await refreshReviewQueue({preserveReference: true});
    reference.envelope = await jsonRequest(imageURL('/reference'), 'DELETE', {expected_reference_id: record.reference_id});
    withdrawn = true; setStatus(t('referenceWithdrawn'));
  } catch (error) { reference.error = `${t('referenceFailed')}: ${error.message}`; setStatus(t('referenceFailed'), true); }
  finally { clearReferenceConfirmation(); state.busy = false; updateControls(); }
  if (withdrawn && reviewMode()) await refreshReviewQueue().catch(handleError);
}
async function exportHumanReferences() {
  if (reviewMode() || $('btn-reference-export').disabled) return;
  state.busy = true; updateControls(); setStatus(t('referenceExporting'));
  try {
    await flushEdits();
    const response = await request(`/api/batch/${enc(state.batch)}/references.json`);
    const url = URL.createObjectURL(await response.blob()), link = document.createElement('a');
    link.href = url; link.download = `wecfu_${state.batch}_references.json`;
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    setStatus(t('exportDownloadStarted'));
  } finally { state.busy = false; updateControls(); }
}

// Model trials are separate from editable marks, threshold masks and human references.
function modelSignature() {
  return modelHelpers.signature(keyFor(), state.imageSourceHash, state.plate,
    state.doc?.params, state.doc?.mode, state.detections, selectedModelEngine(),
    modelCapability());
}
function modelCandidateCurrent() {
  const trial = state.modelPreview, capability = modelCapability();
  return Boolean(trial.candidate && trial.signature === modelSignature() && modelHelpers.valid(trial.candidate, {
    hash: state.imageSourceHash, revision: state.saveQueues.get(keyFor())?.revision,
    plate: state.plate, inset: fixedRecipeMethod() ? modelHelpers.SAM_INSET : state.doc?.params?.plate_inset,
    engine: selectedModelEngine(), model_sha256: capability.model_sha256, recipe_id: capability.recipe_id,
  }));
}
function displayedModelCandidate() {
  return modelMethod() && !state.crop && modelCandidateCurrent() ? state.modelPreview.candidate : null;
}
function previewCanvasReadOnly() {
  return Boolean(state.modelPreview.loading || state.modelPreview.candidate);
}
function clearModelPreview(message = '') {
  const trial = state.modelPreview;
  if (trial.pendingApply) return; // An unknown write outcome must be resolved before any new edits.
  const hadPreview = Boolean(trial.candidate || trial.loading);
  trial.controller?.abort();
  if (trial.timer !== null) clearTimeout(trial.timer);
  Object.assign(trial, {candidate: null, signature: null, token: trial.token + 1,
    controller: null, timer: null, loading: false, error: '', message, engine: null});
  syncWorkflowRoute();
  if (hadPreview) draw();
}
function updateModelControls() {
  const trial = state.modelPreview, capability = modelCapability();
  const cfu = modelCapability(MODEL_ENGINE), sam = modelCapability(SAM_ENGINE), fusion = modelCapability(FUSION_ENGINE), fusionV2 = modelCapability(FUSION_V2_ENGINE);
  const enabled = Boolean(capability?.enabled && !reviewMode()), selected = modelMethod();
  const locked = state.loading || state.busy || Boolean(state.crop) || applyPending() || reviewBlocked();
  const manual = (state.doc?.mode || $('mode-select').value) === 'manual';
  const inset = modelInset();
  const manualFusionPlate = fusionMethod() && state.doc?.plate_manual === true;
  const unsupportedView = fusionMethod() && Boolean(state.doc) && !['main','blank'].includes(state.sourceView);
  const roiValid = fixedRecipeMethod() || (inset > 0 && inset <= 1 && inset === state.doc?.params?.plate_inset);
  $('method-control').hidden = !(!reviewMode() && (cfu.enabled || sam.enabled || fusion.enabled || fusionV2.enabled)) && builtinEngines().length < 2;
  $('method-enhanced').hidden = $('method-enhanced').disabled = !builtinEngines().includes(ENHANCED_ENGINE);
  $('method-model').hidden = $('method-model').disabled = !cfu.enabled || reviewMode();
  $('method-sam').hidden = $('method-sam').disabled = !sam.enabled || reviewMode();
  $('method-fusion').hidden = !fusion.enabled || reviewMode();
  $('method-fusion').disabled = !fusion.enabled || !fusion.available || reviewMode();
  $('method-fusion-v2').hidden = !fusionV2.enabled || reviewMode();
  $('method-fusion-v2').disabled = !fusionV2.enabled || !fusionV2.available || reviewMode();
  $('method-select').disabled = locked;
  $('viewer').classList.toggle('model-method', selected);
  $('model-inset-control').hidden = $('advanced-inset-control').hidden = fixedRecipeMethod();
  if (fixedRecipeMethod()) $('p-inset').disabled = $('s-inset').disabled = true;
  $('model-warning').textContent = t(selectedModelEngine() === FUSION_V2_ENGINE ? 'fusionV2Warning' : fusionMethod() ? 'fusionWarning' : samMethod() ? 'samWarning' : 'modelWarning');
  $('model-roi-hint').textContent = t(fusionMethod() ? 'fusionRoiHint' : samMethod() ? 'samRoiHint' : 'modelRoiHint');
  const trialVisible = trial.loading || trial.candidate || trial.error || trial.pendingApply || trial.message;
  $('model-tools').hidden = !state.config || !selected || (normalWorkflow() && !trialVisible && !manualFusionPlate && !unsupportedView && capability.available);
  const replacementHint = $('model-tools').querySelector?.('.model-replacement');
  if (replacementHint) replacementHint.hidden = normalWorkflow() && !trial.candidate && !trial.pendingApply;
  $('btn-model-preview').disabled = !enabled || !capability.available || !selected || manual || manualFusionPlate || unsupportedView || locked || !state.doc || !state.img || trial.loading || !roiValid;
  $('btn-model-discard').disabled = locked || (!trial.candidate && !trial.loading && !trial.engine);
  $('btn-model-apply').disabled = locked || manual || manualFusionPlate || unsupportedView || !enabled || !capability.available || !selected || !roiValid || !modelCandidateCurrent();
  if (normalWorkflow()) {
    $('btn-model-discard').hidden = Boolean(trial.pendingApply) || (!trial.candidate && !trial.loading && !trial.engine);
    $('btn-model-apply').hidden = Boolean(trial.pendingApply) || !trial.candidate;
  }
  $('btn-model-retry').hidden = !trial.pendingApply || Boolean(trial.pendingApply.needsReload);
  $('btn-model-retry').disabled = state.busy || !trial.pendingApply;
  $('btn-model-reload').hidden = !trial.pendingApply?.uncertain;
  $('btn-model-reload').disabled = state.busy || !trial.pendingApply?.uncertain;
  $('model-count').textContent = trial.candidate
    ? `${t(samMethod() ? 'samPreview' : 'modelTemporary')}: ${trial.candidate.candidate_count} · ${t('modelCurrent')}: ${state.detections.length} · ${t('modelNotAdopted')}` : '';
  $('model-empty-warning').hidden = !trial.candidate || trial.candidate.candidate_count !== 0;
  $('model-message').textContent = !state.config ? '' : trial.error || (trial.pendingApply ? t('modelApplying') : trial.loading ? t('modelLoading')
    : manual ? t('modelManual') : unsupportedView ? t('sourceViewRequired') : manualFusionPlate ? t('fusionAutomaticPlateRequired') : !capability?.available
      ? `${t('modelUnavailable')}${typeof capability?.reason === 'string' && capability.reason ? ` ${capability.reason}` : ''}`
      : trial.message ? t(trial.message) : '');
  $('model-message').classList.toggle('error', Boolean(trial.error));
}
function changeMethod() {
  if (restrictedReview()) { updateControls(); return; }
  if (state.busy || state.loading || state.crop || applyPending()) return;
  clearModelPreview(); clearPreview();
  clearReferenceConfirmation();
  updateControls();
  if (!modelMethod()) refreshMaskPreview();
}
async function runModelPreview({engine = selectedModelEngine()} = {}) {
  if (!editable() || state.doc.mode === 'manual' || state.modelPreview.loading || applyPending()) return;
  const capability = modelCapability(engine);
  if (!capability.enabled || !capability.available) { setStatus(t('modelUnavailable'), true); updateControls(); return; }
  if (normalWorkflow() && !customWorkflow()) {
    if (previewActive()) return;
    // Keep an explicit refinement engine through validation, adoption and uncertain-write retries.
    // Synchronizing the default route must not relabel or invalidate that candidate.
    state.modelPreview.engine = engine; syncWorkflowRoute(); updateControls();
  }
  if ($('btn-model-preview').disabled || !modelMethod()) { clearModelPreview(); updateControls(); return; }
  clearModelPreview();
  if (normalWorkflow() && !customWorkflow()) { state.modelPreview.engine = engine; syncWorkflowRoute(); }
  clearPreview(); cancelGesture();
  const trial = state.modelPreview, token = trial.token, key = keyFor(), url = imageURL('/model-preview'), rawURL = imageURL('/raw');
  const controller = new AbortController(); trial.controller = controller; trial.loading = true;
  clearReferenceConfirmation(); updateControls();
  const current = () => token === trial.token && key === keyFor() && modelMethod() && !applyPending();
  try {
    await flushEdits();
    if (!current()) return;
    // Reload and display the exact source bytes whose hash is submitted, including TIFF previews.
    const photo = await loadPlateImage(rawURL, !state.config?.web_mode, controller.signal);
    if (!current()) return;
    const resized = state.img.width !== photo.image.width || state.img.height !== photo.image.height;
    state.img = photo.image; state.display = boundedImage(photo.image); state.imageSourceHash = photo.sourceHash;
    invalidateBackground(); if (resized) fitToCanvas();
    const revision = state.saveQueues.get(key)?.revision;
    if (!Number.isInteger(revision)) throw new Error(t('modelMissingRevision'));
    const signature = modelSignature();
    const response = await request(url, {method: 'POST', signal: controller.signal,
      headers: {'content-type': 'application/json'}, body: JSON.stringify({engine: selectedModelEngine(),
        expected_revision: revision, expected_image_sha256: photo.sourceHash,
        model_params: fixedRecipeMethod() ? {} : {plate_inset: state.doc.params.plate_inset}})});
    const candidate = await response.json();
    if (!current() || signature !== modelSignature()) return;
    trial.candidate = candidate; trial.signature = signature;
    if (!modelCandidateCurrent()) { clearModelPreview('modelExpired'); updateControls(); return; }
    trial.timer = setTimeout(() => {
      if (trial.candidate === candidate && !applyPending()) { clearModelPreview('modelExpired'); updateControls(); }
    }, Math.max(1, Math.min(2147483647, modelHelpers.expiresAt(candidate) - Date.now())));
  } catch (error) {
    if (current() && error.name !== 'AbortError') trial.error = `${t('modelFailed')}: ${error.message}`;
  } finally {
    if (token === trial.token) { trial.loading = false; trial.controller = null; updateControls(); draw(); }
  }
}
async function applyModelPreview() {
  if ($('btn-model-apply').disabled || !editable() || !modelMethod() || state.doc.mode === 'manual') return;
  state.busy = true; updateControls();
  try {
    await flushEdits();
    if (!modelCandidateCurrent()) { clearModelPreview('modelExpired'); return; }
    const trial = state.modelPreview;
    trial.pendingApply = {key: keyFor(), url: imageURL('/model-preview/apply'), before: snapshot(), uncertain: false,
      body: {candidate_id: trial.candidate.candidate_id, expected_revision: state.saveQueues.get(keyFor()).revision,
        expected_image_sha256: state.imageSourceHash, replace_all: true, request_id: crypto.randomUUID()}};
  } finally { state.busy = false; updateControls(); }
  if (applyPending()) await confirmModelApply();
}
async function confirmModelApply() {
  const trial = state.modelPreview, pending = trial.pendingApply;
  if (!pending || state.busy || pending.needsReload) return;
  state.busy = true; trial.error = ''; updateControls();
  let data;
  try { data = await jsonRequest(pending.url, 'POST', pending.body); }
  catch (error) {
    if (modelHelpers.ambiguous(error)) {
      pending.uncertain = true; trial.error = `${t('modelUnknown')} ${error.message}`;
    } else if (pending.uncertain) {
      pending.needsReload = true; trial.error = `${t('modelReloadRequired')} ${error.message}`;
    } else {
      trial.pendingApply = null; clearModelPreview(); trial.error = `${t('modelApplyFailed')} ${error.message}`;
    }
  }
  if (data) {
    // Only an acknowledged write enters history; retries cannot add a second entry.
    state.history.push(pending.before); if (state.history.length > 80) state.history.shift();
    trial.pendingApply = null; clearModelPreview('modelApplied');
    clearReferenceConfirmation();
    trackRevision(data); adopt(data); draw();
  }
  state.busy = false; updateControls();
  if (data) await loadImages().catch(error => setStatus(`${t('modelApplied')} ${t('modelListRefreshFailed')}: ${error.message}`, true));
}
async function reloadModelApplyOutcome() {
  const pending = state.modelPreview.pendingApply;
  if (!pending?.uncertain || state.busy) return;
  state.busy = true; updateControls();
  try {
    // Read only: never flush the pre-apply local snapshot over an uncertain server result.
    const [data, photo] = await Promise.all([jsonRequest(imageURL('/detections')), loadPlateImage(imageURL('/raw'), !state.config?.web_mode)]);
    state.img = photo.image; state.display = boundedImage(photo.image); state.imageSourceHash = photo.sourceHash;
    const receipt = data._model_preview_apply;
    if (receipt?.request_id === pending.body.request_id && receipt.applied_revision === data.revision
      && photo.sourceHash === pending.body.expected_image_sha256) {
      state.history.push(pending.before); if (state.history.length > 80) state.history.shift();
    } else state.history = []; // Do not offer an undo that would overwrite another tab's later work.
    state.modelPreview.pendingApply = null; clearModelPreview('modelReloaded');
    resetReferenceContext(null); trackRevision(data); adopt(data); fitToCanvas();
  } catch (error) { state.modelPreview.error = `${t('modelReloadRequired')} ${error.message}`; }
  finally { state.busy = false; updateControls(); draw(); }
}

// Canvas: repaint at most once per animation frame. Colony edits reuse a cached viewport.
function ratio() { return Math.min(window.devicePixelRatio || 1, 2); }
function resizeCanvas() {
  const rect = $('canvas-wrap').getBoundingClientRect(), scale = ratio();
  const width = Math.max(1, Math.floor(rect.width * scale)), height = Math.max(1, Math.floor(rect.height * scale));
  const next = {width: width / scale, height: height / scale, ratio: scale}, previous = state.canvasSize;
  const canvas = $('canvas');
  if (canvas.width === width && canvas.height === height && previous.width === next.width
    && previous.height === next.height && previous.ratio === scale) return false;
  // Keep CSS-pixel dimensions separately: the old backing pixels may have a different device ratio.
  const hadSize = previous.width > 0 && previous.height > 0;
  const center = hadSize ? screenToImg(previous.width / 2, previous.height / 2) : null;
  if (state.gesture) cancelGesture(); // A drag's starting offsets are no longer valid after layout changes.
  canvas.width = width; canvas.height = height; state.canvasSize = next;
  if (state.img) {
    if (state.view.fitted || !hadSize) fitViewToSize(next.width, next.height);
    else {
      state.view.ox = next.width / 2 - center[0] * state.view.zoom;
      state.view.oy = next.height / 2 - center[1] * state.view.zoom;
    }
  }
  state.backdropDirty = true;
  return true;
}
function fitViewToSize(width, height) {
  if (!state.img) return;
  // The machine's medium boundary never limits the photo a human can inspect.
  state.view.zoom = Math.min(width / state.img.width, height / state.img.height) * 0.94;
  state.view.ox = width / 2 - state.img.width / 2 * state.view.zoom;
  state.view.oy = height / 2 - state.img.height / 2 * state.view.zoom;
  state.view.fitted = true;
}
function fitToCanvas() {
  resizeCanvas();
  fitViewToSize(state.canvasSize.width, state.canvasSize.height);
  invalidateBackground();
}
function screenToImg(x, y) { return [(x - state.view.ox) / state.view.zoom, (y - state.view.oy) / state.view.zoom]; }
function pointerPosition(event) {
  const rect = $('canvas').getBoundingClientRect();
  return [event.clientX - rect.left, event.clientY - rect.top];
}
function imageTransform(ctx) {
  ctx.scale(ratio(), ratio()); ctx.translate(state.view.ox, state.view.oy); ctx.scale(state.view.zoom, state.view.zoom);
}
function invalidateBackground() { state.backdropDirty = true; draw(); }
function draw() {
  if (state.frame !== null) return;
  state.frame = requestAnimationFrame(() => { state.frame = null; paint(); });
}
// Saved and temporary colony marks share source colors; preview state stays separate.
function paintColonyMark(ctx, detection, showLabel = false) {
  const ink = detection.source === 'manual' ? 'rgba(117,149,166,0.9)' : 'rgba(183,131,150,0.9)';
  ctx.setLineDash([]);
  ctx.strokeStyle = ink; ctx.lineWidth = 2.75 / state.view.zoom;
  ctx.beginPath(); ctx.arc(detection.cx, detection.cy, Math.max(detection.r, 2), 0, Math.PI * 2); ctx.stroke();
  if (showLabel) {
    ctx.fillStyle = ink;
    ctx.fillText(String(detection.id), detection.cx + detection.r + 3, detection.cy - 3);
  }
}
function paint() {
  resizeCanvas();
  const canvas = $('canvas'), ctx = canvas.getContext('2d');
  if (!state.backdrop) state.backdrop = document.createElement('canvas');
  if (state.backdrop.width !== canvas.width || state.backdrop.height !== canvas.height) {
    state.backdrop.width = canvas.width; state.backdrop.height = canvas.height; state.backdropDirty = true;
  }
  if (state.backdropDirty) {
    const bg = state.backdrop.getContext('2d');
    bg.fillStyle = '#f1f1f1'; bg.fillRect(0, 0, canvas.width, canvas.height);
    if (state.img) {
      bg.save(); imageTransform(bg);
      const display = state.view.zoom * ratio() > state.display.width / state.img.width * 1.6 ? state.img : state.display;
      bg.drawImage(display, 0, 0, state.img.width, state.img.height);
      if (state.preview?.plate && !state.crop && !modelMethod()) {
        // The API's preview includes a grey exterior; never paint that over the source photo.
        // Bind the clip to the preview request, including while a newer preview is pending.
        const previewPlate = state.preview.plate;
        bg.save(); bg.beginPath();
        bg.arc(previewPlate.cx, previewPlate.cy, previewPlate.r, 0, Math.PI * 2); bg.clip();
        bg.globalAlpha = 0.65;
        bg.drawImage(state.preview.image, state.preview.x, state.preview.y);
        bg.restore();
      }
      bg.restore();
    }
    state.backdropDirty = false;
  }
  ctx.drawImage(state.backdrop, 0, 0);
  if (!state.img) return;
  ctx.save(); imageTransform(ctx);
  const plate = state.crop || state.plate;
  if (plate) {
    ctx.strokeStyle = state.crop ? '#444444' : 'rgba(180,180,180,0.9)'; ctx.lineWidth = 2 / state.view.zoom;
    ctx.setLineDash(state.crop ? [8 / state.view.zoom, 5 / state.view.zoom] : []);
    ctx.beginPath(); ctx.arc(plate.cx, plate.cy, plate.r, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
    if (state.crop) {
      const length = 10 / state.view.zoom;
      ctx.beginPath(); ctx.moveTo(plate.cx - length, plate.cy); ctx.lineTo(plate.cx + length, plate.cy);
      ctx.moveTo(plate.cx, plate.cy - length); ctx.lineTo(plate.cx, plate.cy + length); ctx.stroke();
      ctx.fillStyle = '#444444';
      for (const [x, y] of [[plate.cx + plate.r, plate.cy], [plate.cx - plate.r, plate.cy], [plate.cx, plate.cy + plate.r], [plate.cx, plate.cy - plate.r]]) {
        ctx.beginPath(); ctx.arc(x, y, 5 / state.view.zoom, 0, Math.PI * 2); ctx.fill();
      }
    }
  }
  if (modelMethod() && !state.crop) {
    const roi = modelHelpers.roiCircle(state.plate, modelInset());
    if (roi) {
      ctx.strokeStyle = '#777777'; ctx.lineWidth = 1.25 / state.view.zoom;
      ctx.setLineDash([3 / state.view.zoom, 4 / state.view.zoom]);
      ctx.beginPath(); ctx.arc(roi.cx, roi.cy, roi.r, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
    }
  }
  ctx.lineWidth = 2 / state.view.zoom; ctx.font = `${13 / state.view.zoom}px sans-serif`;
  const width = canvas.width / ratio(), height = canvas.height / ratio();
  // A model preview is a separate result, not additional marks on the saved
  // algorithm result. Saved marks remain intact and reappear when discarded.
  const candidate = displayedModelCandidate();
  const displayedDetections = candidate ? candidate.detections : state.detections;
  for (const detection of displayedDetections) {
    const x = detection.cx * state.view.zoom + state.view.ox, y = detection.cy * state.view.zoom + state.view.oy;
    const radius = detection.r * state.view.zoom;
    if (x + radius < 0 || x - radius > width || y + radius < 0 || y - radius > height) continue;
    paintColonyMark(ctx, detection, !candidate && (state.detections.length < 1200 || state.view.zoom > 0.4));
  }
  ctx.restore();
  const gesture = state.gesture;
  if (gesture?.kind === 'select') {
    ctx.save(); ctx.scale(ratio(), ratio()); ctx.strokeStyle = '#444444'; ctx.fillStyle = 'rgba(80,80,80,0.16)';
    ctx.setLineDash([5, 3]); ctx.lineWidth = 1.5;
    ctx.fillRect(gesture.sx, gesture.sy, gesture.x - gesture.sx, gesture.y - gesture.sy);
    ctx.strokeRect(gesture.sx, gesture.sy, gesture.x - gesture.sx, gesture.y - gesture.sy); ctx.restore();
  }
}
function findHit(x, y) {
  return state.detections.filter(d => Math.hypot(x - d.cx, y - d.cy) <= Math.max(d.r, 5 / state.view.zoom))
    .sort((a, b) => a.r - b.r)[0];
}
function cancelGesture() {
  if (state.gesture) clearTimeout(state.gesture.timer);
  state.gesture = null;
  $('canvas').classList.remove('panning');
  draw();
}
function onPointerDown(event) {
  if (modalOpen()) return;
  focusCanvas();
  if (state.loading || state.busy || applyPending() || reviewBlocked() || !state.img || !state.doc || ![0, 1].includes(event.button)) return;
  event.preventDefault();
  const [x, y] = pointerPosition(event), [ix, iy] = screenToImg(x, y);
  const gesture = {sx: x, sy: y, x, y, ix, iy, ox: state.view.ox, oy: state.view.oy, id: event.pointerId, kind: 'pending'};
  state.gesture = gesture;
  $('canvas').setPointerCapture(event.pointerId);
  if (previewCanvasReadOnly() || event.metaKey || event.ctrlKey || event.button === 1) gesture.kind = 'pan';
  else if (state.crop) {
    gesture.cropStart = {...state.crop};
    gesture.kind = Math.abs(Math.hypot(ix - state.crop.cx, iy - state.crop.cy) - state.crop.r) * state.view.zoom < 16 ? 'crop-resize' : 'crop-move';
  } else gesture.timer = setTimeout(() => {
    if (state.gesture === gesture && gesture.kind === 'pending') { gesture.kind = 'pan'; $('canvas').classList.add('panning'); }
  }, 350);
  if (gesture.kind === 'pan') $('canvas').classList.add('panning');
}
function onPointerMove(event) {
  const gesture = state.gesture;
  if (!gesture || event.pointerId !== gesture.id) return;
  const [x, y] = pointerPosition(event); gesture.x = x; gesture.y = y;
  if (previewCanvasReadOnly()) gesture.kind = 'pan';
  const distance = Math.hypot(x - gesture.sx, y - gesture.sy);
  if (gesture.kind === 'pending' && distance > 6) { clearTimeout(gesture.timer); gesture.kind = 'select'; }
  if (gesture.kind === 'pan') {
    if (distance > 0) state.view.fitted = false;
    state.view.ox = gesture.ox + x - gesture.sx; state.view.oy = gesture.oy + y - gesture.sy;
    invalidateBackground();
  } else if (gesture.kind.startsWith('crop-')) {
    const [ix, iy] = screenToImg(x, y);
    if (gesture.kind === 'crop-move') state.crop = clampCrop({...gesture.cropStart,
      cx: gesture.cropStart.cx + ix - gesture.ix, cy: gesture.cropStart.cy + iy - gesture.iy});
    else state.crop = clampCrop({...gesture.cropStart, r: Math.hypot(ix - gesture.cropStart.cx, iy - gesture.cropStart.cy)});
    syncCropInputs(); draw();
  } else draw();
}
function onPointerUp(event) {
  const gesture = state.gesture;
  if (!gesture || event.pointerId !== gesture.id) return;
  const [x, y] = pointerPosition(event), [ix, iy] = screenToImg(x, y);
  // A preview can arrive after pointerdown. Never edit saved marks that are
  // currently hidden behind the separate candidate view.
  if (previewCanvasReadOnly()) gesture.kind = 'pan';
  if (gesture.kind === 'select') {
    const [startX, startY] = screenToImg(gesture.sx, gesture.sy);
    const keep = state.detections.filter(d => !(d.cx >= Math.min(startX, ix) && d.cx <= Math.max(startX, ix) && d.cy >= Math.min(startY, iy) && d.cy <= Math.max(startY, iy)));
    if (keep.length !== state.detections.length) { remember(); state.detections = keep; changed(); }
  } else if (gesture.kind === 'pending') {
    if (ix < 0 || iy < 0 || ix >= state.img.width || iy >= state.img.height) fitToCanvas();
    else if (!findHit(ix, iy)) {
      remember();
      const id = state.detections.reduce((max, d) => Math.max(max, Number(d.id)), 0) + 1;
      const radius = Math.min(300, Math.hypot(state.img.width, state.img.height), Math.max(3, Number($('p-radius').value) || 40));
      state.detections.push({id, cx: ix, cy: iy, r: radius, score: 1, accepted: true, source: 'manual'}); changed();
    }
  }
  cancelGesture();
  if ($('canvas').hasPointerCapture(event.pointerId)) $('canvas').releasePointerCapture(event.pointerId);
}
function onContextMenu(event) {
  event.preventDefault();
  if (!editable() || previewCanvasReadOnly()) return;
  const [x, y] = screenToImg(...pointerPosition(event));
  const hit = findHit(x, y);
  if (hit) { remember(); state.detections = state.detections.filter(d => d.id !== hit.id); changed(); }
}
function onWheel(event) {
  event.preventDefault();
  if (!state.img || state.loading || state.busy || applyPending() || reviewBlocked()) return;
  cancelGesture();
  const [x, y] = pointerPosition(event), [ix, iy] = screenToImg(x, y);
  state.view.fitted = false;
  state.view.zoom = Math.min(12, Math.max(0.015, state.view.zoom * (event.deltaY < 0 ? 1.15 : 1 / 1.15)));
  state.view.ox = x - ix * state.view.zoom; state.view.oy = y - iy * state.view.zoom; invalidateBackground();
}
function undo() {
  if (!editable() || !state.history.length) return;
  clearModelPreview();
  const previous = state.history.pop();
  // Undo concerns colony/crop/count actions; subsequent note edits are independent.
  previous.notes = state.doc.notes;
  adopt(previous); changed({recordEdit: false}); refreshMaskPreview();
  // A server-reported stale record can become valid again after Undo; only the server may confirm that.
  if (reviewMode() && state.reference.envelope?.status === 'stale') return refreshReference().catch(handleError);
}
function clearAll() {
  if (!editable() || !state.detections.length) return;
  remember(); state.detections = []; changed();
}
function changeMode() {
  if (restrictedReview()) { $('mode-select').value = manualOnlyReview() ? 'manual' : 'auto'; updateControls(); return; }
  if (!state.doc) { updateControls(); return; }
  if (!editable()) return;
  remember(); state.doc.mode = $('mode-select').value;
  if (state.doc.mode === 'manual') {
    state.detections = state.detections.filter(d => d.source === 'manual');
    state.doc.machine_count_initial = 0; state.doc.counted = false; state.doc.count_params = null;
    state.doc.count_engine = null; state.doc.count_model = null;
  }
  state.paramsDirty = paramsDiffer();
  changed();
}
function clampCrop(circle) {
  return {...circle, cx: Math.min(state.img.width, Math.max(0, circle.cx)),
    cy: Math.min(state.img.height, Math.max(0, circle.cy)),
    r: Math.min(Math.max(state.img.width, state.img.height), Math.max(10, circle.r))};
}
function syncCropInputs() {
  for (const key of ['cx', 'cy', 'r']) $(`crop-${key}`).value = Math.round(state.crop[key] * 10) / 10;
}
function openCrop() {
  if (!editable()) return;
  $('image-actions-menu').open = false;
  clearModelPreview();
  clearPreview(); state.crop = {...state.plate}; syncCropInputs(); updateControls(); fitToCanvas();
}
function cancelCrop() { state.crop = null; cancelGesture(); updateControls(); fitToCanvas(); refreshMaskPreview(); }
function applyCrop() {
  if (!state.crop) return;
  remember(); state.plate = {...state.crop}; state.doc.plate_manual = true;
  state.crop = null; changed(); fitToCanvas(); refreshMaskPreview();
}
function cropInputChanged() {
  const values = Object.fromEntries(['cx', 'cy', 'r'].map(key => [key, Number($(`crop-${key}`).value)]));
  if (!Object.values(values).every(Number.isFinite) || values.r < 10) return;
  state.crop = clampCrop({...state.crop, ...values}); draw();
}

// Preview is a threshold mask only. Other filters never pretend to change it.
// Keep the last valid overlay visible while replacing it, and discard stale responses.
let previewTimer;
function setPreviewStatus(key = '') {
  state.previewStatus = key;
  $('preview-status').textContent = key ? t(key) : '';
  const failed = key === 'previewFailed' || key === 'previewFailedOld';
  $('preview-status').classList.toggle('error', failed);
  if (!failed) $('preview-status').title = '';
}
function clearPreview({keepImage = false} = {}) {
  clearTimeout(previewTimer); ++state.previewToken;
  state.previewController?.abort(); state.previewController = null;
  if (!keepImage) { state.preview = null; invalidateBackground(); }
  setPreviewStatus('');
}
function refreshMaskPreview() {
  if (restrictedReview() || (normalWorkflow() && (!customWorkflow() || !state.workflow.adjustmentsOpen)) || modelMethod() || applyPending() || reviewBlocked() || !$('p-preview').checked || !state.doc || state.crop) { clearPreview(); return; }
  let params; try { params = paramsBody(); } catch (_) { return; }
  const plate = {...state.plate};
  const signature = JSON.stringify(['foreground-mint-v1', keyFor(), plate.cx, plate.cy, plate.r,
    params.min_value, params.max_saturation, params.plate_inset]);
  clearPreview({keepImage: true});
  if (state.preview?.signature === signature) { setPreviewStatus('previewReady'); return; }
  const token = state.previewToken, key = keyFor(), url = imageURL('/mask_preview.png');
  setPreviewStatus(state.preview ? 'previewRefreshing' : 'previewLoading');
  previewTimer = setTimeout(async () => {
    const controller = new AbortController(); state.previewController = controller;
    let objectURL;
    try {
      await flushEdits();
      if (token !== state.previewToken || key !== keyFor()) return;
      const response = await request(url, {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(params), signal: controller.signal});
      objectURL = URL.createObjectURL(await response.blob());
      const image = await loadImage(objectURL);
      if (token === state.previewToken && key === keyFor()) {
        state.preview = {image, signature, plate, x: Math.max(0, Math.floor(plate.cx - plate.r - 24)), y: Math.max(0, Math.floor(plate.cy - plate.r - 24))};
        setPreviewStatus('previewReady'); invalidateBackground();
      }
    } catch (error) {
      if (error.name !== 'AbortError' && token === state.previewToken) {
        setPreviewStatus(state.preview ? 'previewFailedOld' : 'previewFailed'); $('preview-status').title = error.message;
        console.warn('Threshold preview failed:', error);
      }
    } finally { if (objectURL) URL.revokeObjectURL(objectURL); }
  }, 250);
}

async function recount() {
  if (restrictedReview() || !editable() || state.doc.mode === 'manual' || modelMethod()) return;
  clearModelPreview();
  const params = normalWorkflow() ? (customWorkflow() ? appliedCustomParams() : {...DEFAULTS}) : paramsBody(), engine = selectedBuiltinEngine();
  const hash = state.imageSourceHash;
  if (!/^[a-f0-9]{64}$/.test(hash || '')) throw new Error(t('recognitionSourceUnavailable'));
  let url = `${imageURL('/run')}?engine=${enc(engine)}&expected_image_sha256=${hash}`;
  state.busy = true; updateControls(); setStatus(t('statusProcessing')); clearPreview();
  try {
    await flushEdits();
    if (reviewMode()) await refreshReviewQueue({preserveReference: true});
    if (state.workflow.enabled) {
      const revision = state.saveQueues.get(keyFor())?.revision ?? state.doc.revision ?? 0;
      if (!Number.isInteger(revision)) throw new Error(t('modelMissingRevision'));
      url += `&expected_revision=${revision}`;
    }
    if (normalWorkflow()) {
      const reference = state.config?.web_mode ? {status: 'missing'} : await jsonRequest(imageURL('/reference'));
      const protection = workflowHelpers.batchProtection(state.doc, reference);
      if (protection && !window.confirm(t('customProtectedConfirm').replace('{name}', state.imageName).replace('{count}', state.detections.length))) {
        setStatus(''); return;
      }
      // Reference confirmation does not bump the image revision. Recheck unprotected work
      // under the server lock too; only an explicit replacement confirmation may opt out.
      if (!protection) url += '&protect_existing_edits=true';
    }
    const before = snapshot();
    const data = await jsonRequest(url, 'POST', params);
    state.history.push(before); if (state.history.length > 80) state.history.shift();
    trackRevision(data); adopt(data); state.paramsDirty = false; setStatus(t('statusDone'));
    await loadImages();
  } finally { state.busy = false; updateControls(); draw(); refreshMaskPreview(); }
}
async function countAll() {
  if (normalWorkflow()) {
    if (customWorkflow()) return countCustomBatch();
    return countDefaultBatch();
  }
  if (reviewMode() || !state.batch || state.loading || state.busy || state.crop || applyPending() || modelMethod() || $('mode-select').value === 'manual') return;
  clearModelPreview();
  const params = paramsBody(), batch = state.batch, engine = selectedBuiltinEngine();
  state.busy = true; state.cancelRun = false; updateControls(); clearPreview();
  $('btn-stop-run').hidden = false;
  try {
    await flushEdits();
    const items = [...state.imageList]; let count = 0, skipped = 0;
    for (let index = 0; index < items.length; index++) {
      if (state.cancelRun) break;
      const item = items[index];
      const existing = await request(imageURL('/detections', batch, item.name)).then(r => r.json()).catch(error => {
        if (error.status === 404) return null;
        throw error;
      });
      // Manual and already-counted images are preserved. Recount is explicit per image.
      if (existing?.mode === 'manual' || (existing && (existing.reviewed || existing.machine_count_initial > 0 || existing.detections?.length || existing.counted))) { skipped++; continue; }
      setStatus(`${t('statusProcessing')} ${index + 1}/${items.length} · ${item.name}`);
      const data = await jsonRequest(`${imageURL('/run', batch, item.name)}?engine=${enc(engine)}`, 'POST', params); count++;
      if (item.name === state.imageName) { remember(); trackRevision(data); adopt(data); draw(); }
    }
    await loadImages();
    setStatus(`${t(state.cancelRun ? 'countStopped' : 'statusDone')} · ${count} ${t('countCompleted')} · ${skipped} ${t('countSkipped')}`);
  } finally { state.busy = false; $('btn-stop-run').hidden = true; updateControls(); refreshMaskPreview(); }
}
function renderBatchReport(report) {
  const records = report.results, total = report.total;
  const completed = records.filter(r => r.status === 'completed').length;
  const skipped = records.filter(r => r.status === 'skipped').length;
  const failed = records.filter(r => ['failed', 'uncertain'].includes(r.status)).length;
  const remaining = total - records.length;
  const text = `${t(state.batchRun.active ? 'statusProcessing' : report.stopped ? 'countStopped' : 'statusDone')} · ${completed} ${t('countCompleted')} · ${skipped} ${t('countSkipped')} · ${failed} ${t('customBatchFailed')}${remaining ? ` · ${remaining} ${t('batchRemaining')}` : ''}`;
  $('batch-report').hidden = false;
  $('batch-report-summary').textContent = text;
  const fragment = document.createDocumentFragment();
  for (const record of records) {
    const row = document.createElement('li');
    const reason = record.status === 'completed' ? '' : record.reason;
    const labels = {completed: 'countCompleted', skipped: 'countSkipped', failed: 'customBatchFailed', uncertain: 'batchUncertain'};
    row.textContent = `${record.name} · ${t(labels[record.status])}${reason ? ` · ${batchReason(reason)}` : ''}`;
    fragment.appendChild(row);
  }
  $('batch-report-items').replaceChildren(fragment);
  if (!state.batchRun.active) setStatus(text, failed > 0);
}
function batchReason(reason) {
  const keys = {already_counted: 'batchAlreadyCounted', existing_marks: 'batchProtected',
    human_work: 'batchProtected', manual_mode: 'batchProtected', reference: 'batchProtected', source_view: 'sourceViewRequired'};
  return keys[reason] ? t(keys[reason]) : reason;
}
async function countDefaultBatch({onlyCurrent = false} = {}) {
  if (!normalWorkflow() || customWorkflow() || !state.batch || !state.imageList.length || state.loading || state.busy
    || state.crop || previewActive() || $('mode-select').value === 'manual') return;
  const engine = workflowDefaultEngine(), params = {...DEFAULTS};
  const useSam = engine === SAM_ENGINE, capability = clone(modelCapability(SAM_ENGINE));
  if (useSam && (!capability.enabled || !capability.available)) { setStatus(t('modelUnavailable'), true); return; }
  const batch = state.batch, items = state.imageList.filter(item => !onlyCurrent || item.name === state.imageName).map(item => ({name: item.name}));
  const report = {results: [], stopped: false, total: items.length};
  clearModelPreview(); clearPreview(); state.busy = true; state.cancelRun = false;
  state.batchRun = {active: true, report}; updateControls(); $('btn-stop-run').hidden = false;
  $('batch-report').open = false;
  try {
    await flushEdits();
    const outcome = await window.WECFU_SERIAL_BATCH.run(items, {
      shouldStop: () => state.cancelRun,
      onProgress: ({index, total, item}) => setStatus(`${t('statusProcessing')} ${index + 1}/${total} · ${item.name}`),
      runItem: async ({name}) => {
        const result = await window.WECFU_DEFAULT_BATCH[useSam ? 'recognize' : 'recognizeBuiltin']({batch, name, engine, params, capability, webMode: Boolean(state.config?.web_mode)}, {
          json: jsonRequest,
          source: async url => (await loadPlateImage(url)).sourceHash,
          valid: modelHelpers.valid,
          uuid: () => crypto.randomUUID(),
        });
        // The report contains names/outcomes only; marks and provenance stay in saved image state.
        report.results.push({name, status: result.status, reason: result.reason});
        if (result.status === 'completed') {
          if (batch === state.batch && name === state.imageName) {
            if (state.imageSourceHash === result.hash) {
              state.history.push(clone(result.before)); if (state.history.length > 80) state.history.shift();
              trackRevision(result.doc); adopt(result.doc); draw();
            } else emptyViewer(); // Never draw marks on source bytes that have changed.
          }
          await loadImages().catch(error => { report.listError = error.message; });
        } else if (result.status === 'uncertain' && batch === state.batch && name === state.imageName) {
          // Do not allow stale local edits to be saved over a possibly successful adoption.
          emptyViewer();
        }
        renderBatchReport(report);
        return {stop: result.stop === true};
      },
    });
    report.stopped = outcome.stopped;
  } finally {
    state.busy = false; state.batchRun.active = false; $('btn-stop-run').hidden = true;
    state.workflow.lastBatchReport = report;
    updateControls(); renderBatchReport(report); refreshMaskPreview();
  }
}

async function countCustomBatch() {
  if (!customWorkflow() || !state.batch || state.loading || state.busy || state.crop || applyPending()
    || $('mode-select').value === 'manual') return;
  // One immutable recipe for this entire explicit batch, including after adopting a current-image result.
  const params = appliedCustomParams(), batch = state.batch, engine = workflowBuiltinEngine();
  const items = state.imageList.map(item => ({...item}));
  const report = {completed: [], protected: [], failed: [], canceled: false};
  clearModelPreview(); clearPreview(); state.busy = true; state.cancelRun = false;
  updateControls(); $('btn-stop-run').hidden = false;
  try {
    await flushEdits();
    for (let index = 0; index < items.length; index++) {
      if (state.cancelRun) { report.canceled = true; break; }
      const name = items[index].name;
      let submitted = false;
      setStatus(`${t('statusProcessing')} ${index + 1}/${items.length} · ${name}`);
      try {
        const existing = await jsonRequest(imageURL('/detections', batch, name)).catch(error => {
          if (error.status === 404) return null;
          throw error;
        });
        let protection = workflowHelpers.batchProtection(existing, {status: 'missing'});
        if (!protection) {
          const reference = state.config?.web_mode ? {status: 'missing'} : await jsonRequest(imageURL('/reference', batch, name));
          protection = workflowHelpers.batchProtection(existing, reference);
        }
        if (protection) { report.protected.push({name, reason: protection}); continue; }
        if (state.cancelRun) { report.canceled = true; break; }
        const revision = existing?.revision ?? 0;
        if (!Number.isInteger(revision)) throw new Error(t('modelMissingRevision'));
        const hash = (await loadPlateImage(imageURL('/raw', batch, name))).sourceHash;
        if (!/^[a-f0-9]{64}$/.test(hash || '')) throw new Error(t('recognitionSourceUnavailable'));
        submitted = true;
        const data = await jsonRequest(`${imageURL('/run', batch, name)}?engine=${enc(engine)}&expected_revision=${revision}&protect_existing_edits=true&expected_image_sha256=${hash}`, 'POST', params);
        report.completed.push(name);
        if (batch === state.batch && name === state.imageName && state.imageSourceHash === hash) {
          // Undo restores exactly the server state replaced by this run, including a newer
          // machine-only result from another tab, not this tab's older displayed snapshot.
          if (existing) { state.history.push(clone(existing)); if (state.history.length > 80) state.history.shift(); }
          else state.history = [];
          trackRevision(data); adopt(data); draw();
        } else if (batch === state.batch && name === state.imageName) emptyViewer();
      } catch (error) {
        // A concurrent edit or newly created reference is protected under the server lock. Never retry it.
        const uncertain = submitted && (!Number.isInteger(error.status) || error.status >= 500);
        (error.status === 409 ? report.protected : report.failed).push({name, reason: error.message, ...(uncertain ? {uncertain: true} : {})});
        if (uncertain) {
          // A lost response may follow a successful write. Stop rather than overwrite from stale state.
          if (batch === state.batch && name === state.imageName) emptyViewer();
          report.canceled = true; break;
        }
      }
    }
    await loadImages();
    setStatus(`${t(report.canceled ? 'countStopped' : 'statusDone')} · ${report.completed.length} ${t('countCompleted')} · ${report.protected.length} ${t('countSkipped')} · ${report.failed.length} ${t('customBatchFailed')}`, report.failed.length > 0);
    $('status').title = [...report.protected, ...report.failed].map(item => `${item.name}: ${item.reason}`).join('\n');
  } finally {
    state.workflow.lastBatchReport = report;
    state.busy = false; $('btn-stop-run').hidden = true; updateControls(); refreshMaskPreview();
  }
}

async function ingestPath(path) {
  if (reviewMode() || state.busy || state.loading || state.crop || applyPending()) return;
  clearModelPreview();
  state.busy = true; updateControls(); setStatus(t('statusIngesting'));
  try {
    await flushEdits();
    const result = await jsonRequest('/api/ingest', 'POST', {paths: [path], view: 'unknown', ...(state.batch ? {batch: state.batch} : {})});
    state.batch = result.batch; await loadImages(); setStatus(t('statusDone'));
  } finally { state.busy = false; updateControls(); }
}
async function uploadFiles(fileList) {
  if (reviewMode() || state.busy || state.loading || state.crop || applyPending()) return;
  clearModelPreview();
  const files = Array.from(fileList).filter(file => /\.(jpe?g|png|tif{1,2})$/i.test(file.name));
  if (!files.length) throw new Error(t('noImages'));
  state.busy = true; updateControls(); setStatus(t('statusUploading'));
  const batch = state.batch || `upload_${new Date().toISOString().replace(/[:.]/g, '-')}`;
  try {
    await flushEdits();
    const data = new FormData(); data.append('batch', batch); data.append('view', 'unknown');
    for (const file of files) data.append('files', file);
    const result = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest(); xhr.open('POST', '/api/upload');
      xhr.upload.addEventListener('progress', event => {
        if (event.lengthComputable) setStatus(`${t('statusUploading')} ${Math.round(event.loaded / event.total * 100)}% · ${files.length}`);
      });
      xhr.onload = () => {
        let body; try { body = JSON.parse(xhr.responseText); } catch (_) { body = {}; }
        if (xhr.status >= 200 && xhr.status < 300) resolve(body);
        else reject(new Error(body.detail || `HTTP ${xhr.status}`));
      };
      xhr.onerror = () => reject(new Error(t('networkError'))); xhr.send(data);
    });
    state.batch = result.batch || batch; await loadImages(); setStatus(t('statusDone'));
  } finally { state.busy = false; $('file-input').value = ''; updateControls(); }
}
async function walkDir(entry, files) {
  if (entry.isFile) { files.push(await new Promise((resolve, reject) => entry.file(resolve, reject))); return; }
  const reader = entry.createReader();
  while (true) {
    const entries = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
    if (!entries.length) break;
    for (const child of entries) await walkDir(child, files);
  }
}
function bulkSelectionLocked() {
  return reviewMode() || state.busy || state.loading || Boolean(state.crop) || applyPending() || state.modelPreview.loading;
}
function updateBulkSelectionControls() {
  const selection = state.bulkSelection;
  if (selection.batch !== state.batch || reviewMode()) {
    selection.batch = state.batch; selection.enabled = false; selection.names.clear();
  }
  const available = new Set(state.imageList.map(item => item.name));
  for (const name of selection.names) if (!available.has(name)) selection.names.delete(name);
  const locked = bulkSelectionLocked();
  $('bulk-image-tools').hidden = reviewMode() || !state.imageList.length;
  $('btn-bulk-select').disabled = locked;
  $('btn-bulk-select').textContent = t(selection.enabled ? 'finishSelection' : 'bulkDeleteMode');
  $('btn-bulk-select').setAttribute('aria-expanded', String(selection.enabled));
  $('bulk-selection-actions').hidden = !selection.enabled;
  $('bulk-selected-count').textContent = t('imagesSelected').replace('{count}', selection.names.size);
  const allSelected = state.imageList.length > 0 && selection.names.size === state.imageList.length;
  $('btn-bulk-all').disabled = locked || !selection.enabled || !state.imageList.length;
  $('btn-bulk-all').setAttribute('aria-checked', allSelected ? 'true' : selection.names.size ? 'mixed' : 'false');
  $('btn-bulk-all').title = t(allSelected ? 'selectNoImages' : 'selectAllImages');
  $('btn-bulk-delete').disabled = locked || !selection.names.size;
  $('image-list').classList.toggle('bulk-selecting', selection.enabled);
  for (const row of $('image-list').children) {
    const checked = selection.names.has(row.dataset.name);
    row.classList.toggle('bulk-selected', selection.enabled && checked);
    const check = row.querySelector('.row-select-check');
    if (check) { check.hidden = !selection.enabled; check.textContent = checked ? '✓' : ''; }
    if (selection.enabled) {
      row.setAttribute('role', 'checkbox'); row.setAttribute('aria-checked', String(checked)); row.disabled = locked;
    } else {
      row.removeAttribute('role'); row.removeAttribute('aria-checked'); row.disabled = false;
    }
  }
}
function toggleBulkSelection() {
  if (bulkSelectionLocked() || !state.imageList.length) return;
  state.bulkSelection.enabled = !state.bulkSelection.enabled;
  state.bulkSelection.batch = state.batch; state.bulkSelection.names.clear();
  updateBulkSelectionControls();
}
function toggleBulkImage(name) {
  if (bulkSelectionLocked() || !state.bulkSelection.enabled || !state.imageList.some(item => item.name === name)) return;
  const names = state.bulkSelection.names;
  if (names.has(name)) names.delete(name); else names.add(name);
  updateBulkSelectionControls();
}
function selectBulkImages(all) {
  if (bulkSelectionLocked() || !state.bulkSelection.enabled) return;
  state.bulkSelection.names = new Set(all ? state.imageList.map(item => item.name) : []);
  updateBulkSelectionControls();
}
function toggleAllBulkImages() {
  const available = state.imageList.map(item => item.name);
  selectBulkImages(!available.length || !available.every(name => state.bulkSelection.names.has(name)));
}
async function removeSelectedImages() {
  if (bulkSelectionLocked() || !state.bulkSelection.enabled || !state.batch) return;
  const batch = state.batch;
  const names = state.imageList.filter(item => state.bulkSelection.names.has(item.name)).map(item => item.name);
  if (!names.length) return;
  const details = names.slice(0, 8).join('\n') + (names.length > 8 ? '\n…' : '');
  if (!window.confirm(t('bulkDeleteConfirm').replace('{count}', names.length) + '\n\n' + details)) return;
  clearModelPreview(); clearPreview();
  state.busy = true; updateControls();
  const report = {removed: [], failed: []};
  let currentRemoved = false;
  const oldIndex = state.imageList.findIndex(item => item.name === state.imageName);
  try {
    await flushEdits();
    for (const name of names) {
      setStatus(t('bulkDeleting').replace('{current}', report.removed.length + report.failed.length + 1).replace('{total}', names.length));
      try {
        await jsonRequest(imageURL('', batch, name), 'DELETE');
      } catch (error) {
        if (error.status !== 404) { report.failed.push({name, reason: error.message}); continue; }
      }
      report.removed.push(name);
      state.saveQueues.delete(keyFor(batch, name));
      state.bulkSelection.names.delete(name);
      state.imageList = state.imageList.filter(item => item.name !== name);
      if (name === state.imageName) { currentRemoved = true; emptyViewer(); }
    }
    if (!state.imageList.length || !state.bulkSelection.names.size) state.bulkSelection.enabled = false;
    renderImageList();
    // Refresh failure must not turn acknowledged removals back into local editable rows.
    await loadImages().catch(error => { report.refreshError = error.message; });
  } finally {
    state.bulkSelection.lastReport = report;
    state.busy = false; updateControls(); draw();
  }
  if (currentRemoved && state.imageList.length) {
    await selectImage(state.imageList[Math.min(Math.max(oldIndex, 0), state.imageList.length - 1)].name)
      .catch(error => { report.refreshError = error.message; });
  }
  const message = t('bulkDeleteDone').replace('{count}', report.removed.length)
    + (report.failed.length ? ' · ' + t('bulkDeleteFailed').replace('{count}', report.failed.length) : '')
    + (report.refreshError ? ' · ' + t('bulkRefreshFailed') : '');
  setStatus(message, Boolean(report.failed.length || report.refreshError));
  $('status').title = report.failed.map(item => `${item.name}: ${item.reason}`).join('\n');
}

async function removeImage() {
  if (reviewMode() || !editable()) return;
  const name = state.imageName, url = imageURL(), key = keyFor();
  const index = state.imageList.findIndex(item => item.name === name);
  if (!window.confirm(`${t('removeImageConfirm')}\n${name}`)) return;
  state.busy = true; updateControls();
  try {
    await flushEdits(); await jsonRequest(url, 'DELETE');
    state.saveQueues.delete(key); emptyViewer(); await loadImages();
  } finally { state.busy = false; updateControls(); }
  if (state.imageList.length) await selectImage(state.imageList[Math.min(index, state.imageList.length - 1)].name);
}

let exportFormat = 'csv';
function openExportModal(format) {
  if (reviewMode() || state.busy || state.loading || state.crop || applyPending()) return;
  exportFormat = format;
  const base = state.imageList.length === 1 ? state.imageList[0].name.replace(/\.[^.]+$/, '') : `wecfu_${state.batch}`;
  $('export-filename').value = `${base}.${format}`; $('export-backdrop').hidden = false;
  $('export-filename').focus(); $('export-filename').select();
}
async function pickSaveLocation() {
  if (!window.showDirectoryPicker) { setStatus(t('exportSaveLocationDefault')); return; }
  try { state.saveDirHandle = await window.showDirectoryPicker({mode: 'readwrite'}); $('export-location-btn').textContent = `${state.saveDirHandle.name}/`; }
  catch (error) { if (error.name !== 'AbortError') throw error; }
}
async function doExport() {
  if (reviewMode() || state.busy || state.loading || applyPending()) return;
  const filename = $('export-filename').value.trim() || `wecfu_${state.batch}.${exportFormat}`;
  const finalName = filename.toLowerCase().endsWith(`.${exportFormat}`) ? filename : `${filename}.${exportFormat}`;
  state.busy = true; updateControls(); $('btn-export-confirm').disabled = true; $('btn-export-cancel').disabled = true;
  setStatus(t(exportFormat === 'csv' ? 'exportPreparingCSV' : 'exportPreparingZIP'));
  let writable;
  try {
    await flushEdits();
    const response = await request(`/api/batch/${enc(state.batch)}/export.${exportFormat}?filename=${enc(finalName)}`);
    if (state.saveDirHandle && window.showDirectoryPicker) {
      const file = await state.saveDirHandle.getFileHandle(finalName, {create: true}); writable = await file.createWritable();
    }
    const total = Number(response.headers.get('content-length'));
    let received = 0; const chunks = [];
    if (response.body?.getReader) {
      const reader = response.body.getReader();
      while (true) {
        const {done, value} = await reader.read(); if (done) break;
        received += value.byteLength;
        if (writable) await writable.write(value); else chunks.push(value);
        setStatus(`${t('exportReceiving')} ${total ? `${Math.round(received / total * 100)}%` : `${(received / 1048576).toFixed(1)} MB`}`);
      }
    } else {
      const blob = await response.blob(); if (writable) await writable.write(blob); else chunks.push(blob);
    }
    if (writable) { await writable.close(); writable = null; }
    else {
      const url = URL.createObjectURL(new Blob(chunks)); const link = document.createElement('a');
      link.href = url; link.download = finalName; document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    }
    setStatus(t(state.saveDirHandle ? 'exportSaved' : 'exportDownloadStarted')); $('export-backdrop').hidden = true;
  } finally {
    if (writable) await writable.abort().catch(() => {});
    state.busy = false; $('btn-export-confirm').disabled = false; $('btn-export-cancel').disabled = false; updateControls();
  }
}
function openHelp() { $('help-body').innerHTML = t('helpBody'); $('modal-backdrop').hidden = false; }
function closeHelp() { $('modal-backdrop').hidden = true; }
function populateLangSelect() {
  for (const [code, name] of Object.entries(LANG_NAMES)) { const option = document.createElement('option'); option.value = code; option.textContent = name; $('lang-select').appendChild(option); }
  $('lang-select').value = getLang();
  $('lang-select').addEventListener('change', event => {
    setLang(event.target.value); renderImageList(); updateControls(); syncSliders();
    $('help-body').innerHTML = t('helpBody');
    focusAfterSelect(event.currentTarget || $('lang-select'));
  });
}
function onKeyDown(event) {
  if (event.key === 'Escape') {
    $('recognition-mode-info').open = false;
    cancelGesture(); if (state.crop) cancelCrop(); closeHelp();
    if (!state.busy) $('export-backdrop').hidden = true;
    return;
  }
  const target = document.activeElement || event.target;
  const ownsKeys = workflowHelpers ? workflowHelpers.ownsArrowKeys(target)
    : target?.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target?.tagName);
  if (modalOpen() || ownsKeys || event.defaultPrevented || event.isComposing) return;
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); return undo(); }
  const direction = workflowHelpers ? workflowHelpers.navigationDelta(event, target, false)
    : event.key === 'ArrowRight' || event.key === 'j' ? 1 : event.key === 'ArrowLeft' || event.key === 'k' ? -1 : 0;
  if (direction) { event.preventDefault(); return moveSelection(direction); }
  if (!event.metaKey && !event.ctrlKey && !event.altKey && event.key.toLowerCase() === 'f') fitToCanvas();
}
function wireUpHandlers() {
  const actions = {
    'btn-ingest': () => { const path = $('path-input').value.trim(); if (path) return ingestPath(path); },
    'btn-add-images': () => { if (!reviewMode()) $('file-input').click(); }, 'btn-remove-image': removeImage,
    'btn-bulk-select': toggleBulkSelection, 'btn-bulk-all': toggleAllBulkImages,
    'btn-bulk-delete': removeSelectedImages,
    'btn-adjustments-toggle': toggleAdjustmentPanel,
    'btn-run': countAll, 'btn-recognize-all': countAll, 'btn-stop-run': () => { state.cancelRun = true; setStatus(t('batchStopping')); },
    'btn-rerun': recount, 'btn-apply-params': () => customWorkflow() ? applyCustomSettings() : recount(), 'btn-defaults': resetDefaults,
    'btn-undo': undo, 'btn-clear': clearAll, 'btn-fit': fitToCanvas,
    'btn-prev': () => moveSelection(-1), 'btn-next': () => moveSelection(1),
    'btn-crop': openCrop, 'btn-crop-apply': applyCrop, 'btn-crop-cancel': cancelCrop,
    'btn-save-retry': flushEdits,
    'btn-export-csv': () => openExportModal('csv'), 'btn-export-zip': () => openExportModal('zip'),
    'btn-export-cancel': () => { if (!state.busy) $('export-backdrop').hidden = true; },
    'btn-export-confirm': doExport, 'export-location-btn': pickSaveLocation,
    'btn-help': openHelp, 'btn-help-close': closeHelp,
    'btn-reference-save': saveHumanReference, 'btn-reference-refresh': () => refreshReference({reloadImage: true}),
    'btn-reference-withdraw': withdrawHumanReference, 'btn-reference-export': exportHumanReferences,
    'btn-model-preview': runModelPreview, 'btn-model-apply': applyModelPreview,
    'btn-model-discard': () => { if (!applyPending()) { clearModelPreview(); updateControls(); } },
    'btn-model-retry': confirmModelApply, 'btn-model-reload': reloadModelApplyOutcome,
    'btn-review-refresh': refreshReviewProgress,
    'btn-review-params': () => {
      const expanded = $('viewer').classList.toggle('review-params-open');
      $('btn-review-params').setAttribute('aria-expanded', String(expanded));
    },
  };
  if (state.workflow.enabled) {
    actions['btn-recognize-current'] = recognizeCurrent;
    actions['btn-custom-run-all'] = countAll;
    $('recognition-profile').addEventListener('change', safeAction(event => { changeRecognitionProfile(); focusAfterSelect(event.currentTarget || $('recognition-profile')); }));
  }
  for (const id of ['lang-select', 'mode-select', 'method-select', 'preset-select', ...(state.workflow.enabled ? ['recognition-profile'] : [])]) {
    const select = $(id);
    select.addEventListener('pointerdown', () => pointerSelects.add(select));
    select.addEventListener('keydown', () => pointerSelects.delete(select));
  }
  for (const [id, action] of Object.entries(actions)) $(id).addEventListener('click', safeAction(event => {
    const result = action(event);
    focusCanvas(); // Return focus immediately, never after a long request while the user may be typing.
    return result;
  }));
  $('file-input').addEventListener('change', safeAction(event => uploadFiles(event.target.files)));
  $('mode-select').addEventListener('change', event => { changeMode(); focusAfterSelect(event.currentTarget || $('mode-select')); });
  $('method-select').addEventListener('change', event => { changeMethod(); focusAfterSelect(event.currentTarget || $('method-select')); });
  $('reference-panel').addEventListener('toggle', safeAction(() => {
    updateReferenceControls();
    if ($('reference-panel').open) return refreshReference({reloadImage: true});
  }));
  $('reference-confirmed').addEventListener('change', updateReferenceControls);
  $('reference-crop-confirmed').addEventListener('change', updateReferenceControls);
  $('reference-annotator').addEventListener('input', () => {
    try { localStorage.setItem('wecfu.reference.annotator', $('reference-annotator').value.trim()); } catch (_) { /* Optional reviewer preference. */ }
    updateReferenceControls();
  });
  $('preset-select').addEventListener('change', event => { applyPreset(event.target.value); focusAfterSelect(event.currentTarget || $('preset-select')); });
  for (const [key, id] of Object.entries(PARAM_IDS)) $(id).addEventListener('input', () => {
    $('preset-select').value = 'custom'; syncSliders(); parametersChanged(key);
  });
  for (const [key, spec] of Object.entries(paramControls.SPECS)) {
    const slider = $(`s-${spec.id}`);
    slider.addEventListener('input', () => sliderChanged(key));
    const input = $(`v-${spec.id}`);
    input.addEventListener('focus', () => input.select?.());
    input.addEventListener('input', () => { input.dataset.edited = '1'; input.removeAttribute('aria-invalid'); });
    input.addEventListener('change', () => commitSliderValue(key));
    input.addEventListener('blur', () => commitSliderValue(key));
    input.addEventListener('keydown', event => {
      if (event.isComposing) return;
      if (event.key === 'Enter') { event.preventDefault(); commitSliderValue(key); input.blur?.(); }
      else if (event.key === 'Escape') { event.preventDefault(); input.dataset.edited = ''; syncSliders(); input.removeAttribute('aria-invalid'); input.blur?.(); }
    });
    if (spec.integer) slider.addEventListener('keydown', event => sliderKeyDown(key, event));
  }
  $('current-source-view').addEventListener('change', safeAction(changeSourceView));
  $('p-radius').addEventListener('input', () => { syncSliders(); updateControls(); });
  $('p-preview').addEventListener('change', () => {
    try { localStorage.setItem('wecfu.preview.enabled', String($('p-preview').checked)); } catch (_) { /* Optional browser preference. */ }
    refreshMaskPreview();
  });
  $('notes-input').addEventListener('input', () => {
    if (!editable()) return; clearModelPreview(); state.doc.notes = $('notes-input').value; queueSave(); updateCurrentRow(); updateControls();
  });
  for (const key of ['cx', 'cy', 'r']) $(`crop-${key}`).addEventListener('input', cropInputChanged);
  $('modal-backdrop').addEventListener('click', event => { if (event.target.id === 'modal-backdrop') closeHelp(); });
  $('export-backdrop').addEventListener('click', event => { if (event.target.id === 'export-backdrop' && !state.busy) $('export-backdrop').hidden = true; });
  const canvas = $('canvas');
  canvas.tabIndex = 0;
  $('canvas-wrap').addEventListener('pointerdown', event => {
    if (event.target === $('canvas-wrap') || event.target === $('canvas-message')) focusCanvas();
  });
  canvas.addEventListener('pointerdown', onPointerDown); canvas.addEventListener('pointermove', onPointerMove);
  canvas.addEventListener('pointerup', onPointerUp); canvas.addEventListener('pointercancel', cancelGesture);
  canvas.addEventListener('lostpointercapture', cancelGesture);
  canvas.addEventListener('contextmenu', onContextMenu); canvas.addEventListener('wheel', onWheel, {passive: false});
  new ResizeObserver(() => { resizeCanvas(); invalidateBackground(); }).observe($('canvas-wrap'));
  window.addEventListener('keydown', safeAction(onKeyDown));
  window.addEventListener('beforeunload', event => {
    if (state.batchRun.active || applyPending() || Array.from(state.saveQueues.values()).some(queue => queue.pending || queue.saving)) {
      event.preventDefault(); event.returnValue = ''; // Warn for unsaved edits or an unresolved replacement.
    }
  });
  const dropzone = $('dropzone');
  dropzone.addEventListener('dragover', event => { event.preventDefault(); dropzone.classList.add('dragging'); });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragging'));
  dropzone.addEventListener('drop', safeAction(async event => {
    event.preventDefault(); dropzone.classList.remove('dragging');
    if (reviewMode() || state.busy || state.loading || state.crop || applyPending()) return;
    const entries = [], files = [];
    for (const item of event.dataTransfer.items) {
      if (item.kind !== 'file') continue;
      const entry = item.webkitGetAsEntry?.();
      if (entry) entries.push(entry); else { const file = item.getAsFile(); if (file) files.push(file); }
    }
    for (const entry of entries) await walkDir(entry, files);
    await uploadFiles(files);
  }));
}
async function readServerConfig() {
  // Only this startup GET can retry. Recognition, adoption and edits stay single-attempt.
  const delays = [0, 300, 900];
  for (let attempt = 0; attempt < delays.length; attempt++) {
    if (delays[attempt]) await new Promise(resolve => setTimeout(resolve, delays[attempt]));
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      return await (await request('/api/config', {method: 'GET', cache: 'no-store', signal: controller.signal})).json();
    } catch (error) {
      const transient = error.name === 'TypeError' || error.name === 'AbortError'
        || [502, 503, 504].includes(error.status);
      if (!transient || attempt === delays.length - 1) throw error;
    } finally { clearTimeout(timer); }
  }
}
async function applyServerConfig() {
  const config = await readServerConfig(); state.config = config;
  const configDefaults = config.default_params;
  const fallback = !builtinEngines().includes(ENHANCED_ENGINE) ? LEGACY_DEFAULTS : DEFAULTS;
  for (const key of Object.keys(DEFAULTS)) DEFAULTS[key] = Number.isFinite(configDefaults?.[key]) ? configDefaults[key] : fallback[key];
  PRESETS.white = {...DEFAULTS};
  state.workflow.customParams ||= {...DEFAULTS};
  state.workflow.appliedCustomParams ||= {...DEFAULTS};
  if (normalWorkflow()) syncWorkflowRoute();
  else $('method-select').value = defaultBuiltinEngine();
  if (!state.doc) fillParams(normalWorkflow() ? workflowParams() : DEFAULTS);
  updateControls();
  if (config.web_mode) {
    $('path-import').hidden = true;
    for (const id of ['path-input', 'btn-ingest']) $(id).hidden = true;
    document.querySelector('[data-i18n="pasteHint"]').hidden = true;
    $('export-location-btn').closest('label').hidden = true;
    $('reference-panel').hidden = true;
  }
}
window.addEventListener('DOMContentLoaded', async () => {
  applyI18n(); populateLangSelect();
  try { $('p-preview').checked = localStorage.getItem('wecfu.preview.enabled') !== 'false'; } catch (_) { $('p-preview').checked = true; }
  try { $('reference-annotator').value = localStorage.getItem('wecfu.reference.annotator') || ''; } catch (_) { /* Optional reviewer preference. */ }
  configureReviewMode(); initializeWorkflow(); wireUpHandlers(); fillParams(DEFAULTS); updateControls(); draw();
  try { await applyServerConfig(); await loadDefaultBatch(); } catch (error) { handleError(error); }
});
