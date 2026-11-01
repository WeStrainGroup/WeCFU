// Actual app workflow functions in a synthetic VM; no browser, HTTP, photos or model.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../wecfu/server/static/app.js'), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));
const defaults = {plate_inset: .88, min_value: 200, max_saturation: 100,
  min_circularity: .55, min_area_frac: .0001, peak_min_distance: 15};
const savedParams = {...defaults, min_value: 183, plate_inset: .83};
const savedDoc = {mode: 'auto', plate: {cx: 100, cy: 100, r: 90}, params: savedParams,
  count_params: savedParams, count_engine: 'baseline', count_model: null,
  revision: 7, counted: true, reviewed: false, plate_manual: false, notes: '',
  machine_count_initial: 1, detections: [{id: 9, cx: 80, cy: 90, r: 5, source: 'cv', score: .8, accepted: true}]};

function ui() {
  const nodes = new Map(), windowListeners = new Map(), errors = [];
  const document = {activeElement: null};
  function node(id = '', tagName = 'DIV') {
    const classes = new Set(), attributes = new Map(), handlers = new Map();
    return {id, tagName, value: '', textContent: '', checked: false, disabled: false, hidden: false,
      open: false, dataset: {}, children: [], style: {setProperty() {}}, attributes, handlers,
      scrollTop: 0, clientHeight: 200, scrollHeight: 1000, clientTop: 0,
      rect: {top: 0, bottom: 20, width: 500, height: 200}, focusCalls: [],
      classList: {toggle(name, force) { const add = force ?? !classes.has(name); if (add) classes.add(name); else classes.delete(name); return add; },
        add(name) { classes.add(name); }, remove(name) { classes.delete(name); }, contains(name) { return classes.has(name); }},
      setAttribute(key, value) { attributes.set(key, value); }, removeAttribute(key) { attributes.delete(key); },
      addEventListener(type, fn) { if (!handlers.has(type)) handlers.set(type, []); handlers.get(type).push(fn); },
      async fire(type, event = {}) { for (const fn of handlers.get(type) || []) await fn({target: this, ...event}); },
      focus(options) { this.focusCalls.push(plain(options)); document.activeElement = this; },
      getBoundingClientRect() { return this.rect; },
      checkValidity() { return this.value !== '' && Number.isFinite(Number(this.value)); },
      closest() { return null; },
      append(...children) { this.children.push(...children); }, appendChild(child) { this.children.push(child); },
      replaceChildren(fragment) { this.children = [...fragment.children]; },
      querySelector(selector) { return this.children.find(child => child.className === selector.slice(1)) || null; },
      scrollIntoView() { throw new Error('must not scroll the page'); },
    };
  }
  function element(id) {
    if (!nodes.has(id)) nodes.set(id, node(id));
    return nodes.get(id);
  }
  document.getElementById = element;
  document.createElement = tag => node('', tag.toUpperCase());
  document.createDocumentFragment = () => node('', 'FRAGMENT');
  document.querySelector = () => null;
  document.activeElement = node('body', 'BODY');
  const replacementHint = node(); replacementHint.className = 'model-replacement';
  element('model-tools').appendChild(replacementHint);
  const window = {location: {search: ''},
    addEventListener(type, fn) { if (!windowListeners.has(type)) windowListeners.set(type, []); windowListeners.get(type).push(fn); },
    confirm: () => false,
    WECFU_I18N: {t: key => key, getLang: () => 'en'},
    WECFU_PARAM_CONTROLS: require('../wecfu/server/static/param_controls.js'),
    WECFU_REFERENCE_CONTROLS: require('../wecfu/server/static/reference_controls.js'),
    WECFU_MODEL_PREVIEW_CONTROLS: require('../wecfu/server/static/model_preview_controls.js'),
    WECFU_REVIEW_QUEUE_CONTROLS: require('../wecfu/server/static/review_queue_controls.js'),
    WECFU_WORKFLOW_CONTROLS: require('../wecfu/server/static/workflow_controls.js')};
  const context = vm.createContext({window, document, console: {error: e => errors.push(e)},
    URLSearchParams, AbortController, clearTimeout, setTimeout, requestAnimationFrame: () => 1,
    ResizeObserver: class { observe() {} }, queueMicrotask() {},
    fetch() { throw new Error('real network is forbidden'); }});
  vm.runInContext(source, context);
  context.fixtureDoc = plain(savedDoc);
  const run = code => vm.runInContext(code, context);
  run(`
    let calls = [], saves = [], previews = 0, moves = [], confirmations = [];
    draw = () => {}; invalidateBackground = () => {}; refreshMaskPreview = () => { previews++; };
    loadImages = async () => {}; queueSave = () => { saves.push(snapshot()); }; flushEdits = async () => {};
    jsonRequest = async (url, method = 'GET', body) => { calls.push({url, method, body: body === undefined ? null : clone(body)}); throw new Error('unexpected request ' + url); };
    state.config = {web_mode: false, builtin_algorithms: ['baseline', ENHANCED_ENGINE], default_count_engine: ENHANCED_ENGINE,
      default_params: {...DEFAULTS}, experimental_models: {cfucounter: {enabled: false, available: false}},
      models: {fusion_v2: {enabled: true, available: true, engine: FUSION_V2_ENGINE,
        model_sha256: 'b'.repeat(64), recipe_id: modelHelpers.FUSION_V2_RECIPE},
        sam2: {enabled: true, available: true, engine: SAM_ENGINE,
          model_sha256: 'c'.repeat(64), recipe_id: modelHelpers.SAM_RECIPE}}};
    state.sourceView = 'main'; state.batch = 'synthetic'; state.imageName = 'first.png'; state.img = {width: 200, height: 200};
    state.imageSourceHash = 'a'.repeat(64); state.imageList = [{name: 'first.png', counted: true}];
    state.saveQueues.set(keyFor(), {revision: 9});
    $('modal-backdrop').hidden = $('export-backdrop').hidden = true;
    $('p-radius').value = 40; $('mode-select').value = 'auto';
    initializeWorkflow(); adopt(fixtureDoc); wireUpHandlers();
  `);
  return {run, context, element, node, document, window, errors,
    async key(event) { for (const fn of windowListeners.get('keydown') || []) await fn(event); }};
}

