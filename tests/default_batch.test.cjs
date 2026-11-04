// Pure synthetic transport fixtures. No model inference, photos, server or user data.
const test = require('node:test');
const assert = require('node:assert/strict');
const batch = require('../wecfu/server/static/default_batch.js');
const serial = require('../wecfu/server/static/serial_batch.js');
const model = require('../wecfu/server/static/model_preview_controls.js');
const product = require('../wecfu/server/product_fusion_v2.json');
const clone = value => JSON.parse(JSON.stringify(value));
const HASH = 'a'.repeat(64), OTHER_HASH = 'b'.repeat(64);
const PLATE = {cx: 160, cy: 120, r: 110};
const MARKS = [{id: 1, cx: 150, cy: 125, r: 12, score: .8, accepted: true, source: 'cv'}];
const error = (status, message = 'synthetic transport failure') => Object.assign(new Error(message), {status});
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise, resolve}; };
function unrecognized() {
  return {counted: false, mode: 'auto', detections: [], machine_count_initial: 0,
    reviewed: false, notes: '', plate_manual: false, plate: clone(PLATE), revision: 7};
}
function candidate() {
  return {candidate_id: 'synthetic-candidate', engine: model.FUSION_V2_ENGINE,
    image_sha256: HASH, base_revision: 7, plate: clone(PLATE),
    model_sha256: product.model_sha256, recipe_id: model.FUSION_V2_RECIPE,
    model_params: {plate_inset: .95}, detections: clone(MARKS), candidate_count: 1, raw_count: 1,
    expires_at: new Date(Date.now() + 60000).toISOString(),
    fusion_provenance: {image_sha256: HASH, source_view: 'main', plate_inset: .95,
      model_sha256: product.model_sha256, recipe_id: model.FUSION_V2_RECIPE,
      annotation_kind: model.FUSION_ANNOTATION, candidate_count: 1, d0_count: 1, supplemental_count: 0,
      feature_projection: [...model.FUSION_V2_PROJECTION], coordinate_method: 'raw_DINO_unchanged',
      D0_exclusion_fraction: .025, DINO_dedup_fraction: .005, ROI_max_radial: .95,
      filter_artifact_sha256: product.filter_artifact_sha256, sam_model_sha256: product.sam_model_sha256,
      dino_model_sha256: product.dino_model_sha256, detector_contract_sha256: product.detector_contract_sha256},
  };
}
function fixture(options = {}) {
  const sam = options.engine === model.SAM_ENGINE;
  const item = {batch: 'synthetic batch', name: options.name || 'fixture.png', engine: options.engine || model.FUSION_V2_ENGINE,
    capability: {enabled: true, available: true, model_sha256: sam ? 'c'.repeat(64) : product.model_sha256,
      recipe_id: sam ? model.SAM_RECIPE : model.FUSION_V2_RECIPE},
    webMode: options.webMode || false};
  const before = options.before === null ? null : {...unrecognized(), ...(options.before || {})};
  const initialized = {...unrecognized(), ...(options.initialized || {})};
  const suggestion = candidate();
  if (sam) {
    Object.assign(suggestion, {engine: model.SAM_ENGINE, model_sha256: item.capability.model_sha256, recipe_id: model.SAM_RECIPE});
    delete suggestion.fusion_provenance;
  }
  options.mutateCandidate?.(suggestion);
  const reference = options.reference || {status: 'missing', reference: null};
  const view = {source_sha256: HASH, declared: true, view: 'main', ...(options.view || {})};
  const calls = []; let detectionReads = 0, applied = null;
  const record = entry => { calls.push(entry); options.trace?.push(`${item.name}:${entry.path}:${entry.method}`); };
  const io = {
    valid: model.valid,
    uuid: () => '00000000-0000-4000-8000-000000000001',
    source: async url => { record({path: '/raw', method: 'GET', url}); return HASH; },
    json: async (url, method = 'GET', body) => {
      const path = url.slice(url.indexOf('/image/') + '/image/'.length).slice(encodeURIComponent(item.name).length);
      record({path, method, body: body === undefined ? undefined : clone(body), url});
      if (path === '/detections') {
        if (++detectionReads === 1) {
          if (options.beforeError) throw options.beforeError;
          if (before === null) throw error(404);
          return clone(before);
        }
        if (options.reconcileError) throw options.reconcileError;
        if (options.reconcileDoc === null) return null;
        const saved = clone(applied); options.mutateReceipt?.(saved);
        return saved;
      }
      if (path === '/reference') {
        if (options.referenceError) throw options.referenceError;
        return clone(reference);
      }
      if (path === '/initialize') return clone(initialized);
      if (path === '/source_view') return clone(view);
      if (path === '/model-preview') {
        await options.onPreview?.();
        if (options.previewError) throw options.previewError;
        return clone(suggestion);
      }
      if (path === '/model-preview/apply') {
        await options.onApply?.();
        applied = {...clone(before || initialized), revision: body.expected_revision + 1, counted: true,
          detections: clone(suggestion.detections), machine_count_initial: suggestion.candidate_count,
          count_engine: item.engine, count_model: clone(sam ? {model_sha256: suggestion.model_sha256,
            recipe_id: suggestion.recipe_id, plate_inset: .95} : suggestion.fusion_provenance),
          _model_preview_apply: {request_id: body.request_id, request: clone(body),
            applied_revision: body.expected_revision + 1}};
        if (options.applyError) throw options.applyError;
        const response = clone(applied); options.mutateResponse?.(response);
        return response;
      }
      assert.fail(`Unexpected request ${method} ${path}`);
    },
  };
  return {item, io, before, calls, suggestion,
    run: () => batch.recognize(item, io),
    callsTo: path => calls.filter(call => call.path === path),
  };
}
function noInference(f) {
  assert.equal(f.callsTo('/model-preview').length, 0);
  assert.equal(f.callsTo('/model-preview/apply').length, 0);
}

