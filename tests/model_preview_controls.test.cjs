// Synthetic state only. No browser, model weights, server or user workspace.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const helpers = require('../wecfu/server/static/model_preview_controls.js');
const reference = require('../wecfu/server/static/reference_controls.js');
const params = require('../wecfu/server/static/param_controls.js');
const workflow = require('../wecfu/server/static/workflow_controls.js');
const publicFusion = require('../wecfu/server/product_fusion_v2.json');
const source = fs.readFileSync(path.join(__dirname, '../wecfu/server/static/app.js'), 'utf8');
const hash = 'a'.repeat(64);
const plate = {cx: 160, cy: 120, r: 110};
const marks = [{id: 3, cx: 110, cy: 110, r: 8, score: 1, accepted: true, source: 'cv'},
  {id: 9, cx: 180, cy: 130, r: 10, score: 1, accepted: true, source: 'manual'}];
const plain = x => JSON.parse(JSON.stringify(x));
function candidate(overrides = {}) {
  return {candidate_id: 'synthetic-candidate', engine: helpers.ENGINE, base_revision: 17, image_sha256: hash, plate,
    model_params: {plate_inset: .82, score_threshold: .45, nms_threshold: .5}, model_sha256: 'b'.repeat(64),
    detections: [{id: 1, cx: 150, cy: 125, r: 12, score: .8, accepted: true, source: 'cv'}],
    raw_count: 2, candidate_count: 1, elapsed_ms: 5, expires_at: new Date(Date.now() + 60000).toISOString(), ...overrides};
}
function ui() {
  const nodes = new Map(), timers = new Map(); let timerId = 0;
  const element = id => {
    if (!nodes.has(id)) nodes.set(id, {value: '', checked: false, hidden: false, disabled: false, open: false,
      textContent: '', children: [], dataset: {}, classList: {toggle() {}, add() {}, remove() {}}, style: {setProperty() {}, removeProperty() {}}, setAttribute() {}, removeAttribute() {}, closest() { return null; },
      checkValidity() { return this.value !== '' && Number.isFinite(Number(this.value)); }});
    return nodes.get(id);
  };
  const context = vm.createContext({window: {WECFU_MODEL_PREVIEW_CONTROLS: helpers, WECFU_PARAM_CONTROLS: params,
    WECFU_REFERENCE_CONTROLS: reference, WECFU_WORKFLOW_CONTROLS: workflow,
    WECFU_DEFAULT_BATCH: require('../wecfu/server/static/default_batch.js'),
    WECFU_REVIEW_QUEUE_CONTROLS: require('../wecfu/server/static/review_queue_controls.js'),
    WECFU_I18N: {t: key => key, getLang: () => 'en'}, addEventListener() {}},
    document: {getElementById: element}, console, AbortController, crypto: webcrypto,
    setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id; }, clearTimeout(id) { timers.delete(id); }});
  vm.runInContext(source, context);
  context.fixtureHash = hash; context.fixturePlate = plain(plate); context.fixtureMarks = plain(marks);
  context.fixtureCandidate = candidate();
  const run = code => vm.runInContext(code, context);
  run(`
    const productionLoadPlateImage = loadPlateImage;
    let requests = [], saves = [], reloads = 0, rawLoads = [];
    draw = () => {}; invalidateBackground = () => {}; cancelGesture = () => {}; fitToCanvas = () => {};
    loadImages = async () => {};
    queueSave = () => { saves.push(snapshot()); };
    flushEdits = async () => {};
    loadPlateImage = async (...args) => { rawLoads.push(args); reloads++; return {image: {width: 320, height: 240}, sourceHash: fixtureHash}; };
    request = async (url, options) => { requests.push({url, options}); return {json: async () => fixtureCandidate}; };
    state.batch = 'synthetic'; state.imageName = 'fixture.png'; state.img = {width: 320, height: 240};
    state.plate = fixturePlate; state.detections = fixtureMarks; state.imageSourceHash = fixtureHash;
    state.doc = {plate: fixturePlate, detections: fixtureMarks, mode: 'auto', params: {...LEGACY_DEFAULTS},
      notes: 'synthetic note', counted: true, count_params: {...LEGACY_DEFAULTS}, machine_count_initial: 1,
      count_engine: 'baseline', count_model: null, plate_manual: true, reviewed: true, revision: 16};
    state.config = {experimental_models: {cfucounter: {enabled: true, available: true}}};
    state.saveQueues.set(keyFor(), {revision: 17});
    state.reference.key = keyFor();
    state.reference.envelope = {status: 'verified', reference: {sha256: fixtureHash, plate: fixturePlate,
      detections_geometry: fixtureMarks.map(d => [d.cx, d.cy, d.r]), verified_at_utc: '2026-10-28T00:00:00Z'}};
    $('method-select').value = MODEL_ENGINE; $('mode-select').value = 'auto';
    fillParams(LEGACY_DEFAULTS); updateControls();
  `);
  return {context, run, element, timers};
}

test('candidate is bound to exact source, revision, circle, ROI and expiry', () => {
  const c = candidate(), context = {hash, revision: 17, plate, inset: .82};
  assert.equal(helpers.valid(c, context), true);
  for (const change of [{hash: 'c'.repeat(64)}, {revision: 18}, {plate: {...plate, r: 109}}, {inset: .8}]) {
    assert.equal(helpers.valid(c, {...context, ...change}), false);
  }
  assert.equal(helpers.valid({...c, expires_at: 'bad date'}, context), false);
  assert.equal(helpers.valid(c, context, Date.parse(c.expires_at)), false);
  const original = helpers.signature('one', hash, plate, {a: 1, b: 2}, 'auto', marks);
  assert.equal(original, helpers.signature('one', hash, plate, {b: 2, a: 1}, 'auto', marks));
  assert.notEqual(original, helpers.signature('two', hash, plate, {a: 1, b: 2}, 'auto', marks));
});

test('trial displays separate candidates without changing marks, history, counts or human references', async () => {
  const view = ui(), before = plain(view.run('snapshot()'));
  view.element('reference-confirmed').checked = true;
  view.context.fixtureCandidate = candidate({detections: [], candidate_count: 0});
  await view.run('runModelPreview()');
  assert.deepEqual(plain(view.run('snapshot()')), before);
  assert.equal(view.run('state.history.length'), 0);
  assert.equal(view.run('saves.length'), 0);
  assert.equal(view.run('reloads'), 1);
  const body = JSON.parse(view.run('requests[0].options.body'));
  assert.equal(body.expected_revision, 17); // doc.revision is intentionally old.
  assert.equal(body.expected_image_sha256, hash);
  assert.deepEqual(body.model_params, {plate_inset: .82});
  assert.equal(view.element('model-empty-warning').hidden, false);
  assert.equal(view.element('count-badge').textContent, 'modelTemporary · 0');
  assert.equal(view.element('reference-summary-status').textContent, 'referenceVerified');
  assert.equal(view.element('reference-confirmed').checked, false);
  assert.equal(view.element('btn-reference-save').disabled, true);
});