function custom(view) {
  view.element('recognition-profile').value = 'custom';
  view.run('changeRecognitionProfile()');
}

test('custom parameter edits remain a draft and never save into the loaded document', () => {
  const v = ui(), before = plain(v.run('snapshot()'));
  custom(v);
  v.element('p-min-value').value = 172;
  v.run("parametersChanged('min_value')");
  assert.equal(v.run('state.workflow.customParams.min_value'), 172);
  assert.deepEqual(plain(v.run('snapshot()')), before);
  assert.equal(v.run('saves.length'), 0);
  assert.equal(v.run('calls.length'), 0);
  assert.equal(v.run('state.history.length'), 0);
});

test('adopting another image retains the custom draft and each image original mark provenance', () => {
  const v = ui(); custom(v);
  v.element('p-min-value').value = 171;
  v.run("parametersChanged('min_value')");
  const other = {...plain(savedDoc), params: {...savedParams, min_value: 222},
    count_engine: 'sam_dino_fusion_local_v1', count_model: {recipe_id: 'saved-v1', model_sha256: 'd'.repeat(64)},
    count_params: null, detections: [{id: 70, cx: 60, cy: 70, r: 4, source: 'manual'}]};
  v.context.other = other;
  v.run("state.imageName = 'other.png'; adopt(other)");
  assert.equal(v.run('paramsBody().min_value'), 171);
  assert.equal(v.run('state.doc.params.min_value'), 222);
  assert.deepEqual(plain(v.run('state.detections')), other.detections);
  assert.deepEqual(plain(v.run('state.doc.count_model')), other.count_model);
  v.run("state.imageName = 'first.png'; adopt(fixtureDoc)");
  assert.equal(v.run('paramsBody().min_value'), 171);
  assert.deepEqual(plain(v.run('state.doc.params')), savedParams);
  assert.equal(v.run('state.doc.count_engine'), 'baseline');
  assert.equal(v.run('saves.length'), 0);
});