for (const view of ['unknown', 'back']) test(`SAM batch accepts unified ${view} photos without a Fusion view declaration`, async () => {
  const f = fixture({engine: model.SAM_ENGINE, view: {view, declared: false}});
  const result = await f.run();
  assert.equal(result.status, 'completed');
  assert.equal(result.doc.count_engine, model.SAM_ENGINE);
  assert.equal(result.doc.count_model.recipe_id, model.SAM_RECIPE);
  assert.equal(f.callsTo('/source_view').length, 0, 'SAM must not depend on obsolete import categories');
  assert.deepEqual(f.callsTo('/model-preview')[0].body, {engine: model.SAM_ENGINE,
    expected_revision: 7, expected_image_sha256: HASH, model_params: {}, only_unrecognized: true});
  assert.equal(f.callsTo('/model-preview/apply')[0].body.only_unrecognized, true);
  assert.equal(f.callsTo('/reference').length, 1);
});

test('SAM default still protects saved zero counts and human references, and never adopts a mismatched model', async () => {
  for (const options of [{before: {counted: true}}, {reference: {status: 'verified', reference: {synthetic: true}}}]) {
    const f = fixture({engine: model.SAM_ENGINE, ...options});
    assert.equal((await f.run()).status, 'skipped'); noInference(f);
  }
  for (const change of [c => { c.engine = model.FUSION_V2_ENGINE; }, c => { c.image_sha256 = OTHER_HASH; },
    c => { c.model_sha256 = OTHER_HASH; }, c => { c.recipe_id = model.FUSION_V2_RECIPE; }]) {
    const f = fixture({engine: model.SAM_ENGINE, mutateCandidate: change});
    assert.equal((await f.run()).status, 'failed');
    assert.equal(f.callsTo('/model-preview/apply').length, 0);
  }
});

