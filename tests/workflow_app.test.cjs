// Actual app workflow functions in a synthetic VM; no browser, HTTP, photos or model.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../wecfu/server/static/app.js'), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));
const defaults = {plate_inset: .95, min_value: 200, max_saturation: 100,
  min_circularity: .55, min_area_frac: .0001, peak_min_distance: 15};
const savedParams = {...defaults, min_value: 183, plate_inset: .83};
const savedDoc = {mode: 'auto', plate: {cx: 100, cy: 100, r: 90}, params: savedParams,
  count_params: savedParams, count_engine: 'baseline', count_model: null,
  revision: 7, counted: true, reviewed: false, plate_manual: false, notes: '',
  machine_count_initial: 1, detections: [{id: 9, cx: 80, cy: 90, r: 5, source: 'cv', score: .8, accepted: true}]};

function ui(locale) {
  const nodes = new Map(), windowListeners = new Map(), errors = [];
  let uuidSequence = 0;
  const crypto = {randomUUID: () => `00000000-0000-4000-8000-${String(++uuidSequence).padStart(12, '0')}`};
  const document = {activeElement: null};
  function node(id = '', tagName = 'DIV') {
    const classes = new Set(), attributes = new Map(), handlers = new Map();
    return {id, tagName, value: '', textContent: '', checked: false, disabled: false, hidden: false,
      open: false, isConnected: true, dataset: {}, children: [], style: {setProperty() {}}, attributes, handlers,
      scrollTop: 0, clientHeight: 200, scrollHeight: 1000, clientTop: 0,
      rect: {top: 0, bottom: 20, width: 500, height: 200}, focusCalls: [],
      classList: {toggle(name, force) { const add = force ?? !classes.has(name); if (add) classes.add(name); else classes.delete(name); return add; },
        add(name) { classes.add(name); }, remove(name) { classes.delete(name); }, contains(name) { return classes.has(name); }},
      setAttribute(key, value) { attributes.set(key, value); }, getAttribute(key) { return attributes.get(key) ?? null; }, removeAttribute(key) { attributes.delete(key); },
      addEventListener(type, fn) { if (!handlers.has(type)) handlers.set(type, []); handlers.get(type).push(fn); },
      async fire(type, event = {}) { for (const fn of handlers.get(type) || []) await fn({target: this, ...event}); },
      focus(options) { this.focusCalls.push(options === undefined ? undefined : plain(options)); document.activeElement = this; },
      select() { this.selected = true; },
      showModal() { if (this.open) throw new Error('already open'); this.open = true; this.showModalCalls = (this.showModalCalls || 0) + 1; },
      close() { this.open = false; },
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
  const window = {location: {search: ''}, crypto,
    addEventListener(type, fn) { if (!windowListeners.has(type)) windowListeners.set(type, []); windowListeners.get(type).push(fn); },
    removeEventListener(type, fn) { windowListeners.set(type, (windowListeners.get(type) || []).filter(item => item !== fn)); },
    dispatchEvent(event) { for (const fn of [...(windowListeners.get(event.type) || [])]) fn(event); },
    confirm: () => { throw new Error('native confirm is not available in this WebView'); },
    WECFU_I18N: {t: key => key, getLang: () => 'en'},
    WECFU_PARAM_CONTROLS: require('../wecfu/server/static/param_controls.js'),
    WECFU_REFERENCE_CONTROLS: require('../wecfu/server/static/reference_controls.js'),
    WECFU_MODEL_PREVIEW_CONTROLS: require('../wecfu/server/static/model_preview_controls.js'),
    WECFU_REVIEW_QUEUE_CONTROLS: require('../wecfu/server/static/review_queue_controls.js'),
    WECFU_WORKFLOW_CONTROLS: require('../wecfu/server/static/workflow_controls.js'),
    WECFU_DEFAULT_BATCH: require('../wecfu/server/static/default_batch.js'),
    WECFU_SERIAL_BATCH: require('../wecfu/server/static/serial_batch.js')};
  if (locale) {
    const translationContext = {window: {}, localStorage: {getItem() {}, setItem() {}},
      document: {querySelectorAll: () => [], documentElement: {}}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../wecfu/server/static/i18n.js'), 'utf8'), translationContext);
    translationContext.window.WECFU_I18N.setLang(locale);
    window.WECFU_I18N = translationContext.window.WECFU_I18N;
  }
  const context = vm.createContext({window, document, console: {error: e => errors.push(e)},
    URLSearchParams, AbortController, crypto, clearTimeout, setTimeout, requestAnimationFrame: () => 1,
    ResizeObserver: class { observe() {} }, queueMicrotask() {},
    fetch() { throw new Error('real network is forbidden'); }});
  vm.runInContext(source, context);
  context.fixtureDoc = plain(savedDoc);
  const run = code => vm.runInContext(code, context);
  run(`
    let calls = [], saves = [], previews = 0, moves = [], confirmations = [];
    draw = () => {}; invalidateBackground = () => {}; refreshMaskPreview = () => { previews++; };
    loadImages = async () => {}; loadPlateImage = async () => ({sourceHash:'a'.repeat(64)}); queueSave = () => { saves.push(snapshot()); }; flushEdits = async () => {};
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
    initializeWorkflow(); state.workflow.kind = 'classical'; adopt(fixtureDoc); wireUpHandlers();
  `);
  return {run, context, element, node, document, window, errors,
    async key(event) { for (const fn of windowListeners.get('keydown') || []) await fn(event); }};
}

function custom(view) {
  view.element('recognition-profile').value = 'custom';
  view.run('changeRecognitionProfile()');
}

function samDefault(view) {
  view.run("state.config.default_model = SAM_ENGINE; state.workflow.kind = 'default'; syncWorkflowRoute(); updateControls();");
}

async function answerConfirmation(view, pending, accept) {
  // Callers may flush queued saves or read a reference before opening the dialog.
  for (let turn = 0; turn < 20 && !view.element('confirmation-dialog').open; turn++) await Promise.resolve();
  assert.equal(view.element('confirmation-dialog').open, true, 'must ask before writing');
  await view.element(accept ? 'btn-confirm-accept' : 'btn-confirm-cancel').fire('click');
  return pending;
}

for (const available of [true, false]) {
  test(`initial Ultra waits for capability before displaying ${available ? 'ready' : 'unavailable'} state`, async () => {
    const v = ui(); samDefault(v);
    v.context.configAvailable = available;
    v.run(`let finishConfig;
      const nextConfig = clone(state.config); nextConfig.models.sam2.available = configAvailable;
      delete state.config; updateControls();
      request = async (url) => {
        calls.push({url});
        if (url !== '/api/config') throw Error('Unexpected request before configuration');
        return {json: () => new Promise(resolve => { finishConfig = resolve; })};
      };`);
    const pending = v.run('applyServerConfig()');
    await Promise.resolve();
    assert.equal(v.element('batch-hint').hidden, true);
    assert.equal(v.element('batch-hint').textContent, '');
    assert.equal(v.element('model-tools').hidden, true);
    assert.equal(v.element('model-message').textContent, '');
    assert.equal(v.element('btn-recognize-current').disabled, true);
    assert.equal(v.element('btn-recognize-all').disabled, true);
    assert.equal(v.element('method-select').value, 'sam2_local_v1');
    assert.deepEqual(plain(v.run('calls')), [{url:'/api/config'}]);
    v.run('finishConfig(nextConfig);');
    await pending;
    assert.equal(v.element('batch-hint').hidden, available);
    assert.equal(v.element('batch-hint').textContent, available ? '' : 'modelUnavailable');
    assert.equal(v.element('model-tools').hidden, available);
    assert.equal(v.element('model-message').textContent, available ? '' : 'modelUnavailable');
    assert.equal(v.element('btn-recognize-current').disabled, !available);
    assert.equal(v.element('btn-recognize-all').disabled, !available);
    assert.equal(v.element('method-select').value, 'sam2_local_v1');
    assert.equal(v.run('saves.length'), 0);
    assert.deepEqual(v.errors, []);
  });
}

test('a failed initial configuration reports the request failure without claiming SAM is unavailable', async () => {
  const v = ui(); samDefault(v);
  v.run(`let failConfig;
    delete state.config; updateControls();
    request = async (url) => {
      calls.push({url});
      return new Promise((_, reject) => { failConfig = reject; });
    };`);
  const pending = v.run('applyServerConfig().catch(handleError)');
  v.run("failConfig(Error('synthetic configuration request failed'));");
  await pending;
  assert.equal(v.element('batch-hint').hidden, true);
  assert.equal(v.element('model-tools').hidden, true);
  assert.equal(v.element('model-message').textContent, '');
  assert.equal(v.element('btn-recognize-current').disabled, true);
  assert.equal(v.element('btn-recognize-all').disabled, true);
  assert.equal(v.element('status').textContent, 'actionFailed: synthetic configuration request failed');
  assert.equal(v.element('status').classList.contains('error'), true);
  assert.equal(v.errors.length, 1);
  assert.equal(v.run('saves.length'), 0);
  assert.deepEqual(plain(v.run('calls')), [{url:'/api/config'}]);
});

test('startup configuration recovers from bounded transient failures using only uncached GETs', async () => {
  const v = ui(); samDefault(v);
  v.run(`const readyConfig=clone(state.config); delete state.config; updateControls();
    request = async (url, options) => {
      calls.push({url,method:options.method,cache:options.cache,hasSignal:!!options.signal});
      if (calls.length === 1) throw TypeError('synthetic connection refused');
      if (calls.length === 2) throw Object.assign(Error('synthetic startup unavailable'), {status:503});
      return {json:async()=>readyConfig};
    };`);
  await v.run('applyServerConfig()');
  assert.deepEqual(plain(v.run('calls')), Array.from({length:3}, () => ({
    url:'/api/config',method:'GET',cache:'no-store',hasSignal:true,
  })));
  assert.equal(v.element('btn-recognize-current').disabled, false);
  assert.equal(v.element('batch-hint').hidden, true);
  assert.equal(v.element('status').textContent, '');
  assert.equal(v.run('saves.length'), 0);
  assert.deepEqual(v.errors, []);
});

test('startup network failure stops after three GETs and preserves disabled state and saved work', async () => {
  const v = ui(); samDefault(v);
  const before = plain(v.run('snapshot()'));
  v.run(`delete state.config; updateControls();
    request = async (url,options) => {
      calls.push({url,method:options.method,cache:options.cache});
      throw TypeError('synthetic persistent network failure');
    };`);
  await v.run('applyServerConfig().catch(handleError)');
  assert.equal(v.run('calls.length'), 3);
  assert.equal(v.element('status').textContent, 'actionFailed: synthetic persistent network failure');
  assert.equal(v.element('btn-recognize-current').disabled, true);
  assert.equal(v.element('btn-recognize-all').disabled, true);
  assert.equal(v.element('batch-hint').hidden, true);
  assert.equal(v.element('model-tools').hidden, true);
  assert.deepEqual(plain(v.run('snapshot()')), before);
  assert.equal(v.run('saves.length'), 0);
  assert.equal(v.errors.length, 1);
});

test('a permanent configuration HTTP error is not retried', async () => {
  const v = ui(); samDefault(v);
  v.run(`delete state.config; updateControls();
    request = async (url,options) => {
      calls.push({url,method:options.method});
      throw Object.assign(Error('synthetic forbidden configuration'), {status:403});
    };`);
  await v.run('applyServerConfig().catch(handleError)');
  assert.equal(v.run('calls.length'), 1);
  assert.equal(v.element('status').textContent, 'actionFailed: synthetic forbidden configuration');
  assert.equal(v.element('btn-recognize-current').disabled, true);
  assert.equal(v.run('saves.length'), 0);
});

test('each startup attempt has its own eight-second abort and an overall retry limit', async () => {
  const v = ui(); samDefault(v);
  const scheduled = [];
  v.context.setTimeout = (callback, milliseconds) => {
    scheduled.push(milliseconds); queueMicrotask(callback); return scheduled.length;
  };
  v.context.clearTimeout = () => {};
  v.run(`delete state.config; updateControls();
    request = async (url,options) => {
      calls.push({url,method:options.method});
      return new Promise((_,reject)=>options.signal.addEventListener('abort',()=>{
        reject(Object.assign(Error('synthetic startup timeout'), {name:'AbortError'}));
      },{once:true}));
    };`);
  await v.run('applyServerConfig().catch(handleError)');
  assert.deepEqual(scheduled, [8000,300,8000,900,8000]);
  assert.equal(v.run('calls.length'), 3);
  assert.equal(v.element('status').textContent, 'actionFailed: synthetic startup timeout');
  assert.equal(v.element('btn-recognize-all').disabled, true);
});

test('ordinary write requests remain single-attempt after adding startup retries', async () => {
  const v = ui();
  const transport = [];
  v.context.fetch = async (url,options) => {
    transport.push({url,method:options.method}); throw new TypeError('synthetic lost write response');
  };
  await assert.rejects(v.run("request('/api/batch/synthetic/image/first.png/model-preview/apply', {method:'POST'})"), /synthetic lost write response/);
  assert.deepEqual(transport, [{url:'/api/batch/synthetic/image/first.png/model-preview/apply',method:'POST'}]);
});

for (const button of ['btn-recognize-all', 'btn-run']) {
  test(`wired ${button} uses serial SAM for local default and captures one capability`, async () => {
    const v = ui(); samDefault(v);
    v.run(`emptyViewer(); let recognizedItems = [], activeItems = 0, maxActiveItems = 0;
      state.imageList = [{name:'first.png'}, {name:'second.png'}];
      window.WECFU_DEFAULT_BATCH = {
        recognizeBuiltin: async () => { throw Error('must not fall back to classical'); },
        recognize: async item => {
          activeItems++; maxActiveItems = Math.max(maxActiveItems, activeItems);
          recognizedItems.push(clone(item));
          state.config.models.sam2.model_sha256 = 'd'.repeat(64);
          await Promise.resolve(); activeItems--;
          return {name:item.name, status:'completed'};
        }}; updateControls();`);
    await v.element(button).fire('click');
    const items = plain(v.run('recognizedItems'));
    assert.deepEqual(items.map(item => item.name), ['first.png', 'second.png']);
    assert.ok(items.every(item => item.engine === 'sam2_local_v1'));
    assert.ok(items.every(item => item.capability.model_sha256 === 'c'.repeat(64)));
    assert.equal(v.run('maxActiveItems'), 1);
    assert.equal(v.run('state.workflow.lastBatchReport.results.length'), 2);
    assert.equal(v.run('state.busy'), false);
    assert.equal(v.run('saves.length'), 0);
    assert.equal(v.run('calls.length'), 0);
    assert.deepEqual(v.errors, []);
  });
}

test('wired fresh-current default SAM validates and adopts only this image with guarded receipt and Undo', async () => {
  const v = ui();
  const fresh = {...plain(savedDoc), revision:42, counted:false, detections:[], machine_count_initial:0,
    count_engine:null, count_model:null, count_params:null};
  v.context.freshBefore = fresh;
  v.run(`adopt(freshBefore); trackRevision(freshBefore);
    state.sourceView = 'unknown'; state.imageList = [{name:'first.png'}, {name:'second.png'}];
    const samMarks = [{id:1,cx:80,cy:90,r:5,source:'cv',score:.98,accepted:true}];
    jsonRequest = async (url, method='GET', body) => {
      calls.push({url,method,body:body === undefined ? null : clone(body)});
      if (url.endsWith('/detections')) return clone(freshBefore);
      if (url.endsWith('/reference')) return {status:'missing'};
      if (url.endsWith('/model-preview')) return {candidate_id:'synthetic-sam-candidate',
        base_revision:42,image_sha256:'a'.repeat(64),engine:SAM_ENGINE,model_sha256:'c'.repeat(64),
        recipe_id:modelHelpers.SAM_RECIPE,plate:clone(freshBefore.plate),model_params:{plate_inset:.95},
        candidate_count:1,detections:clone(samMarks),expires_at:Date.now()/1000+60};
      if (url.endsWith('/model-preview/apply')) return {...clone(freshBefore),revision:43,counted:true,
        detections:clone(samMarks),machine_count_initial:1,count_engine:SAM_ENGINE,
        count_model:{model_sha256:'c'.repeat(64),recipe_id:modelHelpers.SAM_RECIPE,plate_inset:.95},
        _model_preview_apply:{request_id:body.request_id,request:clone(body),applied_revision:43}};
      throw Error('unexpected route '+url);
    };`);
  samDefault(v);
  await v.element('btn-recognize-current').fire('click');
  const calls = plain(v.run('calls')), posts = calls.filter(call => call.method === 'POST');
  assert.equal(posts.length, 2);
  assert.ok(calls.every(call => call.url.includes('/first.png/')));
  assert.equal(calls.some(call => call.url.endsWith('/source_view') || call.url.includes('/run?')), false);
  assert.deepEqual(posts[0].body, {engine:'sam2_local_v1',expected_revision:42,
    expected_image_sha256:'a'.repeat(64),model_params:{},only_unrecognized:true});
  assert.equal(posts[1].body.only_unrecognized, true);
  assert.equal(posts[1].body.replace_all, true);
  assert.equal(posts[1].body.expected_revision, 42);
  assert.equal(v.run('state.doc.count_engine'), 'sam2_local_v1');
  assert.equal(v.run('state.doc.reviewed'), false);
  assert.deepEqual(plain(v.run('state.history[0]')), fresh);
  assert.equal(v.run('state.workflow.lastBatchReport.total'), 1);
  assert.equal(v.run('saves.length'), 0);
  v.run('undo()');
  assert.equal(v.run('state.doc.counted'), false);
  assert.deepEqual(plain(v.run('state.detections')), []);
  assert.equal(v.run('state.saveQueues.get(keyFor()).revision'), 43);
  assert.deepEqual(v.errors, []);
});

test('wired existing-current default SAM keeps a validated preview separate from saved provenance', async () => {
  const v = ui(), before = plain(v.run('snapshot()')); samDefault(v);
  v.run(`let requestedPreview = [];
    countDefaultBatch = async () => { throw Error('existing result must not auto-adopt'); };
    recount = async () => { throw Error('must not invoke classical'); };
    loadPlateImage = async () => ({sourceHash:'a'.repeat(64),image:{width:200,height:200}});
    boundedImage = image => image;
    request = async (url, options) => {
      requestedPreview.push({url,body:JSON.parse(options.body)});
      return {json:async()=>({candidate_id:'explicit-sam-preview',base_revision:9,
        image_sha256:'a'.repeat(64),engine:SAM_ENGINE,model_sha256:'c'.repeat(64),
        recipe_id:modelHelpers.SAM_RECIPE,plate:clone(fixtureDoc.plate),model_params:{plate_inset:.95},
        candidate_count:0,detections:[],expires_at:Date.now()/1000+60})};
    };`);
  await v.element('btn-recognize-current').fire('click');
  try {
    assert.deepEqual(plain(v.run('requestedPreview')), [{url:'/api/batch/synthetic/image/first.png/model-preview',
      body:{engine:'sam2_local_v1',expected_revision:9,expected_image_sha256:'a'.repeat(64),model_params:{}}}]);
    assert.equal(v.run('state.modelPreview.candidate.candidate_id'), 'explicit-sam-preview');
    assert.equal(v.element('btn-model-apply').hidden, false);
    assert.equal(v.element('btn-model-apply').disabled, false);
    assert.deepEqual(plain(v.run('snapshot()')), before);
    assert.equal(v.run('state.doc.count_engine'), 'baseline');
    assert.equal(v.element('recognition-route').textContent, 'defaultRoute');
    assert.equal(v.element('saved-source-visible').hidden, false);
    assert.equal(v.run('saves.length'), 0);
    assert.equal(v.run('calls.length'), 0);
    assert.deepEqual(v.errors, []);
  } finally { v.run('clearModelPreview()'); }
});

for (const unavailable of ["available = false", "enabled = false", "recipe_id = 'wrong'", "model_sha256 = 'invalid'"]) {
  test(`unavailable default SAM (${unavailable}) disables both actions and never falls back`, async () => {
    const v = ui();
    v.run(`state.config.models.sam2.${unavailable};`); samDefault(v);
    assert.equal(v.element('btn-recognize-current').disabled, true);
    assert.equal(v.element('btn-recognize-all').disabled, true);
    assert.equal(v.element('method-select').value, 'sam2_local_v1');
    // Fire handlers directly as well: disabled DOM is not the only safety gate.
    await v.element('btn-recognize-current').fire('click');
    await v.element('btn-recognize-all').fire('click');
    await v.element('btn-run').fire('click');
    assert.equal(v.run('calls.length'), 0);
    assert.equal(v.run('saves.length'), 0);
    assert.equal(v.element('status').textContent, 'modelUnavailable');
    assert.equal(v.element('status').classList.contains('error'), true);
    assert.equal(v.element('method-select').value, 'sam2_local_v1');
    assert.deepEqual(v.errors, []);
  });
}

test('explicit classical profile keeps improved builtin current and batch routes with fixed defaults', async () => {
  const v = ui(); samDefault(v);
  v.element('recognition-profile').value = 'classical';
  await v.element('recognition-profile').fire('change');
  v.run(`state.config.models.sam2.available = false; updateControls();
    jsonRequest = async (url, method='GET', body) => {
      calls.push({url,method,body:body === undefined ? null : clone(body)});
      if (url.endsWith('/reference')) return {status:'missing'};
      if (url.includes('/run?')) return {...snapshot(),revision:10,counted:true,
        count_engine:ENHANCED_ENGINE,count_model:null,count_params:clone(body),params:clone(body)};
      throw Error('unexpected route '+url);
    };`);
  assert.equal(v.element('method-select').value, 'component_watershed_v1');
  assert.equal(v.element('recognition-route').textContent, 'classicalRoute');
  assert.equal(v.element('btn-recognize-current').disabled, false);
  assert.equal(v.element('btn-recognize-all').disabled, false);
  await v.element('btn-recognize-current').fire('click');
  const posts = plain(v.run("calls.filter(call => call.method === 'POST')"));
  assert.equal(posts.length, 1);
  assert.match(posts[0].url, /engine=component_watershed_v1/);
  assert.deepEqual(posts[0].body, defaults);
  v.run(`let classicalItems=[]; emptyViewer();
    window.WECFU_DEFAULT_BATCH = {
      recognize:async()=>{throw Error('explicit classical must not invoke SAM');},
      recognizeBuiltin:async item=>{classicalItems.push(clone(item));return {name:item.name,status:'completed'};}
    };`);
  await v.element('btn-recognize-all').fire('click');
  assert.equal(v.run('classicalItems.length'), 1);
  assert.equal(v.run('classicalItems[0].engine'), 'component_watershed_v1');
  assert.deepEqual(plain(v.run('classicalItems[0].params')), defaults);
  assert.deepEqual(v.errors, []);
});

test('web exposes all three profiles and never relabels unavailable Ultra as Lite', async () => {
  const v = ui(); samDefault(v);
  v.run('state.config.web_mode=true; state.config.models.sam2.available=false; syncWorkflowRoute(); updateControls();');
  assert.equal(v.element('profile-option-default').textContent, 'profileDefault');
  assert.equal(v.element('profile-option-classical').hidden, false);
  assert.equal(v.element('mode-info-title').textContent, 'profileDefault');
  assert.equal(v.element('method-select').value, 'sam2_local_v1');
  assert.equal(v.element('recognition-route').textContent, 'defaultRoute');
  assert.equal(v.element('btn-recognize-current').disabled, true);
  assert.equal(v.element('btn-recognize-all').disabled, true);
  await v.element('btn-recognize-current').fire('click');
  await v.element('btn-recognize-all').fire('click');
  assert.equal(v.run('calls.length'), 0);
  assert.equal(v.run('saves.length'), 0);
  assert.equal(v.element('status').textContent, 'modelUnavailable');
  assert.deepEqual(v.errors, []);
});

test('web Ultra recognizes the selected image and serial batch through SAM only', async () => {
  const v = ui(); samDefault(v);
  v.run(`state.config.web_mode=true;
    adopt({...fixtureDoc, counted:false, detections:[], machine_count_initial:0, count_engine:null});
    state.imageList = [{name:'first.png'}, {name:'second.png'}];
    let recognizedItems=[], activeItems=0, maxActiveItems=0;
    window.WECFU_DEFAULT_BATCH = {...window.WECFU_DEFAULT_BATCH,
      recognizeBuiltin: async () => { throw Error('Ultra must not invoke Lite'); },
      recognize: async item => {
        activeItems++; maxActiveItems=Math.max(maxActiveItems,activeItems);
        recognizedItems.push(clone(item)); await Promise.resolve(); activeItems--;
        return {name:item.name,status:'completed'};
      }}; updateControls();`);
  assert.equal(v.element('btn-recognize-current').disabled, false);
  assert.equal(v.element('btn-recognize-all').disabled, false);
  await v.element('btn-recognize-current').fire('click');
  assert.deepEqual(plain(v.run('recognizedItems.map(x => x.name)')), ['first.png']);
  v.run('recognizedItems=[];');
  await v.element('btn-recognize-all').fire('click');
  assert.deepEqual(plain(v.run('recognizedItems.map(x => x.name)')), ['first.png','second.png']);
  assert.equal(v.run('recognizedItems.every(x => x.engine === SAM_ENGINE && x.webMode === true)'), true);
  assert.equal(v.run('maxActiveItems'), 1);
  assert.equal(v.run('saves.length'), 0);
  assert.deepEqual(v.errors, []);
});

test('recognition menu has exactly Ultra Lite and Custom with no separate refinement entry', () => {
  const html = fs.readFileSync(path.join(__dirname, '../wecfu/server/static/index.html'), 'utf8');
  const select = html.match(/<select id="recognition-profile">([\s\S]*?)<\/select>/)[1];
  assert.deepEqual([...select.matchAll(/<option[^>]+value="([^"]+)"/g)].map(x => x[1]), ['default','classical','custom']);
  assert.doesNotMatch(html, /btn-refine-current|data-i18n="refineCurrent"/);
  assert.doesNotMatch(source, /refineCurrent|btn-refine-current/);
});

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

test('applying custom settings freezes the recipe and closes the panel without recognizing or editing a photo', async () => {
  const v = ui(), before = plain(v.run('snapshot()')); custom(v);
  assert.equal(v.run('state.workflow.adjustmentsOpen'), true);
  assert.equal(v.element('btn-recognize-current').hidden, false);
  assert.equal(v.element('btn-recognize-all').hidden, false);
  v.element('p-min-value').value = 172;
  v.run("parametersChanged('min_value')");
  assert.equal(v.run('state.workflow.customParams.min_value'), 172);
  assert.equal(v.run('state.workflow.appliedCustomParams.min_value'), 200);
  v.document.activeElement = v.element('p-min-value');
  await v.element('btn-apply-params').fire('click');
  const recipe = {...defaults, min_value:172};
  assert.deepEqual(plain(v.run('state.workflow.appliedCustomParams')), recipe);
  assert.equal(v.run('state.workflow.adjustmentsOpen'), false);
  assert.equal(v.element('adjustments-panel').hidden, true);
  assert.equal(v.element('btn-adjustments-toggle').attributes.get('aria-expanded'), 'false');
  assert.equal(v.document.activeElement, v.element('canvas'));
  assert.deepEqual(plain(v.run('snapshot()')), before);
  assert.equal(v.run('calls.length'), 0);
  assert.equal(v.run('saves.length'), 0);
  assert.equal(v.run('state.history.length'), 0);
  await v.element('btn-adjustments-toggle').fire('click');
  assert.equal(v.run('state.workflow.adjustmentsOpen'), true);
  assert.equal(v.element('adjustments-panel').hidden, false);
  assert.equal(v.element('btn-adjustments-toggle').attributes.get('aria-expanded'), 'true');
  v.element('p-min-value').value = 77; v.run("parametersChanged('min_value')");
  await v.element('btn-adjustments-toggle').fire('click');
  assert.equal(v.run('state.workflow.kind'), 'custom');
  assert.equal(v.run('state.workflow.adjustmentsOpen'), false);
  assert.deepEqual(plain(v.run('state.workflow.appliedCustomParams')), recipe);
  assert.equal(v.run('state.workflow.customParams.min_value'), 77);
  assert.deepEqual(plain(v.run('snapshot()')), before);
  assert.deepEqual(v.errors, []);
});

test('custom recipe and draft survive navigation and profile changes, while reset changes only the draft', async () => {
  const v = ui(); custom(v);
  v.element('p-min-value').value = 177; v.run("parametersChanged('min_value'); applyCustomSettings()");
  v.run('toggleAdjustmentPanel()');
  v.element('p-min-value').value = 166; v.run("parametersChanged('min_value')");
  v.context.otherCustomDoc = {...plain(savedDoc), params:{...savedParams,min_value:222}};
  v.run("state.imageName='second.png'; adopt(otherCustomDoc)");
  assert.equal(v.run('state.workflow.customParams.min_value'), 166);
  assert.equal(v.run('state.workflow.appliedCustomParams.min_value'), 177);
  assert.equal(v.run('paramsBody().min_value'), 166);
  v.element('recognition-profile').value = 'default';
  await v.element('recognition-profile').fire('change');
  custom(v);
  assert.equal(v.run('state.workflow.adjustmentsOpen'), true);
  assert.equal(v.run('paramsBody().min_value'), 166);
  assert.equal(v.run('state.workflow.appliedCustomParams.min_value'), 177);
  await v.element('btn-defaults').fire('click');
  assert.deepEqual(plain(v.run('state.workflow.customParams')), defaults);
  assert.equal(v.run('state.workflow.appliedCustomParams.min_value'), 177);
  assert.equal(Number(v.element('p-inset').value), .95);
  assert.equal(v.element('v-inset').value, '0.90');
  assert.equal(v.run('state.doc.params.min_value'), 222);
  assert.equal(v.run('calls.length'), 0);
  assert.equal(v.run('saves.length'), 0);
  assert.deepEqual(v.errors, []);
});

test('invalid custom draft cannot replace an applied recipe or trigger recognition', async () => {
  const v = ui(); custom(v);
  v.element('p-min-value').value = 177; v.run("parametersChanged('min_value'); applyCustomSettings(); toggleAdjustmentPanel()");
  const applied = plain(v.run('state.workflow.appliedCustomParams'));
  v.element('p-min-value').value = '';
  await v.element('btn-apply-params').fire('click');
  assert.deepEqual(plain(v.run('state.workflow.appliedCustomParams')), applied);
  assert.equal(v.run('state.workflow.adjustmentsOpen'), true);
  assert.equal(v.run('calls.length'), 0);
  assert.equal(v.run('saves.length'), 0);
});

for (const inputOrder of ['pending','blur-first']) test(`Apply rejects an invalid normalized number (${inputOrder}) without applying another draft`, async () => {
  const v=ui();custom(v);
  const input=v.element('v-min-value');
  input.value='.9';await input.fire('input');
  await v.element('btn-apply-params').fire('click');
  assert.equal(v.run('state.workflow.appliedCustomParams.min_value'),230);
  v.run('toggleAdjustmentPanel()');
  v.element('p-min-value').value=166;v.run("parametersChanged('min_value')");
  input.value='1.5';await input.fire('input');
  if(inputOrder==='blur-first')await input.fire('blur');
  await v.element('btn-apply-params').fire('click');
  assert.equal(v.run('state.workflow.appliedCustomParams.min_value'),230);
  assert.equal(v.run('state.workflow.adjustmentsOpen'),true);
  assert.equal(input.attributes.get('aria-invalid'),'true');
  assert.equal(v.run('calls.length'),0);
  assert.equal(v.run('saves.length'),0);
  if(inputOrder==='pending'){
    input.value='.8';await input.fire('input');await input.fire('blur');
    await v.element('btn-apply-params').fire('click');
    assert.equal(v.run('state.workflow.appliedCustomParams.min_value'),204);
  }else{
    await v.element('btn-defaults').fire('click');
    await v.element('btn-apply-params').fire('click');
    assert.deepEqual(plain(v.run('state.workflow.appliedCustomParams')),defaults);
  }
  assert.equal(v.run('state.workflow.adjustmentsOpen'),false);
  assert.notEqual(input.attributes.get('aria-invalid'),'true');
  assert.deepEqual(v.errors,[]);
});

test('dragging a slider repairs only its own invalid numeric value and leaves other errors blocking Apply',async()=>{
  const v=ui();custom(v);
  const original=plain(v.run('state.workflow.appliedCustomParams'));
  const brightness=v.element('v-min-value'),color=v.element('v-max-sat');
  for(const input of [brightness,color]){
    input.value='1.5';await input.fire('input');await input.fire('blur');
    assert.equal(input.attributes.get('aria-invalid'),'true');
  }
  const brightnessSlider=v.element('s-min-value');
  brightnessSlider.value=.5;await brightnessSlider.fire('input');
  assert.equal(v.run('state.workflow.customParams.min_value'),128);
  assert.notEqual(brightness.attributes.get('aria-invalid'),'true');
  assert.equal(color.attributes.get('aria-invalid'),'true');
  await v.element('btn-apply-params').fire('click');
  assert.deepEqual(plain(v.run('state.workflow.appliedCustomParams')),original);
  assert.equal(v.run('state.workflow.adjustmentsOpen'),true);
  const colorSlider=v.element('s-max-sat');
  colorSlider.value=.25;await colorSlider.fire('input');
  assert.notEqual(color.attributes.get('aria-invalid'),'true');
  await v.element('btn-apply-params').fire('click');
  assert.deepEqual(plain(v.run('state.workflow.appliedCustomParams')),{...defaults,min_value:128,max_saturation:64});
  assert.equal(v.run('state.workflow.adjustmentsOpen'),false);
  assert.equal(v.run('calls.length'),0);
  assert.equal(v.run('saves.length'),0);
  assert.deepEqual(v.errors,[]);
});

test('custom current recognition uses the applied recipe even with an uncommitted draft and a viewed photo', async () => {
  const v = ui(); custom(v);
  v.element('p-min-value').value = 177; v.run("parametersChanged('min_value'); applyCustomSettings(); toggleAdjustmentPanel()");
  v.element('p-min-value').value = 88; v.run("parametersChanged('min_value')");
  v.run(`state.imageList[0].viewed=true;
    jsonRequest=async(url,method='GET',body)=>{
      calls.push({url,method,body:body===undefined?null:clone(body)});
      if(url.endsWith('/reference')) return {status:'missing'};
      if(url.includes('/run?')) return {...snapshot(),revision:10,counted:true,
        count_engine:ENHANCED_ENGINE,count_model:null,count_params:clone(body),params:clone(body)};
      throw Error('unexpected route '+url);
    };`);
  await v.element('btn-recognize-current').fire('click');
  const posts=plain(v.run("calls.filter(call=>call.method==='POST')"));
  assert.equal(posts.length,1);
  assert.deepEqual(posts[0].body,{...defaults,min_value:177});
  assert.notEqual(new URL(posts[0].url,'http://synthetic').searchParams.get('only_unreviewed'),'true');
  assert.equal(v.run('state.workflow.customParams.min_value'),88);
  assert.equal(v.run('state.workflow.appliedCustomParams.min_value'),177);
  assert.equal(v.run('state.doc.count_params.min_value'),177);
  assert.equal(v.run('state.history.length'),1);
  assert.equal(v.run('confirmations.length'),0);
  assert.deepEqual(v.errors,[]);
});

test('custom all batch captures applied parameters and protects existing human work',async()=>{
  const v=ui();custom(v);
  v.element('p-min-value').value=181;v.run("parametersChanged('min_value');applyCustomSettings();toggleAdjustmentPanel()");
  v.element('p-min-value').value=91;v.run("parametersChanged('min_value')");
  v.run(`const scopeDocs={
    'first.png':{...fixtureDoc,revision:10},'seen.png':{...fixtureDoc,revision:11},
    'edited.png':{...fixtureDoc,revision:12,reviewed:true},'manual.png':{...fixtureDoc,revision:13,mode:'manual'},
    'notes.png':{...fixtureDoc,revision:14,notes:'preserve'},'reference.png':{...fixtureDoc,revision:15},
    'race.png':{...fixtureDoc,revision:16},'last.png':{...fixtureDoc,revision:17}};
    state.imageList=Object.entries(scopeDocs).map(([name,doc])=>({name,counted:true,viewed:name==='seen.png',
      reviewed:Boolean(doc.reviewed),mode:doc.mode,notes:doc.notes}));
    jsonRequest=async(url,method='GET',body)=>{
      calls.push({url,method,body:body===undefined?null:clone(body)});
      const name=decodeURIComponent(url.split('/image/')[1].split('/')[0]);
      if(url.endsWith('/detections')) return clone(scopeDocs[name]);
      if(url.endsWith('/reference')) return {status:name==='reference.png'?'verified':'missing'};
      if(url.includes('/run?')) {
        if(name==='race.png'){const error=Error('concurrent review');error.status=409;throw error;}
        if(name==='first.png'){
          state.workflow.customParams={...DEFAULTS,min_value:71};
          state.workflow.appliedCustomParams={...DEFAULTS,min_value:72};
          state.config.default_count_engine='baseline';state.config.builtin_algorithms=['baseline'];
        }
        return {...clone(scopeDocs[name]),revision:scopeDocs[name].revision+1,
          params:clone(body),count_params:clone(body),count_engine:ENHANCED_ENGINE,count_model:null};
      }
      throw Error('unexpected route '+url);
    };`);
  await v.element('btn-recognize-all').fire('click');
  const calls=plain(v.run('calls')),posts=calls.filter(call=>call.method==='POST');
  const names=posts.map(call=>decodeURIComponent(call.url.split('/image/')[1].split('/')[0]));
  assert.deepEqual(names,['first.png','seen.png','race.png','last.png']);
  for(const post of posts){
    assert.deepEqual(post.body,{...defaults,min_value:181});
    const query=new URL(post.url,'http://synthetic').searchParams;
    assert.equal(query.get('engine'),'component_watershed_v1');
    assert.equal(query.get('protect_existing_edits'),'true');
    assert.notEqual(query.get('only_unreviewed'),'true');
  }
  assert.equal(posts.filter(call=>call.url.includes('race.png')).length,1);
  assert.equal(posts.some(call=>/edited|manual|notes|reference/.test(call.url)),false);
  assert.equal(calls.some(call=>call.url.endsWith('/reference.png/reference')),true);
  assert.equal(v.run('state.busy'),false);
  assert.equal(v.run('saves.length'),0);
  assert.deepEqual(v.errors,[]);
});

for (const status of [undefined,503]) test(`custom batch stops after an uncertain write (${status || 'disconnect'}) and clears the stale current photo`,async()=>{
  const v=ui();custom(v);v.run('applyCustomSettings()');
  v.context.uncertainStatus=status;
  v.run(`state.imageList=[{name:'first.png'},{name:'next.png'}];
    jsonRequest=async(url,method='GET',body)=>{
      calls.push({url,method,body:body===undefined?null:clone(body)});
      if(url.endsWith('/detections'))return clone(fixtureDoc);
      if(url.endsWith('/reference'))return {status:'missing'};
      if(method==='POST'){const error=Error('synthetic write outcome unknown');
        if(uncertainStatus!==undefined)error.status=uncertainStatus;throw error;}
      throw Error('unexpected route '+url);
    };`);
  await v.element('btn-recognize-all').fire('click');
  const calls=plain(v.run('calls'));
  assert.equal(calls.filter(call=>call.method==='POST').length,1);
  assert.equal(calls.some(call=>call.url.includes('next.png')),false);
  assert.equal(v.run('state.workflow.lastBatchReport.canceled'),true);
  assert.equal(v.run('state.workflow.lastBatchReport.failed[0].uncertain'),true);
  assert.equal(v.run('state.doc'),null);
  assert.equal(v.run('state.imageName'),null);
  assert.equal(v.run('state.history.length'),0);
  assert.equal(v.run('saves.length'),0);
  assert.equal(v.run('state.busy'),false);
  assert.deepEqual(v.errors,[]);
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

test('legacy config without a default model uses improved builtin fixed defaults', async () => {
  const v = ui();
  v.run(`let routes = []; runModelPreview = async () => { throw Error('must not run a model'); };
    state.config.models.sam2.available = false; state.config.models.fusion_v2.available = false;
    state.workflow.customParams = {...DEFAULTS, min_value:77}; fillParams(state.workflow.customParams);
    jsonRequest = async (url, method='GET', body) => {
      if (url.endsWith('/reference')) return {status:'missing'};
      routes.push({url, body:clone(body)});
      return {...snapshot(), revision:10, counted:true, count_engine:ENHANCED_ENGINE, count_params:clone(body), params:clone(body)};
    };`);
  assert.equal(v.element('method-select').value, 'component_watershed_v1');
  await v.run('recognizeCurrent()');
  const routes = plain(v.run('routes'));
  assert.equal(routes.length, 1);
  assert.match(routes[0].url, /engine=component_watershed_v1/);
  assert.deepEqual(routes[0].body, defaults);
  assert.equal(v.run('state.workflow.customParams.min_value'), 77);
  assert.equal(v.run('state.history.length'), 1);
  assert.equal(v.run('saves.length'), 0);
});

test('custom batch recounts machine-only results with one captured recipe, skips human work and never retries 409', async () => {
  const v = ui(); custom(v);
  v.element('p-min-value').value = 190;
  v.run("parametersChanged('min_value'); applyCustomSettings()");
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
  v.run(`state.doc.notes = 'preserve edited note';
    flushEdits = async () => { state.saveQueues.get(keyFor()).revision = 31; };
    jsonRequest = async (url, method = 'GET', body) => {
      calls.push({url, method, body: body === undefined ? null : clone(body)});
      if (url.endsWith('/reference')) return {status: 'missing'};
      if (method === 'POST') return {...snapshot(), count_engine: ENHANCED_ENGINE, params: clone(body), count_params: clone(body), revision: 32};
      throw new Error('unexpected route');
    };`);
  const before = plain(v.run('snapshot()'));
  await answerConfirmation(v, v.run('recount()'), false);
  assert.equal(v.run("calls.filter(c => c.method === 'POST').length"), 0);
  assert.equal(v.run('state.history.length'), 0);
  assert.deepEqual(plain(v.run('snapshot()')), before);
  await answerConfirmation(v, v.run('recount()'), true);
  const posts = plain(v.run("calls.filter(c => c.method === 'POST')"));
  assert.equal(posts.length, 1);
  assert.equal(new URL(posts[0].url, 'http://synthetic').searchParams.get('expected_revision'), '31');
  assert.equal(v.element('confirmation-dialog').showModalCalls, 2);
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
  assert.equal(v.element('confirmation-dialog').showModalCalls || 0, 0);
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
    {name: 'unavailable', setup: 'state.config.models.sam2.available = false', hint: false, message: 'modelUnavailable'},
  ];
  for (const item of states) {
    v.run(`Object.assign(state.modelPreview, {loading: false, candidate: null, error: '', message: '', pendingApply: null, engine: SAM_ENGINE}); syncWorkflowRoute();
      state.doc.plate_manual = false; state.config.models.sam2.available = true;
      ${item.setup}; updateModelControls();`);
    assert.equal(panel.hidden, false, item.name);
    assert.equal(hint.hidden, !item.hint, item.name);
    assert.equal(v.element('btn-model-apply').hidden, item.name !== 'candidate', item.name);
    assert.equal(v.element('btn-model-discard').hidden, item.name === 'pending apply', item.name);
    if (item.message) assert.equal(v.element('model-message').textContent, item.message, item.name);
  }
  v.run('state.config.models.sam2.available = true; clearModelPreview(); updateModelControls()');
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
  assert.equal(v.element('btn-recognize-current').disabled, false);
  assert.deepEqual(plain(v.run('calls[0].body')), {source_sha256: 'a'.repeat(64), view: 'back'});
  assert.deepEqual(plain(v.run('snapshot()')), before);
  assert.equal(v.run('saves.length'), 0);
});

test('public Lite uses advertised improved builtin without requiring SAM', () => {
  const v = ui();
  v.run(`state.config.web_mode = true; state.config.models.sam2.available = false;
    syncWorkflowRoute(); updateControls();`);
  assert.equal(v.element('method-select').value, 'component_watershed_v1');
  assert.equal(v.element('btn-recognize-current').disabled, false);
  assert.equal(v.element('model-tools').hidden, true);
});

test('legacy builtin recognize-all needs no selection and guards loading and preview', async () => {
  const v = ui();
  v.run('emptyViewer(); updateControls();');
  assert.equal(v.run('state.imageName'), null);
  assert.equal(v.element('btn-recognize-all').hidden, false);
  assert.equal(v.element('btn-recognize-all').disabled, false);
  assert.equal(v.element('btn-recognize-current').disabled, true);
  for (const setup of [
    'state.loading = true', 'state.busy = true', 'state.modelPreview.loading = true',
    'state.modelPreview.pendingApply = {uncertain: true}',
    "$('mode-select').value = 'manual'",
    'state.modelPreview.candidate = {candidate_count: 1}',
    "state.modelPreview.engine = FUSION_V2_ENGINE; state.modelPreview.error = 'failed'",
  ]) {
    const blocked = ui();
    blocked.run(`emptyViewer(); let recognizeCalls = 0;
      window.WECFU_DEFAULT_BATCH = {recognizeBuiltin: async () => { recognizeCalls++; }};
      ${setup}; updateControls();`);
    assert.equal(blocked.element('btn-recognize-all').hidden, false, setup);
    assert.equal(blocked.element('btn-recognize-all').disabled, true, setup);
    await blocked.run('countAll()'); // Also check the action guard, independent of disabled DOM behavior.
    assert.equal(blocked.run('recognizeCalls'), 0, setup);
    assert.equal(blocked.run('calls.length'), 0, setup);
  }
  custom(v);
  assert.equal(v.element('btn-recognize-all').hidden, false);
});

test('legacy builtin recognize-all uses fixed defaults without selection', async () => {
  const v = ui();
  v.run(`emptyViewer(); let recognizedItems = [];
    countCustomBatch = async () => { throw new Error('custom batch must not run'); };
    state.imageList = [{name: 'first.png'}, {name: 'second.png'}];
    window.WECFU_DEFAULT_BATCH = {recognizeBuiltin: async item => {
      recognizedItems.push(clone(item));
      return {name: item.name, status: 'completed'};
    }}; updateControls();`);
  await v.element('btn-recognize-all').fire('click');
  assert.deepEqual(plain(v.run('recognizedItems.map(item => item.name)')), ['first.png', 'second.png']);
  assert.deepEqual(plain(v.run('recognizedItems.map(item => item.params)')), [defaults, defaults]);
  assert.equal(v.run('recognizedItems.every(item => item.engine === ENHANCED_ENGINE)'), true);
  assert.deepEqual(plain(v.run('state.workflow.lastBatchReport')), {
    total: 2, stopped: false,
    results: [{name: 'first.png', status: 'completed'}, {name: 'second.png', status: 'completed'}],
  });
  assert.equal(v.run('calls.length'), 0);
  assert.equal(v.run('saves.length'), 0);
  assert.equal(v.run('state.doc'), null);
  assert.equal(v.run('state.busy'), false);
  assert.equal(v.element('btn-stop-run').hidden, true);
  assert.deepEqual(v.errors, []);
});

test('real builtin batch preserves the fresh server before-state for Undo and uses fixed params', async () => {
  const v = ui();
  const fresh = {...plain(savedDoc), revision:42, counted:false, detections:[], machine_count_initial:0,
    count_engine:null, count_model:null, count_params:null, params:{...savedParams,min_value:211}};
  v.context.freshBatchBefore = fresh;
  v.run(`let batchDraws=0, listReloads=0;
    draw=()=>{batchDraws++;}; loadImages=async()=>{listReloads++;};
    const batchMarks=[{id:81,cx:101,cy:102,r:4,source:'cv',score:.98,accepted:true}];
    loadPlateImage=async url=>{calls.push({url,method:'GET',body:null});return {sourceHash:'a'.repeat(64)};};
    jsonRequest=async(url,method='GET',body)=>{
      calls.push({url,method,body:body===undefined?null:clone(body)});
      if(url.endsWith('/detections')) return clone(freshBatchBefore);
      if(url.endsWith('/reference')) return {status:'missing'};
      if(url.includes('/run?')) return {...clone(freshBatchBefore),revision:43,counted:true,
        detections:clone(batchMarks),machine_count_initial:1,reviewed:false,
        count_engine:ENHANCED_ENGINE,count_model:null,count_params:clone(body),params:clone(body)};
      throw Error('unexpected route '+url);
    };`);
  await v.element('btn-recognize-all').fire('click');
  const posts=plain(v.run("calls.filter(call=>call.method==='POST')"));
  assert.equal(posts.length,1);
  const query=new URL(posts[0].url,'http://synthetic').searchParams;
  assert.equal(query.get('engine'),'component_watershed_v1');
  assert.equal(query.get('only_unrecognized'),'true');
  assert.equal(query.get('protect_existing_edits'),'true');
  assert.equal(query.get('expected_revision'),'42');
  assert.equal(query.get('expected_image_sha256'),'a'.repeat(64));
  assert.deepEqual(posts[0].body,defaults);
  assert.equal(v.run('state.detections[0].id'),81);
  assert.equal(v.run('state.doc.reviewed'),false);
  assert.equal(v.run('state.doc.count_engine'),'component_watershed_v1');
  assert.deepEqual(plain(v.run('state.history[0]')),fresh);
  assert.equal(v.run('batchDraws'),1); assert.equal(v.run('listReloads'),1);
  assert.equal(v.run('saves.length'),0);
  v.run('undo()');
  assert.deepEqual(plain(v.run('state.detections')),fresh.detections);
  assert.deepEqual(plain(v.run('state.doc.params')),fresh.params);
  assert.equal(v.run('state.doc.counted'),false);
  assert.equal(v.run('state.saveQueues.get(keyFor()).revision'),43);
  assert.equal(v.run('state.history.length'),0);
  assert.deepEqual(plain(v.run('saves[0].detections')),[]);
  assert.deepEqual(v.errors,[]);
});

test('wired stop lets the active batch item settle and never starts the next item', async () => {
  const v = ui();
  const started = new Promise(resolve => { v.context.batchItemStarted = resolve; });
  v.run(`emptyViewer(); let batchNames = [], settleBatchItem;
    state.imageList = [{name: 'first.png'}, {name: 'second.png'}];
    window.WECFU_DEFAULT_BATCH = {recognizeBuiltin: async item => {
      batchNames.push(item.name); batchItemStarted();
      return new Promise(resolve => { settleBatchItem = resolve; });
    }}; updateControls();`);
  const running = v.element('btn-recognize-all').fire('click');
  await started;
  await v.element('btn-stop-run').fire('click');
  assert.equal(v.run('state.busy'), true);
  assert.equal(v.run('state.batchRun.report.results.length'), 0);
  assert.deepEqual(plain(v.run('batchNames')), ['first.png']);
  v.run("settleBatchItem({name: 'first.png', status: 'completed'})");
  await running;
  assert.deepEqual(plain(v.run('batchNames')), ['first.png']);
  assert.deepEqual(plain(v.run('state.workflow.lastBatchReport')), {
    total: 2, stopped: true, results: [{name: 'first.png', status: 'completed'}],
  });
  assert.match(v.element('batch-report-summary').textContent, /countStopped.*1 countCompleted.*1 batchRemaining/);
  assert.equal(v.run('state.busy'), false);
  assert.equal(v.element('btn-stop-run').hidden, true);
  assert.deepEqual(v.errors, []);
});

test('failed and uncertain outcomes are reported separately from successful recognition and uncertainty clears stale viewer', async () => {
  const v = ui();
  v.run(`let emptiedViewers = 0; const originalEmptyViewer = emptyViewer;
    emptyViewer = () => { emptiedViewers++; originalEmptyViewer(); };
    state.imageList = [{name: 'failed.png'}, {name: 'first.png'}, {name: 'untouched.png'}];
    window.WECFU_DEFAULT_BATCH = {recognizeBuiltin: async item => item.name === 'failed.png'
      ? {name: item.name, status: 'failed', reason: 'synthetic inference failure'}
      : {name: item.name, status: 'uncertain', reason: 'synthetic adoption response lost', stop: true}};`);
  await v.element('btn-recognize-all').fire('click');
  const report = plain(v.run('state.workflow.lastBatchReport'));
  assert.deepEqual(report.results.map(item => [item.name, item.status]), [['failed.png', 'failed'], ['first.png', 'uncertain']]);
  assert.equal(report.stopped, true);
  assert.equal(report.total, 3);
  assert.match(v.element('batch-report-summary').textContent, /countStopped.*0 countCompleted.*2 customBatchFailed.*1 batchRemaining/);
  assert.equal(v.element('status').classList.contains('error'), true);
  assert.match(v.element('batch-report-items').children[1].textContent, /batchUncertain/);
  assert.equal(v.run('emptiedViewers'), 1);
  assert.equal(v.run('state.imageName'), null);
  assert.equal(v.run('state.doc'), null);
  assert.equal(v.run('state.img'), null);
  assert.equal(v.run('state.history.length'), 0);
  assert.equal(v.run('saves.length'), 0);
  assert.deepEqual(v.errors, []);
});

test('a failed batch item cannot produce a success-only summary when the queue finishes normally', async () => {
  const v = ui(), before = plain(v.run('snapshot()'));
  v.run(`window.WECFU_DEFAULT_BATCH = {recognizeBuiltin: async item => ({name: item.name,
    status: 'failed', reason: 'synthetic failure'})};`);
  await v.run('countAll()');
  assert.equal(v.run('state.workflow.lastBatchReport.stopped'), false);
  assert.match(v.element('batch-report-summary').textContent, /0 countCompleted.*1 customBatchFailed/);
  assert.equal(v.element('status').classList.contains('error'), true);
  assert.deepEqual(plain(v.run('snapshot()')), before);
  assert.equal(v.run('saves.length'), 0);
});

test('completed batch adoption with changed displayed image bytes clears the viewer instead of drawing mismatched marks', async () => {
  const v = ui();
  v.run(`let drawnMarks = [], emptiedViewers = 0; draw = () => { drawnMarks.push(clone(state.detections)); };
    const originalEmptyViewer = emptyViewer;
    emptyViewer = () => { emptiedViewers++; originalEmptyViewer(); };
    window.WECFU_DEFAULT_BATCH = {recognizeBuiltin: async item => ({name: item.name, status: 'completed',
      hash: 'f'.repeat(64), before: clone(fixtureDoc), doc: {...clone(fixtureDoc), revision: 8,
        detections: [{id: 99, cx: 10, cy: 10, r: 4, source: 'cv'}]}})};`);
  await v.run('countAll()');
  assert.equal(v.run('emptiedViewers'), 1);
  // emptyViewer cancels a gesture (which can redraw old marks), but must never
  // adopt/draw the new marks against the mismatched displayed source.
  assert.equal(v.run('drawnMarks.some(marks => marks.some(mark => mark.id === 99))'), false);
  assert.equal(v.run('state.doc'), null);
  assert.equal(v.run('state.imageSourceHash'), null);
  assert.equal(v.run('state.history.length'), 0);
  assert.equal(v.run('saves.length'), 0);
  assert.equal(v.run('state.workflow.lastBatchReport.results[0].status'), 'completed');
});

test('bulk selection is independent of the displayed photo and never records a human view or edit', async () => {
  const v = ui(), before = plain(v.run('snapshot()'));
  v.run(`state.imageList = [{name:'first.png'}, {name:'second.png'}, {name:'third.png'}];
    let selectedViews = []; selectImage = async name => selectedViews.push(name); renderImageList();`);
  await v.element('btn-bulk-select').fire('click');
  const rows = v.element('image-list').children;
  await rows[1].fire('click');
  assert.equal(rows[1].attributes.get('aria-checked'), 'true');
  assert.equal(v.run('state.imageName'), 'first.png');
  assert.deepEqual(plain(v.run('selectedViews')), []);
  assert.deepEqual(plain(v.run('snapshot()')), before);
  assert.equal(v.run('saves.length'), 0);
  assert.equal(v.run('calls.length'), 0);
  await v.element('btn-bulk-all').fire('click');
  assert.equal(v.run('state.bulkSelection.names.size'), 3);
  await v.element('btn-bulk-all').fire('click');
  assert.equal(v.run('state.bulkSelection.names.size'), 0);
  assert.equal(v.element('btn-bulk-delete').disabled, true);
  await v.element('btn-bulk-select').fire('click');
  assert.equal(v.run('state.bulkSelection.enabled'), false);
  assert.equal(rows[1].attributes.has('aria-checked'), false);
});

test('one select-all control toggles empty, partial and full selection with matching checkbox state', async () => {
  const v = ui();
  v.run(`state.imageList = [{name:'first.png'}, {name:'second.png'}, {name:'third.png'}];
    renderImageList(); toggleBulkSelection();`);
  const all = v.element('btn-bulk-all'), rows = v.element('image-list').children;
  assert.equal(all.attributes.get('aria-checked'), 'false');
  assert.equal(all.disabled, false);
  await all.fire('click');
  assert.equal(all.attributes.get('aria-checked'), 'true');
  assert.equal(all.title, 'selectNoImages');
  assert.equal(all.disabled, false, 'full selection must remain actionable to clear it');
  assert.ok(rows.every(row => row.attributes.get('aria-checked') === 'true'));
  await rows[1].fire('click');
  assert.equal(all.attributes.get('aria-checked'), 'mixed');
  assert.equal(all.title, 'selectAllImages');
  assert.equal(v.run('state.bulkSelection.names.size'), 2);
  await all.fire('click');
  assert.equal(all.attributes.get('aria-checked'), 'true');
  assert.equal(v.run('state.bulkSelection.names.size'), 3);
  await all.fire('click');
  assert.equal(all.attributes.get('aria-checked'), 'false');
  assert.equal(v.run('state.bulkSelection.names.size'), 0);
  assert.ok(rows.every(row => row.attributes.get('aria-checked') === 'false'));
  assert.equal(v.element('btn-bulk-delete').disabled, true);
  assert.equal(v.run('state.bulkSelection.enabled'), true, 'clearing keeps selection mode open');
  assert.equal(v.run('calls.length'), 0);
  assert.equal(v.run('saves.length'), 0);
});

test('select-all is empty and disabled with no photos or outside selection mode', async () => {
  const v = ui();
  v.run('renderImageList();');
  assert.equal(v.element('btn-bulk-all').disabled, true);
  await v.element('btn-bulk-all').fire('click');
  assert.equal(v.run('state.bulkSelection.names.size'), 0);
  v.run('toggleBulkSelection(); state.imageList = []; updateBulkSelectionControls();');
  assert.equal(v.element('btn-bulk-all').attributes.get('aria-checked'), 'false');
  assert.equal(v.element('btn-bulk-all').disabled, true);
  await v.element('btn-bulk-all').fire('click');
  assert.equal(v.run('state.bulkSelection.names.size'), 0);
  assert.equal(v.element('bulk-image-tools').hidden, true);
});

test('select-all cannot change selection while recognition, navigation or saving is busy', async () => {
  for (const guard of ['state.busy = true', 'state.loading = true', 'state.crop = {}',
    'state.modelPreview.loading = true', 'state.modelPreview.pendingApply = {}']) {
    const v = ui();
    v.run(`state.imageList = [{name:'first.png'}, {name:'second.png'}]; renderImageList();
      toggleBulkSelection(); toggleBulkImage('first.png'); ${guard}; updateBulkSelectionControls();`);
    assert.equal(v.element('btn-bulk-all').disabled, true, guard);
    assert.equal(v.element('btn-bulk-all').attributes.get('aria-checked'), 'mixed', guard);
    await v.element('btn-bulk-all').fire('click');
    assert.deepEqual(plain(v.run('Array.from(state.bulkSelection.names)')), ['first.png'], guard);
    assert.equal(v.run('calls.length'), 0, guard);
  }
});

test('select-all markup has a leading decorative indicator and one accessible checkbox control', () => {
  const html = fs.readFileSync(path.join(__dirname, '../wecfu/server/static/index.html'), 'utf8');
  assert.match(html, /id="btn-bulk-all"[^>]*role="checkbox"[^>]*aria-checked="false"><span class="bulk-all-indicator" aria-hidden="true"><\/span><span data-i18n="selectAllImages">/);
  assert.doesNotMatch(html, /id="btn-bulk-none"/);
});

test('cancelled bulk deletion sends no deletion, preserves selection and saves no state', async () => {
  const v = ui();
  v.run(`state.imageList = [{name:'first.png'}, {name:'second.png'}]; renderImageList(); toggleBulkSelection(); selectBulkImages(true);
    let flushed = 0; flushEdits = async () => { flushed++; };`);
  await answerConfirmation(v, v.element('btn-bulk-delete').fire('click'), false);
  assert.equal(v.run('calls.length'), 0);
  assert.equal(v.run('flushed'), 0);
  assert.equal(v.run('state.bulkSelection.names.size'), 2);
  assert.equal(v.run('state.imageList.length'), 2);
});

test('bulk deletion flushes first, removes only the chosen photos sequentially and preserves unchosen view', async () => {
  const v = ui(), before = plain(v.run('snapshot()'));
  v.run(`state.imageList = [{name:'first.png'}, {name:'a & b.png'}, {name:'third.png'}]; renderImageList();
    toggleBulkSelection(); toggleBulkImage('a & b.png'); toggleBulkImage('third.png');
    let order = []; flushEdits = async () => order.push('flush');
    jsonRequest = async (url, method) => { if (method !== 'DELETE') throw Error('wrong method'); order.push(url); return {ok:true}; };`);
  await answerConfirmation(v, v.element('btn-bulk-delete').fire('click'), true);
  assert.deepEqual(plain(v.run('order')), ['flush', '/api/batch/synthetic/image/a%20%26%20b.png', '/api/batch/synthetic/image/third.png']);
  assert.deepEqual(plain(v.run('state.imageList')), [{name:'first.png'}]);
  assert.equal(v.run('state.imageName'), 'first.png');
  assert.deepEqual(plain(v.run('snapshot()')), before);
  assert.equal(v.run('state.bulkSelection.enabled'), false);
  assert.deepEqual(plain(v.run('state.bulkSelection.lastReport')), {removed:['a & b.png','third.png'],failed:[]});
});

test('deleting the displayed photo selects a remaining photo; failed removals stay selected and are reported', async () => {
  const v = ui();
  v.run(`state.imageList = [{name:'first.png'}, {name:'fail.png'}, {name:'keep.png'}]; renderImageList();
    toggleBulkSelection(); toggleBulkImage('first.png'); toggleBulkImage('fail.png');
    let opened = []; selectImage = async name => opened.push(name);
    jsonRequest = async (url, method) => { if (url.endsWith('/fail.png')) throw Object.assign(new Error('synthetic failure'),{status:500}); return {ok:true}; };`);
  await answerConfirmation(v, v.element('btn-bulk-delete').fire('click'), true);
  assert.equal(v.run('state.doc'), null);
  assert.equal(v.run("state.saveQueues.has('synthetic\\nfirst.png')"), false);
  assert.deepEqual(plain(v.run('opened')), ['fail.png']);
  assert.deepEqual(plain(v.run('state.imageList.map(i=>i.name)')), ['fail.png','keep.png']);
  assert.deepEqual(plain(v.run('Array.from(state.bulkSelection.names)')), ['fail.png']);
  assert.equal(v.element('status').classList.contains('error'), true);
  assert.match(v.element('status').title, /fail.png: synthetic failure/);
});

test('all deleted or already absent photos leave an empty viewer; no retry on uncertain deletion', async () => {
  const v = ui();
  v.run(`renderImageList(); toggleBulkSelection(); selectBulkImages(true);
    jsonRequest = async (url, method) => { calls.push({url,method}); throw Object.assign(new Error('already absent'), {status:404}); };`);
  await answerConfirmation(v, v.element('btn-bulk-delete').fire('click'), true);
  assert.equal(v.run('state.imageList.length'), 0);
  assert.equal(v.run('state.doc'), null);
  assert.equal(v.element('bulk-image-tools').hidden, true);
  assert.equal(v.run('calls.length'), 1);
  assert.equal(v.run('state.bulkSelection.lastReport.removed.length'), 1);
});

test('pending saves, recognition and verification contexts cannot trigger bulk deletion', async () => {
  for (const guard of ['state.busy = true', 'state.loading = true', 'state.crop = {}',
    'state.modelPreview.loading = true', 'state.modelPreview.pendingApply = {}', 'state.review.requested = true']) {
    const v = ui();
    v.run('renderImageList(); toggleBulkSelection(); selectBulkImages(true); ' + guard);
    await v.run('removeSelectedImages()');
    assert.equal(v.run('calls.length'), 0, guard);
    assert.equal(v.element('confirmation-dialog').open, false, guard);
  }
  const v = ui();
  v.run(`renderImageList(); toggleBulkSelection(); selectBulkImages(true); flushEdits = async () => { throw Error('save failed'); };`);
  await assert.rejects(answerConfirmation(v, v.run('removeSelectedImages()'), true), /save failed/);
  assert.equal(v.run('state.busy'), false);
  assert.equal(v.run('calls.length'), 0);
  assert.equal(v.run('state.bulkSelection.names.size'), 1);
});

test('changing batch or refreshing removed names cannot leak stale bulk selection into another batch', () => {
  const v = ui();
  v.run('renderImageList(); toggleBulkSelection(); selectBulkImages(true); state.batch = "other"; updateBulkSelectionControls();');
  assert.equal(v.run('state.bulkSelection.enabled'), false);
  assert.equal(v.run('state.bulkSelection.names.size'), 0);
  v.run(`toggleBulkSelection(); selectBulkImages(true); state.imageList = [{name:'other.png'}]; updateBulkSelectionControls();`);
  assert.equal(v.run('state.bulkSelection.names.size'), 0);
  assert.equal(v.element('btn-bulk-delete').disabled, true);
});

test('in-app confirmation defaults to cancel, blocks background keys/edits and restores trigger focus', async () => {
  const v = ui(), trigger = v.element('btn-bulk-delete');
  v.document.activeElement = trigger;
  v.run(`renderImageList(); toggleBulkSelection(); selectBulkImages(true);
    moveSelection = async delta => moves.push(delta);`);
  const before = plain(v.run('snapshot()'));
  const pending = trigger.fire('click');
  assert.equal(v.element('confirmation-dialog').open, true);
  assert.equal(v.document.activeElement, v.element('btn-confirm-cancel'));
  assert.equal(v.run('modalOpen()'), true);
  assert.equal(v.run('editable()'), false);
  await v.key({key: 'ArrowRight', preventDefault() {}});
  await v.key({key: 'Enter', preventDefault() {}});
  v.run('clearAll(); toggleAllBulkImages();');
  assert.equal(v.run('moves.length'), 0);
  assert.equal(v.run('calls.length'), 0);
  assert.equal(v.run('state.bulkSelection.names.size'), 1);
  assert.deepEqual(plain(v.run('snapshot()')), before);
  let prevented = false;
  await v.key({key: 'Escape', preventDefault() { prevented = true; }});
  await pending;
  assert.equal(prevented, true);
  assert.equal(v.element('confirmation-dialog').open, false);
  assert.equal(v.document.activeElement, trigger);
  assert.equal(v.run('calls.length'), 0);
  assert.equal(v.run('saves.length'), 0);
});

test('modal confirmation is safe text, ignores duplicate requests and does not cancel a new decision on a late close event', async () => {
  const v = ui();
  const first = v.run(`confirmAction({title: 'Delete', message: '<img src=x onerror=bad()>\\nphoto.png'})`);
  assert.equal(v.element('confirmation-message').textContent, '<img src=x onerror=bad()>\nphoto.png');
  assert.equal(v.element('confirmation-message').innerHTML, undefined);
  assert.equal(await v.run(`confirmAction({title: 'Second', message: 'must not replace first'})`), false);
  assert.equal(v.element('confirmation-title').textContent, 'Delete');
  await v.element('btn-confirm-cancel').fire('click');
  assert.equal(await first, false);
  const next = v.run(`confirmAction({title: 'Next', message: 'New decision'})`);
  await v.element('confirmation-dialog').fire('close'); // queued from the previous close()
  assert.equal(v.element('confirmation-dialog').open, true);
  assert.equal(v.run('Boolean(pendingConfirmation)'), true);
  await v.element('btn-confirm-accept').fire('click');
  await v.element('btn-confirm-accept').fire('click');
  assert.equal(await next, true);
  assert.equal(v.run('Boolean(pendingConfirmation)'), false);
});

test('native dialog cancel, unexpected close and failure to open all fail closed', async () => {
  const v = ui();
  for (const kind of ['cancel', 'close']) {
    const pending = v.run('removeImage()');
    if (kind === 'close') v.element('confirmation-dialog').close();
    await v.element('confirmation-dialog').fire(kind, {preventDefault() {}});
    await pending;
    assert.equal(v.run('calls.length'), 0);
    assert.equal(v.element('confirmation-dialog').open, false);
  }
  v.element('confirmation-dialog').showModal = () => { throw Error('dialog unavailable'); };
  await assert.rejects(v.run('removeImage()'), /dialog unavailable/);
  assert.equal(v.run('Boolean(pendingConfirmation)'), false);
  assert.equal(v.run('calls.length'), 0);
  assert.equal(v.run('state.imageName'), 'first.png');
});

test('single image deletion waits for an explicit dialog decision and flushes exactly once before deletion', async () => {
  const v = ui();
  v.run(`let order = [], opened = [];
    flushEdits = async () => order.push('flush');
    jsonRequest = async (url, method) => { order.push({url,method}); return {ok:true}; };
    loadImages = async () => { state.imageList = [{name:'remaining.png'}]; };
    selectImage = async name => opened.push(name);`);
  const pending = v.run('removeImage()');
  assert.deepEqual(plain(v.run('order')), []);
  await v.run('removeImage()'); // duplicate invocation cannot consume the decision
  assert.equal(v.element('confirmation-dialog').showModalCalls, 1);
  await answerConfirmation(v, pending, true);
  assert.deepEqual(plain(v.run('order')), ['flush', {url:'/api/batch/synthetic/image/first.png',method:'DELETE'}]);
  assert.deepEqual(plain(v.run('opened')), ['remaining.png']);
  assert.equal(v.run('state.doc'), null);
  assert.equal(v.run('state.busy'), false);
});

test('confirmation cannot authorize deletion after its batch, selection, or displayed document changes', async () => {
  for (const change of ['state.batch = "other"', 'state.bulkSelection.names.clear()', 'state.loading = true']) {
    const v = ui();
    v.run('renderImageList(); toggleBulkSelection(); selectBulkImages(true);');
    const pending = v.run('removeSelectedImages()');
    v.run(change);
    await answerConfirmation(v, pending, true);
    assert.equal(v.run('calls.length'), 0, change);
  }
  for (const change of ['state.batch = "other"', 'state.doc = {...state.doc}', 'state.imageName = "other.png"']) {
    const v = ui(), pending = v.run('removeImage()');
    v.run(change);
    await answerConfirmation(v, pending, true);
    assert.equal(v.run('calls.length'), 0, change);
  }
});

test('protected recount discards a dialog decision if the displayed image source changes while awaiting it', async () => {
  const v = ui(); custom(v);
  v.run(`state.doc.notes = 'manual note';
    jsonRequest = async (url, method='GET') => {calls.push({url,method});return {status:'missing'};};`);
  const pending = v.run('recount()');
  for (let turn = 0; turn < 20 && !v.element('confirmation-dialog').open; turn++) await Promise.resolve();
  assert.equal(v.element('confirmation-dialog').open, true);
  v.run("state.imageSourceHash = 'f'.repeat(64)");
  await answerConfirmation(v, pending, true);
  assert.equal(v.run("calls.filter(c=>c.method === 'POST').length"), 0);
  assert.equal(v.run('state.history.length'), 0);
  assert.equal(v.run('state.busy'), false);
});

for (const locale of ['en', 'zh-CN', 'fr', 'ru']) {
  test(`${locale} confirmation labels and all three protection messages are localized`, async () => {
    const v = ui(locale), translations = v.window.WECFU_I18N;
    for (const [title, message] of [['deleteSelectedImages','bulkDeleteConfirm'], ['removeImage','removeImageConfirm'], ['recognizeCurrent','customProtectedConfirm']]) {
      assert.ok(Object.hasOwn(translations.I18N[locale], title), title);
      assert.ok(Object.hasOwn(translations.I18N[locale], message), message);
      v.context.confirmTitle = title; v.context.confirmMessage = message;
      const pending = v.run(`confirmAction({title:t(confirmTitle),message:t(confirmMessage).replace('{count}',2).replace('{name}','synthetic.png')})`);
      assert.equal(v.element('confirmation-title').textContent, translations.t(title));
      assert.equal(v.element('btn-confirm-accept').textContent, translations.t(title));
      assert.equal(v.element('btn-confirm-cancel').textContent, translations.t('exportCancel'));
      assert.doesNotMatch(v.element('confirmation-message').textContent, /\{count\}|\{name\}/);
      await answerConfirmation(v, pending, false);
    }
  });
}

test('confirmation markup uses native modal semantics with an accessible name, safe message and cancel-first buttons', () => {
  const html = fs.readFileSync(path.join(__dirname, '../wecfu/server/static/index.html'), 'utf8');
  assert.match(html, /<dialog id="confirmation-dialog" aria-labelledby="confirmation-title" aria-describedby="confirmation-message">/);
  assert.match(html, /id="btn-confirm-cancel" type="button" autofocus/);
  assert.match(html, /id="btn-confirm-accept" type="button"/);
  assert.ok(html.indexOf('id="btn-confirm-cancel"') < html.indexOf('id="btn-confirm-accept"'));
  assert.doesNotMatch(source, /\bwindow\.confirm\s*\(/);
});

test('unified path import declares unknown rather than inventing main/blank/back metadata', async()=>{
  const v=ui(),before=plain(v.run('snapshot()'));
  v.run(`$('import-view').value='main'; jsonRequest=async(url,method,body)=>{
    calls.push({url,method,body:clone(body)});return {batch:'synthetic'};
  };`);
  await v.run("ingestPath('/synthetic/folder')");
  assert.deepEqual(plain(v.run('calls')), [{url:'/api/ingest',method:'POST',body:{paths:['/synthetic/folder'],view:'unknown',batch:'synthetic'}}]);
  assert.deepEqual(plain(v.run('snapshot()')),before);
  assert.equal(v.element('source-view-metadata').hidden,true);
  const html=fs.readFileSync(path.join(__dirname,'../wecfu/server/static/index.html'),'utf8');
  assert.equal(html.includes('id="import-view"'),false);
});

test('unified file import declares unknown and does not request inference automatically', async()=>{
  const v=ui();
  v.context.FormData=class {constructor(){this.entries=[];}append(k,value){this.entries.push([k,value]);}};
  v.context.XMLHttpRequest=class {
    constructor(){this.upload={addEventListener(){}};this.status=200;this.responseText=JSON.stringify({batch:'synthetic'});}
    open(method,url){this.method=method;this.url=url;}
    send(data){v.context.uploaded={method:this.method,url:this.url,entries:data.entries};this.onload();}
  };
  await v.run("uploadFiles([{name:'synthetic.jpg'},{name:'skip.txt'}])");
  assert.deepEqual(plain(v.context.uploaded),{method:'POST',url:'/api/upload',entries:[['batch','synthetic'],['view','unknown'],['files',{name:'synthetic.jpg'}]]});
  assert.equal(v.run('calls.length'),0);
  assert.equal(v.run('saves.length'),0);
});

test('current default and custom recount bind to displayed SHA and preserve work on source conflict', async()=>{
  for(const profile of ['default','custom']) {
    const v=ui();if(profile==='custom')custom(v);
    const before=plain(v.run('snapshot()'));
    v.run(`jsonRequest=async(url,method='GET',body)=>{
      calls.push({url,method,body:body===undefined?null:clone(body)});
      if(url.endsWith('/reference'))return {status:'missing'};
      throw Object.assign(Error('source changed'),{status:409});
    };`);
    await assert.rejects(v.run('recount()'),/source changed/);
    const posts=plain(v.run("calls.filter(call=>call.method==='POST')"));
    assert.equal(posts.length,1);
    assert.equal(new URL(posts[0].url,'http://synthetic').searchParams.get('expected_image_sha256'),'a'.repeat(64));
    assert.deepEqual(plain(v.run('snapshot()')),before);
    assert.equal(v.run('state.history.length'),0);
    assert.equal(v.run('saves.length'),0);
    v.run("state.imageSourceHash=null;calls=[];");
    await assert.rejects(v.run('recount()'),/recognitionSourceUnavailable/);
    assert.equal(v.run('calls.length'),0);
  }
});

test('custom batch binds fresh source bytes and never draws result on a stale displayed image', async()=>{
  const v=ui();custom(v);
  v.run(`let paintedMarks=[];draw=()=>paintedMarks.push(clone(state.detections));
    loadPlateImage=async url=>{calls.push({url,method:'GET'});return {sourceHash:'b'.repeat(64)};};
    jsonRequest=async(url,method='GET',body)=>{
      calls.push({url,method,body:body===undefined?null:clone(body)});
      if(url.endsWith('/detections'))return clone(fixtureDoc);
      if(url.endsWith('/reference'))return {status:'missing'};
      return {...clone(fixtureDoc),revision:8,count_engine:ENHANCED_ENGINE,count_params:clone(body),
        detections:[{id:999,cx:120,cy:120,r:5,source:'cv'}]};
    };`);
  await v.run('countCustomBatch()');
  const post=plain(v.run("calls.find(call=>call.method==='POST')"));
  assert.equal(new URL(post.url,'http://synthetic').searchParams.get('expected_image_sha256'),'b'.repeat(64));
  assert.equal(v.run('paintedMarks.some(marks=>marks.some(mark=>mark.id===999))'),false);
  assert.equal(v.run('state.doc'),null);
  assert.equal(v.run('state.imageSourceHash'),null);
  assert.equal(v.run('state.history.length'),0);
  assert.equal(v.run('saves.length'),0);
  assert.deepEqual(plain(v.run('state.workflow.lastBatchReport.completed')),['first.png']);
});

// Desktop export acceptance uses only a synthetic response and mocked native
// boundary; actual filesystem/native-dialog acceptance is performed on the app.
function exportFixture({native = true, locale = 'en', prepare = {id: 'export-1', path: '/Users/test/成果 & <1>.csv'}, failAt} = {}) {
  const view = ui(locale), commands = [], downloads = [], timers = new Map();
  let nextTimer = 0;
  view.context.setTimeout = (fn, ms) => { const id = ++nextTimer; timers.set(id, {fn, ms}); return id; };
  view.context.clearTimeout = id => timers.delete(id);
  view.context.Blob = Blob;
  view.context.URL = {createObjectURL: () => 'blob:http://127.0.0.1:1234/export-1', revokeObjectURL() {}};
  const originalElement = view.document.createElement;
  view.document.createElement = tag => {
    const element = originalElement(tag);
    element.click = () => downloads.push({href: element.href, download: element.download});
    element.remove = () => {};
    return element;
  };
  view.document.body = view.node('body', 'BODY');
  view.window.__WECFU_DESKTOP_EXPORT__ = native;
  view.window.__WECFU_DESKTOP_PLATFORM__ = 'macos';
  view.window.__TAURI__ = {core: {invoke: async (command, args) => {
    commands.push({command, args: plain(args)});
    if (failAt === command) throw new Error('synthetic native failure');
    if (command === 'desktop_export_prepare') return prepare;
  }}};
  view.context.exportFetchFailure = failAt === 'fetch';
  view.context.syntheticBlob = new Blob(['name,count\nsynthetic,2\n']);
  view.run(`request = async url => {
    calls.push({url});
    if (exportFetchFailure) throw new Error('synthetic export failure');
    return {headers: {get: () => null}, blob: async () => syntheticBlob};
  }; openExportModal('csv');`);
  const complete = detail => view.window.dispatchEvent({type: 'wecfu:desktop-export', detail});
  return {...view, commands, downloads, timers, complete};
}
async function exportDownloaded(view) {
  for (let turn = 0; turn < 30 && !view.downloads.length; turn++) await Promise.resolve();
  assert.equal(view.downloads.length, 1);
}

test('desktop Save As cancellation makes no export request or download and resets controls', async () => {
  const v = exportFixture({prepare: null});
  assert.equal(v.element('export-browser-location').hidden, true);
  assert.equal(v.element('export-desktop-location').hidden, false);
  await v.run('doExport()');
  assert.deepEqual(plain(v.run('calls')), []);
  assert.equal(v.downloads.length, 0);
  assert.equal(v.commands.length, 1);
  assert.equal(v.commands[0].command, 'desktop_export_prepare');
  assert.equal(v.element('status').textContent, 'Export cancelled');
  assert.equal(v.element('export-backdrop').hidden, false);
  assert.equal(v.element('btn-export-confirm').disabled, false);
  assert.equal(v.run('state.busy'), false);
});

for (const failAt of ['desktop_export_prepare', 'fetch', 'desktop_export_arm']) {
  test(`desktop ${failAt} failure cannot report a saved file`, async () => {
    const v = exportFixture({failAt});
    await assert.rejects(v.run('doExport()'));
    assert.equal(v.element('export-receipt').hidden, true);
    assert.equal(v.element('export-backdrop').hidden, false);
    assert.equal(v.run('desktopExportReceipt'), null);
    assert.equal(v.run('state.busy'), false);
    assert.equal(v.downloads.length, 0);
    assert.notEqual(v.element('status').textContent, 'Export saved');
    assert.equal(v.commands.some(c => c.command === 'desktop_export_cancel'), failAt !== 'desktop_export_prepare');
  });
}

for (const locale of ['en', 'zh-CN', 'fr', 'ru']) {
  test(`desktop ${locale} shows exact saved path and reveal only after native completion`, async () => {
    const v = exportFixture({locale});
    const path = '/Users/test/成果 & <1>.csv';
    const pending = v.run('doExport()');
    await exportDownloaded(v);
    assert.equal(v.element('export-receipt').hidden, true);
    assert.equal(v.run('state.busy'), true);
    v.complete({id: 'unrelated', status: 'saved', path});
    await Promise.resolve();
    assert.equal(v.run('desktopExportReceipt'), null);
    v.complete({id: 'export-1', status: 'saved', path});
    await pending;
    assert.equal(v.element('export-backdrop').hidden, false, 'keep a discoverable receipt');
    assert.equal(v.element('export-form-fields').hidden, true);
    assert.equal(v.element('export-receipt').hidden, false);
    assert.equal(v.element('export-saved-path').textContent, path);
    assert.equal(v.element('btn-export-confirm').hidden, true);
    assert.equal(v.element('btn-export-cancel').disabled, false);
    assert.equal(v.run('state.busy'), false);
    const translations = v.window.WECFU_I18N;
    assert.equal(v.element('status').textContent, translations.t('exportSaved'));
    assert.equal(v.element('btn-export-reveal').textContent, translations.t('exportRevealFinder'));
    await v.run('revealDesktopExport()');
    assert.deepEqual(v.commands.at(-1), {command: 'desktop_export_reveal', args: {id: 'export-1'}});
    assert.equal(v.commands.some(c => c.command === 'desktop_export_cancel'), false);
    assert.equal([...v.timers.values()].some(timer => timer.ms === 15 * 60 * 1000), false, 'completion timeout must be removed');
    v.run("openExportModal('zip')");
    assert.equal(v.element('export-receipt').hidden, true);
    assert.equal(v.element('export-form-fields').hidden, false);
    assert.equal(v.element('btn-export-confirm').hidden, false);
    assert.equal(v.run('desktopExportReceipt'), null);
  });
}

for (const outcome of ['error', 'different-path', 'timeout']) {
  test(`desktop ${outcome} completion remains unsaved and allows retry`, async () => {
    const v = exportFixture(), pending = v.run('doExport()');
    await exportDownloaded(v);
    if (outcome === 'timeout') [...v.timers.values()].find(timer => timer.ms === 15 * 60 * 1000).fn();
    else v.complete({id: 'export-1', status: outcome === 'error' ? 'error' : 'saved', path: '/wrong/path.csv'});
    await assert.rejects(pending, outcome === 'timeout' ? /not confirmed/ : /could not be saved/);
    assert.equal(v.run('desktopExportReceipt'), null);
    assert.equal(v.element('export-receipt').hidden, true);
    assert.equal(v.element('btn-export-confirm').disabled, false);
    assert.equal(v.commands.at(-1).command, 'desktop_export_cancel');
  });
}

test('desktop bridge unavailability never silently falls back to browser downloads', async () => {
  const v = exportFixture();
  delete v.window.__TAURI__;
  await assert.rejects(v.run('doExport()'), /Saving is unavailable/);
  assert.equal(v.downloads.length, 0);
  assert.deepEqual(plain(v.run('calls')), []);
  assert.equal(v.run('state.busy'), false);
});

test('browser retains download flow and does not claim the download has been saved', async () => {
  const v = exportFixture({native: false});
  assert.equal(v.element('export-browser-location').hidden, false);
  assert.equal(v.element('export-desktop-location').hidden, true);
  await v.run('doExport()');
  assert.equal(v.commands.length, 0);
  assert.equal(v.downloads.length, 1);
  assert.equal(v.element('status').textContent, 'Download started — check your browser downloads');
  assert.equal(v.element('export-backdrop').hidden, true);
  assert.equal(v.run('desktopExportReceipt'), null);
});

test('desktop native save ignores any stale browser folder handle', async () => {
  const v = exportFixture();
  v.window.showDirectoryPicker = () => { throw new Error('browser folder picker must not be used'); };
  v.context.forbiddenFolder = {getFileHandle() { throw new Error('stale browser folder must not receive the export'); }};
  v.run('state.saveDirHandle = forbiddenFolder');
  const pending = v.run('doExport()');
  await exportDownloaded(v);
  v.complete({id: 'export-1', status: 'saved', path: '/Users/test/成果 & <1>.csv'});
  await pending;
  assert.equal(v.element('status').textContent, 'Export saved');
});

test('browser chosen-folder flow closes the writable before reporting saved', async () => {
  const v = exportFixture({native: false}), writes = [];
  let closed = false;
  v.window.showDirectoryPicker = () => {};
  v.context.browserFolder = {async getFileHandle(name, options) {
    assert.equal(name, 'first.csv'); assert.equal(options.create, true);
    return {async createWritable() { return {
      async write(blob) { writes.push(await blob.text()); },
      async close() { closed = true; }, async abort() { throw new Error('successful write should not be aborted'); },
    }; }};
  }};
  v.run('state.saveDirHandle = browserFolder');
  await v.run('doExport()');
  assert.equal(closed, true);
  assert.deepEqual(writes, ['name,count\nsynthetic,2\n']);
  assert.equal(v.downloads.length, 0);
  assert.equal(v.commands.length, 0);
  assert.equal(v.element('status').textContent, 'Export saved');
});

test('reveal failure retains the successful path for manual finding', async () => {
  const v = exportFixture({failAt: 'desktop_export_reveal'}), pending = v.run('doExport()');
  await exportDownloaded(v);
  const path = '/Users/test/成果 & <1>.csv';
  v.complete({id: 'export-1', status: 'saved', path});
  await pending;
  await assert.rejects(v.run('revealDesktopExport()'), /folder could not be opened/);
  assert.equal(v.element('export-saved-path').textContent, path);
  assert.equal(v.element('export-receipt').hidden, false);
  assert.equal(v.element('btn-export-reveal').disabled, false);
  assert.deepEqual(plain(v.run('desktopExportReceipt')), {id: 'export-1', path});
});

test('native rejection codes become localized actionable messages, without an export request', async () => {
  for (const [code, key] of [['invalid_destination', 'exportSaveFailed'], ['invalid_export_name', 'exportFileNameInvalid']]) {
    const v = exportFixture({locale: 'zh-CN'});
    v.window.__TAURI__.core.invoke = async () => { throw code; };
    await assert.rejects(v.run('doExport()'), error => error.message === v.window.WECFU_I18N.t(key));
    assert.deepEqual(plain(v.run('calls')), []);
    assert.equal(v.run('state.busy'), false);
  }
});

for (const locale of ['en', 'zh-CN', 'fr', 'ru']) {
  test(`native folder selection imports the chosen path once (${locale})`, async () => {
    const v = ui(locale), nativeCalls = [];
    const selected = String.raw`C:\用户资料\photo set\папка`;
    v.window.__WECFU_DESKTOP_IMPORT__ = true;
    v.window.__WECFU_DESKTOP_PLATFORM__ = 'windows';
    v.window.__TAURI__ = {core: {invoke: async (command, args) => {
      nativeCalls.push({command, args: plain(args)}); return selected;
    }}};
    v.run(`jsonRequest = async (url, method, body) => {calls.push({url, method, body:clone(body)}); return {batch:'synthetic'};}; updateControls();`);
    assert.equal(v.element('btn-choose-folder').hidden, false);
    assert.equal(v.element('path-input').placeholder, 'C:\\Photos');
    await v.element('btn-choose-folder').fire('click');
    assert.deepEqual(nativeCalls, [{command:'desktop_choose_import_folder', args:{locale}}]);
    assert.deepEqual(plain(v.run('calls')), [{url:'/api/ingest', method:'POST', body:{paths:[selected], view:'unknown', batch:'synthetic'}}]);
    assert.equal(v.element('path-input').value, selected);
    assert.equal(v.run('state.busy'), false);
    assert.equal(v.errors.length, 0);
  });
}

test('canceling a native folder picker preserves the session and blocks duplicate requests while open', async () => {
  const v = ui(); let finish, count = 0;
  v.window.__WECFU_DESKTOP_IMPORT__ = true;
  v.window.__TAURI__ = {core:{invoke: () => {count++; return new Promise(resolve => {finish = resolve;});}}};
  v.element('path-input').value = '/previous/path';
  const before = plain(v.run('snapshot()'));
  const pending = v.run('chooseImportFolder()');
  assert.equal(v.run('state.busy'), true);
  for (const id of ['btn-choose-folder','btn-ingest','btn-add-images','path-input','btn-recognize-all']) assert.equal(v.element(id).disabled, true, id);
  await v.run('chooseImportFolder()');
  assert.equal(count, 1);
  finish(null); await pending;
  assert.equal(v.run('state.busy'), false);
  assert.equal(v.run('calls.length'), 0);
  assert.equal(v.element('path-input').value, '/previous/path');
  assert.deepEqual(plain(v.run('snapshot()')), before);
});

test('a failed or invalid native folder selection never imports and releases busy state', async () => {
  for (const response of ['throw', undefined, '', {}, 'bad\0path']) {
    const v = ui();
    v.window.__WECFU_DESKTOP_IMPORT__ = true;
    v.window.__TAURI__ = {core:{invoke: async () => { if (response === 'throw') throw 'import_unavailable'; return response; }}};
    await assert.rejects(v.run('chooseImportFolder()'), /chooseFolderFailed/);
    assert.equal(v.run('state.busy'), false);
    assert.equal(v.run('calls.length'), 0);
  }
});

test('folder import stays unavailable in browsers, hosted sessions, review queues and locked workflows', async () => {
  const browser = ui(); browser.run('updateControls()');
  assert.equal(browser.element('btn-choose-folder').hidden, true);
  await assert.rejects(browser.run('chooseImportFolder()'), /chooseFolderUnavailable/);
  for (const setup of ["state.config.web_mode=true", "state.busy=true", "state.loading=true", "state.crop={}", "reviewMode=()=>true"]) {
    const v = ui(); let invoked = false;
    v.window.__WECFU_DESKTOP_IMPORT__ = true;
    v.window.__TAURI__ = {core:{invoke: async () => {invoked = true; return '/forbidden';}}};
    v.run(`${setup}; updateControls();`);
    await v.run('chooseImportFolder()');
    assert.equal(invoked, false, setup);
    assert.equal(v.run('calls.length'), 0);
  }
});
