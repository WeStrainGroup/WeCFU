const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadI18n(storedLanguage) {
  const storage = new Map();
  if (storedLanguage !== undefined) storage.set('wecfu.lang', storedLanguage);
  const context = vm.createContext({
    window: {},
    localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    document: { querySelectorAll: () => [], documentElement: {} },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../wecfu/server/static/i18n.js'), 'utf8'), context);
  return context.window.WECFU_I18N;
}

const locales = ['en', 'zh-CN', 'fr', 'ru'];
const helpActions = [
  'addImages', 'chooseFolder', 'ingestBtn', 'profileDefault', 'profileClassical', 'profileCustom',
  'recognizeAll', 'recognizeCurrent', 'stopCounting', 'modelApply', 'modelDiscard',
  'livePreview', 'applyParams', 'openAdjustments',
  'manualMarkSettings', 'imageActions', 'adjustCrop', 'bulkDeleteMode',
  'selectAllImages', 'deleteSelectedImages', 'exportMenu', 'referenceTitle', 'referenceSave',
];
const oldApplyLabels = /Apply and recount|应用并重新计数|Appliquer et recompter/i;
const removedRefinementLabels = /Detailed check|精细补检|Vérification détaillée/i;

test('supported locales are English, Chinese, French and Russian', () => {
  const i18n = loadI18n();
  assert.deepEqual(Object.keys(i18n.LANG_NAMES), locales);
  assert.deepEqual(Object.keys(i18n.I18N), locales);
  assert.equal(i18n.LANG_NAMES.ru, 'Русский');
  assert.equal(i18n.getLang(), 'en');
  assert.equal(i18n.t('normalizedValueInvalid'), 'Enter a value from 0 to 1.');
  i18n.setLang('zh-CN');
  assert.equal(i18n.t('normalizedValueInvalid'), '请输入 0 到 1 之间的数值。');
  assert.equal(i18n.t('profileDefault'), 'Ultra');
  assert.equal(i18n.t('profileClassical'), 'Lite');
  assert.equal(i18n.t('profileCustom'), '自定义');
});

test('English is the first-launch and removed-locale fallback; supported preferences persist', () => {
  for (const stored of [undefined, '', 'ja', 'es', 'unknown', '__proto__', 'constructor']) {
    assert.equal(loadI18n(stored).getLang(), 'en', `stored locale: ${stored}`);
  }
  for (const stored of locales) assert.equal(loadI18n(stored).getLang(), stored);
  const i18n = loadI18n('ru');
  i18n.setLang('ja');
  assert.equal(i18n.getLang(), 'ru', 'removed language cannot replace an active supported choice');
  i18n.setLang('en');
  assert.equal(i18n.getLang(), 'en');
});

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
    assert.doesNotMatch(body, removedRefinementLabels);
    assert.doesNotMatch(i18n.t('applyParams'), oldApplyLabels);
    assert.doesNotMatch(i18n.t('paramsChanged'), oldApplyLabels);
    assert.equal(Object.hasOwn(i18n.I18N[locale], 'refineCurrent'), false);
    assert.equal(Object.hasOwn(i18n.I18N[locale], 'refineCurrentHint'), false);
    for (const match of body.matchAll(/<\/?([a-z0-9]+)\b/g)) {
      assert.ok(['h3', 'p', 'b', 'section'].includes(match[1]), `unexpected help tag: ${match[1]}`);
    }
    for (const key of helpActions) {
      const label = i18n.t(key);
      assert.notEqual(label, key);
      assert.ok(body.includes(label), `${key}: help must use visible label ${label}`);
    }
    for (const term of ['Ultra', 'Lite', 'SAM', 'CSV', 'ZIP', '--root']) assert.ok(body.includes(term));
    assert.equal((help.match(/mailto:/g) || []).length, 4, 'preserve all author contact credits');
    if (locale === 'en') {
      const words = body.replace(/<[^>]*>/g, ' ').trim().split(/\s+/);
      assert.ok(words.length <= 550, `${words.length} English words exceeds the short-help budget`);
    }
  });
}

