// Lightweight i18n for WeCFU.
//
// English is the source of truth. Other languages keyed by the same string ids.
// Translations missing in a non-English language fall back to English.
//
// Wrapped in an IIFE so identifiers (t, setLang, applyI18n, ...) do NOT
// leak to the global scope — otherwise they would clash with the same
// names destructured from window.WECFU_I18N in app.js.

(function () {

const AUTHORS_FOOTER = `
<div class="help-footer">
  <p><b>Authors</b></p>
  <p>Jianghua Zhang (张江华) &mdash;
    <a href="mailto:zhangjianghua@westlake.edu.cn">zhangjianghua@westlake.edu.cn</a></p>
  <p>Xinyu Wang (王欣宇) &mdash;
    <a href="mailto:wangxinyu30@westlake.edu.cn">wangxinyu30@westlake.edu.cn</a></p>
</div>`;

const I18N = {
  en: {
    appTitle: 'WeCFU',
    language: 'Language',
    helpButton: 'Help',
    dropHint: 'Drop image files or a folder here',
    dropSubHint: '(symlinked, your originals are not modified)',
    pasteHint: 'Or paste an absolute path',
    ingestBtn: 'Ingest path',
    countAll: 'Count all',
    countOne: 'Recount',
    undo: '↶ Undo',
    exportCSV: 'Export CSV',
    exportBundle: 'Export bundle',
    selectAnImage: 'select an image',
    cfuSuffix: 'CFU',
    notProcessed: 'not counted',
    legend: '<b>Left click</b> empty space to add &middot; <b>Right click</b> a circle to delete &middot; <b>Wheel</b> to zoom &middot; <b>Cmd/Ctrl drag</b> to pan &middot; <b>← →</b> previous or next image',
    legendAuto: 'auto',
    legendManual: 'manual',
    presetLabel: 'Preset',
    presetWhite: 'White colonies (default)',
    presetCream: 'Cream or pale yellow',
    presetYellow: 'Yellow colonies',
    presetAny: 'Any bright',
    presetCustom: 'Custom',
    paramRadius: 'New colony radius (px)',
    paramMinValue: 'min value',
    paramMaxSat: 'max saturation',
    paramInset: 'plate inset',
    paramCirc: 'min circularity',
    paramArea: 'min area frac',
    paramPeak: 'peak min distance',
    livePreview: 'Live threshold preview',
    applyParams: 'Apply and recount',
    notesLabel: 'Notes',
    notesPlaceholder: 'Per image note, stored in CSV',
    statusReady: '',
    statusProcessing: 'Counting',
    statusDone: 'Done',
    statusIngesting: 'Ingesting',
    statusUploading: 'Uploading',
    flagUnprocessed: 'Not counted yet',
    flagReviewed: 'You have viewed this image',
    flagLowConfidence: 'Low confidence (algorithm thinks the plate may be confluent or unusual)',
    metaLowConf: 'low confidence',
    exportTitle: 'Export',
    exportFileName: 'File name',
    exportSaveLocation: 'Save to',
    exportSaveLocationPick: 'Choose folder',
    exportSaveLocationDefault: 'Downloads (browser default)',
    exportFormatCSV: 'CSV only (counts)',
    exportFormatZip: 'Bundle (CSV plus annotated images and JSON)',
    exportConfirm: 'Save',
    exportCancel: 'Cancel',
    helpTitle: 'WeCFU quick help',
    helpClose: 'Close',
    helpBody: `
<h3>What is WeCFU?</h3>
<p>A friendly, browser based colony counter for petri dish photos. Drop images in, auto count, click to fix, export results.</p>

<h3>Adding images</h3>
<ul>
  <li><b>Drag and drop</b> files or a folder onto the sidebar drop zone.</li>
  <li><b>Paste a path</b> instead. That path is symlinked, your originals are never copied or modified.</li>
</ul>

<h3>Counting</h3>
<p>Click <b>Count all</b>. Each image gets a count next to it on the left. Click an image to inspect it. Auto detected colonies appear as green circles with numbers.</p>

<h3>Reviewing</h3>
<ul>
  <li><b>Left click</b> empty plate area to add a manual colony (cyan).</li>
  <li><b>Right click</b> a circle to delete it.</li>
  <li><b>Cmd/Ctrl Z</b> undoes the last add or delete.</li>
  <li><b>← →</b> previous or next image. <b>Mouse wheel</b> zoom, <b>Cmd/Ctrl drag</b> pan.</li>
  <li>Simply opening an image marks it as reviewed (green dot in the sidebar).</li>
</ul>

<h3>Sidebar flag dots</h3>
<ul>
  <li><span style="display:inline-block;width:10px;height:10px;background:#555;border-radius:50%"></span> Not yet viewed.</li>
  <li><span style="display:inline-block;width:10px;height:10px;background:#e3a73d;border-radius:50%"></span> Low confidence. The algorithm thinks the plate may be confluent or unusual; please check.</li>
  <li><span style="display:inline-block;width:10px;height:10px;background:#54d486;border-radius:50%"></span> You have viewed this image.</li>
</ul>

<h3>Tuning</h3>
<p>Pick a colony color <b>preset</b> (white, cream, yellow, any) or change parameters by hand and click <b>Apply and recount</b>. Turn on <b>Live threshold preview</b> to see in real time which pixels are being treated as colonies; pixels included by the current <i>min value</i> and <i>max saturation</i> get a green tint. Use this to tune the thresholds visually before you commit.</p>

<h3>Parameter cheatsheet</h3>
<ul>
  <li><b>New colony radius (px)</b>: the radius of the cyan circle drawn when you left click to add a manual colony. Purely visual, does not affect counts.</li>
  <li><b>min value</b>: pixel must be at least this bright (0 to 255). Raise for stricter selection, lower to catch dimmer colonies.</li>
  <li><b>max saturation</b>: pixel must be at most this saturated. Low means strict white. Raise to include yellows or oranges.</li>
  <li><b>plate inset</b>: fraction of plate radius kept. Lower if rim glare is being counted as colonies.</li>
  <li><b>min circularity</b>: a candidate must be at least this round. Range 0 to 1.</li>
  <li><b>min area frac</b>: minimum colony area as a fraction of plate area. Lower to keep small dots, raise to drop noise.</li>
  <li><b>peak min distance</b>: minimum pixels between two seed points. Lower to split touching colonies, raise to merge.</li>
</ul>

<h3>Exporting</h3>
<p><b>Export CSV</b> writes just the counts. <b>Export bundle</b> writes a zip with the CSV, annotated PNGs and a JSON state file per image. Both let you choose the file name; on Chromium based browsers you can also pick where to save.</p>
` + AUTHORS_FOOTER,
  },

  'zh-CN': {
    appTitle: 'WeCFU',
    language: '语言',
    helpButton: '帮助',
    dropHint: '把图片或文件夹拖到这里',
    dropSubHint: '只建符号链接，不动你的原图',
    pasteHint: '或者粘贴一个绝对路径',
    ingestBtn: '导入路径',
    countAll: '全部计数',
    countOne: '重新计数',
    undo: '↶ 撤销',
    exportCSV: '导出 CSV',
    exportBundle: '打包导出',
    selectAnImage: '请选一张图片',
    cfuSuffix: 'CFU',
    notProcessed: '尚未计数',
    legend: '<b>左键</b>空白处加菌落 &middot; <b>右键</b>圆圈删除 &middot; <b>滚轮</b>缩放 &middot; <b>Cmd/Ctrl 拖拽</b>平移 &middot; <b>← →</b>切上一张或下一张',
    legendAuto: '自动',
    legendManual: '手动',
    presetLabel: '预设',
    presetWhite: '白色菌落（默认）',
    presetCream: '乳白或淡黄',
    presetYellow: '黄色菌落',
    presetAny: '任意亮色',
    presetCustom: '自定义',
    paramRadius: '新增菌落半径（像素）',
    paramMinValue: '亮度下限',
    paramMaxSat: '饱和度上限',
    paramInset: '皿内缩比例',
    paramCirc: '最小圆度',
    paramArea: '最小面积占比',
    paramPeak: '最小种子间距',
    livePreview: '实时阈值预览',
    applyParams: '应用并重新计数',
    notesLabel: '备注',
    notesPlaceholder: '给这张图写一句备注，会写进 CSV',
    statusReady: '',
    statusProcessing: '正在计数',
    statusDone: '完成',
    statusIngesting: '正在导入',
    statusUploading: '正在上传',
    flagUnprocessed: '尚未查看',
    flagReviewed: '已查看',
    flagLowConfidence: '低置信：算法觉得这板可能铺满或形态异常，建议你点开看一下',
    metaLowConf: '低置信',
    exportTitle: '导出',
    exportFileName: '文件名',
    exportSaveLocation: '保存到',
    exportSaveLocationPick: '选择文件夹',
    exportSaveLocationDefault: '浏览器默认下载位置',
    exportFormatCSV: '只导 CSV（计数表）',
    exportFormatZip: '打包（CSV、标注图、JSON 状态档）',
    exportConfirm: '保存',
    exportCancel: '取消',
    helpTitle: 'WeCFU 使用帮助',
    helpClose: '关闭',
    helpBody: `
<h3>WeCFU 是什么</h3>
<p>一个跑在浏览器里的菌落计数小工具，专门用来对付平皿照片：拖图进来，自动数一遍，鼠标点几下校正，然后导出结果。无需联网，全在本地完成。</p>

<h3>导入图片</h3>
<ul>
  <li>直接把图片或者整个文件夹<b>拖到左侧</b>那个拖拽区。</li>
  <li>或者在下方输入框里<b>粘贴一个绝对路径</b>，点「导入路径」。这种方式只建符号链接，原图安然无恙。</li>
</ul>

<h3>开始计数</h3>
<p>点顶部「<b>全部计数</b>」。每张图左侧会显示数到的菌落数。点开任意一张图就能看到识别结果，每个菌落用<b>绿圈加编号</b>标出。</p>

<h3>人工校对</h3>
<ul>
  <li><b>左键</b>点皿面空白处 —— 加一个手动菌落（青色圆圈）。</li>
  <li><b>右键</b>点圆圈 —— 直接删掉它。</li>
  <li><b>Cmd/Ctrl Z</b> —— 撤销上一步增删。</li>
  <li><b>← →</b> —— 上一张、下一张。<b>滚轮</b>缩放，<b>Cmd/Ctrl 拖拽</b>平移。</li>
  <li>只要你点开过一张图，左侧的圆点就会变成绿色，表示你已经看过了，不需要专门"标记"。</li>
</ul>

<h3>左侧小圆点的含义</h3>
<ul>
  <li><span style="display:inline-block;width:10px;height:10px;background:#555;border-radius:50%"></span> 灰色：还没点开看过。</li>
  <li><span style="display:inline-block;width:10px;height:10px;background:#e3a73d;border-radius:50%"></span> 黄色：算法标记为低置信，可能数不准，请你重点看一下。</li>
  <li><span style="display:inline-block;width:10px;height:10px;background:#54d486;border-radius:50%"></span> 绿色：你已经查看过这张图。</li>
</ul>

<h3>调参</h3>
<p>底部参数栏里，<b>预设</b>下拉里有四种常见情形（白色、乳白、黄色、任意亮色），切换后点「应用并重新计数」就行。如果想精调，可以一边动数字一边勾上「<b>实时阈值预览</b>」—— 当前阈值下被算作菌落的像素会被涂上绿色高亮，所见即所得。调到满意后再点「应用并重新计数」生效。</p>

<h3>参数详解</h3>
<ul>
  <li><b>新增菌落半径（像素）</b>：你左键加菌落时画的那个圆有多大。纯视觉效果，不影响计数对错。</li>
  <li><b>亮度下限</b>（min value，0 到 255）：像素必须比这个值更亮才会算菌落。如果漏识真菌落 → 调低；如果反光被识别 → 调高。</li>
  <li><b>饱和度上限</b>（max saturation）：颜色越接近白色饱和度越低。默认严格选白色，调高才能纳入黄色或橙色菌落。</li>
  <li><b>皿内缩比例</b>（plate inset，0 到 1）：实际处理的圆形区域占皿半径的比例。皿壁反光被识别成菌落时，把这个值调低（比如 0.78）排除外圈。</li>
  <li><b>最小圆度</b>（min circularity，0 到 1）：候选必须有多圆。形状不规则的伪影调高就能滤掉。</li>
  <li><b>最小面积占比</b>（min area frac）：菌落最小面积，按皿面积的比例计。想保留小菌点就调低，想滤掉噪点就调高。</li>
  <li><b>最小种子间距</b>（peak min distance，像素）：相邻两个菌落中心至少要差几像素。粘连菌落被合并 → 调低拆开；单个菌落被劈成两半 → 调高合并。</li>
</ul>

<h3>导出</h3>
<p><b>导出 CSV</b>：只给计数表格，五列足够分析用。<br>
<b>打包导出</b>：给一个 zip，里面除了 CSV 还有每张图的标注 PNG 和 JSON 状态档；如果以后想完全复现这次的计数（包括你手动加删的每一个圆圈），就用这个。<br>
两种方式都可以自己定文件名；在 Chrome / Edge 上还能选保存到哪个文件夹（Safari 走浏览器默认下载位置）。</p>

<h3>小提示</h3>
<p>每次重新启动 WeCFU 都会清空上次的所有导入和计数痕迹，所以每一次都是干净的工作台。如果你想把这次的进度留下来，导出 zip 即可。</p>
` + AUTHORS_FOOTER,
  },

  ja: {
    appTitle: 'WeCFU',
    language: '言語',
    helpButton: 'ヘルプ',
    dropHint: '画像ファイルまたはフォルダをここにドロップ',
    dropSubHint: 'シンボリックリンクのみ。元画像は変更されません',
    pasteHint: '絶対パスを貼り付け',
    ingestBtn: 'パスを取り込む',
    countAll: '全部カウント',
    countOne: '再カウント',
    undo: '↶ 元に戻す',
    exportCSV: 'CSV を書き出し',
    exportBundle: 'バンドルを書き出し',
    selectAnImage: '画像を選択',
    cfuSuffix: 'CFU',
    notProcessed: '未カウント',
    legend: '<b>左クリック</b> 追加 &middot; <b>右クリック</b> 削除 &middot; <b>ホイール</b> 拡大縮小 &middot; <b>Cmd/Ctrl ドラッグ</b> 移動 &middot; <b>← →</b> 前 / 次',
    legendAuto: '自動',
    legendManual: '手動',
    presetLabel: 'プリセット',
    presetWhite: '白いコロニー（既定）',
    presetCream: 'クリーム / 薄黄',
    presetYellow: '黄色コロニー',
    presetAny: '任意の明るい色',
    presetCustom: 'カスタム',
    paramRadius: '追加半径 (px)',
    paramMinValue: 'min value',
    paramMaxSat: 'max saturation',
    paramInset: 'plate inset',
    paramCirc: 'min circularity',
    paramArea: 'min area frac',
    paramPeak: 'peak min distance',
    livePreview: 'しきい値ライブプレビュー',
    applyParams: '適用して再カウント',
    notesLabel: 'メモ',
    notesPlaceholder: '画像ごとのメモ。CSV に保存されます',
    statusProcessing: 'カウント中',
    statusDone: '完了',
    statusIngesting: '取り込み中',
    statusUploading: 'アップロード中',
    flagUnprocessed: '未カウント',
    flagReviewed: '閲覧済み',
    flagLowConfidence: '低信頼（コロニーが密集または異常な可能性）',
    metaLowConf: '低信頼',
    exportTitle: '書き出し',
    exportFileName: 'ファイル名',
    exportSaveLocation: '保存先',
    exportSaveLocationPick: 'フォルダを選択',
    exportSaveLocationDefault: 'ダウンロード（既定）',
    exportFormatCSV: 'CSV のみ',
    exportFormatZip: 'バンドル (CSV + 注釈付き画像 + JSON)',
    exportConfirm: '保存',
    exportCancel: 'キャンセル',
    helpTitle: 'WeCFU クイックヘルプ',
    helpClose: '閉じる',
    helpBody: AUTHORS_FOOTER,
  },

  es: {
    appTitle: 'WeCFU',
    language: 'Idioma',
    helpButton: 'Ayuda',
    dropHint: 'Suelta imágenes o una carpeta aquí',
    dropSubHint: 'Se enlaza por symlink, los originales no se modifican',
    pasteHint: 'O pega una ruta absoluta',
    ingestBtn: 'Importar ruta',
    countAll: 'Contar todo',
    countOne: 'Recontar',
    undo: '↶ Deshacer',
    exportCSV: 'Exportar CSV',
    exportBundle: 'Exportar paquete',
    selectAnImage: 'elige una imagen',
    cfuSuffix: 'CFU',
    notProcessed: 'sin contar',
    legend: '<b>Clic izq.</b> añadir &middot; <b>Clic der.</b> borrar &middot; <b>Rueda</b> zoom &middot; <b>Cmd/Ctrl arrastrar</b> mover &middot; <b>← →</b> ant / sig',
    legendAuto: 'auto',
    legendManual: 'manual',
    presetLabel: 'Preset',
    presetWhite: 'Colonias blancas (por defecto)',
    presetCream: 'Crema o amarillo claro',
    presetYellow: 'Colonias amarillas',
    presetAny: 'Cualquier color brillante',
    presetCustom: 'Personalizado',
    paramRadius: 'Radio nueva colonia (px)',
    paramMinValue: 'min value',
    paramMaxSat: 'max saturation',
    paramInset: 'plate inset',
    paramCirc: 'min circularity',
    paramArea: 'min area frac',
    paramPeak: 'peak min distance',
    livePreview: 'Vista previa de umbral en vivo',
    applyParams: 'Aplicar y recontar',
    notesLabel: 'Notas',
    notesPlaceholder: 'Nota por imagen, se guarda en el CSV',
    statusProcessing: 'Contando',
    statusDone: 'Listo',
    statusIngesting: 'Importando',
    statusUploading: 'Subiendo',
    flagUnprocessed: 'Aún no contada',
    flagReviewed: 'Vista',
    flagLowConfidence: 'Baja confianza (puede ser confluente o inusual)',
    metaLowConf: 'baja confianza',
    exportTitle: 'Exportar',
    exportFileName: 'Nombre del archivo',
    exportSaveLocation: 'Guardar en',
    exportSaveLocationPick: 'Elegir carpeta',
    exportSaveLocationDefault: 'Descargas (por defecto)',
    exportFormatCSV: 'Solo CSV (recuentos)',
    exportFormatZip: 'Paquete (CSV más imágenes y JSON)',
    exportConfirm: 'Guardar',
    exportCancel: 'Cancelar',
    helpTitle: 'WeCFU ayuda rápida',
    helpClose: 'Cerrar',
    helpBody: AUTHORS_FOOTER,
  },

  fr: {
    appTitle: 'WeCFU',
    language: 'Langue',
    helpButton: 'Aide',
    dropHint: 'Déposez images ou un dossier ici',
    dropSubHint: 'Liens symboliques, les originaux ne sont pas modifiés',
    pasteHint: 'Ou collez un chemin absolu',
    ingestBtn: 'Importer le chemin',
    countAll: 'Tout compter',
    countOne: 'Recompter',
    undo: '↶ Annuler',
    exportCSV: 'Exporter CSV',
    exportBundle: 'Exporter le pack',
    selectAnImage: 'choisissez une image',
    cfuSuffix: 'CFU',
    notProcessed: 'non compté',
    legend: '<b>Clic gauche</b> ajouter &middot; <b>Clic droit</b> supprimer &middot; <b>Molette</b> zoom &middot; <b>Cmd/Ctrl glisser</b> déplacer &middot; <b>← →</b> préc / suiv',
    legendAuto: 'auto',
    legendManual: 'manuel',
    presetLabel: 'Préréglage',
    presetWhite: 'Colonies blanches (défaut)',
    presetCream: 'Crème ou jaune pâle',
    presetYellow: 'Colonies jaunes',
    presetAny: 'Toute couleur claire',
    presetCustom: 'Personnalisé',
    paramRadius: 'Rayon nouvelle colonie (px)',
    paramMinValue: 'min value',
    paramMaxSat: 'max saturation',
    paramInset: 'plate inset',
    paramCirc: 'min circularity',
    paramArea: 'min area frac',
    paramPeak: 'peak min distance',
    livePreview: 'Aperçu de seuil en direct',
    applyParams: 'Appliquer et recompter',
    notesLabel: 'Notes',
    notesPlaceholder: 'Note par image, enregistrée dans le CSV',
    statusProcessing: 'Comptage',
    statusDone: 'Terminé',
    statusIngesting: 'Importation',
    statusUploading: 'Téléversement',
    flagUnprocessed: 'Non compté',
    flagReviewed: 'Vu',
    flagLowConfidence: 'Faible confiance (peut être confluent ou inhabituel)',
    metaLowConf: 'faible confiance',
    exportTitle: 'Exporter',
    exportFileName: 'Nom du fichier',
    exportSaveLocation: 'Enregistrer dans',
    exportSaveLocationPick: 'Choisir un dossier',
    exportSaveLocationDefault: 'Téléchargements (par défaut)',
    exportFormatCSV: 'CSV uniquement',
    exportFormatZip: 'Pack (CSV plus images et JSON)',
    exportConfirm: 'Enregistrer',
    exportCancel: 'Annuler',
    helpTitle: 'WeCFU aide rapide',
    helpClose: 'Fermer',
    helpBody: AUTHORS_FOOTER,
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
})();