test('default recognition dispatches only the selected available model and never falls back after failure', async () => {
  const v = ui();
  v.run(`let routes = []; runModelPreview = async () => { routes.push(selectedModelEngine()); throw new Error('synthetic model failure'); };
    recount = async () => { routes.push('builtin'); };`);
  assert.equal(v.element('method-select').value, 'sam_dino_fusion_local_v2');
  await assert.rejects(v.run('recognizeCurrent()'), /synthetic model failure/);
  assert.deepEqual(plain(v.run('routes')), ['sam_dino_fusion_local_v2']);
  v.run('state.config.models.fusion_v2.available = false; syncWorkflowRoute();');
  await assert.rejects(v.run('recognizeCurrent()'), /synthetic model failure/);
  assert.deepEqual(plain(v.run('routes')), ['sam_dino_fusion_local_v2', 'sam_dino_fusion_local_v2']);
  v.run('state.config.models.sam2.available = false; syncWorkflowRoute();');
  await assert.rejects(v.run('recognizeCurrent()'), /synthetic model failure/);
  assert.deepEqual(plain(v.run('routes')), ['sam_dino_fusion_local_v2', 'sam_dino_fusion_local_v2', 'sam_dino_fusion_local_v2']);
  assert.equal(v.run('state.history.length'), 0);
  assert.equal(v.run('saves.length'), 0);
});

test('custom batch recounts machine-only results with one captured recipe, skips human work and never retries 409', async () => {
  const v = ui(); custom(v);
  v.element('p-min-value').value = 190;
  v.run("parametersChanged('min_value')");
  v.run(`
    const docs = {'first.png': {...fixtureDoc, revision: 10}, 'second.png': {...fixtureDoc, revision: 11},
      'manual.png': {...fixtureDoc, mode: 'manual'}, 'notes.png': {...fixtureDoc, notes: 'preserve'},
      'reference.png': {...fixtureDoc}, 'race.png': {...fixtureDoc, revision: 14}};
    state.imageList = Object.keys(docs).map(name => ({name, counted: true}));
    jsonRequest = async (url, method = 'GET', body) => {
      calls.push({url, method, body: body === undefined ? null : clone(body)});
      const name = decodeURIComponent(url.split('/image/')[1].split('/')[0]);
      if (url.endsWith('/detections')) return clone(docs[name]);
      if (url.endsWith('/reference')) return {status: name === 'reference.png' ? 'stale' : 'missing'};
      if (method === 'POST' && url.includes('/run?')) {
        if (name === 'race.png') { const e = new Error('concurrent edit'); e.status = 409; throw e; }
        if (name === 'first.png') {
          state.workflow.customParams = {...DEFAULTS, min_value: 77};
          state.config.builtin_algorithms = ['baseline']; state.config.default_count_engine = 'baseline';
        }
        return {...clone(docs[name]), params: clone(body), count_params: clone(body), count_engine: ENHANCED_ENGINE, revision: docs[name].revision + 1};
      }
      throw new Error('unexpected route');
    };`);
  await v.run('countAll()');
  const calls = plain(v.run('calls')), posts = calls.filter(c => c.method === 'POST');
  assert.equal(posts.length, 3);
  assert.deepEqual(posts.map(c => new URL(c.url, 'http://synthetic').searchParams.get('expected_revision')), ['10', '11', '14']);
  for (const post of posts) {
    const query = new URL(post.url, 'http://synthetic').searchParams;
    assert.equal(query.get('engine'), 'component_watershed_v1');
    assert.equal(query.get('protect_existing_edits'), 'true');
    assert.equal(post.body.min_value, 190);
  }
  assert.equal(posts.filter(c => c.url.includes('race.png')).length, 1);
  assert.equal(calls.some(c => /manual\.png\/reference|notes\.png\/reference/.test(c.url)), false);
  const report = plain(v.run('state.workflow.lastBatchReport'));
  assert.deepEqual(report.completed, ['first.png', 'second.png']);
  assert.deepEqual(report.protected.map(p => p.name), ['manual.png', 'notes.png', 'reference.png', 'race.png']);
  assert.deepEqual(report.failed, []);
});

test('single edited recount asks permission and uses the latest queue revision after flush', async () => {
  const v = ui(); custom(v);
  v.run(`state.doc.notes = 'preserve edited note'; let allow = false;
    window.confirm = text => { confirmations.push(text); return allow; };
    flushEdits = async () => { state.saveQueues.get(keyFor()).revision = 31; };
    jsonRequest = async (url, method = 'GET', body) => {
      calls.push({url, method, body: body === undefined ? null : clone(body)});
      if (url.endsWith('/reference')) return {status: 'missing'};
      if (method === 'POST') return {...snapshot(), count_engine: ENHANCED_ENGINE, params: clone(body), count_params: clone(body), revision: 32};
      throw new Error('unexpected route');
    };`);
  const before = plain(v.run('snapshot()'));
  await v.run('recount()');
  assert.equal(v.run("calls.filter(c => c.method === 'POST').length"), 0);
  assert.equal(v.run('state.history.length'), 0);
  assert.deepEqual(plain(v.run('snapshot()')), before);
  v.run('allow = true');
  await v.run('recount()');
  const posts = plain(v.run("calls.filter(c => c.method === 'POST')"));
  assert.equal(posts.length, 1);
  assert.equal(new URL(posts[0].url, 'http://synthetic').searchParams.get('expected_revision'), '31');
  assert.equal(v.run('confirmations.length'), 2);
  assert.equal(v.run('state.history.length'), 1);
});

