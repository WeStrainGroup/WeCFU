// No browser or server required: mapping semantics plus exact-value UI synchronization.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const controls = require('../wecfu/server/static/param_controls.js');
const appSource = fs.readFileSync(path.join(__dirname, '../wecfu/server/static/app.js'), 'utf8');

test('effect directions, endpoints and logarithmic area scale', () => {
  assert.equal(controls.fromNormalized('min_value', 0), 0);
  assert.equal(controls.fromNormalized('min_value', 1), 255);
  assert.equal(controls.fromNormalized('max_saturation', 1), 255);
  assert.equal(controls.fromNormalized('plate_inset', 1), 1);
  assert.equal(controls.fromNormalized('min_circularity', 1), 1);
  assert.equal(controls.fromNormalized('peak_min_distance', 0), 80);
  assert.equal(controls.fromNormalized('peak_min_distance', 1), 2);
  // Middle position represents the geometric mean, not the arithmetic mean.
  assert.equal(controls.fromNormalized('min_area_frac', .5), .0001);
  assert.equal(controls.toNormalized('min_area_frac', .0001), .5);
  assert.equal(controls.fromNormalized('radius', 0), 3);
  assert.equal(controls.fromNormalized('radius', 1), 300);
  for (const [key, spec] of Object.entries(controls.SPECS)) {
    let previous = controls.fromNormalized(key, 0);
    for (let step = 1; step <= 100; step++) {
      const current = controls.fromNormalized(key, step / 100);
      assert.ok(current >= spec.min && current <= spec.max, `${key} remains in range`);
      assert.ok(spec.inverse ? current <= previous : current >= previous, `${key} follows its direction`);
      previous = current;
    }
  }
});

test('unusual raw values are clamped for presentation only and remain recognizable', () => {
  assert.equal(controls.toNormalized('min_area_frac', 7e-8), 0);
  assert.equal(controls.outsideSliderRange('min_area_frac', 7e-8), true);
  assert.equal(controls.toNormalized('peak_min_distance', 123), 0);
  assert.equal(controls.outsideSliderRange('peak_min_distance', 123), true);
  assert.equal(controls.toNormalized('min_value', NaN), null);
  assert.throws(() => controls.fromNormalized('min_value', NaN));
});

function createUI(stubChanges = true) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      value: id === 'p-radius' ? '40' : '', checked: true, hidden: false, dataset: {}, classList: {toggle() {}},
      style: {setProperty() {}}, setAttribute() {},
      checkValidity() { return this.value !== '' && Number.isFinite(Number(this.value)); },
    });
    return elements.get(id);
  }
  const context = vm.createContext({
    window: {WECFU_PARAM_CONTROLS: controls,
      WECFU_I18N: {t: key => key}, addEventListener() {}},
    document: {getElementById: element}, console,
  });
  vm.runInContext(appSource, context);
  // Mapping tests do not save, draw, or contact a server.
  if (stubChanges) vm.runInContext('parametersChanged = () => {};', context);
  return {element, context, run: expression => vm.runInContext(expression, context)};
}
function plain(value) { return JSON.parse(JSON.stringify(value)); }

test('loading precise old values never round-trips them through sliders', () => {
  const ui = createUI();
  const raw = {plate_inset: .333333333333, min_value: 197, max_saturation: 93,
    min_circularity: .1234567890123, min_area_frac: 7.123456789e-8, peak_min_distance: 123};
  ui.context.loadedValues = raw;
  ui.run('fillParams(loadedValues); syncSliders(); syncSliders();');
  assert.deepEqual(plain(ui.run('paramsBody()')), raw);
  assert.equal(ui.element('slider-range-warning').hidden, false);
  assert.equal(ui.element('v-peak').value, '0.00');
  assert.equal(ui.element('v-peak').title, 'sliderRangeWarning');
  ui.element('s-max-sat').value = '0.9';
  ui.run("sliderChanged('max_saturation');");
  assert.deepEqual(plain(ui.run('paramsBody()')), {...raw, max_saturation: 230});
});

test('new defaults are explicit while legacy and color presets retain exact values', () => {
  const ui = createUI();
  const presets = plain(ui.run('PRESETS'));
  const original = {plate_inset: .82, min_value: 200, max_saturation: 60, min_circularity: .55, min_area_frac: .0001, peak_min_distance: 15};
  assert.deepEqual(presets, {white: {...original, plate_inset: .88, max_saturation: 100}, legacy: original, cream: {...original, min_value: 180, max_saturation: 100},
    yellow: {...original, min_value: 160, max_saturation: 200, min_circularity: .50},
    any: {...original, min_value: 140, max_saturation: 255, min_circularity: .45}});
  for (const [name, raw] of Object.entries(presets)) {
    ui.run(`fillParams(PRESETS[${JSON.stringify(name)}]);`);
    assert.deepEqual(plain(ui.run('paramsBody()')), raw);
    assert.equal(ui.element('preset-select').value, name);
  }
  for (const previewChoice of [false, true]) {
    ui.element('p-preview').checked = previewChoice;
    ui.element('p-radius').value = '147.25';
    ui.run('resetDefaults();');
    assert.deepEqual(plain(ui.run('paramsBody()')), plain(ui.run('DEFAULTS')));
    assert.equal(ui.element('p-preview').checked, previewChoice);
    assert.equal(ui.element('p-radius').value, '147.25', 'recognition reset preserves independent manual marker size');
  }
});

test('only brightness, color and inset advertise live threshold updates', () => {
  const supported = Object.entries(controls.SPECS).filter(([, spec]) => spec.preview).map(([key]) => key);
  assert.deepEqual(supported, ['min_value', 'max_saturation', 'plate_inset']);
});

test('count-only controls save their values without requesting a misleading preview', () => {
  const ui = createUI(false);
  ui.run(`
    let previewCalls = 0;
    refreshMaskPreview = () => { previewCalls++; };
    updateControls = () => {};
    queueSave = () => {};
    state.doc = {params: {...DEFAULTS}, mode: 'auto', count_params: {...DEFAULTS}};
    fillParams(DEFAULTS);
  `);
  for (const key of ['min_circularity', 'min_area_frac', 'peak_min_distance']) {
    ui.run(`parametersChanged(${JSON.stringify(key)});`);
  }
  assert.equal(ui.run('previewCalls'), 0);
  for (const key of ['min_value', 'max_saturation', 'plate_inset']) {
    ui.run(`parametersChanged(${JSON.stringify(key)});`);
  }
  assert.equal(ui.run('previewCalls'), 3);
});


test('normalized text parser accepts decimal boundaries without clamping malformed or out-of-range input', () => {
  for (const text of ['0', '1', '.5', '0.50', '1.', ' 0.125 ', '00.00']) {
    assert.deepEqual(controls.parseNormalizedInput(text), {valid: true, value: Number(text)});
  }
  for (const text of ['', '  ']) assert.deepEqual(controls.parseNormalizedInput(text), {valid: false, reason: 'empty'});
  for (const text of ['-1', '+0.5', '1e-1', '0x0', 'NaN', 'Infinity', '0.2foo', '0 .2', null, .5, {}, true]) {
    assert.deepEqual(controls.parseNormalizedInput(text), {valid: false, reason: 'invalid'});
  }
  for (const text of ['1.01', '2', '9'.repeat(400)]) assert.deepEqual(controls.parseNormalizedInput(text), {valid: false, reason: 'range'});
});