test('explicit full replacement preserves an undo snapshot including provenance and manual IDs', async () => {
  const view = ui(), before = plain(view.run('snapshot()'));
  await view.run('runModelPreview()');
  view.run(`jsonRequest = async (url, method, body) => {
    requests.push({url, method, body});
    return {...snapshot(), detections: fixtureCandidate.detections, machine_count_initial: 1,
      count_engine: MODEL_ENGINE, count_model: {model_sha256: 'fixture-model'}, count_params: null, revision: 18};
  };`);
  await view.run('applyModelPreview()');
  assert.equal(view.run('state.detections.length'), 1);
  assert.equal(view.run('state.detections.some(d => d.source === "manual")'), false);
  assert.equal(view.run('state.history.length'), 1);
  assert.equal(view.run('state.saveQueues.get(keyFor()).revision'), 18);
  assert.equal(view.run('state.modelPreview.candidate'), null);
  assert.equal(view.element('reference-summary-status').textContent, 'referenceStale');
  assert.equal(view.run('requests[1].body.replace_all'), true);
  assert.equal(view.run('requests[1].body.expected_revision'), 17);
  view.run('undo()');
  assert.deepEqual(plain(view.run('snapshot()')), before);
  assert.equal(view.run('state.saveQueues.get(keyFor()).revision'), 18);
  assert.deepEqual(plain(view.run('saves[0]')), before);
  assert.equal(view.element('reference-summary-status').textContent, 'referenceVerified');
});

test('unknown apply outcome locks edits and safely retries exactly the same request once', async () => {
  const view = ui(); await view.run('runModelPreview()');
  view.run(`let attempts = [];
    jsonRequest = async (url, method, body) => {
      attempts.push(JSON.stringify(body));
      if (attempts.length === 1) throw new TypeError('simulated disconnected response');
      return {...snapshot(), detections: fixtureCandidate.detections, count_engine: MODEL_ENGINE,
        count_model: {model_sha256: 'fixture-model'}, count_params: null, revision: 18};
    };`);
  await view.run('applyModelPreview()');
  assert.equal(view.run('editable()'), false);
  assert.equal(view.run('state.detections.length'), 2);
  assert.equal(view.run('state.history.length'), 0);
  assert.equal(view.element('notes-input').disabled, true);
  assert.equal(view.element('method-select').disabled, true);
  assert.equal(view.element('btn-model-retry').hidden, false);
  await view.run('selectImage("other.png"); clearAll(); undo(); countAll(); recount();');
  assert.equal(view.run('state.imageName'), 'fixture.png');
  assert.equal(view.run('state.detections.length'), 2);
  await view.run('confirmModelApply()');
  assert.equal(view.run('attempts[0] === attempts[1]'), true);
  assert.equal(view.run('applyPending()'), false);
  assert.equal(view.run('state.history.length'), 1);
});

test('conflicting retry keeps the lock until saved state is reloaded without a write', async () => {
  const view = ui(); await view.run('runModelPreview()');
  view.run(`jsonRequest = async () => { throw new TypeError('lost response'); };`);
  await view.run('applyModelPreview()');
  view.run(`jsonRequest = async () => { const e = new Error('changed in another tab'); e.status = 409; throw e; };`);
  await view.run('confirmModelApply()');
  assert.equal(view.run('applyPending()'), true);
  assert.equal(view.element('btn-model-reload').hidden, false);
  view.run(`let outcomeReads = []; jsonRequest = async (url, method = 'GET') => {
    outcomeReads.push({url, method}); return {...snapshot(), notes: 'newer saved note', revision: 20};
  }; flushEdits = async () => { throw new Error('must not flush old marks'); };`);
  await view.run('reloadModelApplyOutcome()');
  assert.equal(view.run('applyPending()'), false);
  assert.equal(view.run('state.doc.notes'), 'newer saved note');
  assert.equal(view.run('state.saveQueues.get(keyFor()).revision'), 20);
  assert.equal(view.run('outcomeReads[0].method'), 'GET');
  assert.equal(view.run('saves.length'), 0);
  assert.equal(view.run('state.history.length'), 0);
});

test('known rejection never replaces marks or enters undo history', async () => {
  const view = ui(); await view.run('runModelPreview()');
  view.run(`jsonRequest = async () => { const e = new Error('expired'); e.status = 410; throw e; };`);
  await view.run('applyModelPreview()');
  assert.equal(view.run('applyPending()'), false);
  assert.equal(view.run('state.history.length'), 0);
  assert.deepEqual(plain(view.run('state.detections')), marks);
  assert.match(view.element('model-message').textContent, /modelApplyFailed/);
});

test('persistent unknown errors allow read-only recovery; a matching adoption receipt retains Undo', async () => {
  const view = ui(); await view.run('runModelPreview()');
  view.run(`jsonRequest = async () => { const e = new Error('temporarily unavailable'); e.status = 503; throw e; };`);
  await view.run('applyModelPreview()');
  assert.equal(view.element('btn-model-reload').hidden, false);
  assert.equal(view.element('btn-model-retry').hidden, false);
  view.run(`jsonRequest = async () => ({...snapshot(), detections: fixtureCandidate.detections,
    revision: 18, count_engine: MODEL_ENGINE, count_model: {model_sha256: 'fixture-model'}, count_params: null,
    _model_preview_apply: {request_id: state.modelPreview.pendingApply.body.request_id, applied_revision: 18}});`);
  await view.run('reloadModelApplyOutcome()');
  assert.equal(view.run('state.history.length'), 1);
  view.run('undo()');
  assert.deepEqual(plain(view.run('state.detections')), marks);
});

test('changed marks, any parameter and crop invalidate candidates; stale replies cannot return', async () => {
  for (const edit of ['state.detections = []; changed();', "$('p-circ').value = .1; parametersChanged('min_circularity');", 'openCrop();']) {
    const view = ui(); await view.run('runModelPreview()');
    view.run(edit);
    assert.equal(view.run('state.modelPreview.candidate'), null, edit);
  }
  const view = ui();
  view.run(`let finishRequest; request = async () => new Promise(resolve => { finishRequest = resolve; });`);
  const task = view.run('runModelPreview()');
  await new Promise(resolve => setImmediate(resolve));
  view.run(`clearModelPreview(); state.imageName = 'another.png'; finishRequest({json: async () => fixtureCandidate});`);
  await task;
  assert.equal(view.run('state.modelPreview.candidate'), null);
  assert.equal(view.run('state.imageName'), 'another.png');
});

test('pure manual, unavailable capability, saved edits failure and model batch counting never run a trial', async () => {
  for (const prepare of ["state.doc.mode = 'manual';", 'state.config.experimental_models.cfucounter.available = false;',
    'state.config.experimental_models.cfucounter.enabled = false;']) {
    const view = ui(); view.run(`${prepare} updateControls();`); await view.run('runModelPreview()');
    assert.equal(view.run('requests.length'), 0);
  }
  const view = ui();
  view.run(`flushEdits = async () => { throw new Error('unsaved edits'); };`);
  await view.run('runModelPreview()');
  assert.equal(view.run('requests.length'), 0);
  assert.match(view.element('model-message').textContent, /unsaved edits/);
  await view.run('countAll(); recount();');
  assert.equal(view.run('requests.length'), 0);
});

