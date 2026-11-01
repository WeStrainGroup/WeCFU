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
  <p>Wenhao Zhou (周文浩) &mdash;
    <a href="mailto:zhouwenhao@westlake.edu.cn">zhouwenhao@westlake.edu.cn</a></p>
  <p>Zhanyi Zhu (朱展翼) &mdash;
    <a href="mailto:zhuzhanyi@westlake.edu.cn">zhuzhanyi@westlake.edu.cn</a></p>
</div>`;

const I18N = {
  en: {
    appTitle: 'WeCFU',
    language: 'Language',
    helpButton: 'Help',
    dropHint: 'Drop image files or a folder here',
    dropSubHint: 'Symlinked, your originals are not modified',
    pasteHint: 'Or paste an absolute path',
    ingestBtn: 'Ingest path',
    countAll: 'Count all',
    countOne: 'Recount',
    undo: '↶ Undo',
    exportCSV: 'Export CSV',
    exportBundle: 'Export bundle',
    selectAnImage: 'Select an image',
    cfuSuffix: 'CFU',
    notProcessed: 'Not counted',
    legend: '<b>Left click</b> empty space to add &middot; <b>Right click</b> a circle to delete &middot; <b>Wheel</b> to zoom &middot; <b>Cmd/Ctrl drag</b> to pan &middot; <b>← →</b> previous or next image',
    legendAuto: 'Machine',
    legendManual: 'Manual',
    presetLabel: 'Preset',
    presetWhite: 'White colonies (default)',
    presetCream: 'Cream or pale yellow',
    presetYellow: 'Yellow colonies',
    presetAny: 'Any bright',
    presetCustom: 'Custom',
    paramRadius: 'New colony radius',
    paramMinValue: 'Min value',
    paramMaxSat: 'Max saturation',
    paramInset: 'Plate inset',
    paramCirc: 'Min circularity',
    paramArea: 'Min area frac',
    paramPeak: 'Peak min distance',
    livePreview: 'Live threshold preview',
    applyParams: 'Apply and recount',
    notesLabel: 'Notes',
    notesPlaceholder: 'Per image note, stored in CSV',
    statusReady: '',
    statusProcessing: 'Counting…',
    statusAutoCounting: 'Auto counting this plate…',
    statusDone: 'Done',
    statusIngesting: 'Ingesting…',
    statusUploading: 'Uploading…',
    flagUnprocessed: 'Not counted yet',
    flagCounted: 'Algorithm result; not a human verification',
    flagReviewed: 'Edited or legacy viewed flag; protected from batch recount, not human verified',
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
<p>Click <b>Count all</b>. Each image gets a count next to it on the left. Click an image to inspect it. Machine detected colonies appear as <b style="color:#999999">light gray circles</b> with numbers.</p>

<h3>Reviewing</h3>
<ul>
  <li><b>Left click</b> empty plate area to add a manual colony, drawn in <b style="color:#444444">gray</b>.</li>
  <li><b>Right click</b> a circle to delete it.</li>
  <li><b>Cmd/Ctrl Z</b> undoes the last add or delete.</li>
  <li><b>← →</b> previous or next image. <b>Mouse wheel</b> zoom, <b>Cmd/Ctrl drag</b> pan.</li>
  <li>Opening an image does not change its review state. Human verification requires an explicit confirmation and save.</li>
  <li><b>New colony radius</b> sets the size of the gray circle drawn when you left click. Purely visual, does not change counts.</li>
</ul>

<h3>Sidebar dot colors</h3>
<ul>
  <li><span style="display:inline-block;width:10px;height:10px;background:#555;border-radius:50%"></span> Gray. Image uploaded, not counted yet.</li>
  <li><span style="display:inline-block;width:10px;height:10px;background:#999999;border-radius:50%"></span> Light gray. An algorithm count is available; this is not human verification.</li>
  <li><span style="display:inline-block;width:10px;height:10px;background:#444444;border-radius:50%"></span> Gray. Edited or marked as viewed in an older version; protected from batch recount, not human verified.</li>
</ul>

<h3>Tuning</h3>
<p>Pick a colony color <b>preset</b> (white, cream, yellow, any) or change parameters by hand and click <b>Apply and recount</b>. Turn on <b>Live threshold preview</b> to see in real time which pixels are being treated as colonies; pixels included by the current <i>Min value</i> and <i>Max saturation</i> get a bright mint tint. Use this to tune the thresholds visually before you commit.</p>

<h3>Parameter cheatsheet</h3>
<ul>
  <li><b>Min value</b>: pixel must be at least this bright (0 to 255). Raise for stricter selection, lower to catch dimmer colonies.</li>
  <li><b>Max saturation</b>: pixel must be at most this saturated. Low means strict white. Raise to include yellows or oranges.</li>
  <li><b>Plate inset</b>: fraction of plate radius kept. Lower if rim glare is being counted as colonies.</li>
  <li><b>Min circularity</b>: a candidate must be at least this round. Range 0 to 1.</li>
  <li><b>Min area frac</b>: minimum colony area as a fraction of plate area. Lower to keep small dots, raise to drop noise.</li>
  <li><b>Peak min distance</b>: minimum pixels between two seed points. Lower to split touching colonies, raise to merge.</li>
</ul>

<h3>Exporting</h3>
<p><b>Export CSV</b> writes just the counts: filename, total count, machine count, number removed, number added, and your notes.<br>
<b>Export bundle</b> writes a zip with the CSV, annotated PNGs and a JSON state file per image. Both let you choose the file name; on Chromium based browsers you can also pick where to save.</p>
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
    legendAuto: '机器识别',
    legendManual: '人工添加',
    presetLabel: '预设',
    presetWhite: '白色菌落（默认）',
    presetCream: '乳白或淡黄',
    presetYellow: '黄色菌落',
    presetAny: '任意亮色',
    presetCustom: '自定义',
    paramRadius: '新增菌落半径',
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
    statusProcessing: '正在计数…',
    statusAutoCounting: '正在自动计数这张图…',
    statusDone: '完成',
    statusIngesting: '正在导入…',
    statusUploading: '正在上传…',
    flagUnprocessed: '尚未计数',
    flagCounted: '已有算法计数，不代表人工核验',
    flagReviewed: '已编辑或历史查看标志；保留结果，不代表人工核验',
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
<p>一个跑在浏览器里的菌落计数小工具，专门对付平皿照片：把图拖进来，自动数一遍，鼠标点几下校正，再导出结果。无需联网，全在本地完成。</p>

<h3>导入图片</h3>
<ul>
  <li>直接把图片或者整个文件夹<b>拖到左侧</b>那个拖拽区。</li>
  <li>或者在下方输入框里<b>粘贴一个绝对路径</b>，点「导入路径」。这种方式只建符号链接，原图安然无恙。</li>
</ul>

<h3>开始计数</h3>
<p>点顶部「<b>全部计数</b>」。每张图左侧会显示数到的菌落数。点开任意一张图就能看到识别结果，机器识别到的菌落用<b style="color:#999999">浅灰圆圈</b>加编号标出。</p>

<h3>人工校对</h3>
<ul>
  <li><b>左键</b>点皿面空白处 —— 加一个手动菌落，画成<b style="color:#444444">灰色</b>圆圈。</li>
  <li><b>右键</b>点圆圈 —— 直接删掉它。</li>
  <li><b>Cmd/Ctrl Z</b> —— 撤销上一步增删。</li>
  <li><b>← →</b> —— 上一张、下一张。<b>滚轮</b>缩放，<b>Cmd/Ctrl 拖拽</b>平移。</li>
  <li>打开图片不会改变核验状态；人工核验必须主动勾选确认并保存。</li>
  <li><b>新增菌落半径</b>：你左键加菌落时画的那个绿圈有多大。纯视觉效果，不影响计数。</li>
</ul>

<h3>左侧小圆点的含义</h3>
<ul>
  <li><span style="display:inline-block;width:10px;height:10px;background:#555;border-radius:50%"></span> 灰色：图已上传，但还没算过。</li>
  <li><span style="display:inline-block;width:10px;height:10px;background:#999999;border-radius:50%"></span> 浅灰：已有算法计数，不代表人工核验。</li>
  <li><span style="display:inline-block;width:10px;height:10px;background:#444444;border-radius:50%"></span> 灰色：已编辑或历史查看标志；保留结果，不代表人工核验。</li>
</ul>

<h3>调参</h3>
<p>底部参数栏里，<b>预设</b>下拉里有四种常见情形（白色、乳白、黄色、任意亮色），切换后点「应用并重新计数」就行。如果想精调，可以一边动数字一边勾上「<b>实时阈值预览</b>」—— 当前阈值下被算作菌落的像素会被涂上亮青绿色高亮，所见即所得。调到满意后再点「应用并重新计数」生效。</p>

<h3>参数详解</h3>
<ul>
  <li><b>亮度下限</b>（Min value，0 到 255）：像素必须比这个值更亮才会算菌落。如果漏识真菌落 → 调低；如果反光被识别 → 调高。</li>
  <li><b>饱和度上限</b>（Max saturation）：颜色越接近白色饱和度越低。默认严格选白色，调高才能纳入黄色或橙色菌落。</li>
  <li><b>皿内缩比例</b>（Plate inset，0 到 1）：实际处理的圆形区域占皿半径的比例。皿壁反光被识别成菌落时，把这个值调低（比如 0.78）排除外圈。</li>
  <li><b>最小圆度</b>（Min circularity，0 到 1）：候选必须有多圆。形状不规则的伪影调高就能滤掉。</li>
  <li><b>最小面积占比</b>（Min area frac）：菌落最小面积，按皿面积的比例计。想保留小菌点就调低，想滤掉噪点就调高。</li>
  <li><b>最小种子间距</b>（Peak min distance，像素）：相邻两个菌落中心至少要差几像素。粘连菌落被合并 → 调低拆开；单个菌落被劈成两半 → 调高合并。</li>
</ul>

<h3>导出</h3>
<p><b>导出 CSV</b>：只给计数表，五列：文件名、最终总数、机器识别数、人工删除数、人工新增数、备注。<br>
<b>打包导出</b>：给一个 zip，里面除了 CSV 还有每张图的标注 PNG 和 JSON 状态档；如果以后想完全复现这次的计数（包括你手动加删的每一个圆圈），就用这个。<br>
两种方式都可以自己定文件名；在 Chrome / Edge 上还能选保存到哪个文件夹（Safari 走浏览器默认下载位置）。</p>

<h3>小提示</h3>
<p>每次重新启动 WeCFU 都会清空上次的所有导入和计数痕迹，所以每一次都是干净的工作台。如果想留下进度，导出 zip 即可。</p>
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
    legendAuto: '機械',
    legendManual: '手動',
    presetLabel: 'プリセット',
    presetWhite: '白いコロニー（既定）',
    presetCream: 'クリーム / 薄黄',
    presetYellow: '黄色コロニー',
    presetAny: '任意の明るい色',
    presetCustom: 'カスタム',
    paramRadius: '新規コロニー半径',
    paramMinValue: 'Min value',
    paramMaxSat: 'Max saturation',
    paramInset: 'Plate inset',
    paramCirc: 'Min circularity',
    paramArea: 'Min area frac',
    paramPeak: 'Peak min distance',
    livePreview: 'しきい値ライブプレビュー',
    applyParams: '適用して再カウント',
    notesLabel: 'メモ',
    notesPlaceholder: '画像ごとのメモ。CSV に保存されます',
    statusProcessing: 'カウント中…',
    statusAutoCounting: 'このプレートを自動カウント中…',
    statusDone: '完了',
    statusIngesting: '取り込み中…',
    statusUploading: 'アップロード中…',
    flagUnprocessed: '未カウント',
    flagCounted: 'アルゴリズムの計数結果。人による確認とは別です',
    flagReviewed: '編集済み・過去の閲覧記録。結果を保持します。人による確認とは別です',
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
    dropSubHint: 'Enlace simbólico, los originales no se modifican',
    pasteHint: 'O pega una ruta absoluta',
    ingestBtn: 'Importar ruta',
    countAll: 'Contar todo',
    countOne: 'Recontar',
    undo: '↶ Deshacer',
    exportCSV: 'Exportar CSV',
    exportBundle: 'Exportar paquete',
    selectAnImage: 'Elige una imagen',
    cfuSuffix: 'CFU',
    notProcessed: 'Sin contar',
    legend: '<b>Clic izq.</b> añadir &middot; <b>Clic der.</b> borrar &middot; <b>Rueda</b> zoom &middot; <b>Cmd/Ctrl arrastrar</b> mover &middot; <b>← →</b> ant / sig',
    legendAuto: 'Máquina',
    legendManual: 'Manual',
    presetLabel: 'Preset',
    presetWhite: 'Colonias blancas (por defecto)',
    presetCream: 'Crema o amarillo claro',
    presetYellow: 'Colonias amarillas',
    presetAny: 'Cualquier color brillante',
    presetCustom: 'Personalizado',
    paramRadius: 'Radio nueva colonia',
    paramMinValue: 'Min value',
    paramMaxSat: 'Max saturation',
    paramInset: 'Plate inset',
    paramCirc: 'Min circularity',
    paramArea: 'Min area frac',
    paramPeak: 'Peak min distance',
    livePreview: 'Vista previa de umbral en vivo',
    applyParams: 'Aplicar y recontar',
    notesLabel: 'Notas',
    notesPlaceholder: 'Nota por imagen, se guarda en el CSV',
    statusProcessing: 'Contando…',
    statusAutoCounting: 'Contando esta placa…',
    statusDone: 'Listo',
    statusIngesting: 'Importando…',
    statusUploading: 'Subiendo…',
    flagUnprocessed: 'Aún no contada',
    flagCounted: 'Resultado del algoritmo; no es verificación humana',
    flagReviewed: 'Editada o vista anteriormente; resultado protegido, sin verificación humana',
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
    selectAnImage: 'Choisissez une image',
    cfuSuffix: 'CFU',
    notProcessed: 'Non compté',
    legend: '<b>Clic gauche</b> ajouter &middot; <b>Clic droit</b> supprimer &middot; <b>Molette</b> zoom &middot; <b>Cmd/Ctrl glisser</b> déplacer &middot; <b>← →</b> préc / suiv',
    legendAuto: 'Machine',
    legendManual: 'Manuel',
    presetLabel: 'Préréglage',
    presetWhite: 'Colonies blanches (défaut)',
    presetCream: 'Crème ou jaune pâle',
    presetYellow: 'Colonies jaunes',
    presetAny: 'Toute couleur claire',
    presetCustom: 'Personnalisé',
    paramRadius: 'Rayon nouvelle colonie',
    paramMinValue: 'Min value',
    paramMaxSat: 'Max saturation',
    paramInset: 'Plate inset',
    paramCirc: 'Min circularity',
    paramArea: 'Min area frac',
    paramPeak: 'Peak min distance',
    livePreview: 'Aperçu de seuil en direct',
    applyParams: 'Appliquer et recompter',
    notesLabel: 'Notes',
    notesPlaceholder: 'Note par image, enregistrée dans le CSV',
    statusProcessing: 'Comptage…',
    statusAutoCounting: 'Comptage automatique de cette boîte…',
    statusDone: 'Terminé',
    statusIngesting: 'Importation…',
    statusUploading: 'Téléversement…',
    flagUnprocessed: 'Non compté',
    flagCounted: 'Résultat de l’algorithme ; sans validation humaine',
    flagReviewed: 'Modifiée ou consultée auparavant ; résultat protégé, sans validation humaine',
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

// Internal interaction update. New keys use English fallback for other languages.
Object.assign(I18N.en, {
  internalBuild: 'Internal preview · local only',
  addImages: 'Add images', removeImage: 'Remove image',
  removeImageConfirm: 'Remove this image and its counting state from this session? Your original photo is not deleted.',
  clearAll: 'Clear all marks', retrySave: 'Retry save',
  saving: 'Saving…', saved: 'Saved locally', saveFailed: 'Unsaved — retry save',
  countMode: 'Mode', modeAuto: 'Automatic + manual', modeManual: 'Pure manual',
  manualHint: 'No automatic counting. Click to add colonies.',
  autoHint: 'Opening an image does not count it. Click Recount when ready.',
  fitView: 'Fit full photo', adjustCrop: 'Adjust medium boundary',
  boundaryViewHint: 'The circle is the maximum growth-medium boundary, excluding the dish wall. Edge coverage may narrow recognition; the full photo stays visible and editable.',
  frozenBoundaryHint: 'This circle is a growth-medium reference, excluding the dish wall. Adjusting it does not rerun frozen candidates; marks can be added anywhere in the photo.',
  previousImage: 'Previous image', nextImage: 'Next image',
  cropHint: 'Follow the growth medium, excluding the dish wall. Drag inside to move or drag the edge to resize. Saving the boundary preserves current marks.',
  cropRadius: 'Radius', applyCrop: 'Save medium boundary', resetDefaults: 'Reset defaults',
  paramsChanged: 'Parameters changed. Apply and recount to update marks.',
  invalidParams: 'Check the parameter range and step.',
  actionFailed: 'Action failed', loadingImage: 'Loading photo and medium boundary…',
  imageLoadFailed: 'Cannot load this image. Please retry.', networkError: 'Network connection failed',
  noImages: 'No supported images found (.jpg, .jpeg, .png, .tif, .tiff).',
  stopCounting: 'Stop after this image', countStopped: 'Stopped',
  countCompleted: 'counted', countSkipped: 'preserved',
  exportHint: 'CSV is fastest. The bundle also generates annotated images and may take longer.',
  exportPreparingCSV: 'Preparing CSV…', exportPreparingZIP: 'Preparing bundle and annotated images…',
  exportReceiving: 'Saving export…', exportSaved: 'Export saved',
  exportDownloadStarted: 'Download started — check your browser downloads',
  legend: '<b>Click</b> add · <b>Right click</b> remove · <b>Quick left drag</b> box remove · <b>Hold 0.35 s then drag</b> pan · <b>Wheel</b> zoom · <b>Outside click / F</b> fit',
  helpBody: `<h3>Count and correct</h3><p>Import with Add images, drag and drop, or a local path. Further imports append to this session. Opening a photo locates the plate but does not segment colonies or mark it as reviewed. Recount runs automatic counting for the current image. Count all processes untouched automatic images sequentially; manual or edited images are preserved.</p>
  <ul><li>Left click empty photo space to add a colony; right click a mark to remove it.</li><li>Quickly drag with the left button to remove every mark whose center is inside the rectangle. Clear all marks empties the current image. Both operations support Undo / Cmd or Ctrl Z.</li><li>Hold the mouse still for 0.35 seconds, then drag to pan. Cmd/Ctrl drag and middle-button drag also work. Use the wheel to zoom; Fit full photo, F, or a click outside the photo restores the full view.</li><li>Use the arrow buttons beside the image or the left/right keys to switch images.</li></ul>
  <h3>Manual mode and boundaries</h3><p>Pure manual mode removes machine marks and resets their baseline while preserving your manual marks. It never runs automatic counting. Undo restores the previous state. Switching back to Automatic + manual does not count until Recount is pressed.</p>
  <p>The full original photo is always visible. Adjust medium boundary sets the maximum growth-medium range for machine recognition, excluding the dish wall; edge coverage may narrow that range. Drag the circle to move its center or its edge to resize it; X, Y, and Radius allow precise adjustment in original-image pixels. Save medium boundary preserves current marks and supports Undo. In frozen candidate queues it only saves a human boundary reference and never reruns recognition.</p>
  <h3>Parameters and saving</h3><p>Each preset fills all six algorithm fields. Reset defaults restores the white-colony preset, a 40-pixel manual radius while keeping your preview preference. Parameters are saved per image; Apply and recount updates its automatic result. Recount can be undone.</p>
  <p>Edits save locally in the background. Saved locally confirms success; Unsaved remains visible after an error and Retry save retries the pending changes. Switching images, recounting and exporting wait for pending edits. Keep the page open while unsaved. Remove image removes its imported entry and count state only; original source photos remain untouched.</p>
  <p>CSV is the fastest export. A bundle also contains annotated images and JSON states. Existing annotated images are reused when unchanged. This is an internal preview and does not publish your data.</p>` + AUTHORS_FOOTER,
});
Object.assign(I18N['zh-CN'], {
  internalBuild: '内部试用版 · 仅本地',
  addImages: '添加板子图片', removeImage: '移除当前板子',
  removeImageConfirm: '从本次列表移除这张图片及其计数记录？不会删除你的原始照片。',
  clearAll: '全部取消标记', retrySave: '重试保存',
  saving: '正在保存…', saved: '已保存到本地', saveFailed: '尚未保存，请重试',
  countMode: '计数模式', modeAuto: '自动识别＋手动校正', modeManual: '纯手动',
  manualHint: '不运行自动识别，点击图片添加菌落。',
  autoHint: '打开图片不会自动计数；准备好后点击「重新计数」。',
  fitView: '全图最佳视野', adjustCrop: '调整培养基边界',
  boundaryViewHint: '圈线为培养基最大边界，不含皿外壁；识别范围可按边缘覆盖内缩，全图始终可查看、补点。',
  frozenBoundaryHint: '圈线为培养基边界参考，不含皿外壁；调圈不会重新识别固定候选，图内圈外均可补点。',
  previousImage: '上一张', nextImage: '下一张',
  cropHint: '沿培养基边缘设圈，不包含培养皿外壁。拖动圆内移动、拖动圆边缩放；保存边界保留当前标记。',
  cropRadius: '半径', applyCrop: '保存培养基边界', resetDefaults: '恢复默认',
  paramsChanged: '参数已修改，点击「应用并重新计数」更新标记。',
  invalidParams: '请检查参数的取值范围和步长。',
  actionFailed: '操作未完成', loadingImage: '正在加载照片与培养基边界…',
  imageLoadFailed: '图片加载失败，请重试。', networkError: '网络连接失败',
  noImages: '未找到支持的图片（.jpg、.jpeg、.png、.tif、.tiff）。',
  stopCounting: '完成当前板子后停止', countStopped: '已停止',
  countCompleted: '张已计数', countSkipped: '张保留原有结果',
  exportHint: 'CSV 导出最快；完整包还会生成标注图片，耗时较长。',
  exportPreparingCSV: '正在准备 CSV…', exportPreparingZIP: '正在生成完整包及标注图片…',
  exportReceiving: '正在保存导出文件…', exportSaved: '导出文件已保存',
  exportDownloadStarted: '已开始下载，请查看浏览器下载列表',
  legend: '<b>左击</b> 添加 · <b>右击</b> 删除 · <b>左键快速拖框</b> 批量取消 · <b>长按 0.35 秒后拖动</b> 平移 · <b>滚轮</b> 缩放 · <b>点击圆外 / F</b> 最佳视野',
  helpBody: `<h3>计数与校正</h3><p>点击「添加板子图片」、拖入文件或文件夹，或填写本地路径进行导入。后续导入会追加到当前列表。打开图片只定位培养皿，不会自动识别菌落或标为已查看；点击「重新计数」运行当前板子的自动识别。「全部计数」逐张处理尚未计数的自动模式图片，保留纯手动和已有校正结果。</p>
  <ul><li>在图片内空白处左击添加菌落，右击已有标记删除。</li><li>左键按下后立即拖出方框，取消中心点在框内的全部标记。「全部取消标记」清空当前板子的标记。两者均支持「撤销」及 Cmd / Ctrl Z。</li><li>鼠标按住不动约 0.35 秒后拖动即可平移，也可使用 Cmd / Ctrl 拖动或鼠标中键拖动。滚轮缩放；「全图最佳视野」、F 键或点击图片外区域可恢复整张照片。</li><li>图片两侧的箭头按钮和键盘左右键可以切换板子。</li></ul>
  <h3>纯手动模式与边界调整</h3><p>切换「纯手动」会移除机器标记并清零机器计数基线，保留人工添加的标记；可撤销恢复。纯手动模式不运行自动识别。切回自动模式后，需主动点击「重新计数」才会识别。</p>
  <p>原图始终完整显示；「调整培养基边界」为机器设置最大培养基范围，不包含培养皿外壁，实际识别范围还可按边缘覆盖内缩。拖动圆内移动中心、拖动圆边改变大小，也可以用 X、Y、半径精确输入原图像素坐标。保存边界保留当前菌落标记并支持撤销；冻结候选队列只保存人工边界参考，不自动重新识别。</p>
  <h3>参数与保存</h3><p>预设会完整填入全部六项算法参数。「恢复默认」恢复白色菌落默认参数、40 像素的新增标记半径，并保留你选择的预览开关状态。参数按图片保存，点击「应用并重新计数」后更新自动标记。重新计数也可撤销。</p>
  <p>修改会在后台保存到本地。「已保存到本地」表示保存成功；失败时保留「尚未保存」提示，可点击「重试保存」。切换图片、重新计数和导出前会先等待保存。尚未保存时请保持页面打开。「移除当前板子」只移除导入项和本次计数记录，不删除原始照片。</p>
  <p>仅需数字时导出 CSV 最快。完整包还包含标注图片和 JSON 状态，未变化的标注图片会复用缓存。本版本仅用于内部试用，不对外发布数据。</p>` + AUTHORS_FOOTER,
});
// Slider labels describe effects; raw units remain available in Advanced.
Object.assign(I18N.en, {
  sliderBrightness: 'Brightness filter', brightnessLow: 'Include dimmer', brightnessHigh: 'Bright only',
  sliderColor: 'Color tolerance', colorLow: 'Near-white only', colorHigh: 'Include color',
  sliderEdge: 'Edge coverage', edgeLow: 'Avoid reflections', edgeHigh: 'Include edges',
  sliderShape: 'Shape filter', shapeLow: 'Keep irregular', shapeHigh: 'Round only',
  sliderSmall: 'Small-dot filter', smallLow: 'Keep small dots', smallHigh: 'Remove small dots',
  sliderSplit: 'Touching-colony split', splitLow: 'Fewer splits', splitHigh: 'More splits',
  sliderRadius: 'New mark size', radiusLow: 'Small', radiusHigh: 'Large',
  liveControl: 'Live', countControl: 'Recount', manualControl: 'Manual',
  normalizedScale: '0–1 is the slider position, not a confidence score.',
  livePreview: 'Live foreground preview',
  previewLoading: 'Loading reference…', previewRefreshing: 'Updating; previous reference shown…',
  previewReady: 'Gray = threshold foreground', previewFailed: 'Preview unavailable; toggle to retry',
  previewFailedOld: 'Update failed; previous reference shown. Toggle to retry.',
  previewExplanation: 'Bright mint shows threshold foreground, not final colonies. Shape, small-dot filtering and splitting take effect after Apply and recount.',
  advancedParams: 'Advanced: exact values',
  advancedHint: 'Original algorithm units. Loading, presets and saving preserve exact values. Sliders use a practical range; advanced values can go beyond it.',
  sliderRangeWarning: 'An exact value is outside a slider’s usual range and is preserved.',
  paramsChanged: 'Parameters changed; apply and recount to update marks.',
  manualHint: 'Click to count manually; the foreground preview remains available.',
});
Object.assign(I18N['zh-CN'], {
  sliderBrightness: '亮度筛选', brightnessLow: '允许较暗', brightnessHigh: '只取明亮',
  sliderColor: '颜色容许度', colorLow: '仅近白', colorHigh: '包含彩色',
  sliderEdge: '边缘覆盖', edgeLow: '避开反光', edgeHigh: '覆盖边缘',
  sliderShape: '形状筛选', shapeLow: '保留不规则', shapeHigh: '仅较圆',
  sliderSmall: '小菌落筛选', smallLow: '保留小点', smallHigh: '过滤小点',
  sliderSplit: '粘连拆分', splitLow: '少拆分', splitHigh: '多拆分',
  sliderRadius: '新增标记大小', radiusLow: '小', radiusHigh: '大',
  liveControl: '实时', countControl: '重新计数', manualControl: '手动',
  normalizedScale: '0–1 表示调节位置，不表示识别准确率。',
  livePreview: '实时前景预览',
  previewLoading: '正在生成参考…', previewRefreshing: '更新中，暂显示上一版参考…',
  previewReady: '亮青绿 = 阈值前景', previewFailed: '预览暂不可用，重新开关可重试',
  previewFailedOld: '更新失败，仍为上一版参考；重新开关可重试',
  previewExplanation: '亮青绿色仅为阈值前景，并非最终菌落。形状、小菌落筛选、拆分需「应用并重新计数」后生效。',
  advancedParams: '高级：精确参数',
  advancedHint: '沿用原算法单位，加载、预设和保存保留精度。滑块采用常用范围，高级输入可超出该范围。',
  sliderRangeWarning: '部分精确值超出滑块常用范围，原值已保留。',
  paramsChanged: '参数已改，应用并重新计数后更新标记。',
  manualHint: '点击图片手动计数，仍可使用前景预览作参考。',
});
I18N.en.helpBody = I18N.en.helpBody.replace('<h3>Parameters and saving</h3>', '<h3>Sliders and foreground preview</h3><p>Sliders show a normalized 0–1 position and explain the effect at both ends. Small-dot filtering uses a logarithmic scale, and more splitting means smaller spacing between detected peaks. Advanced keeps the original numeric values for precise entry; opening an old result never rounds its saved parameters.</p><p>The preview is enabled initially and remembers your explicit on/off choice across images, modes, defaults and browser reloads. Brightness, color tolerance and edge coverage update the bright mint threshold foreground. It is a visual reference, not a prediction of final colonies; shape, small-dot filtering and splitting require Apply and recount. Pure manual mode can use the preview without automatic segmentation.</p><h3>Parameters and saving</h3>');
I18N['zh-CN'].helpBody = I18N['zh-CN'].helpBody.replace('<h3>参数与保存</h3>', '<h3>滑块与前景参考</h3><p>滑块统一显示 0–1 调节位置，两端文字说明变化方向。小菌落筛选采用对数范围，增加拆分对应缩小种子间距。「高级：精确参数」保留原始数值输入；打开已有结果不会取整或修改已保存参数。</p><p>预览初始开启，主动开关后会记住你的选择；切换图片、模式、恢复默认或刷新页面都不会覆盖这一选择。亮度、颜色容许度和边缘覆盖实时更新亮青绿色阈值前景。预览是视觉参考，不是最终识别到的菌落；形状、小菌落筛选和拆分需点击「应用并重新计数」才更新结果。纯手动模式也可使用预览，不会运行自动分割计数。</p><h3>参数与保存</h3>');

Object.assign(I18N.en, {
  referenceTitle: 'Accuracy verification', referenceOptional: 'Optional',
  referencePurpose: 'Check colony counts and centers, then explicitly save a human reference. Growth-medium boundary verification is separate and optional. A viewed image is not human verified.',
  referenceAnnotator: 'Reviewer code (required)', referenceAnnotatorPlaceholder: 'e.g. reviewer-01',
  referenceGroup: 'Sample group (optional)', referenceGroupPlaceholder: 'e.g. sample-001',
  referenceGroupHint: 'Use the same code for one sample or repeated photos; leave blank if unsure.',
  referenceConfirmation: 'I checked all colony counts, centers, and missed/false marks.',
  referenceCropConfirmation: 'I checked the growth-medium boundary for machine recognition, excluding the dish wall (optional).',
  referenceScopeHint: 'Leave boundary unchecked if you did not check it. It never crops the photo displayed for human review. Marker sizes are not colony outline annotations.',
  referenceCropUnknown: 'Medium boundary: not checked here', referenceScopeLegacy: 'Historical verification scope unspecified',
  referenceCropUnreviewed: 'Medium boundary: not verified', referenceCropVerified: 'Medium boundary: verified',
  referenceCropStale: 'Medium boundary: check again', referenceCropWithdrawn: 'Medium boundary verification withdrawn',
  referenceEmptyWarning: 'There are currently 0 marks. Confirm that this is a genuinely blank plate before checking the box.',
  referenceSave: 'Save colony verification', referenceRefresh: 'Refresh status and photo',
  referenceWithdraw: 'Withdraw reference', referenceExport: 'Export verified references',
  referenceVerified: 'Colony reference verified', referenceMissing: 'Colonies not verified',
  referenceStale: 'Changed; verify again', referenceWithdrawn: 'Withdrawn',
  referenceLastRecord: 'Last human reference', referenceLoading: 'Loading verification status and the source photo…',
  referenceStaleHint: 'The current photo or marks differ from the verified reference. Check them again before saving. If the source photo changed, refresh the photo first.',
  referenceVerifiedHint: 'The photo and marks match the saved verification scope. Medium boundary status is shown separately. Withdrawal preserves the audit history.',
  referenceFailed: 'Reference action failed', referenceSaved: 'Human reference saved', referenceSaving: 'Saving human reference…',
  referenceExporting: 'Preparing currently verified references…',
  referenceMissingImageHash: 'Cannot bind verification to the displayed photo. Refresh the verification photo and try again.',
  referenceMissingRevision: 'The latest saved image revision is unavailable. Reload the image before verification.',
});
Object.assign(I18N['zh-CN'], {
  referenceTitle: '准确率核验', referenceOptional: '可选',
  referencePurpose: '核对菌落数量与中心后，可主动保存人工参考答案。培养基边界单独核验，可不勾选；查看/编辑标志仅用于保留结果，不代表人工核验；打开图片不会改变它。',
  referenceAnnotator: '核验人代号（必填）', referenceAnnotatorPlaceholder: '例如 reviewer-01',
  referenceGroup: '样本分组编号（可选）', referenceGroupPlaceholder: '例如 sample-001',
  referenceGroupHint: '同一样本/重复拍摄用同一编号；不确定可留空。',
  referenceConfirmation: '已逐个核对全部菌落数量、中心位置及漏检／误检',
  referenceCropConfirmation: '已核对机器识别的培养基边界，不含皿外壁（可选）',
  referenceScopeHint: '未检查培养基边界时请勿勾选；该边界不裁掉人工查看的照片，标记圈大小不代表菌落真实轮廓。',
  referenceCropUnknown: '培养基边界：本页尚未核对', referenceScopeLegacy: '历史核验范围未明确',
  referenceCropUnreviewed: '培养基边界：未核验', referenceCropVerified: '培养基边界：已核验',
  referenceCropStale: '培养基边界：需重新核对', referenceCropWithdrawn: '培养基边界核验已撤回',
  referenceEmptyWarning: '当前为 0 个标记，请确认确实是空白皿，再勾选核验。',
  referenceSave: '保存菌落核验', referenceRefresh: '刷新核验状态和照片',
  referenceWithdraw: '撤回人工参考', referenceExport: '导出已核验参考答案',
  referenceVerified: '菌落参考已核验', referenceMissing: '菌落未核验',
  referenceStale: '已变更，需重新核验', referenceWithdrawn: '已撤回',
  referenceLastRecord: '上次人工参考', referenceLoading: '正在加载核验状态及对应原图…',
  referenceStaleHint: '当前照片或标记与人工参考不一致，请重新检查后保存。若原照片发生变化，请先刷新核验照片。',
  referenceVerifiedHint: '当前照片与标记符合已保存的核验范围；培养基边界状态单独显示，撤回会保留历史记录。',
  referenceFailed: '核验操作未完成', referenceSaved: '人工参考答案已保存', referenceSaving: '正在保存人工参考答案…',
  referenceExporting: '正在导出当前有效的已核验参考…',
  referenceMissingImageHash: '无法确认核验对应的照片，请刷新核验照片后重试。',
  referenceMissingRevision: '无法取得最新保存版本，请重新加载图片后再核验。',
});
I18N.en.helpBody = I18N.en.helpBody.replace('<h3>Parameters and saving</h3>', '<h3>Optional human references</h3><p>Accuracy verification is separate from viewing an image. After correcting colony counts and centers, enter your reviewer code and explicitly check the colony confirmation box. Check the separate optional boundary box only if you also reviewed the growth-medium boundary. Zero marks are allowed only after you confirm a blank plate. Save as a human reference records this photo and its current geometry; no ordinary edit or automatic count verifies it for you.</p><p>Geometry edits reset both confirmation boxes. New references bind colony counts and centers; marker radii are not ground truth. The growth-medium boundary affects their validity only when its verification was explicitly included. Older records retain their original geometry binding and show an unspecified historical scope. Notes and algorithm parameters do not change the reference. Refresh status and photo reloads the pixels being verified. Withdraw reference preserves the history; you can check and save a new reference later. Export includes only references that still match their photo and marks.</p><p>Use one sample-group code for repeat photos of the same sample. A group code is only grouping information, not proof that samples are independent. Human reference labels support later evaluation and do not by themselves establish recognition accuracy.</p><h3>Parameters and saving</h3>');
I18N['zh-CN'].helpBody = I18N['zh-CN'].helpBody.replace('<h3>参数与保存</h3>', '<h3>可选的人工参考答案</h3><p>「准确率核验」与打开或查看图片相互独立。核对菌落数量与中心后，填写核验人代号，主动勾选菌落确认，再点击「保存菌落核验」。只有确实检查过培养基边界时，才勾选独立的可选培养基边界确认。0 个标记可以作为空白皿参考，但必须先明确确认。普通编辑、自动识别或历史查看标志都不会自动核验；打开图片不会写入查看标志。</p><p>几何编辑会清除两项确认。新参考绑定菌落数量与中心，标记半径不作真值；仅在明确确认过培养基边界时，边界变化才使该参考失效。旧记录保留原几何绑定，显示历史核验范围未明确。备注和算法参数不改变参考。刷新核验状态和照片会重新加载对应像素。撤回保留历史记录，之后可以重新检查并保存。导出只包含仍与照片和标记一致的有效核验记录。</p><p>同一样本的重复照片使用同一分组编号；该编号只用于归组，不代表已确认样本独立性。人工参考用于后续评估，不能单独作为算法准确率结论。</p><h3>参数与保存</h3>');

Object.assign(I18N.en, {
  recognitionMethod: 'Method', methodBaseline: 'Traditional', methodModel: 'CFUCounter experiment',
  methodSam: 'Local visual model SAM', samSavedSource: 'Saved: local visual model SAM',
  methodFusionV2: 'Fusion v2 (internal trial)', fusionV2SavedSource: 'Saved: fusion v2 (internal trial)',
  fusionV2Warning: 'Separate internal trial. It keeps SAM marks and adds selected candidates; supplemental centers may be offset. Check counts, missed and false marks before adopting. It does not replace the default method.',
  methodFusion: 'Fusion enhancement (trial)', fusionSavedSource: 'Saved: fusion enhancement (trial)',
  fusionWarning: 'Keeps the SAM result from this trial and adds selected supplemental candidates. Supplemental circles only indicate centers; they are not the true colony outlines. Check missed, false and merged marks before adopting.',
  fusionRoiHint: 'Fusion trials support front/blank photos and automatic medium boundaries only, at a fixed 95% radius. Use another method for manually adjusted boundaries. The whole photo remains visible. Amber dashed marks are unsaved candidates; adoption replaces current marks and can be undone.',
  fusionAutomaticPlateRequired: 'Default recognition requires the automatic medium boundary. This photo has a manually adjusted boundary, which will be kept. Switch to Custom recognition or continue manual correction.',
  samWarning: 'The local model provides candidates that still need checking for missed and false marks. Color, brightness and other counting sliders apply only to traditional recognition.',
  samRoiHint: 'SAM analyzes the full photo. Machine mark centers are kept inside the cyan dashed circle, fixed at 95% of the medium radius. Amber dashed marks are unsaved candidates. Changing the boundary needs a new trial; the full photo stays visible and editable.',
  modelTrial: 'Run model trial', modelDiscard: 'Discard trial', modelApply: 'Replace current marks with trial results',
  modelRetry: 'Confirm pending replacement', modelReplaceHint: 'Replaces every current mark, including manual points. You can undo it.',
  modelWarning: 'Experimental model; real-photo accuracy has not been verified. Large spreading or confluent growth may be missed. Check every colony.',
  modelEmptyWarning: 'No detections does not mean a blank plate. Large areas of growth may be missed.',
  modelRoiHint: 'Candidates whose centers are inside the cyan dashed circle are retained. Changed coverage needs a new trial; amber dashed marks are unsaved candidates.',
  modelModeHint: 'Run a model trial to inspect candidates first. Adopt the result before continuing manual corrections.',
  modelManualHint: 'Pure manual mode: click the image to add or remove marks.',
  modelLoading: 'Running a temporary model trial…', modelTemporary: 'Temporary trial', modelCurrent: 'Current marks', modelNotAdopted: 'not adopted',
  modelUnavailable: 'The local model is unavailable. Check the explicitly configured local weights.',
  modelManual: 'Pure manual mode does not run models. Switch to automatic + manual to start a trial.',
  modelExpired: 'The trial is expired or its context changed. Run a new trial.', modelFailed: 'Model trial failed',
  modelApplying: 'Replacing current marks…', modelApplied: 'Trial adopted. Undo restores the previous marks.',
  modelUnknown: 'The replacement response was not received. Editing is paused until its outcome is confirmed. Retry the same request with “Confirm pending replacement”, or reload the saved result without writing local marks.',
  modelApplyFailed: 'Replacement was rejected; current marks were kept.', modelMissingRevision: 'The latest saved revision is unavailable. Reload the image.',
  modelReferenceBlocked: 'Discard or adopt the temporary trial before checking the saved marks as a human reference.',
  modelSavedSource: 'Saved: CFUCounter experiment', modelBaselineSource: 'Saved: traditional',
  modelChanged: 'The context changed. Run a new trial.',
  modelReload: 'Reload saved result', modelReloadRequired: 'The saved result changed while confirming. Reload it before continuing; no local marks will be written.',
  modelReloaded: 'Saved result reloaded. Check it before editing or starting another trial.',
  modelSavePending: 'Replacement awaiting confirmation',
  modelListRefreshFailed: 'The image list could not refresh',
  modelRoiChanged: 'The edge range has changed. Run a new model trial and adopt it to update the model result.',
});
Object.assign(I18N['zh-CN'], {
  recognitionMethod: '识别方法', methodBaseline: '传统识别', methodModel: 'CFUCounter 实验试算',
  methodSam: '本地视觉模型 SAM', samSavedSource: '已保存：本地视觉模型 SAM',
  methodFusionV2: '融合增强 v2（内部试用）', fusionV2SavedSource: '已保存：融合增强 v2（内部试用）',
  fusionV2Warning: '独立内部试用版本，保留 SAM 标记并补充筛选后的候选；补充点的中心位置仍可能偏移。采用前请核对数量、漏检与误检；默认识别方法不变。',
  methodFusion: '融合增强（试用）', fusionSavedSource: '已保存：融合增强（试用）',
  fusionWarning: '保留本次 SAM 识别结果，并补充筛选后的候选。补充圈仅提示菌落中心，不代表菌落真实边界；采用前请检查漏检、误检和粘连。',
  fusionRoiHint: '融合试用仅支持正面/空白图和自动培养基边界；手工调圈请选其他方法。范围固定为半径的 95%，整张照片始终可见。琥珀虚线是未保存候选；主动采用后替换当前标记，可撤销。',
  fusionAutomaticPlateRequired: '默认识别需要自动培养基边界。这张图已手动调整边界，将保留现有范围；可切换到自定义识别，或继续手动校正。',
  samWarning: '本地模型仅提供候选，仍需逐个核对漏检与误检。颜色、亮度等滑条仅适用于传统识别。',
  samRoiHint: 'SAM 整图分析，青色虚线内保留机器标记中心，范围固定为培养基半径的 95%。琥珀虚线为未保存候选。调圈后需重新试算；整张照片始终可见、可补点。',
  modelTrial: '模型试算', modelDiscard: '丢弃试算', modelApply: '用试算结果替换当前标记',
  modelRetry: '确认待定替换结果', modelReplaceHint: '将替换全部当前标记（包括人工添加的点），可撤销。',
  modelWarning: '实验模型，尚未完成真实照片的人工准确率评估；大面积融合或铺展生长可能漏检，请逐个核对。',
  modelEmptyWarning: '未检出不代表空白皿；大面积生长可能漏检。',
  modelRoiHint: '圆内中心的候选会保留，改变范围后需重新试算；青色细虚线为当前范围，琥珀色虚线为未保存候选。',
  modelModeHint: '点击模型试算先查看候选，采用后可继续手动校正。',
  modelManualHint: '纯手动模式：点击图片添加或删除标记。',
  modelLoading: '正在进行临时模型试算…', modelTemporary: '临时试算', modelCurrent: '当前标记', modelNotAdopted: '未采用',
  modelUnavailable: '本地模型不可用，请检查显式配置的本地权重。',
  modelManual: '纯手动模式不运行模型；切换到自动辅助后可主动试算。',
  modelExpired: '候选已过期或上下文已变化，请重新试算。', modelFailed: '模型试算未完成',
  modelApplying: '正在替换当前标记…', modelApplied: '已采用试算结果；撤销可恢复此前全部标记。',
  modelUnknown: '尚未收到替换结果，已暂停编辑以避免覆盖。可点击「确认待定替换结果」安全重试同一请求，或只读重新载入已保存结果。',
  modelApplyFailed: '替换被拒绝，当前标记保持不变。', modelMissingRevision: '无法取得最新保存版本，请重新加载图片。',
  modelReferenceBlocked: '请先丢弃或采用临时试算，再核对正式标记并保存人工参考。',
  modelSavedSource: '已保存：CFUCounter 实验', modelBaselineSource: '已保存：传统识别', modelChanged: '上下文已变化，请重新试算。',
  modelReload: '重新载入已保存结果', modelReloadRequired: '确认期间保存结果已变化。请先重新载入；不会写入当前本地标记。',
  modelReloaded: '已重新载入保存结果，请检查后再编辑或重新试算。',
  modelSavePending: '替换结果待确认',
  modelListRefreshFailed: '图片列表暂未刷新',
  modelRoiChanged: '边缘范围已改变，重新试算并采用后生效。',
});

Object.assign(I18N.en, {
  assistedSavedSource: 'SAM 2 assisted candidates', initialMachineCount: 'Initial machine count',
  assistedFrozenHint: 'Correct the fixed candidates by adding or removing marks. Open verification to confirm and save.',
  methodEnhanced: 'Enhanced (internal trial)', enhancedSavedSource: 'Saved: enhanced internal trial',
  presetLegacy: 'Legacy defaults', builtinMethodPending: 'Selected method changed. Recount replaces the current marks; you can undo it.',
  manualMarksSuffix: 'manual marks', referenceExpandSave: 'Open to confirm and save',
  reviewReferencePurpose: 'Check all colony counts and centers, then confirm and save to count toward progress. Growth-medium boundary verification is separate and optional.',
  imageInteractionLegend: '<b>Click image</b> add · <b>Right click</b> remove · <b>Quick left drag</b> box remove · <b>Hold then drag</b> pan · <b>Wheel</b> zoom · <b>Click outside image / F</b> fit full photo',
  reviewTitle: 'Manual review queue', reviewParams: 'Show/hide counting controls', reviewRefresh: 'Refresh verification progress',
  reviewPosition: 'Image', reviewVerifiedProgress: 'Human verified', reviewLoading: 'Loading review queue…',
  reviewUnavailable: 'Review queue unavailable. Editing is paused; reload this page after the queue is corrected.',
  reviewChanged: 'The review queue changed. Reload this page before continuing.',
  reviewReload: 'Reload review queue', reviewMissing: 'Not verified', reviewVerified: 'Verified',
  reviewStale: 'Changed', reviewWithdrawn: 'Withdrawn',
});
Object.assign(I18N['zh-CN'], {
  assistedSavedSource: 'SAM 2 辅助候选', initialMachineCount: '初始机器计数',
  assistedFrozenHint: '在固定候选上增删标记；核对后展开确认并保存。',
  methodEnhanced: '增强识别（内部试用）', enhancedSavedSource: '已保存：增强识别（内部试用）',
  presetLegacy: '旧版默认', builtinMethodPending: '待用方法已改变；点击重新计数后替换当前标记，可撤销。',
  manualMarksSuffix: '个手动标记', referenceExpandSave: '展开确认并保存',
  reviewReferencePurpose: '核对全部菌落数量与中心，勾选确认并保存后计入进度；培养基边界单独核验，可不勾选。',
  imageInteractionLegend: '<b>左击图片</b> 添加 · <b>右击</b> 删除 · <b>左键快速拖框</b> 批量取消 · <b>长按后拖动</b> 平移 · <b>滚轮</b> 缩放 · <b>点击图片外 / F</b> 全图最佳视野',
  reviewTitle: '人工复核队列', reviewParams: '展开／收起计数参数', reviewRefresh: '刷新核验进度', reviewPosition: '当前',
  reviewVerifiedProgress: '已人工核验', reviewLoading: '正在加载复核队列…',
  reviewUnavailable: '复核队列不可用，已停止编辑；修正队列后请重新加载本页。',
  reviewChanged: '复核队列已变化，请重新加载本页后再继续。', reviewReload: '重新加载复核队列',
  reviewMissing: '未核验', reviewVerified: '已核验', reviewStale: '已变更', reviewWithdrawn: '已撤回',
});

Object.assign(I18N.ja, {manualMarksSuffix: '個の手動マーク'});
Object.assign(I18N.es, {manualMarksSuffix: 'marcas manuales'});
Object.assign(I18N.fr, {manualMarksSuffix: 'marques manuelles'});

for (const language of ['ja', 'es', 'fr']) {
  I18N[language].legend = I18N.en.legend;
  I18N[language].helpBody = I18N.en.helpBody;
}


// The primary workspace keeps implementation names in advanced/source details.
Object.assign(I18N.en, {
  flagUnprocessed: 'Not recognized', flagCounted: 'Machine recognition completed', flagViewed: 'Viewed or edited · not accuracy verification',
  viewStatusFailed: 'View status was not saved. Reopen this photo to retry.',
  legendAuto: 'Machine · rose', legendManual: 'Manual · blue',
  internalBuild: 'Internal', imagesTitle: 'Photos', exportMenu: 'Export', imageActions: 'More',
  importPath: 'Import from a path', resultDetails: 'Result details', interactionHelp: 'Controls',
  recognitionProfile: 'Recognition settings', profileDefault: 'Default', profileCustom: 'Custom',
  recognizeCurrent: 'Recognize current', customSettings: 'Adjustments',
  manualMarkSettings: 'Manual marks', manualMarkRadius: 'Radius (px)', manualMarkHint: 'Only affects new manual marks.',
  customRunAll: 'Recognize all', presetWhite: 'Default',
  applyParams: 'Apply', resetDefaults: 'Reset', sidebarPhotos: 'Photos', sidebarAdjustments: 'Adjustments', sidebarTabs: 'Workspace', modelApply: 'Adopt result', modelDiscard: 'Cancel preview',
  modelTrial: 'Recognize current', modelTemporary: 'Recognition preview', modelNotAdopted: 'Not adopted',
  modelModeHint: 'Preview the current photo, then adopt the result before making manual corrections.',
  modelLoading: 'Recognizing this photo…',
  fusionV2Warning: 'Check counts, missed and false marks before adopting. Supplemental circles indicate centers, not true colony boundaries; their centers may be offset.',
  fusionWarning: 'Check missed, false and merged marks before adopting. Supplemental circles indicate centers, not true colony boundaries.',
  samWarning: 'Check missed and false marks before adopting. Color and brightness controls apply to Custom recognition.',
  modelReplaceHint: 'Adopting replaces current marks, including manual additions. You can undo it.',
  countAll: 'Recognize all', countOne: 'Recognize again',
  dropHint: 'Drop photos here to add', dropSubHint: 'Your original photos stay unchanged.',
  pasteHint: 'Folder or image path', ingestBtn: 'Import path',
  boundaryViewHint: 'The boundary follows the growth medium, excluding the dish wall. The full photo stays visible.',
  customDraftHint: 'Color and shape rules, not default model tuning. Settings carry across photos; Apply recounts.',
  previewExplanation: 'Bright mint shows selected pixels, not final colonies. Apply to recount.',
  customBatchProtectedHint: 'Batch skips photos with manual edits, notes or human verification.',
  customBatchFailed: 'Failed',
  customProtectedConfirm: 'This photo has manual edits or a human verification record. Recounting replaces the current {count} marks and may invalidate the verification. You can undo it.\n\nPhoto: {name}\nContinue?',
  defaultBatchCustomOnly: 'Switch to Custom for batch recognition. Default recognizes only the current photo; adopting its result is a separate action.',
});
Object.assign(I18N['zh-CN'], {
  flagUnprocessed: '未识别', flagCounted: '机器识别完成', flagViewed: '已浏览或编辑 · 非准确率核验',
  viewStatusFailed: '浏览状态未保存，请重新打开此图重试。',
  legendAuto: '机器 · 灰粉', legendManual: '人工 · 灰蓝',
  internalBuild: '内部版', imagesTitle: '照片', exportMenu: '导出', imageActions: '更多',
  importPath: '从路径导入', resultDetails: '结果信息', interactionHelp: '操作说明',
  recognitionProfile: '识别设置', profileDefault: '默认', profileCustom: '自定义',
  recognizeCurrent: '识别当前', customSettings: '调整',
  manualMarkSettings: '手动标记', manualMarkRadius: '半径（px）', manualMarkHint: '仅影响之后添加的标记。',
  customRunAll: '重新识别全部', presetWhite: '默认',
  applyParams: '应用', resetDefaults: '重置', sidebarPhotos: '照片', sidebarAdjustments: '调整', sidebarTabs: '工作区', modelApply: '采用结果', modelDiscard: '取消预览',
  modelTrial: '识别当前', modelTemporary: '识别预览', modelNotAdopted: '待采用',
  modelModeHint: '先识别当前图片，核对预览并采用后，可继续手动校正。',
  modelLoading: '正在识别当前图片…',
  fusionV2Warning: '采用前请核对数量、漏检与误检。补充圈仅提示中心，不代表真实边界，中心位置可能偏移。',
  fusionWarning: '采用前请检查漏检、误检和粘连。补充圈仅提示中心，不代表菌落真实边界。',
  samWarning: '采用前请核对漏检与误检。颜色、亮度等滑条用于自定义识别。',
  modelReplaceHint: '采用后将替换当前标记（含人工添加），可撤销。',
  countAll: '识别全部', countOne: '重新识别',
  dropHint: '拖入照片即可添加', dropSubHint: '原始照片保持不变。',
  pasteHint: '文件夹或图片路径', ingestBtn: '导入路径',
  boundaryViewHint: '边界以培养基为准，不含皿壁；完整照片始终可见。',
  customDraftHint: '按颜色、形状计数，并非调整默认模型。参数跨图保留，应用时生效。',
  previewExplanation: '亮青绿色是选中像素，并非最终菌落；点击「应用」重新计数。',
  customBatchProtectedHint: '批量跳过人工编辑、有备注或核验记录的图片。',
  customBatchFailed: '失败',
  customProtectedConfirm: '这张图片已有人工修改或核验记录。重新计数将替换当前 {count} 个标记，并可能使核验记录失效。可撤销。\n\n图片：{name}\n是否继续？',
  defaultBatchCustomOnly: '批量计数请切换到自定义。默认识别仅处理当前图片，结果需主动采用。',
});


Object.assign(I18N.en, {
  helpBody: `<h3>Default recognition</h3>