test('wired keyboard and select-change handlers focus canvas without scrolling but preserve native editing', async () => {
  const v = ui();
  v.run('moveSelection = async delta => { moves.push(delta); };');
  const profile = v.element('recognition-profile');
  profile.tagName = 'SELECT'; profile.value = 'custom'; v.document.activeElement = profile;
  const initialFocusCalls = v.element('canvas').focusCalls.length;
  await profile.fire('keydown', {key: 'ArrowDown'});
  await profile.fire('change');
  assert.equal(v.document.activeElement, profile);
  assert.equal(v.element('canvas').focusCalls.length, initialFocusCalls);
  assert.equal(v.run('state.workflow.kind'), 'custom');
  // A keyboard action after an earlier pointer opening must also retain native focus.
  await profile.fire('pointerdown');
  await profile.fire('keydown', {key: 'ArrowUp'});
  profile.value = 'default'; await profile.fire('change');
  assert.equal(v.document.activeElement, profile);
  assert.equal(v.element('canvas').focusCalls.length, initialFocusCalls);
  assert.equal(v.run('state.workflow.kind'), 'default');
  await profile.fire('pointerdown'); profile.value = 'custom';
  await profile.fire('change');
  assert.equal(v.document.activeElement, v.element('canvas'));
  assert.deepEqual(v.element('canvas').focusCalls.at(-1), {preventScroll: true});
  let prevented = 0;
  const key = (name, extra = {}) => ({key: name, preventDefault() { prevented++; }, ...extra});
  await v.key(key('ArrowRight'));
  assert.deepEqual(plain(v.run('moves')), [1]);
  for (const type of ['text', 'number', 'range']) {
    v.document.activeElement = v.node('editing', 'INPUT'); v.document.activeElement.type = type;
    await v.key(key('ArrowLeft'));
  }
  v.document.activeElement = profile; await v.key(key('ArrowRight'));
  v.document.activeElement = v.node('editor', 'DIV'); v.document.activeElement.isContentEditable = true;
  await v.key(key('ArrowRight'));
  v.document.activeElement = v.element('canvas');
  v.element('modal-backdrop').hidden = false; await v.key(key('ArrowRight'));
  v.element('modal-backdrop').hidden = true; await v.key(key('ArrowRight', {ctrlKey: true}));
  assert.deepEqual(plain(v.run('moves')), [1]);
  assert.equal(prevented, 1);
  assert.deepEqual(v.errors, []);
});

test('rendered selection updates aria-current and scrolls only the list to reveal clipping', () => {
  const v = ui();
  v.run("state.imageList = [{name:'first.png'}, {name:'second.png'}]; renderImageList();");
  const list = v.element('image-list'), [first, second] = list.children;
  list.scrollTop = 120; list.rect = {top: 50}; list.clientHeight = 200; list.scrollHeight = 1000;
  first.rect = {top: 80, bottom: 110}; second.rect = {top: 240, bottom: 290};
  v.run("state.imageName = 'second.png'; updateSelectedRows({reveal:true});");
  assert.equal(first.attributes.has('aria-current'), false);
  assert.equal(second.attributes.get('aria-current'), 'true');
  assert.equal(first.classList.contains('selected'), false);
  assert.equal(second.classList.contains('selected'), true);
  assert.equal(list.scrollTop, 160);
  second.rect = {top: 100, bottom: 130};
  v.run('updateSelectedRows({reveal:true})');
  assert.equal(list.scrollTop, 160);
  assert.equal(v.element('canvas-wrap').scrollTop, 0);
});

