// Protected serial recognition. Local default uses SAM; explicit classical
// recognition keeps the improved builtin implementation.
(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.WECFU_DEFAULT_BATCH = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  'use strict';
  function protection(doc) {
    if (!doc) return null;
    if (doc.counted !== false) return 'already_counted';
    if (doc.detections?.length || doc.machine_count_initial > 0) return 'existing_marks';
    if (doc.mode === 'manual') return 'manual_mode';
    if (doc.reviewed || doc.notes || doc.plate_manual) return 'human_work';
    return null;
  }
  function receiptMatches(doc, body) {
    const receipt = doc?._model_preview_apply;
    return receipt?.request_id === body.request_id && receipt.applied_revision === doc.revision
      && doc.revision === body.expected_revision + 1
      && receipt.request?.request_id === body.request_id
      && receipt.request?.expected_revision === body.expected_revision
      && receipt.request?.replace_all === body.replace_all
      && receipt.request?.only_unrecognized === body.only_unrecognized
      && receipt.request?.candidate_id === body.candidate_id
      && receipt.request?.expected_image_sha256 === body.expected_image_sha256;
  }
  async function recognize(item, io) {
    const {batch, name, engine, capability, webMode} = item;
    const base = `/api/batch/${encodeURIComponent(batch)}/image/${encodeURIComponent(name)}`;
    let before, hash, applyBody;
    try {
      before = await io.json(base + '/detections').catch(error => {
        if (error.status === 404) return null;
        throw error;
      });
      let reason = protection(before);
      if (reason) return {name, status: 'skipped', reason};
      if (!webMode) {
        const reference = await io.json(base + '/reference');
        if (reference.status !== 'missing' || reference.reference)
          return {name, status: 'skipped', reason: 'reference'};
      }
      if (!before) before = await io.json(base + '/initialize', 'POST', {mode: 'auto'});
      reason = protection(before);
      if (reason) return {name, status: 'skipped', reason};
      hash = await io.source(base + '/raw');
      if (engine !== 'sam2_local_v1') {
        const view = await io.json(base + '/source_view');
        if (view.source_sha256 !== hash || !view.declared || !['main', 'blank'].includes(view.view))
          return {name, status: 'skipped', reason: 'source_view'};
      }
      if (!Number.isInteger(before.revision)) throw new Error('Missing saved revision');
      const context = {hash, revision: before.revision, plate: before.plate, inset: .95,
        engine, model_sha256: capability.model_sha256, recipe_id: capability.recipe_id};
      const candidate = await io.json(base + '/model-preview', 'POST', {engine,
        expected_revision: before.revision, expected_image_sha256: hash,
        model_params: {}, only_unrecognized: true});
      if (!io.valid(candidate, context)) throw new Error('Model candidate does not match this image');
      applyBody = {candidate_id: candidate.candidate_id, expected_revision: before.revision,
        expected_image_sha256: hash, request_id: io.uuid(), replace_all: true, only_unrecognized: true};
      let doc;
      try {
        doc = await io.json(base + '/model-preview/apply', 'POST', applyBody);
        if (!receiptMatches(doc, applyBody)) throw new Error('Missing adoption receipt');
      } catch (error) {
        if (error.status && error.status < 500) throw error;
        // A lost response is not a failed write. Reconcile read-only, never re-run inference.
        const saved = await io.json(base + '/detections').catch(() => null);
        if (receiptMatches(saved, applyBody)) doc = saved;
        else return {name, status: 'uncertain', reason: error.message, stop: true};
      }
      return {name, status: 'completed', doc, before, hash};
    } catch (error) {
      return {name, status: error.status === 409 ? 'skipped' : 'failed', reason: error.message};
    }
  }
  async function recognizeBuiltin(item, io) {
    const {batch, name, engine, params, webMode} = item;
    const base = `/api/batch/${encodeURIComponent(batch)}/image/${encodeURIComponent(name)}`;
    let before, hash, started = false;
    try {
      if (!['component_watershed_v1', 'baseline'].includes(engine)) throw new Error('Unsupported builtin engine');
      before = await io.json(base + '/detections').catch(error => {
        if (error.status === 404) return null;
        throw error;
      });
      let reason = protection(before);
      if (reason) return {name, status: 'skipped', reason};
      if (!webMode) {
        const reference = await io.json(base + '/reference');
        if (reference.status !== 'missing' || reference.reference)
          return {name, status: 'skipped', reason: 'reference'};
      }
      if (!before) before = await io.json(base + '/initialize', 'POST', {mode: 'auto'});
      reason = protection(before);
      if (reason) return {name, status: 'skipped', reason};
      if (!Number.isInteger(before.revision)) throw new Error('Missing saved revision');
      hash = await io.source(base + '/raw');
      if (!/^[a-f0-9]{64}$/.test(hash)) throw new Error('Missing source fingerprint');
      const query = `?engine=${encodeURIComponent(engine)}&expected_revision=${before.revision}`
        + `&protect_existing_edits=true&only_unrecognized=true&expected_image_sha256=${hash}`;
      started = true;
      const doc = await io.json(base + '/run' + query, 'POST', {...params});
      if (!doc?.counted || doc.count_engine !== engine || doc.revision !== before.revision + 1
          || Object.keys(params).some(key => Number(doc.count_params?.[key]) !== Number(params[key])))
        throw new Error('Saved result does not match the requested algorithm');
      return {name, status: 'completed', doc, before, hash};
    } catch (error) {
      // A disconnected run response may already have saved a result. Never retry it
      // or allow a stale current-image edit to overwrite its unknown outcome.
      if (started && (!error.status || error.status >= 500))
        return {name, status: 'uncertain', reason: error.message, stop: true};
      return {name, status: error.status === 409 ? 'skipped' : 'failed', reason: error.message};
    }
  }
  return Object.freeze({protection, receiptMatches, recognize, recognizeBuiltin});
});