test('method switch clears threshold pixels without changing precise HSV values or preview preference', () => {
  const view = ui();
  view.run(`state.doc.params.min_area_frac = 7.123456789e-8; fillParams(state.doc.params);
    $('p-preview').checked = true; state.preview = {image: 'old threshold mask'}; changeMethod();`);
  assert.equal(view.run('state.preview'), null);
  assert.equal(view.element('p-preview').checked, true);
  assert.equal(view.run('paramsBody().min_area_frac'), 7.123456789e-8);
  view.run(`let maskRefreshes = 0; refreshMaskPreview = () => { maskRefreshes++; };
    $('method-select').value = 'baseline'; changeMethod();`);
  assert.equal(view.run('maskRefreshes'), 1);
  assert.equal(view.run('paramsBody().min_area_frac'), 7.123456789e-8);
});

test('invalid visible ROI cannot silently use old saved settings for a model trial', async () => {
  const view = ui();
  view.run("$('p-inset').value = '0'; parametersChanged('plate_inset');");
  assert.equal(view.element('btn-model-preview').disabled, true);
  assert.match(view.element('model-message').textContent, /invalidParams/);
  await view.run('runModelPreview()');
  assert.equal(view.run('requests.length'), 0);
});

test('zero detections become a saved zero only after explicit apply and remain undoable', async () => {
  const view = ui(); view.context.fixtureCandidate = candidate({detections: [], candidate_count: 0, raw_count: 0});
  await view.run('runModelPreview()');
  assert.equal(view.run('state.detections.length'), 2);
  view.run(`jsonRequest = async () => ({...snapshot(), detections: [], machine_count_initial: 0,
    count_engine: MODEL_ENGINE, count_model: {candidate_count: 0}, count_params: null, revision: 18});`);
  await view.run('applyModelPreview()');
  assert.equal(view.run('state.detections.length'), 0);
  assert.equal(view.run('state.doc.counted'), true);
  assert.equal(view.element('count-badge').textContent, '0 cfuSuffix');
  view.run('undo()');
  assert.deepEqual(plain(view.run('state.detections')), marks);
});

test('adopted model compares only its ROI and shows a distinct pending-change hint in either method view', () => {
  const view = ui();
  view.run(`state.doc.count_engine = MODEL_ENGINE; state.doc.count_model = {plate_inset: .82};
    state.doc.count_params = null; $('p-max-sat').value = 199; parametersChanged('max_saturation');`);
  assert.equal(view.run('state.paramsDirty'), false);
  assert.equal(view.element('model-params-hint').hidden, true);
  view.run("$('p-inset').value = .853456789; parametersChanged('plate_inset');");
  assert.equal(view.run('state.paramsDirty'), true);
  assert.equal(view.element('model-params-hint').textContent, 'modelRoiChanged');
  assert.equal(view.element('model-params-hint').hidden, false);
  assert.equal(view.element('params-hint').textContent, '');
  view.run("$('method-select').value = 'baseline'; updateControls();");
  assert.equal(view.element('model-params-hint').hidden, false);
  assert.equal(view.element('params-hint').textContent, '');
  view.run('adopt({...snapshot(), count_model: {plate_inset: .853456789}});');
  assert.equal(view.run('state.paramsDirty'), false);
  assert.equal(view.element('model-params-hint').hidden, true);
});

test('model ROI is drawn separately and a slider redraws its range without inference or rebuilding the backdrop', () => {
  const view = ui();
  view.run(`
    let strokes = [], drawRequests = 0;
    const drawing = {strokeStyle: '', lineWidth: 1, dash: [], arcs: [],
      drawImage() {}, save() {}, restore() {}, scale() {}, translate() {}, fillText() {}, strokeText() {},
      beginPath() { this.arcs = []; }, arc(x, y, r) { this.arcs.push({x, y, r}); },
      setLineDash(value) { this.dash = [...value]; },
      stroke() { strokes.push({color: this.strokeStyle, width: this.lineWidth, dash: [...this.dash], arcs: [...this.arcs]}); }
    };
    $('canvas').width = 640; $('canvas').height = 480; $('canvas').getContext = () => drawing;
    resizeCanvas = () => {}; state.backdrop = {width: 640, height: 480}; state.backdropDirty = false;
    draw = () => { drawRequests++; paint(); }; paint();
  `);
  let roi = plain(view.run("strokes.find(s => s.color === '#777777')"));
  assert.equal(roi.arcs[0].x, plate.cx);
  assert.equal(roi.arcs[0].y, plate.cy);
  assert.ok(Math.abs(roi.arcs[0].r - 90.2) < 1e-9);
  assert.ok(roi.dash.length > 0);
  assert.ok(roi.width < 2);
  assert.equal(view.element('mode-hint').textContent, 'modelModeHint');
  view.run("strokes = []; $('s-inset').value = .2; sliderChanged('plate_inset');");
  roi = plain(view.run("strokes.find(s => s.color === '#777777')"));
  assert.equal(roi.arcs[0].r, 66); // The slider's 0.2 setting keeps 60% of the 110px plate radius.
  assert.ok(view.run('drawRequests') > 0);
  assert.equal(view.run('requests.length'), 0);
  assert.equal(view.run('state.backdropDirty'), false);
  assert.deepEqual(plain(view.run('state.detections')), marks);
  view.run("strokes = []; $('method-select').value = 'baseline'; paint();");
  assert.equal(view.run("strokes.some(s => s.color === '#777777')"), false);
});

test('manual mode hint mentions threshold preview only in the traditional view', () => {
  const view = ui();
  view.run("state.doc.mode = 'manual'; updateControls();");
  assert.equal(view.element('mode-hint').textContent, 'modelManualHint');
  view.run("$('method-select').value = 'baseline'; updateControls();");
  assert.equal(view.element('mode-hint').textContent, 'manualHint');
});

function samUI() {
  const view = ui();
  view.context.fixtureCandidate = candidate({engine: helpers.SAM_ENGINE, recipe_id: helpers.SAM_RECIPE,
    model_params: {plate_inset: .95}});
  view.run(`state.config = {experimental_models: {cfucounter: {enabled: false, available: false}},
    models: {sam2: {engine: SAM_ENGINE, available: true, reason: '', model_sha256: 'b'.repeat(64),
      recipe_id: 'sam_cv_seed_area0.05_color160_edge095_v1', label: 'Local SAM'}}};
    $('method-select').value = SAM_ENGINE; changeMethod();`);
  return view;
}

