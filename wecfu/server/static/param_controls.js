// Presentation-only mappings. Raw algorithm parameters remain the persistence/API format.
(function (root, factory) {
  const controls = factory();
  if (typeof module === 'object' && module.exports) module.exports = controls;
  else root.WECFU_PARAM_CONTROLS = controls;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const SPECS = Object.freeze({
    min_value:       {id: 'min-value', min: 0, max: 255, integer: true, preview: true},
    max_saturation:  {id: 'max-sat', min: 0, max: 255, integer: true, preview: true},
    plate_inset:     {id: 'inset', min: 0.5, max: 1, preview: true},
    min_circularity: {id: 'circ', min: 0, max: 1},
    min_area_frac:   {id: 'min-area', min: 0.000001, max: 0.01, logarithmic: true},
    peak_min_distance: {id: 'peak', min: 2, max: 80, integer: true, inverse: true},
    radius:         {id: 'radius', min: 3, max: 300, integer: true, logarithmic: true},
  });
  function specFor(key) {
    const spec = SPECS[key];
    if (!spec) throw new Error(`Unknown parameter: ${key}`);
    return spec;
  }
  function clamp(value) { return Math.min(1, Math.max(0, value)); }
  function toNormalized(key, raw) {
    const spec = specFor(key);
    if (!Number.isFinite(raw)) return null;
    const value = Math.min(spec.max, Math.max(spec.min, raw));
    const position = spec.logarithmic
      ? Math.log(value / spec.min) / Math.log(spec.max / spec.min)
      : (value - spec.min) / (spec.max - spec.min);
    return clamp(spec.inverse ? 1 - position : position);
  }
  function fromNormalized(key, normalized) {
    const spec = specFor(key);
    if (!Number.isFinite(normalized)) throw new Error('Slider value must be finite');
    let position = clamp(normalized);
    if (spec.inverse) position = 1 - position;
    const raw = spec.logarithmic
      ? spec.min * Math.pow(spec.max / spec.min, position)
      : spec.min + position * (spec.max - spec.min);
    // Rounding applies only to an explicit user slider edit, never to loaded data.
    return spec.integer ? Math.round(raw) : Number(raw.toPrecision(12));
  }
  function parseNormalizedInput(text) {
    if (typeof text !== 'string') return {valid: false, reason: 'invalid'};
    const trimmed = text.trim();
    if (!trimmed) return {valid: false, reason: 'empty'};
    if (!/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(trimmed)) return {valid: false, reason: 'invalid'};
    const value = Number(trimmed);
    return Number.isFinite(value) && value >= 0 && value <= 1
      ? {valid: true, value} : {valid: false, reason: 'range'};
  }
  function outsideSliderRange(key, raw) {
    const spec = specFor(key);
    return Number.isFinite(raw) && (raw < spec.min || raw > spec.max);
  }
  return Object.freeze({SPECS, toNormalized, fromNormalized, outsideSliderRange, parseNormalizedInput});
});