test('single unprotected recount rejects a newly created reference race with protection and no retry', async () => {
  const v = ui(); custom(v);
  const before = plain(v.run('snapshot()'));
  v.run(`let referenceCreated = false;
    window.confirm = text => { confirmations.push(text); return true; };
    jsonRequest = async (url, method = 'GET', body) => {
      calls.push({url, method, body: body === undefined ? null : clone(body)});
      if (url.endsWith('/reference')) {
        referenceCreated = true; // Another client confirms after this missing result is read.
        return {status: 'missing'};
      }
      if (method === 'POST') {
        if (!referenceCreated) throw new Error('invalid race fixture');
        const error = new Error('human reference created concurrently'); error.status = 409; throw error;
      }
      throw new Error('unexpected route');
    };`);
  await assert.rejects(v.run('recount()'), error => error.status === 409 && /reference created/.test(error.message));
  const calls = plain(v.run('calls')), posts = calls.filter(call => call.method === 'POST');
  assert.equal(posts.length, 1);
  assert.equal(calls.filter(call => call.url.endsWith('/reference')).length, 1);
  const query = new URL(posts[0].url, 'http://synthetic').searchParams;
  assert.equal(query.get('protect_existing_edits'), 'true');
  assert.equal(query.get('expected_revision'), '9');
  assert.equal(v.run('confirmations.length'), 0);
  assert.equal(v.run('state.history.length'), 0);
  assert.equal(v.run('saves.length'), 0);
  assert.equal(v.run('state.busy'), false);
  assert.deepEqual(plain(v.run('snapshot()')), before);
});

test('custom batch Undo restores the fresh server machine snapshot rather than stale displayed marks', async () => {
  const v = ui(); custom(v);
  const fresh = {...plain(savedDoc), revision: 42, params: {...savedParams, min_value: 211},
    count_params: null, count_engine: 'sam_dino_fusion_local_v2',
    count_model: {recipe_id: 'server-v2', model_sha256: 'e'.repeat(64)},
    detections: [{id: 42, cx: 111, cy: 112, r: 6, source: 'model', score: .97, accepted: true}]};
  v.context.freshServer = fresh;
  v.run(`jsonRequest = async (url, method = 'GET', body) => {
    calls.push({url, method, body: body === undefined ? null : clone(body)});
    if (url.endsWith('/detections')) return clone(freshServer);
    if (url.endsWith('/reference')) return {status: 'missing'};
    if (method === 'POST') return {...clone(freshServer), revision: 43,
      params: clone(body), count_params: clone(body), count_engine: ENHANCED_ENGINE, count_model: null,
      detections: [{id: 99, cx: 33, cy: 44, r: 3, source: 'cv'}]};
    throw new Error('unexpected route');
  };`);
  assert.equal(v.run('state.detections[0].id'), 9);
  await v.run('countAll()');
  const posts = plain(v.run("calls.filter(call => call.method === 'POST')"));
  assert.equal(posts.length, 1);
  assert.equal(new URL(posts[0].url, 'http://synthetic').searchParams.get('expected_revision'), '42');
  assert.equal(v.run('state.detections[0].id'), 99);
  assert.deepEqual(plain(v.run('state.history[0]')), fresh);
  v.run('undo()');
  assert.deepEqual(plain(v.run('state.detections')), fresh.detections);
  assert.deepEqual(plain(v.run('state.doc.params')), fresh.params);
  assert.deepEqual(plain(v.run('state.doc.count_model')), fresh.count_model);
  assert.equal(v.run('state.doc.count_engine'), fresh.count_engine);
  assert.equal(v.run('state.doc.count_params'), null);
  assert.equal(v.run('state.doc.reviewed'), false);
  assert.equal(v.run('state.history.length'), 0);
  assert.equal(v.run('state.saveQueues.get(keyFor()).revision'), 43);
  assert.equal(v.run('saves.length'), 1);
  assert.deepEqual(plain(v.run('saves[0].detections')), fresh.detections);
  assert.deepEqual(plain(v.run('saves[0].count_model')), fresh.count_model);
});