test('SAM trial uses its own engine and fixed recipe without changing saved HSV, marks or human truth', async () => {
  const view = samUI(), before = plain(view.run('snapshot()'));
  assert.equal(view.element('method-model').hidden, true, 'CFUCounter remains disabled');
  assert.equal(view.element('method-sam').hidden, false);
  assert.equal(view.element('model-inset-control').hidden, true);
  assert.equal(view.element('advanced-inset-control').hidden, true);
  assert.equal(view.element('p-inset').disabled, true);
  assert.equal(view.element('s-inset').disabled, true);
  assert.equal(view.element('p-radius').disabled, false, 'manual marker size remains available');
  assert.equal(view.element('model-warning').textContent, 'samWarning');
  assert.equal(view.element('model-roi-hint').textContent, 'samRoiHint');
  await view.run('runModelPreview()');
  const body = JSON.parse(view.run('requests[0].options.body'));
  assert.equal(body.engine, helpers.SAM_ENGINE);
  assert.deepEqual(body.model_params, {});
  assert.equal(body.expected_revision, 17);
  assert.equal(body.expected_image_sha256, hash);
  assert.deepEqual(plain(view.run('snapshot()')), before);
  assert.equal(view.run('state.modelPreview.candidate.engine'), helpers.SAM_ENGINE);
  assert.equal(view.run('state.history.length'), 0);
  assert.equal(view.run('saves.length'), 0);
  assert.equal(view.element('btn-reference-save').disabled, true);
  await view.run('recount(); countAll();');
  assert.equal(view.run('requests.length'), 1, 'SAM selection cannot invoke builtin or batch inference');
});

test('SAM candidate rejects another engine, checkpoint or recipe and late responses after method changes', async () => {
  for (const change of [{engine: helpers.ENGINE}, {model_sha256: 'c'.repeat(64)}, {image_sha256: 'c'.repeat(64)},
    {recipe_id: 'unrecognized-recipe'}, {recipe_id: undefined}, {model_params: {plate_inset: .82}}]) {
    const view = samUI(); Object.assign(view.context.fixtureCandidate, change);
    await view.run('runModelPreview()');
    assert.equal(view.run('state.modelPreview.candidate'), null);
    assert.deepEqual(plain(view.run('state.detections')), marks);
  }
  const view = samUI();
  view.run(`let finishSAM; request = async () => new Promise(resolve => { finishSAM = resolve; });`);
  const pending = view.run('runModelPreview()');
  await new Promise(resolve => setImmediate(resolve));
  view.run(`$('method-select').value = 'baseline'; changeMethod(); finishSAM({json: async () => fixtureCandidate});`);
  await pending;
  assert.equal(view.run('state.modelPreview.candidate'), null);
  assert.deepEqual(plain(view.run('state.detections')), marks);
});

test('SAM explicit adoption preserves full provenance and Undo restores previous manual marks', async () => {
  for (const previousEngine of ['baseline', helpers.SAM_ENGINE]) {
    const view = samUI();
    if (previousEngine === helpers.SAM_ENGINE) view.run(`adopt({...snapshot(), count_engine: SAM_ENGINE,
      machine_count_initial: 2, count_params: null, count_model: {model_sha256: 'b'.repeat(64), image_sha256: fixtureHash,
        recipe_id: 'sam_cv_seed_area0.05_color160_edge095_v1', plate_inset: .95, raw_count: 3, candidate_count: 2}});`);
    const before = plain(view.run('snapshot()'));
    await view.run('runModelPreview()');
    view.run(`jsonRequest = async (url, method, body) => {
      requests.push({url, method, body});
      return {...snapshot(), detections: fixtureCandidate.detections, count_engine: SAM_ENGINE,
        machine_count_initial: 1, count_params: null, counted: true, reviewed: false, revision: 18,
        count_model: {model_sha256: 'b'.repeat(64), image_sha256: fixtureHash,
          recipe_id: 'sam_cv_seed_area0.05_color160_edge095_v1', plate_inset: .95,
          raw_count: 2, candidate_count: 1}};
    };`);
    await view.run('applyModelPreview()');
    assert.equal(view.element('method-select').value, helpers.SAM_ENGINE);
    assert.equal(view.element('count-source').textContent, 'samSavedSource');
    assert.equal(view.run('snapshot().count_engine'), helpers.SAM_ENGINE);
    assert.equal(view.run('snapshot().count_model.recipe_id'), helpers.SAM_RECIPE);
    assert.equal(view.run('state.doc.params.plate_inset'), .82, 'adoption does not rewrite traditional parameters');
    assert.equal(view.run('state.paramsDirty'), false, 'fixed model is not affected by traditional settings');
    assert.equal(view.element('reference-confirmed').checked, false);
    assert.equal(view.run('requests[1].body.replace_all'), true);
    assert.equal(view.run('state.history.length'), 1);
    view.run('undo()');
    assert.deepEqual(plain(view.run('snapshot()')), before);
    assert.equal(view.run('state.saveQueues.get(keyFor()).revision'), 18);
    assert.deepEqual(plain(view.run('saves[0]')), before);
    assert.equal(view.run('state.doc.count_engine'), previousEngine);
  }
});

test('SAM unavailable, missing config and manual contexts fail closed with no trial', async () => {
  for (const prepare of ["state.config.models.sam2.available = false; state.config.models.sam2.reason = 'not enabled';",
    'state.config.models.sam2.enabled = false;',
    'delete state.config.models;', "state.doc.mode = 'manual';",
    "state.config.models.sam2.recipe_id = 'different';", "state.config.models.sam2.model_sha256 = 'invalid';"]) {
    const view = samUI(); view.run(`${prepare} updateControls();`);
    await view.run('runModelPreview()');
    assert.equal(view.run('requests.length'), 0, prepare);
    assert.deepEqual(plain(view.run('state.detections')), marks);
    if (prepare.includes('not enabled')) assert.match(view.element('model-message').textContent, /not enabled/);
    if (prepare.includes('.enabled = false')) assert.equal(view.element('method-sam').hidden, true);
  }
  const view = samUI();
  view.run(`state.review.requested = true; updateControls();`);
  await view.run('runModelPreview()');
  assert.equal(view.run('requests.length'), 0);
  assert.equal(view.element('method-sam').hidden, true);
});

test('SAM range line uses fixed 95 percent while switching back restores the precise builtin ROI control', () => {
  const view = samUI();
  view.run(`let ranges = [];
    const drawing = {strokeStyle: '', drawImage() {}, save() {}, restore() {}, scale() {}, translate() {}, fillText() {}, strokeText() {},
      beginPath() {}, arc(x, y, r) { if (this.strokeStyle === '#777777') ranges.push(r); }, setLineDash() {}, stroke() {}};
    $('canvas').width = 640; $('canvas').height = 480; $('canvas').getContext = () => drawing;
    resizeCanvas = () => {}; state.backdrop = {width: 640, height: 480}; state.backdropDirty = false;
    paint();`);
  assert.equal(view.run('ranges[0]'), plate.r * .95);
  assert.equal(view.run('state.doc.params.plate_inset'), .82);
  view.run(`$('method-select').value = 'baseline'; changeMethod();`);
  assert.equal(view.element('model-inset-control').hidden, false);
  assert.equal(view.element('advanced-inset-control').hidden, false);
  assert.equal(view.element('p-inset').disabled, false);
  assert.equal(view.element('p-inset').value, .82);
  assert.equal(view.run('requests.length'), 0);
});

