const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadI18n() {
  const storage = new Map();
  const context = vm.createContext({
    window: {},
    localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    document: { querySelectorAll: () => [], documentElement: {} },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../wecfu/server/static/i18n.js'), 'utf8'), context);
  return context.window.WECFU_I18N;
}

test('complete translation script loads and exposes new user-facing labels', () => {
  const i18n = loadI18n();
  assert.equal(i18n.t('normalizedValueInvalid'), 'Enter a value from 0 to 1.');
  assert.equal(i18n.t('importView'), 'Import as');
  assert.equal(i18n.t('viewFront'), 'Front of plate');
  i18n.setLang('zh-CN');
  assert.equal(i18n.t('normalizedValueInvalid'), '请输入 0 到 1 之间的数值。');
  assert.equal(i18n.t('importView'), '导入为');
  assert.equal(i18n.t('viewFront'), '培养皿正面');
  assert.equal(i18n.t('modelUnavailable'), '此识别方法暂不可用。');
  assert.equal(i18n.t('defaultRoute'), '默认：算法 + SAM');
  assert.equal(i18n.t('profileClassical'), 'Lite');
  assert.equal(i18n.t('classicalRoute'), 'Lite');
  assert.match(i18n.t('defaultBatchHint'), /算法 \+ SAM/);
  assert.equal(i18n.t('refineCurrent'), '精细补检 · SAM');
  assert.equal(i18n.t('customRoute'), '自定义：增强算法');
});

const locales = ['en', 'zh-CN', 'ja', 'es', 'fr'];
const helpActions = [
  'addImages', 'ingestBtn', 'profileDefault', 'profileClassical', 'profileCustom',
  'recognizeAll', 'recognizeCurrent', 'stopCounting', 'modelApply', 'modelDiscard',
  'refineCurrent', 'livePreview', 'applyParams', 'openAdjustments',
  'manualMarkSettings', 'imageActions', 'adjustCrop', 'bulkDeleteMode',
  'selectAllImages', 'deleteSelectedImages', 'exportMenu', 'referenceTitle', 'referenceSave',
];
const oldApplyLabels = /Apply and recount|应用并重新计数|適用して再カウント|Aplicar y recontar|Appliquer et recompter/i;

for (const locale of locales) {
  test(`${locale} help is localized, concise and matches visible actions`, () => {
    const i18n = loadI18n();
    i18n.setLang(locale);
    const help = i18n.t('helpBody');
    const body = help.split('<div class="help-footer">')[0];
    assert.equal((body.match(/<h3>/g) || []).length, 7);
    assert.equal((body.match(/<section class="review-help">/g) || []).length, 1);
    if (locale !== 'en') assert.notEqual(help, i18n.I18N.en.helpBody, 'must not use the English help fallback');
    assert.doesNotMatch(body, /DINO|CFUCounter|torch|conda|CUDA/i);
    assert.doesNotMatch(body, oldApplyLabels);
    assert.doesNotMatch(i18n.t('applyParams'), oldApplyLabels);
    assert.doesNotMatch(i18n.t('paramsChanged'), oldApplyLabels);
    for (const match of body.matchAll(/<\/?([a-z0-9]+)\b/g)) {
      assert.ok(['h3', 'p', 'b', 'section'].includes(match[1]), `unexpected help tag: ${match[1]}`);
    }
    for (const key of helpActions) {
      const label = i18n.t(key);
      assert.notEqual(label, key);
      assert.ok(body.includes(label), `${key}: help must use visible label ${label}`);
    }
    assert.match(body, /Ultra/);
    assert.match(body, /Lite/);
    assert.match(body, /SAM/);
    assert.match(body, /CSV/);
    assert.match(body, /ZIP/);
    assert.equal((help.match(/mailto:/g) || []).length, 4, 'preserve all author contact credits');
    if (locale === 'en') {
      const words = body.replace(/<[^>]*>/g, ' ').trim().split(/\s+/);
      assert.ok(words.length <= 500, `${words.length} English words exceeds the short-help budget`);
    }
  });
}

test('Japanese, Spanish and French own the newer workflow labels instead of falling back to English', () => {
  const i18n = loadI18n();
  const translatedKeys = [
    'profileCustom', 'recognizeCurrent', 'recognizeAll', 'modeInfo',
    'modeInfoUltra', 'modeInfoLite', 'modeInfoCustom', 'applyParams',
    'openAdjustments', 'collapseAdjustments', 'adjustmentsPending', 'customDraftHint',
    'modelApply', 'modelDiscard', 'bulkDeleteMode', 'deleteSelectedImages', 'selectAllImages',
  ];
  for (const locale of ['ja', 'es', 'fr']) {
    i18n.setLang(locale);
    for (const key of translatedKeys) {
      assert.ok(Object.hasOwn(i18n.I18N[locale], key), `${locale} lacks ${key}`);
      assert.notEqual(i18n.t(key), i18n.I18N.en[key], `${locale} still uses English ${key}`);
    }
    assert.equal(i18n.t('profileDefault'), 'Ultra');
    assert.equal(i18n.t('profileClassical'), 'Lite');
    assert.match(i18n.t('bulkDeleteConfirm'), /\{count\}/, 'retain the runtime quantity placeholder');
    assert.match(i18n.t('imagesSelected'), /\{count\}/);
  }
});

test('all help locales distinguish applying settings, recognition and formal review', () => {
  const i18n = loadI18n();
  const facts = {
    en: [/does not start recognition/, /does not recognize photos/, /unapplied changes are not used/, /existing results first appear as a preview/, /Lite recounts directly/, /Viewing does not confirm/, /temporary server session/],
    'zh-CN': [/导入不会自动识别/, /不执行识别/, /未应用的修改不会用于识别/, /已有结果先显示预览/, /Lite 直接重新计数/, /仅浏览不算确认/, /临时服务器会话/],
    ja: [/取り込むだけでは認識は始まりません/, /認識は実行しません/, /未適用の変更は使われません/, /既存の結果がある場合はプレビュー/, /Lite は直接再計数/, /閲覧だけでは確認になりません/, /一時的なサーバーセッション/],
    es: [/Importar no inicia el reconocimiento/, /no reconoce fotos/, /los cambios sin aplicar no se usan/, /si ya existen resultados, muestra una vista previa/, /Lite recalcula directamente/, /Mirar una foto no la verifica/, /sesión temporal del servidor/],
    fr: [/L’importation ne lance pas la reconnaissance/, /sans lancer la reconnaissance/, /les changements non appliqués ne sont pas utilisés/, /s’il existe déjà un résultat, un aperçu s’affiche/, /Lite recompte directement/, /Consulter ne vaut pas confirmer/, /session temporaire sur le serveur/],
  };
  for (const locale of locales) {
    i18n.setLang(locale);
    for (const fact of facts[locale]) assert.match(i18n.t('helpBody'), fact, `${locale}: ${fact}`);
  }
});
