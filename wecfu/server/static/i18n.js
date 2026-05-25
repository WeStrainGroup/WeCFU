// Lightweight i18n for WeCFU.
//
// English is the source of truth. Other languages keyed by the same string ids.
// Translations missing in a non-English language fall back to English.
//
// Apply by calling t('key') in JS, or by tagging HTML elements with
//   data-i18n="key"            → element.textContent
//   data-i18n-placeholder="..."→ element.placeholder
//   data-i18n-title="..."      → element.title

const I18N = {
  en: {
    appTitle: 'WeCFU',
    language: 'Language',
    helpButton: 'Help',
    dropHint: 'Drop image files or a folder here',
    dropSubHint: '(symlinked — your originals are not modified)',
    pasteHint: 'Or paste an absolute path:',
    ingestBtn: 'Ingest path',
    countAll: 'Count all',
    countOne: 'Re-count',
    undo: '↶ Undo',
    markReviewed: 'Mark reviewed',
    exportCSV: 'Export CSV…',
    exportBundle: 'Export bundle…',
    selectAnImage: '— select an image —',
    cfuSuffix: 'CFU',
    notProcessed: '— (not counted)',
    legend: '<b>Left-click</b> empty space to add · <b>Right-click</b> a circle to delete · <b>Wheel</b> to zoom · <b>Cmd/Ctrl+drag</b> to pan · <b>← →</b> previous/next · <b>Space</b> mark reviewed',
    legendAuto: 'auto',
    legendManual: 'manual',
    presetLabel: 'Preset',
    presetWhite: 'White colonies (default)',
    presetCream: 'Cream / pale yellow',
    presetYellow: 'Yellow colonies',
    presetAny: 'Any bright',
    presetCustom: 'Custom',
    paramRadius: 'New-colony radius (px)',
    paramMinValue: 'min_value',
    paramMaxSat: 'max_saturation',
    paramInset: 'plate_inset',
    paramCirc: 'min_circularity',
    paramArea: 'min_area_frac',
    paramPeak: 'peak_min_distance',
    livePreview: 'Live threshold preview',
    applyParams: 'Apply & re-count',
    notesLabel: 'Notes:',
    notesPlaceholder: 'Per-image note — stored in CSV',
    statusReady: '',
    statusProcessing: 'Counting…',
    statusDone: 'Done',
    statusIngesting: 'Ingesting…',
    statusUploading: 'Uploading…',
    flagUnprocessed: 'Not counted yet',
    flagReviewed: 'Reviewed by you',
    flagLowConfidence: 'Low-confidence (algorithm thinks the plate may be confluent / unusual)',
    metaReviewed: 'reviewed',
    metaLowConf: 'low confidence',
    exportTitle: 'Export',
    exportFileName: 'File name',
    exportSaveLocation: 'Save to',
    exportSaveLocationPick: 'Choose folder…',
    exportSaveLocationDefault: 'Downloads (browser default)',
    exportFormatCSV: 'CSV only (counts)',
    exportFormatZip: 'Bundle (CSV + annotated images + JSON)',
    exportConfirm: 'Save',
    exportCancel: 'Cancel',
    helpTitle: 'WeCFU — quick help',
    helpClose: 'Close',
    helpBody: `
<h3>What is WeCFU?</h3>
<p>A friendly, browser-based colony counter for petri-dish photos. Drop images in, auto-count, click to fix, export results.</p>

<h3>Adding images</h3>
<ul>
  <li><b>Drag & drop</b> files or a folder onto the sidebar drop-zone.</li>
  <li><b>Paste a path</b> instead — that path is symlinked, your originals are never copied or modified.</li>
</ul>

<h3>Counting</h3>
<p>Click <b>Count all</b>. Each image gets a count next to it on the left. Click an image to inspect it. Auto-detected colonies are green circles with numbers.</p>

<h3>Reviewing</h3>
<ul>
  <li><b>Left-click</b> empty plate area → add a manual colony (cyan).</li>
  <li><b>Right-click</b> a circle → delete it.</li>
  <li><b>Cmd/Ctrl-Z</b> undo · <b>← →</b> prev/next image · <b>Space</b> mark reviewed.</li>
  <li><b>Mouse wheel</b> zoom · <b>Cmd/Ctrl + drag</b> pan.</li>
</ul>

<h3>Sidebar flag dots</h3>
<ul>
  <li><span style="display:inline-block;width:10px;height:10px;background:#555;border-radius:50%"></span> Not yet counted.</li>
  <li><span style="display:inline-block;width:10px;height:10px;background:#e3a73d;border-radius:50%"></span> Low-confidence — algorithm thinks the plate may be confluent / unusual.</li>
  <li><span style="display:inline-block;width:10px;height:10px;background:#54d486;border-radius:50%"></span> You have reviewed this image.</li>
</ul>

<h3>Tuning</h3>
<p>Pick a colony-color <b>preset</b> (white / cream / yellow / any) or change parameters by hand and click <b>Apply & re-count</b>. Turn on <b>Live threshold preview</b> to see in real time which pixels are being treated as colonies.</p>

<h3>Parameter cheatsheet</h3>
<ul>
  <li><b>min_value</b> — pixel must be at least this bright (0–255). Raise for cleaner, lower to catch dimmer colonies.</li>
  <li><b>max_saturation</b> — pixel must be at most this saturated. Low = strict white. Raise to include yellows/oranges.</li>
  <li><b>plate_inset</b> — fraction of plate radius kept. Lower if rim glare is being counted.</li>
  <li><b>min_circularity</b> — colony must be at least this round.</li>
  <li><b>peak_min_distance</b> — minimum px between two seeds. Lower to split touching colonies, raise to merge.</li>
</ul>

<h3>Exporting</h3>
<p><b>Export CSV</b> gives just the counts. <b>Export bundle</b> gives a zip with the CSV, annotated PNGs and a JSON state file per image. Both let you choose the file name; on Chromium browsers you can also pick where to save.</p>
`,
  },

  'zh-CN': {
    appTitle: 'WeCFU',
    language: '语言',
    helpButton: '帮助',
    dropHint: '把图片或文件夹拖到这里',
    dropSubHint: '（仅建符号链接，原图不动）',
    pasteHint: '或粘贴绝对路径：',
    ingestBtn: '导入路径',
    countAll: '全部计数',
    countOne: '重新计数',
    undo: '↶ 撤销',
    markReviewed: '标记已复核',
    exportCSV: '导出 CSV…',
    exportBundle: '导出打包…',
    selectAnImage: '— 选一张图 —',
    cfuSuffix: 'CFU',
    notProcessed: '— (未计数)',
    legend: '<b>左键</b>空白处加菌落 · <b>右键</b>圆圈删除 · <b>滚轮</b>缩放 · <b>Cmd/Ctrl+拖拽</b>平移 · <b>← →</b>上/下一张 · <b>空格</b>标已复核',
    legendAuto: '自动',
    legendManual: '手动',
    presetLabel: '预设',
    presetWhite: '白菌落（默认）',
    presetCream: '乳白 / 淡黄',
    presetYellow: '黄色菌落',
    presetAny: '任意亮色',
    presetCustom: '自定义',
    paramRadius: '新增半径 (px)',
    paramMinValue: 'min_value',
    paramMaxSat: 'max_saturation',
    paramInset: 'plate_inset',
    paramCirc: 'min_circularity',
    paramArea: 'min_area_frac',
    paramPeak: 'peak_min_distance',
    livePreview: '实时阈值预览',
    applyParams: '应用并重跑',
    notesLabel: '备注：',
    notesPlaceholder: '给这一张写一句备注，会进 CSV',
    statusReady: '',
    statusProcessing: '计数中…',
    statusDone: '完成',
    statusIngesting: '导入中…',
    statusUploading: '上传中…',
    flagUnprocessed: '尚未计数',
    flagReviewed: '你已复核',
    flagLowConfidence: '低置信（算法觉得可能铺满或菌落异形）',
    metaReviewed: '已复核',
    metaLowConf: '低置信',
    exportTitle: '导出',
    exportFileName: '文件名',
    exportSaveLocation: '保存到',
    exportSaveLocationPick: '选择文件夹…',
    exportSaveLocationDefault: '浏览器默认下载位置',
    exportFormatCSV: '仅 CSV（计数结果）',
    exportFormatZip: '打包（CSV + 标注图 + JSON）',
    exportConfirm: '保存',
    exportCancel: '取消',
    helpTitle: 'WeCFU — 快速帮助',
    helpClose: '关闭',
    helpBody: `
<h3>WeCFU 是什么？</h3>
<p>一个浏览器里跑的菌落计数工具。把照片拖进去 → 自动数 → 你点几下校正 → 导出。</p>

<h3>导入图片</h3>
<ul>
  <li><b>拖拽</b>文件或文件夹到左侧拖拽区。</li>
  <li><b>粘贴绝对路径</b>到下方输入框 → 工具用符号链接引用，绝不复制或修改你的原图。</li>
</ul>

<h3>计数</h3>
<p>点顶部 <b>「全部计数」</b>。左侧列表里每张图右边会显示菌落数。点开任意一张图，识别到的菌落以绿圈+编号显示。</p>

<h3>复核</h3>
<ul>
  <li><b>左键</b>点空白皿面 → 加一个手动菌落（青色）。</li>
  <li><b>右键</b>点圆圈 → 删除它。</li>
  <li><b>Cmd/Ctrl-Z</b> 撤销 · <b>← →</b> 上/下一张 · <b>空格</b> 标已复核。</li>
  <li><b>滚轮</b>缩放 · <b>Cmd/Ctrl + 拖拽</b>平移。</li>
</ul>

<h3>左侧的小圆点含义</h3>
<ul>
  <li><span style="display:inline-block;width:10px;height:10px;background:#555;border-radius:50%"></span> 尚未计数。</li>
  <li><span style="display:inline-block;width:10px;height:10px;background:#e3a73d;border-radius:50%"></span> 低置信——算法觉得可能铺满或异形，建议人工核对。</li>
  <li><span style="display:inline-block;width:10px;height:10px;background:#54d486;border-radius:50%"></span> 已复核。</li>
</ul>

<h3>调参</h3>
<p>选一个<b>预设</b>（白 / 乳白 / 黄色 / 任意亮色）或自己改参数后点<b>「应用并重跑」</b>。打开<b>「实时阈值预览」</b>能看到当前被当作菌落的像素被实时绿色高亮。</p>

<h3>参数速查</h3>
<ul>
  <li><b>min_value</b>：像素至少这么亮（0–255）。误识背景调高，漏识菌落调低。</li>
  <li><b>max_saturation</b>：颜色饱和度上限。低 = 严格白色，调高包含黄/橙菌落。</li>
  <li><b>plate_inset</b>：保留皿半径的比例。皿壁被识别时调低。</li>
  <li><b>min_circularity</b>：菌落必须有多圆。</li>
  <li><b>peak_min_distance</b>：两个种子的最小像素间隔。调低拆开粘连，调高合并。</li>
</ul>

<h3>导出</h3>
<p><b>导出 CSV</b> 只含计数。<b>导出打包</b> 给一个 zip：CSV + 标注 PNG + 每张图的 JSON 状态档。两种都可以自己定文件名；在 Chrome / Edge 上还能选保存位置。</p>
`,
  },

  ja: {
    appTitle: 'WeCFU',
    language: '言語',
    helpButton: 'ヘルプ',
    dropHint: '画像ファイルまたはフォルダをここにドロップ',
    dropSubHint: '（シンボリックリンクのみ、元画像は変更されません）',
    pasteHint: '絶対パスを貼り付け：',
    ingestBtn: 'パスを取り込む',
    countAll: '全部カウント',
    countOne: '再カウント',
    undo: '↶ 元に戻す',
    markReviewed: '確認済みにする',
    exportCSV: 'CSV を書き出し…',
    exportBundle: 'バンドルを書き出し…',
    selectAnImage: '— 画像を選択 —',
    cfuSuffix: 'CFU',
    notProcessed: '— (未カウント)',
    legend: '<b>左クリック</b> 追加 · <b>右クリック</b> 削除 · <b>ホイール</b> 拡大縮小 · <b>Cmd/Ctrl+ドラッグ</b> 移動 · <b>← →</b> 前/次 · <b>Space</b> 確認済み',
    legendAuto: '自動',
    legendManual: '手動',
    presetLabel: 'プリセット',
    presetWhite: '白いコロニー（既定）',
    presetCream: 'クリーム / 薄黄',
    presetYellow: '黄色コロニー',
    presetAny: '任意の明るい色',
    presetCustom: 'カスタム',
    paramRadius: '追加半径 (px)',
    paramMinValue: 'min_value',
    paramMaxSat: 'max_saturation',
    paramInset: 'plate_inset',
    paramCirc: 'min_circularity',
    paramArea: 'min_area_frac',
    paramPeak: 'peak_min_distance',
    livePreview: 'しきい値ライブプレビュー',
    applyParams: '適用して再カウント',
    notesLabel: 'メモ：',
    notesPlaceholder: '画像ごとのメモ — CSV に保存されます',
    statusProcessing: 'カウント中…',
    statusDone: '完了',
    statusIngesting: '取り込み中…',
    statusUploading: 'アップロード中…',
    flagUnprocessed: '未カウント',
    flagReviewed: '確認済み',
    flagLowConfidence: '低信頼（コロニーが密集または異常な可能性）',
    metaReviewed: '確認済み',
    metaLowConf: '低信頼',
    exportTitle: '書き出し',
    exportFileName: 'ファイル名',
    exportSaveLocation: '保存先',
    exportSaveLocationPick: 'フォルダを選択…',
    exportSaveLocationDefault: 'ダウンロード（既定）',
    exportFormatCSV: 'CSV のみ',
    exportFormatZip: 'バンドル (CSV + 注釈付き画像 + JSON)',
    exportConfirm: '保存',
    exportCancel: 'キャンセル',
    helpTitle: 'WeCFU — クイックヘルプ',
    helpClose: '閉じる',
  },

  es: {
    appTitle: 'WeCFU',
    language: 'Idioma',
    helpButton: 'Ayuda',
    dropHint: 'Suelta imágenes o una carpeta aquí',
    dropSubHint: '(enlace simbólico — los originales no se modifican)',
    pasteHint: 'O pega una ruta absoluta:',
    ingestBtn: 'Importar ruta',
    countAll: 'Contar todo',
    countOne: 'Re-contar',
    undo: '↶ Deshacer',
    markReviewed: 'Marcar revisado',
    exportCSV: 'Exportar CSV…',
    exportBundle: 'Exportar paquete…',
    selectAnImage: '— elige una imagen —',
    cfuSuffix: 'CFU',
    notProcessed: '— (sin contar)',
    legend: '<b>Clic izq.</b> añadir · <b>Clic der.</b> borrar · <b>Rueda</b> zoom · <b>Cmd/Ctrl+arrastrar</b> mover · <b>← →</b> ant/sig · <b>Espacio</b> revisado',
    legendAuto: 'auto',
    legendManual: 'manual',
    presetLabel: 'Preset',
    presetWhite: 'Colonias blancas (predet.)',
    presetCream: 'Crema / amarillo claro',
    presetYellow: 'Colonias amarillas',
    presetAny: 'Cualquier color brillante',
    presetCustom: 'Personalizado',
    paramRadius: 'Radio nuevo (px)',
    livePreview: 'Vista previa de umbral en vivo',
    applyParams: 'Aplicar y re-contar',
    notesLabel: 'Notas:',
    notesPlaceholder: 'Nota por imagen — se guarda en el CSV',
    statusProcessing: 'Contando…',
    statusDone: 'Listo',
    statusIngesting: 'Importando…',
    statusUploading: 'Subiendo…',
    flagUnprocessed: 'Aún no contada',
    flagReviewed: 'Revisada',
    flagLowConfidence: 'Baja confianza (puede ser confluente o inusual)',
    metaReviewed: 'revisada',
    metaLowConf: 'baja confianza',
    exportTitle: 'Exportar',
    exportFileName: 'Nombre de archivo',
    exportSaveLocation: 'Guardar en',
    exportSaveLocationPick: 'Elegir carpeta…',
    exportSaveLocationDefault: 'Descargas (por defecto)',
    exportFormatCSV: 'Solo CSV (recuentos)',
    exportFormatZip: 'Paquete (CSV + imágenes + JSON)',
    exportConfirm: 'Guardar',
    exportCancel: 'Cancelar',
    helpTitle: 'WeCFU — ayuda rápida',
    helpClose: 'Cerrar',
  },

  fr: {
    appTitle: 'WeCFU',
    language: 'Langue',
    helpButton: 'Aide',
    dropHint: 'Déposez images ou un dossier ici',
    dropSubHint: '(lien symbolique — les originaux ne sont pas modifiés)',
    pasteHint: 'Ou collez un chemin absolu :',
    ingestBtn: 'Importer le chemin',
    countAll: 'Tout compter',
    countOne: 'Re-compter',
    undo: '↶ Annuler',
    markReviewed: 'Marquer comme revu',
    exportCSV: 'Exporter CSV…',
    exportBundle: 'Exporter le pack…',
    selectAnImage: '— choisissez une image —',
    cfuSuffix: 'CFU',
    notProcessed: '— (non compté)',
    legend: '<b>Clic gauche</b> ajouter · <b>Clic droit</b> supprimer · <b>Molette</b> zoom · <b>Cmd/Ctrl+glisser</b> déplacer · <b>← →</b> préc/suiv · <b>Espace</b> revu',
    legendAuto: 'auto',
    legendManual: 'manuel',
    presetLabel: 'Préréglage',
    presetWhite: 'Colonies blanches (défaut)',
    presetCream: 'Crème / jaune pâle',
    presetYellow: 'Colonies jaunes',
    presetAny: 'Toute couleur claire',
    presetCustom: 'Personnalisé',
    paramRadius: 'Rayon (px)',
    livePreview: 'Aperçu de seuil en direct',
    applyParams: 'Appliquer et re-compter',
    notesLabel: 'Notes :',
    notesPlaceholder: 'Note par image — enregistrée dans le CSV',
    statusProcessing: 'Comptage…',
    statusDone: 'Terminé',
    statusIngesting: 'Importation…',
    statusUploading: 'Téléversement…',
    flagUnprocessed: 'Non compté',
    flagReviewed: 'Revu',
    flagLowConfidence: 'Faible confiance (peut être confluent / inhabituel)',
    metaReviewed: 'revu',
    metaLowConf: 'faible confiance',
    exportTitle: 'Exporter',
    exportFileName: 'Nom du fichier',
    exportSaveLocation: 'Enregistrer dans',
    exportSaveLocationPick: 'Choisir un dossier…',
    exportSaveLocationDefault: 'Téléchargements (par défaut)',
    exportFormatCSV: 'CSV uniquement',
    exportFormatZip: 'Pack (CSV + images + JSON)',
    exportConfirm: 'Enregistrer',
    exportCancel: 'Annuler',
    helpTitle: 'WeCFU — aide rapide',
    helpClose: 'Fermer',
  },
};

const LANG_NAMES = {
  en: 'English',
  'zh-CN': '简体中文',
  ja: '日本語',
  es: 'Español',
  fr: 'Français',
};

let _lang = localStorage.getItem('wecfu.lang') || 'en';
if (!(_lang in I18N)) _lang = 'en';

function setLang(l) {
  if (!(l in I18N)) return;
  _lang = l;
  localStorage.setItem('wecfu.lang', l);
  applyI18n();
}

function getLang() { return _lang; }

function t(key) {
  const dict = I18N[_lang] || I18N.en;
  return dict[key] ?? I18N.en[key] ?? key;
}

function applyI18n(root = document) {
  root.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    el.innerHTML = t(key);
  });
  root.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  root.querySelectorAll('[data-i18n-title]').forEach(el => {
    el.title = t(el.dataset.i18nTitle);
  });
  document.documentElement.lang = _lang;
}

window.WECFU_I18N = { setLang, getLang, t, applyI18n, LANG_NAMES, I18N };