test('opening records only separate UI activity, editing protects work, and Undo restores legacy flag without attestation', async () => {
  const view = ui();
  view.run(`
    const initial = {...snapshot(), reviewed: false, revision: 17};
    boundedImage = image => image;
    jsonRequest = async (url, method, body) => {
      requests.push({url, method, body});
      if (url.endsWith('/viewed')) return {viewed:true,source_sha256:body.source_sha256};
      if (url.endsWith('/source_view')) return {source_sha256:fixtureHash,view:'main',declared:true};
      return clone(initial);
    };
  `);
  await view.run(`selectImage('new-synthetic.png')`);
  assert.equal(view.run('state.doc.reviewed'), false);
  assert.equal(view.run('saves.length'), 0, 'viewing does not queue a state mutation');
  assert.equal(view.run('requests.length'), 3);
  assert.match(view.run('requests[0].url'), /\/initialize$/);
  assert.match(view.run('requests[1].url'), /\/source_view$/);
  assert.match(view.run('requests[2].url'), /\/viewed$/);
  assert.deepEqual(plain(view.run('requests[2].body')), {source_sha256:hash});
  assert.equal(view.run('state.sourceView'), 'main');
  assert.equal(view.element('reference-confirmed').checked, false);
  assert.equal(view.element('reference-crop-confirmed').checked, false);
  view.run('clearAll();');
  assert.equal(view.run('state.doc.reviewed'), true, 'actual editing protects work from batch replacement');
  assert.equal(view.element('reference-confirmed').checked, false);
  view.run('undo();');
  assert.equal(view.run('state.doc.reviewed'), false);
  assert.deepEqual(plain(view.run('state.detections')), marks);
  assert.deepEqual(plain(view.run('saves.map(saved => saved.reviewed)')), [true, false]);
  assert.equal(view.run('requests.some(r => r.url.endsWith("/reference") && r.method === "POST")'), false);
});

test('batch counting preserves an edited empty auto image that has never been counted', async () => {
  const view = ui();
  view.run(`
    $('method-select').value = 'baseline'; $('mode-select').value = 'auto';
    state.doc = {...snapshot(), counted: false, machine_count_initial: 0, reviewed: false, detections: []};
    state.detections = [{id: 1, cx: 110, cy: 110, r: 8, source: 'manual'}];
    changed(); clearAll();
    state.imageList = [{name: state.imageName}];
    request = async url => { requests.push({url, method: 'GET'}); return {json: async () => snapshot()}; };
    jsonRequest = async url => { throw new Error('Edited empty work must not be recounted: ' + url); };
  `);
  assert.equal(view.run('state.doc.reviewed'), true);
  assert.equal(view.run('state.doc.counted'), false);
  assert.equal(view.run('state.detections.length'), 0);
  await view.run('countAll()');
  assert.equal(view.run('requests.length'), 1);
  assert.match(view.run('requests[0].url'), /\/detections$/);
  assert.equal(view.element('reference-confirmed').checked, false);
});

test('SAM adoption and Undo restore an initially false reviewed flag without human confirmation', async () => {
  const view = samUI();
  view.run('state.doc.reviewed = false;');
  const before = plain(view.run('snapshot()'));
  await view.run('runModelPreview()');
  view.run(`jsonRequest = async (url, method, body) => {
    requests.push({url, method, body});
    return {...snapshot(), detections: fixtureCandidate.detections, count_engine: SAM_ENGINE,
      machine_count_initial: 1, count_params: null, counted: true, reviewed: false, revision: 18,
      count_model: {model_sha256: 'b'.repeat(64), image_sha256: fixtureHash,
        recipe_id: 'sam_cv_seed_area0.05_color160_edge095_v1', plate_inset: .95,
        raw_count: 2, candidate_count: 1}};
  };`);
  await view.run('applyModelPreview()');
  view.run('undo();');
  assert.deepEqual(plain(view.run('snapshot()')), before);
  assert.deepEqual(plain(view.run('saves[0]')), before);
  assert.equal(view.element('reference-confirmed').checked, false);
  assert.equal(view.element('reference-crop-confirmed').checked, false);
  assert.equal(view.run('requests.some(r => r.url.endsWith("/reference") && r.method === "POST")'), false);
});

function fusionUI() {
  const view = ui();
  const provenance = {model_sha256: 'b'.repeat(64), sam_model_sha256: 'c'.repeat(64), dino_model_sha256: 'd'.repeat(64),
    detector_contract_sha256: 'e'.repeat(64), recipe_id: helpers.FUSION_RECIPE, image_sha256: hash,
    plate_inset: .95, automatic_plate: plate, raw_count: 3, candidate_count: 2, d0_count: 1, supplemental_count: 1,
    raw_dino_count: 2, annotation_kind: helpers.FUSION_ANNOTATION};
  view.context.fixtureCandidate = candidate({engine: helpers.FUSION_ENGINE, recipe_id: helpers.FUSION_RECIPE,
    model_params: {plate_inset: .95}, candidate_count: 2, raw_count: 3, fusion_provenance: provenance,
    detections: [{id: 1, cx: 150, cy: 125, r: 12, score: .8, accepted: true, source: 'cv'},
      {id: 2, cx: 195, cy: 145, r: 9, score: .8, accepted: true, source: 'cv'}]});
  view.run(`state.config = {experimental_models: {cfucounter: {enabled: false, available: false}},
    models: {fusion: {engine: FUSION_ENGINE, enabled: true, available: true, reason: '', model_sha256: 'b'.repeat(64),
      recipe_id: 'sam_dino_full88_residual12_threshold075_auto095_v1', label: 'Fusion enhancement (trial)'}}};
    state.doc.plate_manual = false; state.doc.reviewed = false; state.sourceView = 'main';
    $('method-select').value = FUSION_ENGINE; changeMethod();`);
  return view;
}

test('fusion trial is explicit, fixed-recipe and read-only with truthful supplemental-ring guidance', async () => {
  const view = fusionUI(), before = plain(view.run('snapshot()'));
  assert.equal(view.run('defaultBuiltinEngine()'), 'baseline');
  assert.equal(view.element('method-fusion').hidden, false);
  assert.equal(view.element('method-fusion').disabled, false);
  assert.equal(view.element('method-model').hidden, true);
  assert.equal(view.element('model-warning').textContent, 'fusionWarning');
  assert.equal(view.element('model-roi-hint').textContent, 'fusionRoiHint');
  assert.equal(view.element('model-inset-control').hidden, true);
  assert.equal(view.element('p-inset').disabled, true);
  await view.run('runModelPreview()');
  const body = JSON.parse(view.run('requests[0].options.body'));
  assert.equal(body.engine, helpers.FUSION_ENGINE);
  assert.deepEqual(body.model_params, {});
  assert.equal(view.run('modelCandidateCurrent()'), true);
  assert.deepEqual(plain(view.run('snapshot()')), before);
  assert.equal(view.run('state.history.length'), 0);
  assert.equal(view.run('saves.length'), 0);
  assert.equal(view.element('reference-confirmed').checked, false);
  await view.run('recount(); countAll();');
  assert.equal(view.run('requests.length'), 1);
});