<p>Add photos from the sidebar, then select one. Choose <b>Default</b> and <b>Recognize current</b> to inspect a preview. Check missed and false marks, then choose <b>Adopt result</b>. Adoption replaces the current marks, including manual additions; you can undo it. A preview alone does not replace your saved count.</p>
<h3>Custom recognition</h3>
<p><b>Custom</b> recounts using color, brightness, shape and related conditions; its sliders do not tune the default intelligent recognizer. Results may differ. The photo list stays on the left; the <b>Adjustments</b> column sits beside the image. Your custom settings persist between photos. Gray live preview shows threshold foreground, not final colonies. Choose <b>Apply</b> to recount this photo or <b>Recognize all</b> for a batch. Batch recognition skips photos with manual edits, notes, human verification records or pure manual mode. Applying to a protected current photo requires confirmation.</p>
<h3>Photo status</h3><p>Hollow: not recognized. Light gray: machine recognition completed. Dark gray: viewed or edited. Opening a photo records it as viewed; this is separate from accuracy verification. Both use solid circles: muted rose for machine marks and muted blue for manual marks. Use <b>Manual marks</b> above the photo to adjust the size of new manual marks; this does not change recognition settings or existing marks.</p><h3>Correct marks and navigate</h3>
<p>Left click adds a mark; right click removes one. Quickly drag a box to remove several marks. Hold, then drag to pan; use the wheel to zoom. Click outside the photo or press <b>F</b> to fit the full photo. The on-image arrows and <b>← / →</b> move between photos; <b>Cmd/Ctrl Z</b> undoes an edit. When a text field, number, slider or selector is focused, arrow keys stay with that control and do not switch photos. <b>More</b> contains pure manual mode, clear marks and remove photo.</p>
<h3>Growth-medium boundary</h3>
<p>The recognition boundary follows the growth-medium surface, excluding the dish wall. It limits machine recognition; it does not crop the displayed photo. The full photo remains visible. When needed, use <b>More → Adjust medium boundary</b>. Some default recognition methods require an automatic boundary and supported photo views; follow the restriction shown on screen. Marker circles indicate locations, not the true outlines of colonies.</p>
<section class="review-help"><h3>Human verification</h3>
<p>In a review queue, correct the supplied marks and explicitly confirm and save under <b>Accuracy verification</b>; do not use the recognition or batch recount workflow. Viewing a photo does not count as verification. Confirm the growth-medium boundary only if you checked it. Later edits can invalidate an earlier confirmation, so refresh and confirm again when required.</p></section>
<h3>Notes and export</h3>
<p>Notes belong to the current photo. Use <b>Export</b> for a CSV of counts, or a bundle containing counts and annotated results. Your original photos stay unchanged.</p>` + AUTHORS_FOOTER,
});
Object.assign(I18N['zh-CN'], {
  helpBody: `<h3>默认识别</h3>
