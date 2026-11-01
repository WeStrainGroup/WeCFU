const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('complete translation script loads and exposes new user-facing labels', () => {
  const storage = new Map();
  const context = vm.createContext({
    window: {},
    localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    document: { querySelectorAll: () => [], documentElement: {} },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../wecfu/server/static/i18n.js'), 'utf8'), context);
  const i18n = context.window.WECFU_I18N;
  assert.equal(i18n.t('normalizedValueInvalid'), 'Enter a value from 0 to 1.');
  assert.equal(i18n.t('importView'), 'Import as');
  assert.equal(i18n.t('viewFront'), 'Front of plate');
  i18n.setLang('zh-CN');
  assert.equal(i18n.t('normalizedValueInvalid'), '请输入 0 到 1 之间的数值。');
  assert.equal(i18n.t('importView'), '导入为');
  assert.equal(i18n.t('viewFront'), '培养皿正面');
  assert.equal(i18n.t('modelUnavailable'), '默认识别暂不可用。');
});