test('fusion is unselectable when disabled or unavailable and never runs in review or manual mode', async () => {
  for (const prepare of ['state.config.models.fusion.enabled = false;', 'delete state.config.models.fusion.enabled;',
    'state.config.models.fusion.available = false;', 'delete state.config.models;',
    "state.config.models.fusion.recipe_id = 'different';", "state.config.models.fusion.model_sha256 = 'missing';",
    "state.doc.mode = 'manual';", 'state.review.requested = true;']) {
    const view = fusionUI(); view.run(`${prepare} updateControls();`);
    await view.run('runModelPreview()');
    assert.equal(view.run('requests.length'), 0, prepare);
    assert.deepEqual(plain(view.run('state.detections')), marks);
    if (!prepare.includes("state.doc.mode")) assert.equal(view.element('method-fusion').disabled, true, prepare);
  }
});

test('fusion keeps a manually adjusted boundary and disables trial without resetting it', async () => {
  const view = fusionUI(); view.run('state.doc.plate_manual = true; updateControls();');
  const before = plain(view.run('snapshot()'));
  assert.equal(view.element('btn-model-preview').disabled, true);
  assert.equal(view.element('model-message').textContent, 'fusionAutomaticPlateRequired');
  await view.run('runModelPreview()');
  assert.equal(view.run('requests.length'), 0);
  assert.deepEqual(plain(view.run('snapshot()')), before);
});

test('fusion candidate rejects wrong recipe, identity or supplemental provenance', async () => {
  for (const change of [{engine: helpers.SAM_ENGINE}, {recipe_id: 'wrong'}, {model_sha256: 'c'.repeat(64)},
    {fusion_provenance: null}, {model_params: {plate_inset: .82}}]) {
    const view = fusionUI(); Object.assign(view.context.fixtureCandidate, change);
    await view.run('runModelPreview()');
    assert.equal(view.run('state.modelPreview.candidate'), null);
    assert.deepEqual(plain(view.run('state.detections')), marks);
  }
  for (const change of [{annotation_kind: 'true_segmentation_boundary'}, {d0_count: 2}, {supplemental_count: -1},
    {image_sha256: 'c'.repeat(64)}, {candidate_count: 3}, {recipe_id: 'wrong'}]) {
    const view = fusionUI(); Object.assign(view.context.fixtureCandidate.fusion_provenance, change);
    await view.run('runModelPreview()');
    assert.equal(view.run('state.modelPreview.candidate'), null);
    assert.deepEqual(plain(view.run('state.detections')), marks);
  }
});

test('fusion failure or late response never changes current counts or reviewed flags', async () => {
  const view = fusionUI(), before = plain(view.run('snapshot()'));
  view.run(`request = async () => { const error = new Error('synthetic detector timeout'); error.status = 503; throw error; };`);
  await view.run('runModelPreview()');
  assert.equal(view.run('state.modelPreview.candidate'), null);
  assert.match(view.element('model-message').textContent, /synthetic detector timeout/);
  assert.deepEqual(plain(view.run('snapshot()')), before);
  assert.equal(view.run('saves.length'), 0);
  view.run(`let finishFusion; request = async () => new Promise(resolve => { finishFusion = resolve; });`);
  const pending = view.run('runModelPreview()');
  await new Promise(resolve => setImmediate(resolve));
  view.run(`$('method-select').value = 'baseline'; changeMethod(); finishFusion({json: async () => fixtureCandidate});`);
  await pending;
  assert.equal(view.run('state.modelPreview.candidate'), null);
  assert.deepEqual(plain(view.run('snapshot()')), before);
});

test('fusion explicit adoption and Undo preserve complete provenance and the prior false reviewed flag', async () => {
  const view = fusionUI(), before = plain(view.run('snapshot()'));
  await view.run('runModelPreview()');
  view.run(`jsonRequest = async (url, method, body) => {
    requests.push({url, method, body});
    return {...snapshot(), detections: fixtureCandidate.detections, count_engine: FUSION_ENGINE,
      machine_count_initial: 2, count_params: null, counted: true, reviewed: false, revision: 18,
      count_model: clone(fixtureCandidate.fusion_provenance)};
  };`);
  await view.run('applyModelPreview()');
  assert.equal(view.element('method-select').value, helpers.FUSION_ENGINE);
  assert.equal(view.element('count-source').textContent, 'fusionSavedSource');
  assert.deepEqual(plain(view.run('snapshot().count_model')), plain(view.context.fixtureCandidate.fusion_provenance));
  assert.equal(view.run('state.paramsDirty'), false);
  assert.equal(view.run('state.doc.params.plate_inset'), .82);
  assert.equal(view.run('requests[1].body.replace_all'), true);
  assert.equal(view.run('state.history.length'), 1);
  view.run('undo();');
  assert.deepEqual(plain(view.run('snapshot()')), before);
  assert.deepEqual(plain(view.run('saves[0]')), before);
  assert.equal(view.element('reference-confirmed').checked, false);
  assert.equal(view.element('reference-crop-confirmed').checked, false);
  assert.equal(view.run('requests.some(r => r.url.endsWith("/reference") && r.method === "POST")'), false);
});

// Public recipe and real schema, with synthetic coordinates only. No model executes.
function fusionV2UI({web = false, sourceView = 'main'} = {}) {
  const view = ui();
  const provenance = {
    ...Object.fromEntries(['model_sha256', 'filter_artifact_sha256', 'sam_model_sha256',
      'dino_model_sha256', 'detector_contract_sha256', 'recipe_id'].map(key => [key, publicFusion[key]])),
    image_sha256: hash, source_view: sourceView, plate_inset: .95, automatic_plate: plate,
    raw_count: 3, candidate_count: 2, d0_count: 1, supplemental_count: 1, raw_dino_count: 2,
    annotation_kind: helpers.FUSION_ANNOTATION, feature_projection: [0,1,2,5,6,7,8,9,10,11],
    coordinate_method: 'raw_DINO_unchanged', D0_exclusion_fraction: .025,
    DINO_dedup_fraction: .005, ROI_max_radial: .95,
  };
  view.context.fixtureCandidate = candidate({engine: helpers.FUSION_V2_ENGINE,
    model_sha256: publicFusion.model_sha256, recipe_id: publicFusion.recipe_id,
    model_params: {plate_inset: .95}, raw_count: 3, candidate_count: 2, fusion_provenance: provenance,
    detections: [{id: 1, cx: 150, cy: 125, r: 12, score: .8, accepted: true, source: 'cv'},
      {id: 2, cx: 195, cy: 145, r: 9, score: .8, accepted: true, source: 'cv'}]});
  view.context.fixtureWeb = web; view.context.fixtureView = sourceView;
  view.run(`state.config = {web_mode: fixtureWeb, builtin_algorithms:['baseline',ENHANCED_ENGINE], default_count_engine:ENHANCED_ENGINE, default_model:null, default_model_fallback:false,
    models: {fusion_v2: {engine: FUSION_V2_ENGINE, enabled: true, available: true,
      model_sha256: fixtureCandidate.model_sha256, recipe_id: fixtureCandidate.recipe_id},
      sam2: {engine: SAM_ENGINE, enabled: true, available: true,
        model_sha256: 'c'.repeat(64), recipe_id: modelHelpers.SAM_RECIPE}}};
    state.doc.plate_manual = false; state.doc.reviewed = false; state.sourceView = fixtureView;
    state.imageList = [{name: state.imageName, counted: true}];
    state.workflow.enabled = true; state.workflow.kind = 'classical';
    syncWorkflowRoute(); updateControls();`);
  return view;
}

