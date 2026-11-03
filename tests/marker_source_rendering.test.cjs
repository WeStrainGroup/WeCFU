// Synthetic Canvas/API fixtures only: no photos, network, model or user records.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const staticPath = path.join(__dirname, '../wecfu/server/static');
const source = fs.readFileSync(path.join(staticPath, 'app.js'), 'utf8');
const helpers = require(path.join(staticPath, 'model_preview_controls.js'));
const plain = value => JSON.parse(JSON.stringify(value));
const ROSE = 'rgba(183,131,150,0.9)', BLUE = 'rgba(117,149,166,0.9)';
const plate = {cx: 160, cy: 120, r: 110};
const marks = [
  {id: 3, cx: 110, cy: 110, r: 8, score: 1, accepted: true, source: 'cv'},
  {id: 9, cx: 180, cy: 130, r: 10, score: 1, accepted: true, source: 'manual'},
];
const candidateMarks = [{id: 1, cx: 150, cy: 125, r: 12, score: .8, accepted: true, source: 'cv'}];

function ui() {
  const nodes = new Map(), timers = new Map(); let timerId = 0;
  const element = id => {
    if (!nodes.has(id)) nodes.set(id, {value: '', checked: false, hidden: false, disabled: false, open: false,
      textContent: '', children: [], dataset: {}, classList: {toggle() {}, add() {}, remove() {}},
      style: {setProperty() {}, removeProperty() {}}, setAttribute() {}, removeAttribute() {}, closest() { return null; },
      checkValidity() { return this.value !== '' && Number.isFinite(Number(this.value)); }});
    return nodes.get(id);
  };
  const context = vm.createContext({window: {WECFU_MODEL_PREVIEW_CONTROLS: helpers,
    WECFU_PARAM_CONTROLS: require(path.join(staticPath, 'param_controls.js')),
    WECFU_REFERENCE_CONTROLS: require(path.join(staticPath, 'reference_controls.js')),
    WECFU_WORKFLOW_CONTROLS: require(path.join(staticPath, 'workflow_controls.js')),
    WECFU_REVIEW_QUEUE_CONTROLS: require(path.join(staticPath, 'review_queue_controls.js')),
    WECFU_I18N: {t: key => key, getLang: () => 'en'}, addEventListener() {}, devicePixelRatio: 1},
    document: {getElementById: element}, console, AbortController, crypto: webcrypto,
    setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id; }, clearTimeout(id) { timers.delete(id); }});
  vm.runInContext(source, context);
  context.fixturePlate = plain(plate); context.fixtureMarks = plain(marks);
  context.fixtureCandidate = {candidate_id: 'synthetic-candidate', engine: helpers.ENGINE,
    base_revision: 17, image_sha256: 'a'.repeat(64), plate: plain(plate),
    model_params: {plate_inset: .82, score_threshold: .45, nms_threshold: .5}, model_sha256: 'b'.repeat(64),
    detections: plain(candidateMarks), raw_count: 2, candidate_count: 1,
    expires_at: new Date(Date.now() + 60000).toISOString()};
  const run = code => vm.runInContext(code, context);
  run(`
    let requests = [], saves = [];
    draw = () => {}; invalidateBackground = () => {}; cancelGesture = () => {}; fitToCanvas = () => {};
    loadImages = async () => {}; flushEdits = async () => {};
    queueSave = () => saves.push(snapshot());
    loadPlateImage = async () => ({image: {width: 320, height: 240}, sourceHash: 'a'.repeat(64)});
    request = async (url, options) => { requests.push({url, options}); return {json: async () => fixtureCandidate}; };
    state.batch = 'synthetic'; state.imageName = 'fixture.png'; state.img = {width: 320, height: 240};
    state.plate = fixturePlate; state.detections = fixtureMarks; state.imageSourceHash = 'a'.repeat(64);
    state.doc = {plate: fixturePlate, detections: fixtureMarks, mode: 'auto', params: {...LEGACY_DEFAULTS},
      notes: '', counted: true, count_params: {...LEGACY_DEFAULTS}, machine_count_initial: 1,
      count_engine: 'baseline', count_model: null, plate_manual: true, reviewed: false, revision: 17};
    state.config = {experimental_models: {cfucounter: {enabled: true, available: true}}};
    state.saveQueues.set(keyFor(), {revision: 17});
    $('method-select').value = MODEL_ENGINE; $('mode-select').value = 'auto';
    fillParams(LEGACY_DEFAULTS); updateControls();
  `);
  const strokes = [], labels = [], stack = [];
  const drawing = {strokeStyle: '', fillStyle: '', lineWidth: 1, dash: [], arcs: [],
    drawImage() {}, scale() {}, translate() {},
    save() { stack.push({strokeStyle: this.strokeStyle, fillStyle: this.fillStyle,
      lineWidth: this.lineWidth, dash: [...this.dash]}); },
    restore() { Object.assign(this, stack.pop()); },
    beginPath() { this.arcs = []; }, arc(x, y, r) { this.arcs.push({x, y, r}); },
    setLineDash(value) { this.dash = [...value]; },
    stroke() { strokes.push({color: this.strokeStyle, width: this.lineWidth, dash: [...this.dash], arcs: [...this.arcs]}); },
    fillText(text, x, y) { labels.push({text, x, y, color: this.fillStyle}); },
    strokeText() { assert.fail('Colony labels must not draw a white outline'); },
  };
  element('canvas').width = 640; element('canvas').height = 480; element('canvas').getContext = () => drawing;
  run('resizeCanvas = () => {}; state.backdrop = {width: 640, height: 480}; state.backdropDirty = false;');
  return {run, element, strokes, labels, paint() { strokes.length = labels.length = 0; run('paint()'); }};
}