<p>从侧栏添加照片并选中一张，使用<b>默认</b>，点击<b>识别当前</b>查看预览。核对漏检与误检后，再点击<b>采用结果</b>。采用会替换当前标记（含人工添加），可撤销；仅查看预览不会替换已保存计数。</p>
<h3>自定义识别</h3>
<p><b>自定义</b>按颜色、亮度、形状等条件重新计数，滑条并非调整默认智能识别，结果可能不同。左侧照片列表始终保留，<b>调整</b>栏紧邻图片。参数会跨图片保留；亮青绿色实时预览仅表示阈值前景，并非最终菌落。点击<b>应用</b>处理这张图，或<b>重新识别全部</b>批量处理。批量会跳过已有人工编辑、备注、人工核验记录及纯手动模式的图片；单张重新计数遇到受保护结果时需要确认。</p>
<h3>照片状态</h3><p>空心：未识别；浅灰：机器识别完成；深灰：已浏览或编辑。打开图片后自动记录浏览状态，与准确率核验分开。两类标记均使用实线：机器为灰粉色，人工为灰蓝色。在图片上方的<b>手动标记</b>中调整新增标记大小，不影响识别参数或已有标记。</p><h3>标记与浏览</h3>
<p>左击添加标记，右击删除；快速拖框可批量取消。长按后拖动可平移，滚轮缩放。点击图片外或按<b>F</b>回到全图最佳视野。图片两侧按钮和<b>← / →</b>切换图片，<b>Cmd/Ctrl Z</b>撤销编辑。正在编辑文字、数值、滑条或下拉选项时，方向键保留给当前控件，不切换图片。<b>更多</b>中可使用纯手动模式、清空标记和移除图片。</p>
<h3>培养基边界</h3>
<p>机器识别边界沿培养基底部平面设置，不包含皿壁；它限制机器识别范围，不裁掉给人查看的照片。完整照片始终可见。需要时在<b>更多 → 调整培养基边界</b>中修正。部分默认识别方法要求自动边界和受支持的照片视角，请遵循页面提示。标记圈用于定位，不代表菌落真实轮廓。</p>
<section class="review-help"><h3>人工核验</h3>
<p>核验队列中请校正已提供的标记，在<b>准确率核验</b>中明确确认并保存，不使用识别或批量重算流程。仅浏览图片不算完成核验；培养基边界仅在亲自检查后勾选。后续编辑可能使已有确认失效，需要时刷新并重新确认。</p></section>
<h3>备注与导出</h3>
<p>备注对应当前图片。通过<b>导出</b>保存计数CSV，或打包保存计数和标注结果。原始照片保持不变。</p>` + AUTHORS_FOOTER,
});
// Other locales already use English help; keep that fallback in sync.
for (const language of ['ja', 'es', 'fr']) I18N[language].helpBody = I18N.en.helpBody;

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

I18N.en.normalizedValueInvalid = 'Enter a value from 0 to 1.';
I18N['zh-CN'].normalizedValueInvalid = '请输入 0 到 1 之间的数值。';

Object.assign(I18N.en, {
  importView: 'Import as', currentView: 'Photo type', viewFront: 'Front of plate', viewBlank: 'Blank plate', viewBack: 'Back of plate', viewUnknown: 'Not specified',
  sourceViewRequired: 'Default recognition supports front and blank plates. Set the photo type under More.', sourceViewSaved: 'Photo type saved.',
  modelUnavailable: 'Default recognition is unavailable.', fusionV2Warning: 'Recognition is a suggestion. Check the marks before applying.', fusionV2SavedSource: 'Fusion recognition', fusionV2Method: 'Fusion',
  savedLocal: 'Saved',
});
Object.assign(I18N['zh-CN'], {
  importView: '导入为', currentView: '照片类型', viewFront: '培养皿正面', viewBlank: '空白培养皿', viewBack: '培养皿背面', viewUnknown: '未指定',
  sourceViewRequired: '默认识别支持正面与空白皿。请在「更多」中指定照片类型。', sourceViewSaved: '已保存照片类型。',
  modelUnavailable: '默认识别暂不可用。', fusionV2Warning: '请检查识别标记后采用。', fusionV2SavedSource: '融合识别', fusionV2Method: '融合识别',
});