test('default model panel appears only for actionable trial states and replacement hint requires candidate or pending apply', () => {
  const v = ui(), panel = v.element('model-tools'), hint = panel.querySelector('.model-replacement');
  assert.ok(hint);
  assert.equal(panel.hidden, true);
  assert.equal(hint.hidden, true);
  assert.equal(v.element('btn-model-apply').hidden, true);
  assert.equal(v.element('btn-model-discard').hidden, true);
  const states = [
    {name: 'loading', setup: 'state.modelPreview.loading = true', hint: false, message: 'modelLoading'},
    {name: 'candidate', setup: 'state.modelPreview.candidate = {candidate_count: 3}', hint: true},
    {name: 'error', setup: "state.modelPreview.error = 'synthetic error'", hint: false, message: 'synthetic error'},
    {name: 'message', setup: "state.modelPreview.message = 'modelTrialExpired'", hint: false, message: 'modelTrialExpired'},
    {name: 'pending apply', setup: 'state.modelPreview.candidate = {candidate_count: 3}; state.modelPreview.pendingApply = {uncertain: true}', hint: true, message: 'modelApplying'},
    {name: 'manual plate', setup: 'state.doc.plate_manual = true', hint: false, message: 'fusionAutomaticPlateRequired'},
    {name: 'unavailable', setup: 'state.config.models.fusion_v2.available = false', hint: false, message: 'modelUnavailable'},
  ];
  for (const item of states) {
    v.run(`Object.assign(state.modelPreview, {loading: false, candidate: null, error: '', message: '', pendingApply: null});
      state.doc.plate_manual = false; state.config.models.fusion_v2.available = true;
      ${item.setup}; updateModelControls();`);
    assert.equal(panel.hidden, false, item.name);
    assert.equal(hint.hidden, !item.hint, item.name);
    assert.equal(v.element('btn-model-apply').hidden, item.name !== 'candidate', item.name);
    assert.equal(v.element('btn-model-discard').hidden, !['candidate', 'loading'].includes(item.name), item.name);
    if (item.message) assert.equal(v.element('model-message').textContent, item.message, item.name);
  }
  v.run('state.config.models.fusion_v2.available = true; updateModelControls()');
  assert.equal(panel.hidden, true);
  assert.equal(hint.hidden, true);
  assert.equal(v.run('calls.length'), 0);
  assert.equal(v.run('saves.length'), 0);
});

test('wired integer range arrows step exact raw values while native keys and pointer mappings preserve unsaved drafts', async () => {
  const v = ui(); custom(v);
  const original = plain(v.run('snapshot()'));
  v.run('moveSelection = async delta => { moves.push(delta); };');
  const integerRanges = [
    {id: 'min-value', start: 200, delta: 1, min: 0, max: 255},
    {id: 'max-sat', start: 100, delta: 1, min: 0, max: 255},
    {id: 'peak', start: 15, delta: -1, min: 2, max: 80},
    {id: 'radius', start: 297, delta: 1, min: 3, max: 300},
  ];
  for (const id of ['min-value', 'max-sat', 'peak', 'radius', 'inset', 'circ', 'min-area']) {
    const slider = v.element(`s-${id}`); slider.tagName = 'INPUT'; slider.type = 'range';
    // Mirror the HTML range's 0.001 step: near radius 298, normalized round trips
    // cannot represent every integer. Keyboard raw edits must survive this quantization.
    let position = Number(slider.value);
    Object.defineProperty(slider, 'value', {
      get: () => position,
      set: value => { position = Math.round(Math.max(0, Math.min(1, Number(value))) * 1000) / 1000; },
    });
  }
  async function rawInput(id, value) {
    const raw = v.element(`p-${id}`); raw.value = value; await raw.fire('input');
  }
  async function keyOnRange(id, key, consumed, repeat = false) {
    const slider = v.element(`s-${id}`);
    v.document.activeElement = slider;
    let prevented = 0;
    const event = {key, repeat, target: slider, defaultPrevented: false,
      preventDefault() { prevented++; event.defaultPrevented = true; }};
    await slider.fire('keydown', event);
    await v.key(event); // Bubble through the actual global image-navigation handler too.
    assert.equal(prevented, consumed ? 1 : 0, `${id} ${key} default handling`);
    assert.equal(v.document.activeElement, slider);
  }
  for (const range of integerRanges) {
    await rawInput(range.id, range.start);
    for (let step = 1; step <= 3; step++) {
      await keyOnRange(range.id, 'ArrowRight', true, step > 1);
      assert.equal(Number(v.element(`p-${range.id}`).value), range.start + range.delta * step, `${range.id} repeat ${step}`);
    }
    await keyOnRange(range.id, 'ArrowLeft', true);
    assert.equal(Number(v.element(`p-${range.id}`).value), range.start + range.delta * 2, `${range.id} reverse`);
    for (const [bound, outwardKey] of [[range.min, range.delta === 1 ? 'ArrowLeft' : 'ArrowRight'],
      [range.max, range.delta === 1 ? 'ArrowRight' : 'ArrowLeft']]) {
      await rawInput(range.id, bound);
      await keyOnRange(range.id, outwardKey, true);
      await keyOnRange(range.id, outwardKey, true, true);
      assert.equal(Number(v.element(`p-${range.id}`).value), bound, `${range.id} clamped at ${bound}`);
    }
    for (const nativeKey of ['Home', 'End']) {
      const before = Number(v.element(`p-${range.id}`).value);
      await keyOnRange(range.id, nativeKey, false);
      assert.equal(Number(v.element(`p-${range.id}`).value), before, `${range.id} ${nativeKey} stays native`);
    }
  }
  for (const id of ['inset', 'circ', 'min-area']) {
    const before = Number(v.element(`p-${id}`).value);
    await keyOnRange(id, 'ArrowRight', false);
    assert.equal(Number(v.element(`p-${id}`).value), before, `${id} fractional/log range stays native`);
  }
  // Existing input events still use linear, inverse or logarithmic normalized mappings.
  for (const [id, position, expected] of [['min-value', .5, 128], ['max-sat', .25, 64],
    ['peak', .75, 22], ['radius', .5, 30], ['inset', .6, .8], ['circ', .3, .3], ['min-area', .75, .001]]) {
    const slider = v.element(`s-${id}`);
    await slider.fire('pointerdown'); slider.value = position; await slider.fire('input');
    assert.equal(Number(v.element(`p-${id}`).value), expected, `${id} normalized pointer/input mapping`);
  }
  assert.deepEqual(plain(v.run('state.workflow.customParams')), {...defaults,
    min_value: 128, max_saturation: 64, peak_min_distance: 22, plate_inset: .8,
    min_circularity: .3, min_area_frac: .001});
  assert.deepEqual(plain(v.run('snapshot()')), original);
  assert.deepEqual(plain(v.run('moves')), []);
  assert.equal(v.run('saves.length'), 0);
  assert.equal(v.run('calls.length'), 0);
  assert.equal(v.run('state.history.length'), 0);
  assert.deepEqual(v.errors, []);
});