function assertMark(view, mark, color, zoom) {
  const found = view.strokes.filter(s => s.arcs.some(a => a.x === mark.cx && a.y === mark.cy && a.r === mark.r));
  assert.equal(found.length, 1, 'A mark uses one stroke, without an outline/halo layer');
  assert.equal(found[0].color, color);
  assert.deepEqual(found[0].dash, [], 'Both sources and unsaved candidates must use a solid circle');
  assert.equal(found[0].width * zoom, 2.75, 'Screen stroke width stays constant across zoom');
}

for (const zoom of [.5, 1, 2]) {
  test(`preview shows only candidate marks with source colors at zoom ${zoom} without changing state`, async () => {
    const view = ui(); await view.run('runModelPreview()');
    view.run(`state.view.zoom = ${zoom};`);
    const before = plain(view.run('({snapshot: snapshot(), candidate: state.modelPreview.candidate, history: state.history, reference: state.reference, saves})'));
    view.paint();
    for (const oldMark of marks) assert.equal(view.strokes.some(stroke => stroke.arcs.some(arc => arc.x === oldMark.cx && arc.y === oldMark.cy && arc.r === oldMark.r)), false, 'Saved marks must not be painted underneath the separate preview');
    assertMark(view, candidateMarks[0], ROSE, zoom);
    assert.deepEqual(view.labels, [], 'Saved numbering must not remain on the preview');
    assert.equal(view.element('count-badge').textContent, 'modelTemporary · 1');
    assert.match(view.element('model-count').textContent, /modelTemporary: 1.*modelCurrent: 2/);
    assert.deepEqual(plain(view.run('({snapshot: snapshot(), candidate: state.modelPreview.candidate, history: state.history, reference: state.reference, saves})')), before);
    const roi = view.strokes.find(s => s.arcs.some(a => a.x === plate.cx && a.y === plate.cy && Math.abs(a.r - plate.r * .82) < 1e-9));
    assert.equal(roi.color, '#777777'); assert.ok(roi.dash.length, 'ROI is an auxiliary guide, not a colony mark');
  });
}

test('adoption and Undo preserve source styles; discarding a preview changes no saved marks', async () => {
  const view = ui(), before = plain(view.run('snapshot()'));
  await view.run('runModelPreview()');
  view.run('clearModelPreview();'); view.paint();
  assertMark(view, marks[0], ROSE, 1); assertMark(view, marks[1], BLUE, 1);
  assert.equal(view.strokes.some(s => s.arcs.some(a => a.x === candidateMarks[0].cx && a.y === candidateMarks[0].cy)), false);
  assert.deepEqual(plain(view.run('snapshot()')), before);
  assert.equal(view.run('saves.length'), 0);
  await view.run('runModelPreview()');
  view.run(`jsonRequest = async (url, method, body) => {
    requests.push({url, method, body});
    return {...snapshot(), detections: fixtureCandidate.detections, machine_count_initial: 1,
      count_engine: MODEL_ENGINE, count_model: {model_sha256: 'b'.repeat(64)}, count_params: null, revision: 18};
  };`);
  await view.run('applyModelPreview()'); view.paint();
  assert.equal(view.run('state.modelPreview.candidate'), null);
  assert.deepEqual(plain(view.run('state.detections')), candidateMarks);
  assertMark(view, candidateMarks[0], ROSE, 1);
  assert.deepEqual(view.labels.map(l => [l.text, l.color]), [['1', ROSE]]);
  assert.equal(view.run('state.history.length'), 1);
  view.run('undo();'); view.paint();
  assert.deepEqual(plain(view.run('snapshot()')), before);
  assert.deepEqual(plain(view.run('saves[0]')), before);
  assertMark(view, marks[0], ROSE, 1); assertMark(view, marks[1], BLUE, 1);
  assert.equal(view.run('requests.some(r => r.url.endsWith("/reference"))'), false);
});

