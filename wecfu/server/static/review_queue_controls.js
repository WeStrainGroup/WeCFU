// Queue membership is explicit; ordinary viewed/count flags never imply human verification.
(function (root, factory) {
  const helpers = factory();
  if (typeof module === 'object' && module.exports) module.exports = helpers;
  else root.WECFU_REVIEW_QUEUE_CONTROLS = helpers;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const ASSISTED_ENGINE = 'sam2_cv_frozen_v1';
  const STATUSES = Object.freeze(['missing', 'verified', 'stale', 'withdrawn']);
  function queueId(search) {
    const values = new URLSearchParams(search).getAll('review');
    if (!values.length) return null;
    if (values.length !== 1 || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(values[0])) throw new Error('Invalid review queue URL');
    return values[0];
  }
  function plainName(value) {
    return typeof value === 'string' && value.trim() !== '' && !/[\x00-\x1f/\\]/.test(value) && value !== '.' && value !== '..';
  }
  function validate(queue, expectedId) {
    if (!queue || queue.id !== expectedId || !plainName(queue.batch) || typeof queue.title !== 'string'
      || !queue.title.trim() || typeof queue.policy !== 'string' || !queue.policy.trim()
      || !Array.isArray(queue.items) || !queue.items.length || queue.items.length > 1000
      || (expectedId === 'pilot-12' && queue.items.length !== 12)) throw new Error('Invalid review queue manifest');
    if (!['existing', 'manual_only', 'assisted_frozen'].includes(queue.annotation_mode === undefined ? 'existing' : queue.annotation_mode)) {
      throw new Error('Invalid review annotation mode');
    }
    if (queue.annotation_mode === 'assisted_frozen' && queue.engine !== ASSISTED_ENGINE) {
      throw new Error('Invalid frozen review engine');
    }
    const seen = new Set();
    for (const item of queue.items) {
      if (!item || !plainName(item.name) || seen.has(item.name) || !STATUSES.includes(item.reference_status)
        || !(item.group_id === null || (typeof item.group_id === 'string' && item.group_id.trim() && !/[\x00-\x1f]/.test(item.group_id)))) {
        throw new Error('Invalid or duplicate review queue member');
      }
      if (item.context != null && (typeof item.context !== 'string' || !item.context.trim() || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(item.context))) {
        throw new Error('Invalid review item context');
      }
      seen.add(item.name);
    }
    return queue;
  }
  function signature(queue) {
    return JSON.stringify([queue.id, queue.title, queue.batch, queue.policy, queue.annotation_mode || 'existing', queue.engine ?? null,
      queue.items.map(item => [item.name, item.group_id, item.context ?? null])]);
  }
  function filterImages(queue, images) {
    if (!Array.isArray(images)) throw new Error('Invalid image list for review queue');
    const byName = new Map();
    for (const image of images) {
      if (!image || !plainName(image.name) || byName.has(image.name)) throw new Error('Invalid or duplicate batch image');
      byName.set(image.name, image);
    }
    return queue.items.map(item => {
      const image = byName.get(item.name);
      if (!image) throw new Error(`Review image is missing: ${item.name}`);
      return {...image};
    });
  }
  function validateManualState(doc) {
    // Never hide algorithm marks by deleting them or relabeling them as manual.
    if (!doc || doc.mode !== 'manual' || !Array.isArray(doc.detections) || doc.counted === true
      || Number(doc.machine_count_initial || 0) !== 0 || doc.count_engine != null || doc.count_model != null || doc.count_params != null
      || doc.detections.some(mark => mark?.source !== 'manual')) {
      throw new Error('Manual review requires a manual-only image state; existing automatic results were not changed');
    }
    return doc;
  }
  function validateAssistedState(doc) {
    if (!doc || doc.mode !== 'auto' || doc.counted !== true || doc.count_engine !== ASSISTED_ENGINE
      || !Number.isInteger(doc.machine_count_initial) || doc.machine_count_initial < 0
      || !doc.count_model || typeof doc.count_model !== 'object' || Array.isArray(doc.count_model)
      || doc.count_params != null || !Array.isArray(doc.detections)
      || doc.detections.some(mark => !['cv', 'manual'].includes(mark?.source))) {
      throw new Error('Frozen assisted review requires its saved SAM 2 candidates and original provenance');
    }
    const model = doc.count_model;
    if (model.method !== 'sam_cv_seed_area0.05' || model.candidate_count !== doc.machine_count_initial
      || !['model_sha256', 'image_sha256', 'predictions_sha256'].every(key => typeof model[key] === 'string' && /^[a-f0-9]{64}$/i.test(model[key]))
      || !Number.isFinite(model.plate_inset) || model.plate_inset <= 0 || model.plate_inset > 1) {
      throw new Error('Frozen assisted review provenance is incomplete or inconsistent');
    }
    return doc;
  }
  function progress(queue, overrides = new Map()) {
    const counts = {total: queue?.items.length || 0, verified: 0, missing: 0, stale: 0, withdrawn: 0};
    for (const item of queue?.items || []) {
      const status = overrides.get(item.name) || item.reference_status;
      if (STATUSES.includes(status)) counts[status]++;
    }
    return counts;
  }
  function firstUnverified(queue) {
    return (queue.items.find(item => item.reference_status !== 'verified') || queue.items[0]).name;
  }
  return Object.freeze({STATUSES, queueId, validate, signature, filterImages, validateManualState, validateAssistedState, progress, firstUnverified});
});
