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
  'addImages', 'ingestBtn', 'profileDefault', 'profileClassical', 'profileCustom',
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

test('all help locales distinguish recognition, review and temporary sessions', () => {
  const i18n = loadI18n();
  const facts = {
    en: [/does not start recognition/, /does not recognize photos/, /unapplied changes are not used/, /existing results first appear as a preview/, /Lite recounts directly/, /Viewing does not confirm/, /opens an empty session/, /Refreshing the page keeps it/, /fully stopping the local server clears/, /workspace .* is retained/, /temporary server session/],
    'zh-CN': [/导入不会自动识别/, /不执行识别/, /未应用的修改不会用于识别/, /已有结果先显示预览/, /Lite 直接重新计数/, /仅浏览不算确认/, /常规本地启动进入空白会话/, /刷新页面保留当前内容/, /完全停止本地服务后/, /工作区.*保留数据/, /临时服务器会话/],
    fr: [/L’importation ne lance pas la reconnaissance/, /sans lancer la reconnaissance/, /les changements non appliqués ne sont pas utilisés/, /s’il existe déjà un résultat, un aperçu s’affiche/, /Lite recompte directement/, /Consulter ne vaut pas confirmer/, /démarrage local normal ouvre une session vide/, /Actualiser la page la conserve/, /arrêter complètement le serveur local supprime/, /espace explicitement choisi .* est conservé/, /session temporaire sur le serveur/],
    ru: [/Импорт не запускает распознавание/, /но не запускает распознавание/, /неприменённые изменения не используются/, /при наличии результата сначала показывает предпросмотр/, /Lite сразу пересчитывает/, /Просмотр не считается подтверждением/, /локальный запуск открывает пустой сеанс/, /Обновление страницы его сохраняет/, /полная остановка локального сервера очищает/, /рабочая область .* сохраняется/, /временный сеанс на сервере/],
  };
  for (const locale of locales) {
    i18n.setLang(locale);
    for (const fact of facts[locale]) assert.match(i18n.t('helpBody'), fact, `${locale}: ${fact}`);
  }
});