function useRealRawLoader(view) {
  view.context.URL = {createObjectURL: () => 'blob:synthetic', revokeObjectURL() {}};
  view.run(`loadPlateImage = productionLoadPlateImage;
    loadImage = async () => ({width:320,height:240});
    request = async (url, options = {}) => {
      requests.push({url, options});
      if (url.includes('/raw?')) return {
        headers: {get: name => name === 'X-WeCFU-Source-SHA256' ? fixtureHash : null},
        blob: async () => ({synthetic:true})};
      return {json: async () => fixtureCandidate};
    };`);
}

test('explicit public Fusion v2 refinement accepts actual public schema for main and blank without private provenance', async () => {
  for (const sourceView of ['main', 'blank']) {
    const view = fusionV2UI({sourceView}), before = plain(view.run('snapshot()'));
    assert.equal(view.element('method-select').value, view.run('workflowBuiltinEngine()'));
    await view.run('runModelPreview({engine:FUSION_V2_ENGINE})');
    assert.equal(view.run('modelCandidateCurrent()'), true);
    assert.deepEqual(plain(view.run('snapshot()')), before);
    const body = JSON.parse(view.run('requests[0].options.body'));
    assert.deepEqual(body, {engine: helpers.FUSION_V2_ENGINE, expected_revision:17,
      expected_image_sha256:hash, model_params:{}});
    assert.equal(view.run('state.modelPreview.candidate.fusion_provenance.source_view'), sourceView);
    assert.equal(view.run('state.history.length'), 0);
    assert.equal(view.run('saves.length'), 0);
    for (const privateKey of ['source_fullfit_seal', 'source_protocol_sha256', 'training_scope_images'])
      assert.equal(Object.hasOwn(view.context.fixtureCandidate.fusion_provenance, privateKey), false);
  }
});

test('explicit refinement never falls back when Fusion is unavailable, back/unknown or manually cropped', async () => {
  for (const mutation of ["state.sourceView = 'unknown';", "state.sourceView = 'back';",
    'state.doc.plate_manual = true;', 'state.config.models.fusion_v2.available = false;',
    'state.config.models.fusion_v2.enabled = false;', 'delete state.config.models.fusion_v2;']) {
    const view = fusionV2UI({web:true}), before = plain(view.run('snapshot()'));
    view.run(`${mutation} syncWorkflowRoute(); updateControls();`);
    assert.equal(view.element('method-select').value, view.run('workflowBuiltinEngine()'));
    await view.run('runModelPreview({engine:FUSION_V2_ENGINE})');
    assert.equal(view.run('requests.length'), 0, mutation);
    assert.deepEqual(plain(view.run('state.detections')), before.detections);
    assert.equal(view.run('saves.length'), 0);
  }
});

test('public Fusion v2 rejects malformed source-view and fixed numerical provenance', async () => {
  for (const change of [{source_view:'unknown'}, {source_view:'back'}, {source_view:undefined},
    {filter_artifact_sha256:'invalid'}, {coordinate_method:'roundtrip'}, {D0_exclusion_fraction:.02},
    {DINO_dedup_fraction:.01}, {ROI_max_radial:.9}, {feature_projection:[0,1,2,3]}]) {
    const view = fusionV2UI({web:true}), before = plain(view.run('snapshot()'));
    Object.assign(view.context.fixtureCandidate.fusion_provenance, change);
    await view.run('runModelPreview({engine:FUSION_V2_ENGINE})');
    assert.equal(view.run('state.modelPreview.candidate'), null, JSON.stringify(change));
    assert.deepEqual(plain(view.run('snapshot()')), before);
    assert.equal(view.run('saves.length'), 0);
  }
});

test('Web Fusion preview uses display_context raw bytes and explicit apply/Undo preserves public provenance', async () => {
  const view = fusionV2UI({web:true}), before = plain(view.run('snapshot()'));
  useRealRawLoader(view);
  await view.run('runModelPreview({engine:FUSION_V2_ENGINE})');
  assert.equal(view.run('modelCandidateCurrent()'), true);
  assert.match(view.run('requests[0].url'), /\/raw\?display_context=true$/);
  assert.equal(view.run('requests[0].options.cache'), 'no-store');
  assert.match(view.run('requests[1].url'), /\/model-preview$/);
  assert.equal(JSON.parse(view.run('requests[1].options.body')).expected_image_sha256, hash);
  view.run(`jsonRequest = async (url, method, body) => {
    requests.push({url, method, body});
    return {...snapshot(), detections:fixtureCandidate.detections, count_engine:FUSION_V2_ENGINE,
      machine_count_initial:2, count_model:clone(fixtureCandidate.fusion_provenance),
      count_params:null, counted:true, reviewed:false, revision:18};
  };`);
  await view.run('applyModelPreview()');
  assert.equal(view.run('state.history.length'), 1);
  assert.equal(view.element('count-source').textContent, 'fusionV2SavedSource');
  assert.deepEqual(plain(view.run('snapshot().count_model')), plain(view.context.fixtureCandidate.fusion_provenance));
  assert.equal(view.run('requests[2].body.replace_all'), true);
  view.run('undo();');
  assert.deepEqual(plain(view.run('snapshot()')), before);
  assert.deepEqual(plain(view.run('saves[0]')), before);
  assert.equal(view.run('requests.some(r => r.url.includes("reference_context") || /\\/reference(?:$|\\?)/.test(r.url))'), false);
});

test('Web uncertain Fusion apply reloads display_context and retains Undo only for matching receipt', async () => {
  const view = fusionV2UI({web:true}), before = plain(view.run('snapshot()'));
  useRealRawLoader(view); await view.run('runModelPreview({engine:FUSION_V2_ENGINE})');
  view.run(`jsonRequest = async () => { throw new TypeError('synthetic lost response'); };`);
  await view.run('applyModelPreview()');
  assert.equal(view.run('applyPending()'), true);
  view.run(`jsonRequest = async (url, method='GET') => {
    requests.push({url, method});
    return {...snapshot(), detections:fixtureCandidate.detections, revision:18,
      count_engine:FUSION_V2_ENGINE, count_model:clone(fixtureCandidate.fusion_provenance), count_params:null,
      _model_preview_apply:{request_id:state.modelPreview.pendingApply.body.request_id, applied_revision:18}};
  };`);
  await view.run('reloadModelApplyOutcome()');
  assert.equal(view.run('applyPending()'), false);
  assert.equal(view.run('requests.filter(r => r.url.endsWith("/raw?display_context=true")).length'), 2);
  assert.equal(view.run('requests.some(r => r.url.includes("reference_context"))'), false);
  assert.equal(view.run('requests.find(r => r.url.endsWith("/detections")).method'), 'GET');
  assert.equal(view.run('state.history.length'), 1);
  view.run('undo();'); assert.deepEqual(plain(view.run('snapshot()')), before);
});