test('one image binds true candidate validation, preview and adoption to exact source, revision and provenance', async () => {
  const f = fixture(), before = clone(f.before), result = await f.run();
  assert.equal(result.status, 'completed');
  assert.deepEqual(result.before, before); assert.deepEqual(f.before, before);
  assert.equal(result.hash, HASH);
  assert.deepEqual(f.callsTo('/model-preview')[0].body, {engine: model.FUSION_V2_ENGINE,
    expected_revision: 7, expected_image_sha256: HASH, model_params: {}, only_unrecognized: true});
  const apply = f.callsTo('/model-preview/apply');
  assert.equal(apply.length, 1);
  assert.deepEqual(apply[0].body, {candidate_id: 'synthetic-candidate', expected_revision: 7,
    expected_image_sha256: HASH, request_id: '00000000-0000-4000-8000-000000000001',
    replace_all: true, only_unrecognized: true});
  assert.equal(result.doc.revision, 8);
  assert.equal(result.doc.count_engine, model.FUSION_V2_ENGINE);
  assert.deepEqual(result.doc.count_model, f.suggestion.fusion_provenance);
  assert.deepEqual(result.doc.detections, MARKS);
  assert.ok(f.calls.every(call => call.url.startsWith('/api/batch/synthetic%20batch/image/fixture.png/')));
});

for (const [name, mutation] of [
  ['already counted, including a recognized zero', {counted: true}],
  ['legacy status absent', {counted: undefined}], ['unknown legacy status', {counted: null}],
  ['machine marks', {detections: clone(MARKS)}],
  ['manual marks', {detections: [{...MARKS[0], source: 'manual'}]}],
  ['initial count history after deletion', {machine_count_initial: 1}],
  ['manual mode', {mode: 'manual'}], ['human edit flag', {reviewed: true}],
  ['notes', {notes: 'synthetic protected note'}], ['manual boundary', {plate_manual: true}],
]) test(`does not infer or initialize protected ${name}`, async () => {
  const f = fixture({before: mutation}), result = await f.run();
  assert.equal(result.status, 'skipped'); noInference(f);
  assert.equal(f.callsTo('/initialize').length, 0);
  assert.equal(f.calls.length, 1);
});

for (const status of ['verified', 'stale', 'withdrawn', 'invalid']) test(`existing ${status} reference is protected before initialization`, async () => {
  const f = fixture({before: null, reference: {status, reference: {synthetic: true}}}), result = await f.run();
  assert.equal(result.status, 'skipped'); assert.equal(result.reason, 'reference'); noInference(f);
  assert.equal(f.callsTo('/initialize').length, 0);
});

test('web Ultra validates and adopts SAM with source and revision guards without a local reference endpoint', async () => {
  const f = fixture({webMode: true, engine: model.SAM_ENGINE, before: null});
  const result = await f.run();
  assert.equal(result.status, 'completed');
  assert.equal(result.doc.count_engine, model.SAM_ENGINE);
  assert.deepEqual(result.doc.detections, MARKS);
  assert.equal(f.callsTo('/reference').length, 0);
  assert.equal(f.callsTo('/source_view').length, 0);
  assert.deepEqual(f.callsTo('/model-preview').map(x => x.body), [{
    engine:model.SAM_ENGINE, expected_revision:7, expected_image_sha256:HASH,
    model_params:{}, only_unrecognized:true,
  }]);
  assert.deepEqual(f.callsTo('/model-preview/apply').map(x => ({...x.body, request_id:'bound-request'})), [{
    candidate_id:'synthetic-candidate', expected_revision:7, expected_image_sha256:HASH,
    request_id:'bound-request', replace_all:true, only_unrecognized:true,
  }]);
  assert.equal(result.doc.revision, 8);
});

test('reference API failure fails closed; web mode does not call the disabled local reference API', async () => {
  const failed = fixture({referenceError: error(503)});
  assert.equal((await failed.run()).status, 'failed'); noInference(failed);
  const web = fixture({webMode: true}); assert.equal((await web.run()).status, 'completed');
  assert.equal(web.callsTo('/reference').length, 0);
});

test('fresh image initializes once, rechecks protection, and browsing alone is not human verification', async () => {
  const fresh = fixture({before: null}); assert.equal((await fresh.run()).status, 'completed');
  assert.deepEqual(fresh.callsTo('/initialize').map(x => x.body), [{mode: 'auto'}]);
  const raced = fixture({before: null, initialized: {notes: 'edited in another view'}});
  assert.equal((await raced.run()).status, 'skipped'); noInference(raced);
  const viewed = fixture({before: {viewed: true}}); assert.equal((await viewed.run()).status, 'completed');
});

