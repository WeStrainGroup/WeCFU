// Human-reference status is separate from the ordinary viewed/reviewed flag.
(function (root, factory) {
  const helpers = factory();
  if (typeof module === 'object' && module.exports) module.exports = helpers;
  else root.WECFU_REFERENCE_CONTROLS = helpers;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function geometrySignature(plate, detections) {
    if (!plate) return null;
    const geometry = (detections || []).map(d => Array.isArray(d) ? [d[0], d[1], d[2]] : [d.cx, d.cy, d.r]);
    geometry.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
    return JSON.stringify([[plate.cx, plate.cy, plate.r], geometry]);
  }
  function reviewScope(reference) {
    const scope = reference?.review_scope;
    return scope?.colony_count_reviewed === true && scope.colony_center_points_reviewed === true
      && typeof scope.plate_crop_reviewed === 'boolean' ? scope : null;
  }
  function centerSignature(detections) {
    const centers = (detections || []).map(d => Array.isArray(d) ? [d[0], d[1]] : [d.cx, d.cy]);
    centers.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    return JSON.stringify(centers);
  }
  function plateSignature(plate) { return plate ? JSON.stringify([plate.cx, plate.cy, plate.r]) : null; }
  function plateStatus(envelope, plate, displayedSourceHash) {
    const reference = envelope?.reference;
    if (!reference) return 'unreviewed';
    const scope = reviewScope(reference);
    if (!scope) return 'legacy';
    if (!scope.plate_crop_reviewed) return 'unreviewed';
    if (envelope.status === 'withdrawn') return 'withdrawn';
    if (envelope.status !== 'verified' || !displayedSourceHash || reference.sha256 !== displayedSourceHash
      || plateSignature(plate) !== plateSignature(reference.plate)) return 'stale';
    return 'verified';
  }
  function displayStatus(envelope, plate, detections, displayedSourceHash) {
    if (!envelope) return 'unloaded';
    if (envelope.status !== 'verified') return envelope.status;
    const reference = envelope.reference;
    if (!reference || !displayedSourceHash || reference.sha256 !== displayedSourceHash) return 'stale';
    const scope = reviewScope(reference);
    if (scope) {
      const centersMatch = centerSignature(detections) === centerSignature(reference.detections_geometry);
      const plateMatches = !scope.plate_crop_reviewed || plateSignature(plate) === plateSignature(reference.plate);
      return centersMatch && plateMatches ? 'verified' : 'stale';
    }
    // Older records keep their original geometry binding; never infer a crop attestation.
    return geometrySignature(plate, detections) === geometrySignature(reference.plate, reference.detections_geometry)
      ? 'verified' : 'stale';
  }
  return Object.freeze({geometrySignature, reviewScope, centerSignature, plateStatus, displayStatus});
});
