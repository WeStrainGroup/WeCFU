// Temporary model results never become editable state until an explicit apply.
(function (root, factory) {
  const helpers = factory();
  if (typeof module === 'object' && module.exports) module.exports = helpers;
  else root.WECFU_MODEL_PREVIEW_CONTROLS = helpers;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const ENGINE = 'cfucounter_onnx_author_v1';
  const SAM_ENGINE = 'sam2_local_v1';
  const FUSION_ENGINE = 'sam_dino_fusion_local_v1';
  const FUSION_V2_ENGINE = 'sam_dino_fusion_local_v2';
  const FUSION_V2_RECIPE = 'sam_dino_raw10_threshold075_auto095_v2';
  const FUSION_V2_PROJECTION = Object.freeze([0,1,2,5,6,7,8,9,10,11]);
  const FUSION_RECIPE = 'sam_dino_full88_residual12_threshold075_auto095_v1';
  const FUSION_ANNOTATION = 'SAM_D0_plus_box_derived_center_rings';
  const SAM_RECIPE = 'sam_cv_seed_area0.05_color160_edge095_v1';
  const SAM_INSET = .95;
  function isFusionEngine(engine) { return engine === FUSION_ENGINE || engine === FUSION_V2_ENGINE; }
  function fusionRecipe(engine) { return engine === FUSION_V2_ENGINE ? FUSION_V2_RECIPE : FUSION_RECIPE; }
  function isModelEngine(engine) { return engine === ENGINE || engine === SAM_ENGINE || isFusionEngine(engine); }
  function capability(config, engine) {
    if (engine === ENGINE) return config?.experimental_models?.cfucounter || {enabled: false, available: false};
    if (isFusionEngine(engine)) {
      const fusion = engine === FUSION_V2_ENGINE ? config?.models?.fusion_v2 : config?.models?.fusion;
      if (fusion?.engine !== engine) return {enabled: false, available: false};
      return {...fusion, enabled: fusion.enabled === true, available: fusion.enabled === true && fusion.available === true
        && fusion.recipe_id === fusionRecipe(engine) && /^[a-f0-9]{64}$/.test(fusion.model_sha256 || '')};
    }
    const sam = config?.models?.sam2;
    if (engine !== SAM_ENGINE || sam?.engine !== SAM_ENGINE) return {enabled: false, available: false};
    return {...sam, enabled: sam.enabled !== false, available: sam.enabled !== false && sam.available === true && sam.recipe_id === SAM_RECIPE
      && /^[a-f0-9]{64}$/.test(sam.model_sha256 || '')};
  }
  function signature(key, hash, plate, params, mode, detections, engine = null, model = null) {
    const marks = (detections || []).map(d => [d.id, d.cx, d.cy, d.r, d.source]);
    const settings = Object.keys(params || {}).sort().map(key => [key, params[key]]);
    return JSON.stringify([key, hash, plate && [plate.cx, plate.cy, plate.r], settings, mode, marks,
      engine, model?.model_sha256 || null, model?.recipe_id || null]);
  }
  function expiresAt(candidate) {
    return typeof candidate?.expires_at === 'number' ? candidate.expires_at * 1000 : Date.parse(candidate?.expires_at);
  }
  function valid(candidate, context, now = Date.now()) {
    if (!candidate || !context || !candidate.candidate_id || !context.hash || !Number.isInteger(context.revision)
      || candidate.base_revision !== context.revision || candidate.image_sha256 !== context.hash
      || !Number.isFinite(expiresAt(candidate)) || expiresAt(candidate) <= now) return false;
    if (context.engine && candidate.engine !== context.engine) return false;
    if (context.model_sha256 && candidate.model_sha256 !== context.model_sha256) return false;
    if (context.recipe_id && (candidate.recipe_id ?? candidate.model_params?.recipe_id) !== context.recipe_id) return false;
    if (isFusionEngine(context.engine)) {
      const provenance = candidate.fusion_provenance;
      if (!provenance || provenance.annotation_kind !== FUSION_ANNOTATION
        || provenance.model_sha256 !== candidate.model_sha256 || provenance.recipe_id !== fusionRecipe(context.engine)
        || provenance.image_sha256 !== candidate.image_sha256 || provenance.plate_inset !== SAM_INSET
        || provenance.candidate_count !== candidate.candidate_count
        || !Number.isInteger(provenance.d0_count) || provenance.d0_count < 0
        || !Number.isInteger(provenance.supplemental_count) || provenance.supplemental_count < 0
        || provenance.d0_count + provenance.supplemental_count !== candidate.candidate_count) return false;
      if (context.engine === FUSION_V2_ENGINE && (!['main', 'blank'].includes(provenance.source_view)
        || JSON.stringify(provenance.feature_projection) !== JSON.stringify(FUSION_V2_PROJECTION)
        || provenance.coordinate_method !== 'raw_DINO_unchanged'
        || provenance.D0_exclusion_fraction !== .025
        || provenance.DINO_dedup_fraction !== .005 || provenance.ROI_max_radial !== .95
        || !['filter_artifact_sha256',
          'sam_model_sha256', 'dino_model_sha256', 'detector_contract_sha256'].every(key => /^[a-f0-9]{64}$/.test(provenance[key] || '')))) return false;
    }
    return ['cx', 'cy', 'r'].every(key => candidate.plate?.[key] === context.plate?.[key])
      && candidate.model_params?.plate_inset === context.inset;
  }
  function ambiguous(error) { return !error?.status || error.status >= 500; }
  function roiCircle(plate, inset) {
    const value = Number(inset);
    if (!plate || ![plate.cx, plate.cy, plate.r, value].every(Number.isFinite)
      || plate.r <= 0 || value <= 0 || value > 1) return null;
    return {cx: plate.cx, cy: plate.cy, r: plate.r * value};
  }
  return Object.freeze({ENGINE, SAM_ENGINE, SAM_RECIPE, SAM_INSET, FUSION_ENGINE, FUSION_RECIPE, FUSION_ANNOTATION, FUSION_V2_ENGINE, FUSION_V2_RECIPE, FUSION_V2_PROJECTION, isFusionEngine, isModelEngine, capability,
    signature, expiresAt, valid, ambiguous, roiCircle});
});