for (const [name, view] of [
  ['unknown', {view: 'unknown'}], ['back', {view: 'back'}],
  ['undeclared', {declared: false}], ['wrong source hash', {source_sha256: OTHER_HASH}],
]) test(`does not infer ${name} source view`, async () => {
  const f = fixture({view}), result = await f.run();
  assert.equal(result.status, 'skipped'); assert.equal(result.reason, 'source_view'); noInference(f);
});

test('declared blank view is eligible and missing saved revision cannot start inference', async () => {
  const blank = fixture({view: {view: 'blank'}, mutateCandidate: c => { c.fusion_provenance.source_view = 'blank'; }});
  assert.equal((await blank.run()).status, 'completed');
  const missing = fixture({before: {revision: null}}); assert.equal((await missing.run()).status, 'failed'); noInference(missing);
});

for (const [name, mutateCandidate] of [
  ['source hash', c => { c.image_sha256 = OTHER_HASH; }],
  ['revision', c => { c.base_revision++; }], ['expired', c => { c.expires_at = 0; }],
  ['plate', c => { c.plate.r--; }], ['model', c => { c.model_sha256 = OTHER_HASH; }],
  ['recipe', c => { c.recipe_id = 'synthetic-wrong-recipe'; }],
  ['provenance geometry', c => { c.fusion_provenance.D0_exclusion_fraction = .01; }],
  ['provenance counts', c => { c.fusion_provenance.supplemental_count++; }],
]) test(`true model validator rejects mismatched ${name} without applying`, async () => {
  const f = fixture({mutateCandidate}), result = await f.run();
  assert.equal(result.status, 'failed'); assert.equal(f.callsTo('/model-preview').length, 1);
  assert.equal(f.callsTo('/model-preview/apply').length, 0);
});

for (const phase of ['preview', 'apply']) test(`${phase} 409 is a protected skip with no inference retry`, async () => {
  const f = fixture({[`${phase}Error`]: error(409)}), result = await f.run();
  assert.equal(result.status, 'skipped'); assert.equal(result.stop, undefined);
  assert.equal(f.callsTo('/model-preview').length, 1);
  assert.equal(f.callsTo('/model-preview/apply').length, phase === 'apply' ? 1 : 0);
  assert.equal(f.callsTo('/detections').length, 1);
});

test('lost apply response reconciles exact persisted receipt read-only, without any retry', async () => {
  const f = fixture({applyError: new TypeError('synthetic lost response')}), result = await f.run();
  assert.equal(result.status, 'completed'); assert.equal(f.callsTo('/detections').length, 2);
  assert.equal(f.callsTo('/model-preview').length, 1); assert.equal(f.callsTo('/model-preview/apply').length, 1);
  assert.ok(batch.receiptMatches(result.doc, f.callsTo('/model-preview/apply')[0].body));
});

for (const [name, mutateReceipt] of [
  ['missing receipt', d => { delete d._model_preview_apply; }],
  ['request identity', d => { d._model_preview_apply.request_id = 'other-request'; }],
  ['candidate identity', d => { d._model_preview_apply.request.candidate_id = 'other-candidate'; }],
  ['image identity', d => { d._model_preview_apply.request.expected_image_sha256 = OTHER_HASH; }],
  ['self-consistent wrong saved revision', d => { d.revision++; d._model_preview_apply.applied_revision++; }],
  ['embedded expected revision', d => { d._model_preview_apply.request.expected_revision++; }],
  ['embedded request identity', d => { d._model_preview_apply.request.request_id = 'other-request'; }],
  ['replacement guard', d => { d._model_preview_apply.request.replace_all = false; }],
  ['unrecognized-only guard', d => { d._model_preview_apply.request.only_unrecognized = false; }],
]) test(`lost apply response with ${name} stops before another image`, async () => {
  const f = fixture({applyError: error(503), mutateReceipt}), result = await f.run();
  assert.equal(result.status, 'uncertain'); assert.equal(result.stop, true);
  assert.equal(f.callsTo('/model-preview').length, 1); assert.equal(f.callsTo('/model-preview/apply').length, 1);
});