test('activity dots distinguish machine zero, viewed and unrecognized without implying verification', () => {
  const v = ui();
  assert.equal(v.run('imageFlagKey({counted:false, count:0, processed:true})'), 'flagUnprocessed');
  assert.equal(v.run('imageFlagKey({counted:true, count:0})'), 'flagCounted');
  assert.equal(v.run('imageFlagKey({counted:false, count:0, viewed:true})'), 'flagViewed');
  assert.equal(v.run('imageFlagKey({reviewed:true})'), 'flagViewed');
  assert.equal(v.run('imageFlagKey({notes:"edited note"})'), 'flagViewed');
});

test('successful source-bound browsing updates only activity metadata, never marks or human reference', async () => {
  const v = ui(), before = plain(v.run('snapshot()'));
  v.run(`jsonRequest = async (url, method, body) => { calls.push({url, method, body}); return {viewed:true, source_sha256:body.source_sha256}; };`);
  await v.run('recordViewed(state.batch, state.imageName, state.imageSourceHash, state.navToken)');
  assert.equal(v.run('state.imageList[0].viewed'), true);
  assert.deepEqual(plain(v.run('snapshot()')), before);
  assert.equal(v.run('saves.length'), 0);
  const calls = plain(v.run('calls'));
  assert.deepEqual(calls, [{url:'/api/batch/synthetic/image/first.png/viewed', method:'POST', body:{source_sha256:'a'.repeat(64)}}]);
});

test('failed, stale or hash-mismatched activity writes never turn the current dot dark', async () => {
  const v = ui();
  v.context.console.warn = () => {};
  v.run(`jsonRequest = async () => { throw new Error('synthetic failure'); };`);
  await v.run('recordViewed(state.batch, state.imageName, state.imageSourceHash, state.navToken)');
  assert.equal(v.run('Boolean(state.imageList[0].viewed)'), false);
  v.run(`jsonRequest = async () => ({viewed:true, source_sha256:'b'.repeat(64)});`);
  await v.run('recordViewed(state.batch, state.imageName, state.imageSourceHash, state.navToken)');
  assert.equal(v.run('Boolean(state.imageList[0].viewed)'), false);
  v.run(`let finishView; jsonRequest = () => new Promise(resolve => {finishView=resolve;});
    let viewing = recordViewed(state.batch, state.imageName, state.imageSourceHash, state.navToken);
    state.navToken++; state.imageName='second.png'; state.imageList=[{name:'second.png',counted:false}];
    finishView({viewed:true,source_sha256:'a'.repeat(64)});`);
  await v.run('viewing');
  assert.equal(v.run('Boolean(state.imageList[0].viewed)'), false);
  assert.equal(v.run('saves.length'), 0);
});

