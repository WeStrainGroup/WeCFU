// Small UI decisions only: no requests, image access, inference or persisted state.
(function (root, factory) {
  const helpers = factory();
  if (typeof module === 'object' && module.exports) module.exports = helpers;
  else root.WECFU_WORKFLOW_CONTROLS = helpers;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function defaultEngine() {
    // The released Default profile always means Fusion v2. Missing models are
    // reported to the user; Custom is the explicit traditional alternative.
    return 'sam_dino_fusion_local_v2';
  }
  function ownsArrowKeys(target) {
    if (!target) return false;
    if (target.isContentEditable || target.closest?.('[contenteditable="true"], [role="textbox"]')) return true;
    const tag = String(target.tagName || '').toUpperCase();
    // Select keeps native option navigation until a choice is committed. Its change handler
    // returns focus to the canvas; text/number/range editing never does so automatically.
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
  }
  function navigationDelta(event, target, modalOpen) {
    if (modalOpen || event.defaultPrevented || event.isComposing || event.ctrlKey || event.metaKey
      || event.altKey || event.shiftKey || ownsArrowKeys(target)) return 0;
    if (event.key === 'ArrowRight' || event.key === 'j') return 1;
    if (event.key === 'ArrowLeft' || event.key === 'k') return -1;
    return 0;
  }
  function visibleScrollTop({scrollTop, clientHeight, scrollHeight, viewportTop, rowTop, rowBottom}) {
    if (![scrollTop, clientHeight, scrollHeight, viewportTop, rowTop, rowBottom].every(Number.isFinite)
      || clientHeight <= 0) return scrollTop;
    let next = scrollTop;
    if (rowTop < viewportTop) next += rowTop - viewportTop;
    else if (rowBottom > viewportTop + clientHeight) next += rowBottom - viewportTop - clientHeight;
    return Math.max(0, Math.min(Math.max(0, scrollHeight - clientHeight), next));
  }
  function batchProtection(doc, reference) {
    if (doc?.mode === 'manual') return 'manual';
    if (doc?.reviewed || doc?.plate_manual || doc?.notes?.trim()
      || doc?.detections?.some(mark => mark.source === 'manual')) return 'edited';
    if (reference?.reference || ['verified', 'stale', 'withdrawn'].includes(reference?.status)) return 'reference';
    // A successful explicit missing response is required; unknown state is never permission.
    if (reference?.status !== 'missing') return 'unknown';
    return null;
  }
  return Object.freeze({defaultEngine, ownsArrowKeys, navigationDelta, visibleScrollTop, batchProtection});
});