test('unreadable reconciliation stops; malformed successful response may reconcile once to a valid saved receipt', async () => {
  const failed = fixture({applyError: error(500), reconcileError: error(503)});
  assert.equal((await failed.run()).stop, true);
  const recovered = fixture({mutateResponse: d => { delete d._model_preview_apply; }});
  assert.equal((await recovered.run()).status, 'completed');
  assert.equal(recovered.callsTo('/detections').length, 2);
  assert.equal(recovered.callsTo('/model-preview/apply').length, 1);
});

test('two images remain strictly serial through adoption, not just through model preview', async () => {
  const started = deferred(), finish = deferred(), trace = [];
  const first = fixture({name: 'first.png', trace, onApply: async () => { started.resolve(); await finish.promise; }});
  const second = fixture({name: 'second.png', trace});
  const running = serial.run([first, second], {runItem: f => f.run()});
  await started.promise;
  assert.equal(second.calls.length, 0, 'The next image must not start while adoption is in flight');
  finish.resolve(); const result = await running;
  assert.deepEqual(result.results.map(r => r.status), ['completed', 'completed']);
  assert.equal(result.processed, 2); assert.equal(result.stopped, false);
  assert.ok(trace.indexOf('second.png:/detections:GET') > trace.indexOf('first.png:/model-preview/apply:POST'));
});

test('model failure continues to the next image, but uncertain adoption stops the queue', async () => {
  const failed = fixture({name: 'failed.png', previewError: error(503)}), next = fixture({name: 'next.png'});
  const continued = await serial.run([failed, next], {runItem: f => f.run()});
  assert.deepEqual(continued.results.map(r => r.status), ['failed', 'completed']);
  assert.equal(failed.callsTo('/model-preview/apply').length, 0);
  const uncertain = fixture({name: 'uncertain.png', applyError: error(503), reconcileDoc: null});
  const untouched = fixture({name: 'untouched.png'});
  const stopped = await serial.run([uncertain, untouched], {runItem: f => f.run()});
  assert.equal(stopped.stopped, true); assert.equal(stopped.processed, 1); assert.equal(untouched.calls.length, 0);
});

test('stop requested during preview lets the current image finish and blocks every later image', async () => {
  const started = deferred(), finish = deferred(); let stop = false;
  const first = fixture({name: 'first.png', onPreview: async () => { started.resolve(); await finish.promise; }});
  const next = fixture({name: 'next.png'});
  const running = serial.run([first, next], {runItem: f => f.run(), shouldStop: () => stop});
  await started.promise; stop = true; finish.resolve();
  const result = await running;
  assert.equal(result.stopped, true); assert.equal(result.processed, 1);
  assert.equal(result.results[0].status, 'completed');
  assert.equal(first.callsTo('/model-preview/apply').length, 1); assert.equal(next.calls.length, 0);
});

const builtinParams = {plate_inset:.88,min_value:200,max_saturation:100,min_circularity:.55,min_area_frac:.0001,peak_min_distance:15};
function builtinFixture(options={}) {
  const item={batch:'synthetic batch',name:'fixture.png',engine:'component_watershed_v1',params:clone(builtinParams),webMode:!!options.webMode};
  const before=options.before===null?null:{...unrecognized(),...(options.before||{})};
  const calls=[];
  const io={
    source:async url=>{calls.push({url,method:'GET'});return options.hash===undefined?HASH:options.hash;},
    json:async(url,method='GET',body)=>{
      calls.push({url,method,body:body===undefined?undefined:clone(body)});
      if(url.endsWith('/detections')){if(before===null)throw error(404);return clone(before);}
      if(url.endsWith('/reference')){if(options.referenceError)throw options.referenceError;return options.reference||{status:'missing'};}
      if(url.endsWith('/initialize'))return {...unrecognized(),...(options.initialized||{})};
      if(url.includes('/run?')){
        if(options.runError)throw options.runError;
        const result={...clone(before||unrecognized()),revision:8,counted:true,count_engine:item.engine,
          count_model:null,count_params:clone(body),params:clone(body),detections:clone(MARKS)};
        options.mutateResult?.(result);return result;
      }
      assert.fail('unexpected transport '+url);
    },
  };
  return {item,io,calls,run:()=>batch.recognizeBuiltin(item,io)};
}