test('legend swatches and bilingual names match the actual marker source colors', () => {
  const css = fs.readFileSync(path.join(staticPath, 'styles.css'), 'utf8');
  for (const [name, rgb] of [['cv', '183,131,150'], ['manual', '117,149,166']]) {
    const body = css.match(new RegExp(`\\.dot-${name}\\s*\\{([^}]+)\\}`))[1].replace(/\s/g, '');
    assert.ok(body.includes(`border-color:rgba(${rgb},.9)`));
    assert.ok(body.includes('border-style:solid'));
  }
  const language = vm.createContext({window: {}, navigator: {language: 'en'},
    localStorage: {getItem() { return 'en'; }, setItem() {}}, document: {}});
  vm.runInContext(fs.readFileSync(path.join(staticPath, 'i18n.js'), 'utf8'), language);
  const translations = language.window.WECFU_I18N.I18N;
  assert.equal(translations.en.legendAuto, 'Machine · rose');
  assert.equal(translations.en.legendManual, 'Manual · blue');
  assert.equal(translations['zh-CN'].legendAuto, '机器 · 灰粉');
  assert.equal(translations['zh-CN'].legendManual, '人工 · 灰蓝');
  for (const code of ['en', 'zh-CN']) for (const key of ['fusionRoiHint', 'samRoiHint', 'modelRoiHint']) {
    assert.doesNotMatch(translations[code][key], /amber|cyan|琥珀|青色/i);
    assert.match(translations[code][key], code === 'en' ? /unsaved until adopted/ : /预览尚未保存/);
  }
});

test('SAM zero-result preview hides all saved marks, identifies preview count, and discard restores them unchanged', async()=>{
  const view=ui(),before=plain(view.run('snapshot()'));
  view.run(`state.config.models={sam2:{enabled:true,available:true,engine:SAM_ENGINE,
    model_sha256:'b'.repeat(64),recipe_id:modelHelpers.SAM_RECIPE}};
    $('method-select').value=SAM_ENGINE;
    Object.assign(fixtureCandidate,{engine:SAM_ENGINE,recipe_id:modelHelpers.SAM_RECIPE,
      model_params:{plate_inset:.95},detections:[],raw_count:0,candidate_count:0});
    updateControls();`);
  await view.run('runModelPreview()');view.paint();
  for(const mark of marks) assert.equal(view.strokes.some(stroke=>stroke.arcs.some(arc=>arc.x===mark.cx&&arc.y===mark.cy&&arc.r===mark.r)),false);
  assert.equal(view.element('count-badge').textContent,'samPreview · 0');
  assert.match(view.element('model-count').textContent,/samPreview: 0.*modelCurrent: 2/);
  assert.deepEqual(plain(view.run('snapshot()')),before);
  view.run('clearModelPreview();updateControls();');view.paint();
  assertMark(view,marks[0],ROSE,1);assertMark(view,marks[1],BLUE,1);
  assert.equal(view.element('count-badge').textContent,'2 cfuSuffix');
  assert.deepEqual(plain(view.run('snapshot()')),before);
  assert.equal(view.run('saves.length'),0);
});

test('preview canvas pans and zooms without editing hidden saved marks; discard restores normal editing', async()=>{
  const view=ui(),canvas=view.element('canvas');
  canvas.focus=()=>{};canvas.getBoundingClientRect=()=>({left:0,top:0});
  canvas.setPointerCapture=()=>{};canvas.hasPointerCapture=()=>false;
  view.element('modal-backdrop').hidden=view.element('export-backdrop').hidden=true;
  view.run('cancelGesture=()=>{state.gesture=null;};');
  const before=plain(view.run('snapshot()'));
  for(const phase of ['loading','candidate']) {
    if(phase==='candidate')await view.run('runModelPreview()');
    else view.run('state.modelPreview.loading=true;');
    view.run(`state.view={zoom:1,ox:0,oy:0,fitted:true};
      onPointerDown({button:0,pointerId:1,clientX:30,clientY:30,preventDefault(){}});
      onPointerMove({pointerId:1,clientX:45,clientY:45});
      onPointerUp({pointerId:1,clientX:45,clientY:45});
      onContextMenu({clientX:125,clientY:125,preventDefault(){}});
      onWheel({clientX:120,clientY:120,deltaY:-1,preventDefault(){}});`);
    assert.equal(view.run('state.view.ox!==0 && state.view.zoom>1'),true,phase);
    assert.deepEqual(plain(view.run('snapshot()')),before,phase);
    assert.equal(view.run('state.history.length'),0,phase);
    assert.equal(view.run('saves.length'),0,phase);
    if(phase==='candidate')assert.equal(view.run('modelCandidateCurrent()'),true);
    else view.run('state.modelPreview.loading=false;');
  }
  view.run(`clearModelPreview();state.view={zoom:1,ox:0,oy:0,fitted:true};
    onContextMenu({clientX:110,clientY:110,preventDefault(){}});`);
  assert.equal(view.run('state.detections.length'),1);
  assert.equal(view.run('state.history.length'),1);
  assert.equal(view.run('saves.length'),1);
  assert.equal(view.run('state.modelPreview.candidate'),null);
});