test('Russian has every UI translation and preserves interpolation placeholders', () => {
  const { I18N } = loadI18n();
  assert.deepEqual(Object.keys(I18N.ru).sort(), Object.keys(I18N.en).sort());
  const languageIndependent = new Set(['appTitle', 'statusReady', 'profileDefault', 'profileClassical', 'classicalRoute']);
  const placeholders = text => [...text.matchAll(/\{([a-zA-Z]+)\}/g)].map(match => match[1]).sort();
  for (const [key, value] of Object.entries(I18N.en)) {
    if (!languageIndependent.has(key)) {
      assert.notEqual(I18N.ru[key], value, `${key} must have a Russian translation`);
      assert.match(I18N.ru[key], /[А-Яа-яЁё]/, `${key} must contain Russian text`);
    }
    assert.deepEqual(placeholders(I18N.ru[key]), placeholders(value), `${key} interpolation differs`);
  }
});

test('every locale supplies native folder messages and mode/batch explanations', () => {
  const { I18N } = loadI18n();
  const keys = ['chooseFolder', 'chooseFolderTitle', 'chooseFolderFailed', 'chooseFolderUnavailable',
    'modeInfoUltra', 'modeInfoLite', 'modeInfoCustom', 'customBatchScopeHint',
    'countCompleted', 'countSkipped', 'batchAlreadyCounted', 'batchProtected'];
  for (const locale of locales) {
    for (const key of keys) {
      assert.equal(typeof I18N[locale][key], 'string', `${locale} must not fall back for ${key}`);
      assert.ok(I18N[locale][key].trim(), `${locale}: empty ${key}`);
      if (locale !== 'en') assert.notEqual(I18N[locale][key], I18N.en[key], `${locale}: untranslated ${key}`);
    }
  }
});

test('help separates batch policies, browsing, verification and desktop/browser saving', () => {
  const i18n = loadI18n();
  const facts = {
    en: [/does not start recognition/, /does not run recognition/, /Unapplied changes are not used/,
      /only unrecognized photos/, /recounts machine-only results/, /including withdrawn records/,
      /Photos you have only viewed are still recounted/, /A dark dot does not mean the result has been verified/,
      /desktop app.*system folder picker/, /desktop app opens a system save dialog/,
      /browser uses its download settings/, /Export before closing/, /opens an empty session/,
      /refreshing keeps the current work/, /workspace.*is retained/, /temporary sessions/],
    'zh-CN': [/导入后不会自动识别/, /不会立即识别/, /未应用的改动不会用于识别/,
      /只处理尚未识别的照片/, /重算只有机器结果的照片/, /即使撤回核验，也不会批量重算/,
      /仅浏览过照片不会导致跳过/, /深灰不代表核验通过/,
      /桌面版.*系统窗口/, /桌面版会打开系统保存窗口/, /浏览器版按浏览器的下载设置保存/,
      /关闭前请先导出/, /常规本地启动进入空白会话/, /刷新页面会保留当前内容/, /工作区会保留数据/, /临时会话/],
    fr: [/L’importation ne lance pas la reconnaissance/, /sans lancer de comptage/, /Les changements non appliqués ne sont pas utilisés/,
      /uniquement les photos non encore reconnues/, /recalcule aussi les résultats purement automatiques/,
      /ayant un historique de vérification sont également exclues, même après le retrait/, /photo simplement consultée peut toujours être recalculée/,
      /Gris foncé.*sans garantie de vérification/, /application de bureau.*sélecteur de dossiers/,
      /application de bureau ouvre la fenêtre d’enregistrement/, /navigateur.*réglages de téléchargement/,
      /Exportez avant de fermer/, /ouvre une session vide/, /actualiser la page conserve/, /espace choisi.*est conservé/, /sessions temporaires/],
    ru: [/импорт не запускает распознавание/, /не запуская распознавание/, /Неприменённые изменения не используются/,
      /только ещё не распознанные фотографии/, /пересчитывает и готовые машинные результаты/,
      /не пересчитываются пакетно, даже если подтверждение отозвано/, /Один лишь просмотр фотографии не мешает пересчёту/,
      /Тёмно-серый.*не подтверждение точности/, /настольном приложении.*системное окно выбора папки/,
      /Настольное приложение открывает системное окно сохранения/, /браузер использует свои настройки загрузки/,
      /Экспортируйте результаты перед закрытием/, /локальный запуск открывает пустой сеанс/,
      /обновление страницы сохраняет/, /Рабочая область.*сохраняется между запусками/, /временные сеансы/],
  };
  for (const locale of locales) {
    i18n.setLang(locale);
    for (const fact of facts[locale]) assert.match(i18n.t('helpBody'), fact, `${locale}: ${fact}`);
  }
});