test('local model raw context stays protected while Web SAM is explicitly supported', async () => {
  const local = fusionV2UI(); useRealRawLoader(local); await local.run('runModelPreview({engine:FUSION_V2_ENGINE})');
  assert.match(local.run('requests[0].url'), /\/raw\?reference_context=true$/);
  assert.equal(local.run('modelCandidateCurrent()'), true);
  const web = samUI(); web.run('state.config.web_mode=true; updateControls();');
  useRealRawLoader(web); await web.run('runModelPreview()');
  assert.equal(web.run('modelCandidateCurrent()'), true);
  assert.match(web.run('requests[0].url'), /\/raw\?display_context=true$/);
});

test('view designation mutation clears a candidate and a late response cannot restore it', async () => {
  const view = fusionV2UI({web:true});
  await view.run('runModelPreview({engine:FUSION_V2_ENGINE})');
  view.run(`$('current-source-view').value='back';
    jsonRequest=async (url,method,body)=>{requests.push({url,method,body});return {source_sha256:fixtureHash,view:body.view,declared:true};};`);
  await view.run('changeSourceView()');
  assert.equal(view.run('state.modelPreview.candidate'), null);
  assert.equal(view.run('state.sourceView'), 'back');
  assert.equal(view.element('btn-model-preview').disabled, true);
  assert.deepEqual(plain(view.run('requests[1].body')), {source_sha256:hash,view:'back'});
  assert.equal(view.run('saves.length'), 0);
  const race = fusionV2UI({web:true});
  race.run(`let finishPublic; request=async()=>new Promise(resolve=>{finishPublic=resolve;});`);
  const pending = race.run('runModelPreview({engine:FUSION_V2_ENGINE})'); await new Promise(resolve=>setImmediate(resolve));
  race.run(`$('current-source-view').value='blank';
    jsonRequest=async()=>({source_sha256:fixtureHash,view:'blank',declared:true});`);
  await race.run('changeSourceView()');
  race.run('finishPublic({json:async()=>fixtureCandidate});'); await pending;
  assert.equal(race.run('state.modelPreview.candidate'), null);
  assert.equal(race.run('state.sourceView'), 'blank');
  assert.equal(race.run('saves.length'), 0);
});


function publicSamUI(options={}) {
  const view=fusionV2UI(options);
  view.context.fixtureCandidate=candidate({engine:helpers.SAM_ENGINE,recipe_id:helpers.SAM_RECIPE,
    model_sha256:'c'.repeat(64),model_params:{plate_inset:.95}});
  return view;
}

test('Ultra pins SAM through preview and adoption while preserving Undo', async()=>{
  const view=publicSamUI(), before=plain(view.run('snapshot()'));
  view.run("state.workflow.kind='default'; syncWorkflowRoute(); updateControls();");
  assert.equal(view.element('method-select').value,helpers.SAM_ENGINE);
  await view.run('recognizeCurrent()');
  assert.equal(view.run('state.modelPreview.engine'),helpers.SAM_ENGINE);
  assert.equal(view.run('modelCandidateCurrent()'),true);
  for(const id of ['btn-recognize-all','btn-recognize-current'])
    assert.equal(view.element(id).disabled,true);
  view.run('syncWorkflowRoute(); updateControls();');
  assert.equal(view.run('selectedModelEngine()'),helpers.SAM_ENGINE);
  view.run(`jsonRequest=async()=>({...snapshot(),revision:18,detections:fixtureCandidate.detections,
    machine_count_initial:1,count_engine:SAM_ENGINE,count_model:{recipe_id:modelHelpers.SAM_RECIPE},count_params:null});`);
  await view.run('applyModelPreview()');
  assert.equal(view.run('state.modelPreview.engine'),null);
  assert.equal(view.run('selectedModelEngine()'),helpers.SAM_ENGINE);
  assert.equal(view.element('method-select').value,helpers.SAM_ENGINE);
  assert.equal(view.run('state.doc.count_engine'),helpers.SAM_ENGINE);
  assert.equal(view.element('saved-source-visible').textContent,'currentSavedSourcesamSavedSource');
  assert.equal(view.element('btn-recognize-all').disabled,false);
  view.run('undo()'); assert.deepEqual(plain(view.run('snapshot()')),before);
});

test('discarding a failed Ultra preview preserves the selected route and saved work', async()=>{
  const view=publicSamUI(),before=plain(view.run('snapshot()'));
  view.run("state.workflow.kind='default'; syncWorkflowRoute(); updateControls();");
  await view.run('recognizeCurrent()'); view.run('clearModelPreview(); updateControls();');
  assert.equal(view.run('selectedModelEngine()'),helpers.SAM_ENGINE);
  assert.equal(view.element('btn-recognize-all').disabled,false);
  view.run(`request=async()=>{throw Error('synthetic Ultra failure');};`);
  await view.run('recognizeCurrent()');
  assert.equal(view.run('selectedModelEngine()'),helpers.SAM_ENGINE);
  assert.match(view.element('model-message').textContent,/synthetic Ultra failure/);
  assert.equal(view.element('btn-model-discard').hidden,false);
  assert.equal(view.element('btn-recognize-all').disabled,true);
  view.run('clearModelPreview();updateControls();');
  assert.equal(view.element('method-select').value,helpers.SAM_ENGINE);
  assert.equal(view.element('btn-recognize-current').disabled,false);
  assert.deepEqual(plain(view.run('snapshot()')),before);
  assert.equal(view.run('saves.length'),0);
});

test('unavailable Ultra never falls back to Fusion or Lite', async()=>{
  const view=publicSamUI(),before=plain(view.run('snapshot()'));
  view.run("state.workflow.kind='default'; state.config.models.sam2.available=false; syncWorkflowRoute(); updateControls();");
  assert.equal(view.element('btn-recognize-current').disabled,true);
  assert.equal(view.element('btn-recognize-all').disabled,true);
  await view.run('recognizeCurrent()');
  assert.equal(view.run('requests.length'),0);
  assert.equal(view.run('selectedModelEngine()'),helpers.SAM_ENGINE);
  assert.deepEqual(plain(view.run('snapshot()')),before);
});

test('Ultra uses SAM for all photo metadata and manual circles on local and web hosts', async()=>{
  for(const web of [false,true]) for(const sourceView of ['main','blank','back','unknown']) {
    const view=publicSamUI({sourceView,web});
    view.run("state.workflow.kind='default'; state.doc.plate_manual=true;syncWorkflowRoute();updateControls();");
    const beforeWithPlate=plain(view.run('snapshot()'));
    assert.equal(view.element('btn-recognize-current').disabled,false);
    await view.run('recognizeCurrent()');
    assert.equal(view.run('modelCandidateCurrent()'),true,sourceView);
    assert.equal(view.run('requests.length'),1);
    assert.deepEqual(JSON.parse(view.run('requests[0].options.body')),{
      engine:helpers.SAM_ENGINE,expected_revision:17,expected_image_sha256:hash,model_params:{}});
    assert.deepEqual(plain(view.run('snapshot()')),beforeWithPlate);
    assert.equal(view.run('saves.length'),0);
  }
});