test('builtin default batch binds fixed params, SHA and revision and never uses models or source-view routing', async()=>{
  const f=builtinFixture(), result=await f.run();
  assert.equal(result.status,'completed');
  const posts=f.calls.filter(c=>c.method==='POST');
  assert.equal(posts.length,1);
  const query=new URL(posts[0].url,'http://synthetic').searchParams;
  assert.equal(query.get('engine'),'component_watershed_v1');
  assert.equal(query.get('expected_revision'),'7');
  assert.equal(query.get('expected_image_sha256'),HASH);
  assert.equal(query.get('only_unrecognized'),'true');
  assert.equal(query.get('protect_existing_edits'),'true');
  assert.deepEqual(posts[0].body,builtinParams);
  assert.equal(f.calls.some(c=>/model-preview|source_view/.test(c.url)),false);
  assert.equal(result.hash,HASH);
  assert.deepEqual(result.before,unrecognized());
});

test('builtin batch skips all prior counts including zero/model results and protects edits/references', async()=>{
  for(const before of [{counted:true,detections:[]},{counted:true,count_engine:model.SAM_ENGINE},
    {counted:true,count_engine:model.FUSION_V2_ENGINE},{counted:undefined},
    {notes:'preserve'},{plate_manual:true},{reviewed:true},{mode:'manual'},
    {detections:clone(MARKS)},{machine_count_initial:1}]) {
    const f=builtinFixture({before}),result=await f.run();
    assert.equal(result.status,'skipped',JSON.stringify(before));
    assert.equal(f.calls.some(c=>c.method==='POST'),false);
  }
  for(const reference of [{status:'verified'},{status:'stale'},{status:'withdrawn'},
    {status:'missing',reference:{synthetic:true}},{}]) {
    const f=builtinFixture({reference});assert.equal((await f.run()).status,'skipped');
    assert.equal(f.calls.some(c=>c.method==='POST'),false);
  }
});

test('builtin initializes only missing states and rechecks protection before counting', async()=>{
  const f=builtinFixture({before:null});assert.equal((await f.run()).status,'completed');
  assert.equal(f.calls.filter(c=>c.url.endsWith('/initialize')).length,1);
  const race=builtinFixture({before:null,initialized:{counted:true}});
  assert.equal((await race.run()).status,'skipped');
  assert.equal(race.calls.some(c=>c.url.includes('/run?')),false);
});

test('builtin source fingerprint failure and reference failure stop before a run', async()=>{
  for(const opts of [{hash:null},{hash:'invalid'},{referenceError:error(503)}]) {
    const f=builtinFixture(opts); assert.equal((await f.run()).status,'failed');
    assert.equal(f.calls.some(c=>c.url.includes('/run?')),false);
  }
});

test('builtin stale revision conflict is skipped once; unknown write outcome stops without replay', async()=>{
  for(const runError of [error(409),error(503),new TypeError('lost response')]) {
    const f=builtinFixture({runError}),result=await f.run();
    assert.equal(result.status,runError.status===409?'skipped':'uncertain');
    assert.equal(result.stop===true,runError.status!==409);
    assert.equal(f.calls.filter(c=>c.url.includes('/run?')).length,1);
  }
});

test('builtin malformed success cannot be presented as completed', async()=>{
  for(const mutateResult of [doc=>{doc.counted=false;},doc=>{doc.count_engine=model.SAM_ENGINE;},
    doc=>{doc.revision=99;},doc=>{doc.count_params.min_value=150;}]) {
    const f=builtinFixture({mutateResult});assert.equal((await f.run()).status,'uncertain');
    assert.equal(f.calls.filter(c=>c.url.includes('/run?')).length,1);
  }
});

test('builtin web path skips inaccessible human-reference endpoint and uses explicit configured baseline', async()=>{
  const f=builtinFixture({webMode:true});f.item.engine='baseline';
  const result=await f.run();assert.equal(result.status,'completed');
  assert.equal(result.doc.count_engine,'baseline');
  assert.equal(f.calls.some(c=>c.url.endsWith('/reference')),false);
});