test('failed photo display never records a view', async () => {
  const v = ui();
  v.run(`let viewedCalls=0; recordViewed = async () => { viewedCalls++; };
    jsonRequest = async () => clone(fixtureDoc);
    loadPlateImage = async () => { throw new Error('synthetic decode failure'); };`);
  await assert.rejects(v.run("selectImage('broken.png')"), /synthetic decode failure/);
  assert.equal(v.run('viewedCalls'), 0);
  assert.equal(v.run('saves.length'), 0);
});


test('editable slider values commit only valid intentional edits and preserve saved results', async () => {
  const v = ui(); custom(v);
  const before = plain(v.run('snapshot()'));
  const value = v.element('v-min-value');
  await value.fire('change');
  assert.equal(v.run('paramsBody().min_value'), 200, 'focus/blur does not round the displayed .78 back into raw');
  value.value = '.9'; await value.fire('input');
  assert.equal(v.run('paramsBody().min_value'), 200, 'typing is still a draft');
  await value.fire('change');
  assert.equal(v.run('paramsBody().min_value'), 230);
  assert.equal(v.run('state.workflow.customParams.min_value'), 230);
  for (const invalid of ['', '1.1', '0x1', 'NaN', '-.1']) {
    value.value = invalid; await value.fire('input'); await value.fire('blur');
    assert.equal(v.run('paramsBody().min_value'), 230);
    assert.equal(value.attributes.get('aria-invalid'), 'true');
  }
  value.value = '.3'; await value.fire('input');
  await value.fire('keydown', {key: 'Escape', preventDefault() {}});
  assert.equal(v.run('paramsBody().min_value'), 230);
  assert.equal(value.value, '0.90');
  value.value = '.2'; await value.fire('input');
  v.element('s-min-value').disabled = true; await value.fire('change');
  assert.equal(v.run('paramsBody().min_value'), 230, 'disabled/pending input cannot commit');
  assert.deepEqual(plain(v.run('snapshot()')), before);
  assert.equal(v.run('calls.length'), 0);
  assert.equal(v.run('saves.length'), 0);
});

test('manual size numeric edit remains independent from recognition parameters and candidates', async () => {
  const v = ui();
  const before = plain(v.run('paramsBody()'));
  v.run('let clears = 0; clearModelPreview = () => { clears++; };');
  const value = v.element('v-radius');
  value.value = '1'; await value.fire('input'); await value.fire('change');
  assert.equal(Number(v.element('p-radius').value), 300);
  assert.deepEqual(plain(v.run('paramsBody()')), before);
  assert.equal(v.run('clears'), 0);
  assert.equal(v.run('calls.length'), 0);
});


test('public view declaration is SHA bound and never changes saved colony marks', async () => {
  const v = ui(), before = plain(v.run('snapshot()'));
  v.element('current-source-view').value = 'back';
  v.run(`jsonRequest = async (url, method, body) => {
    calls.push({url, method, body}); return {source_sha256: body.source_sha256, view: body.view, declared: true};
  };`);
  await v.run('changeSourceView()');
  assert.equal(v.run('state.sourceView'), 'back');
  assert.equal(v.element('btn-model-preview').disabled, true);
  assert.equal(v.element('model-message').textContent, 'sourceViewRequired');
  assert.deepEqual(plain(v.run('calls[0].body')), {source_sha256: 'a'.repeat(64), view: 'back'});
  assert.deepEqual(plain(v.run('snapshot()')), before);
  assert.equal(v.run('saves.length'), 0);
});

test('public web default remains Fusion and unavailable model never presents a classic substitute', () => {
  const v = ui();
  v.run(`state.config.web_mode = true; state.config.models.fusion_v2.available = false;
    syncWorkflowRoute(); updateControls();`);
  assert.equal(v.element('method-select').value, 'sam_dino_fusion_local_v2');
  assert.equal(v.element('btn-recognize-current').disabled, true);
  assert.equal(v.element('model-tools').hidden, false);
  assert.ok(v.element('model-message').textContent.includes('modelUnavailable'));
});
