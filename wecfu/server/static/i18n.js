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
  fusionRoiHint: 'Fusion supports front/blank photos and the automatic medium boundary, at a fixed 95% radius. The gray dashed circle shows this range. Rose solid circles are machine marks; preview marks stay unsaved until adopted. Adoption replaces current marks and can be undone.',
  fusionAutomaticPlateRequired: 'Detailed check requires the automatic medium boundary. This photo has a manually adjusted boundary, which will be kept. Switch to Custom recognition or continue manual correction.',
  samWarning: 'The local model provides candidates that still need checking for missed and false marks. Color, brightness and other counting sliders apply only to traditional recognition.',
  samRoiHint: 'SAM analyzes the full photo. The gray dashed circle shows the retained range, fixed at 95% of the medium radius. Rose solid circles are machine marks; preview marks stay unsaved until adopted. Changing the boundary requires new recognition.',
  modelTrial: 'Run model trial', modelDiscard: 'Discard trial', modelApply: 'Replace current marks with trial results',
  modelRetry: 'Confirm pending replacement', modelReplaceHint: 'Replaces every current mark, including manual points. You can undo it.',
  modelWarning: 'Experimental model; real-photo accuracy has not been verified. Large spreading or confluent growth may be missed. Check every colony.',
  modelEmptyWarning: 'No detections does not mean a blank plate. Large areas of growth may be missed.',
  modelRoiHint: 'The gray dashed circle shows the retained range. Rose solid circles are machine marks; preview marks stay unsaved until adopted. Changing the range requires new recognition.',
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
  fusionRoiHint: '融合识别支持正面/空白图和自动培养基边界，范围固定为半径的 95%。灰色细虚线表示范围；灰粉实线圈表示机器标记。预览尚未保存，采用后替换当前标记，可撤销。',
  fusionAutomaticPlateRequired: '精细补检需要自动培养基边界。这张图已手动调整边界，将保留现有范围；可切换到自定义识别，或继续手动校正。',
  samWarning: '本地模型仅提供候选，仍需逐个核对漏检与误检。颜色、亮度等滑条仅适用于传统识别。',
  samRoiHint: 'SAM 整图分析，灰色细虚线表示保留范围，固定为培养基半径的 95%。灰粉实线圈表示机器标记；预览尚未保存，采用后才生效。调圈后需重新识别。',
  modelTrial: '模型试算', modelDiscard: '丢弃试算', modelApply: '用试算结果替换当前标记',
  modelRetry: '确认待定替换结果', modelReplaceHint: '将替换全部当前标记（包括人工添加的点），可撤销。',
  modelWarning: '实验模型，尚未完成真实照片的人工准确率评估；大面积融合或铺展生长可能漏检，请逐个核对。',
  modelEmptyWarning: '未检出不代表空白皿；大面积生长可能漏检。',
  modelRoiHint: '灰色细虚线表示保留范围，灰粉实线圈表示机器标记；预览尚未保存，采用后才生效。改变范围后需重新识别。',
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
  recognitionProfile: 'Recognition settings', profileDefault: 'Ultra', profileCustom: 'Custom',
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
  customDraftHint: 'Adjust the traditional algorithm’s color and shape rules. Settings carry across photos; Apply recounts.',
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
  recognitionProfile: '识别设置', profileDefault: 'Ultra', profileCustom: '自定义',
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
  customDraftHint: '调整传统算法的颜色、形状规则。参数跨图保留，应用时生效。',
  previewExplanation: '亮青绿色是选中像素，并非最终菌落；点击「应用」重新计数。',
  customBatchProtectedHint: '批量跳过人工编辑、有备注或核验记录的图片。',
  customBatchFailed: '失败',
  customProtectedConfirm: '这张图片已有人工修改或核验记录。重新计数将替换当前 {count} 个标记，并可能使核验记录失效。可撤销。\n\n图片：{name}\n是否继续？',
  defaultBatchCustomOnly: '批量计数请切换到自定义。默认识别仅处理当前图片，结果需主动采用。',
});


// Current help is localized in every supported language. Keep the author credit intact.
const HELP_CONTENT = {
  en: `<h3>Import and choose a mode</h3>
<p>Use <b>Add images</b> or drag photos/folders into the sidebar. Local use also supports <b>Import path</b>. Importing does not start recognition. <b>Ultra</b> combines the improved algorithm with SAM and needs more computation; <b>Lite</b> uses the lighter algorithm. <b>Custom</b> lets you adjust its parameters. The hosted version offers Lite and Custom. Use ⓘ for mode details.</p>
<h3>Recognize photos</h3>
<p>In Ultra or Lite, <b>Recognize all</b> processes unrecognized photos sequentially, keeping existing results and manual work. Leave the page open; <b>Stop after this image</b> stops after the current photo.</p>
<p><b>Recognize current</b> processes the selected photo. Ultra saves new results directly; existing results first appear as a preview. <b>Adopt result</b> replaces saved marks and can be undone; <b>Cancel preview</b> keeps them. Lite recounts directly, asking before replacing edited results. In Lite, <b>Detailed check · SAM</b>, when available, offers a SAM preview with the same adopt/cancel choice.</p>
<h3>Custom adjustments</h3>
<p>Drag sliders or click a number to type. Bright mint in <b>Live foreground preview</b> shows selected pixels, not final colonies. <b>Apply</b> stores settings for this page session and closes the panel; it does not recognize photos. Then choose <b>Recognize current</b> or <b>Recognize all</b>. <b>Adjust</b> reopens the panel; unapplied changes are not used. These settings adjust the algorithm, not SAM. Custom batch recognition reruns machine-only results but skips manual edits, notes, verification records and manual mode. Current-photo recount asks before replacing protected work.</p>
<h3>Check marks</h3>
<p>Machine marks are muted rose; manual marks muted blue, both solid. Circles locate centers, not exact outlines. Click to add, right-click to remove, or quickly drag a box to remove several. Hold then drag to pan; wheel to zoom; <b>F</b> to fit. <b>← / →</b> changes photos; <b>Cmd/Ctrl Z</b> undoes edits. Arrow keys stay with a focused input, slider or selector. <b>Manual marks</b> changes only new mark sizes. Use <b>More → Adjust medium boundary</b> when needed.</p>
<h3>Status and deletion</h3>
<p>Hollow dot: unrecognized. Light gray: machine result. Dark gray: viewed or edited, not accuracy verification. <b>Batch delete</b> lets you select photos; <b>Select all</b> toggles all/none. <b>Delete selected</b> asks for confirmation, then removes workspace photos and records. Original files remain; deletion cannot be undone.</p>
<h3>Notes and export</h3>
<p>Notes autosave for the current photo. <b>Export</b> saves counts as CSV, or a ZIP with annotated images and state files. The hosted version uploads photos to a temporary server session; export before leaving.</p>
<section class="review-help"><h3>Review queues</h3><p>Correct the supplied marks, explicitly confirm under <b>Accuracy verification</b>, then choose <b>Save colony verification</b>. Viewing does not confirm anything. Later edits may invalidate confirmation. Confirm the medium boundary only if you checked it.</p></section>`,
  'zh-CN': `<h3>导入与模式</h3>
<p>点击<b>添加板子图片</b>，或将照片、文件夹拖入侧栏。本地还可使用<b>导入路径</b>。导入不会自动识别。<b>Ultra</b>结合改进算法与 SAM，计算量较大；<b>Lite</b>使用较轻量的算法；<b>自定义</b>可调整算法参数。网页版提供 Lite 和自定义。点击 ⓘ 查看模式说明。</p>
<h3>识别照片</h3>
<p>Ultra 或 Lite 下，<b>识别全部</b>逐张处理未识别照片，保留已有结果和人工操作。运行时请保持页面打开；点击<b>完成当前板子后停止</b>，会在当前照片完成后停下。</p>
<p><b>识别当前</b>处理选中的照片。Ultra 对新照片直接保存结果，对已有结果先显示预览。<b>采用结果</b>会替换已保存标记，可撤销；<b>取消预览</b>保留原结果。Lite 直接重新计数，替换人工修改前会询问。Lite 下若<b>精细补检 · SAM</b>可用，可查看 SAM 预览，再决定采用或取消。</p>
<h3>自定义调整</h3>
<p>拖动滑条，或点击数字输入。<b>实时前景预览</b>中的亮青绿表示选中像素，并非最终菌落。<b>应用</b>只保存本页面的参数并收起面板，不执行识别；之后再选择<b>识别当前</b>或<b>识别全部</b>。点击<b>调整</b>可重新展开，未应用的修改不会用于识别。这些参数调整算法，不调整 SAM。自定义批量会重新识别仅有机器结果的照片，跳过人工编辑、备注、核验记录和纯手动模式；单张重算替换受保护结果前会询问。</p>
<h3>检查标记</h3>
<p>机器标记为灰粉，人工标记为灰蓝，均为实线。圆圈表示中心位置，不是精确轮廓。左击添加、右击删除，快速拖框批量删除；长按拖动平移，滚轮缩放，<b>F</b>显示全图。<b>← / →</b>切换照片，<b>Cmd/Ctrl Z</b>撤销编辑。输入框、滑条或下拉框有焦点时，方向键留给该控件。<b>手动标记</b>只调整新增标记的大小；需要时可在<b>更多 → 调整培养基边界</b>中修正边界。</p>
<h3>状态与删除</h3>
<p>空心点表示未识别，浅灰表示已有机器结果，深灰表示已浏览或编辑，不代表准确率核验。点击<b>批量删除</b>选择照片；<b>全选</b>可切换全选与全不选。点击<b>删除所选</b>并确认后，移除工作区中的照片和计数记录，原始文件不变；删除不可撤销。</p>
<h3>备注与导出</h3>
<p>备注自动保存到当前照片。<b>导出</b>可保存计数 CSV，或含标注图和状态文件的 ZIP。网页版会将照片上传到临时服务器会话，离开前请导出。</p>
<section class="review-help"><h3>核验队列</h3><p>校正已有标记，在<b>准确率核验</b>中主动勾选确认，再点击<b>保存菌落核验</b>。仅浏览不算确认，后续编辑可能使确认失效；培养基边界仅在亲自检查后确认。</p></section>`,
  ja: `<h3>取り込みとモード</h3>
<p><b>画像を追加</b>を使うか、画像やフォルダをサイドバーにドロップします。ローカル版では<b>パスを取り込む</b>も使えます。取り込むだけでは認識は始まりません。<b>Ultra</b>は改良アルゴリズムと SAM を組み合わせ、計算量が増えます。<b>Lite</b>は軽量なアルゴリズム、<b>カスタム</b>はその設定を調整するモードです。Web 版は Lite とカスタムに対応します。説明は ⓘ で確認できます。</p>
<h3>画像を認識する</h3>
<p>Ultra・Lite の<b>すべて認識</b>は未認識の画像を順番に処理し、既存の結果や手作業を保持します。処理中はページを開いたままにしてください。<b>この画像の完了後に停止</b>で、現在の画像が終わると停止します。</p>
<p><b>現在の画像を認識</b>は選択中の画像を処理します。Ultra は新規の結果を直接保存し、既存の結果がある場合はプレビューを表示します。<b>結果を採用</b>で保存済みマークを置き換えます。採用は元に戻せます。<b>プレビューを取消</b>なら既存の結果を保持します。Lite は直接再計数し、手動編集を置き換える前に確認します。Lite で<b>詳細確認 · SAM</b>が利用できる場合も、SAM のプレビューから採用か取消を選べます。</p>
<h3>カスタム調整</h3>
<p>スライダーを動かすか、数値をクリックして入力します。<b>前景のライブプレビュー</b>の明るいミント色は選択画素であり、最終的なコロニーではありません。<b>適用</b>はこのページで使う設定を保持してパネルを閉じるだけで、認識は実行しません。その後、<b>現在の画像を認識</b>または<b>すべて認識</b>を選びます。<b>調整</b>で再び開けます。未適用の変更は使われません。調整対象はアルゴリズムで、SAM ではありません。カスタムの一括処理は機械結果のみの画像を再計数しますが、手動編集、メモ、検証記録、手動モードの画像は除外します。現在の画像で保護された結果を置き換える際は確認します。</p>
<h3>マークを確認する</h3>
<p>機械マークはくすんだローズ、手動マークはくすんだブルーの実線です。円は中心位置を示し、正確な輪郭ではありません。クリックで追加、右クリックで削除、素早いドラッグの枠で複数削除できます。長押ししてドラッグで移動、ホイールで拡大縮小、<b>F</b>で全体表示。<b>← / →</b>で画像を切り替え、<b>Cmd/Ctrl Z</b>で編集を戻します。入力欄・スライダー・選択欄にフォーカスがある間は方向キーでその項目を操作します。<b>手動マーク</b>の大きさは新規マークだけに反映されます。必要なら<b>その他 → 培地の境界を調整</b>を使います。</p>
<h3>状態と削除</h3>
<p>白抜きの点は未認識、薄い灰色は機械結果あり、濃い灰色は閲覧・編集済みです。閲覧は精度検証ではありません。<b>一括削除</b>で画像を選び、<b>すべて選択</b>で全選択・全解除を切り替えます。<b>選択した画像を削除</b>で確認すると、作業領域の画像と計数記録が削除されます。元ファイルは残ります。削除は元に戻せません。</p>
<h3>メモと書き出し</h3>
<p>メモは現在の画像に自動保存されます。<b>書き出し</b>から計数 CSV、または注釈付き画像と状態ファイルを含む ZIP を保存できます。Web 版は画像を一時的なサーバーセッションへアップロードします。離れる前に書き出してください。</p>
<section class="review-help"><h3>確認キュー</h3><p>既存マークを修正し、<b>精度検証</b>で明示的に確認してから<b>コロニーの検証を保存</b>を選びます。閲覧だけでは確認になりません。後の編集で確認が無効になる場合があります。培地の境界は実際に確認した場合のみ確定してください。</p></section>`,
  es: `<h3>Importar y elegir un modo</h3>
<p>Usa <b>Añadir imágenes</b> o arrastra fotos o carpetas a la barra lateral. En local también puedes usar <b>Importar ruta</b>. Importar no inicia el reconocimiento. <b>Ultra</b> combina el algoritmo mejorado con SAM y requiere más cálculo; <b>Lite</b> usa el algoritmo ligero. <b>Personalizado</b> permite ajustar sus parámetros. La versión web ofrece Lite y Personalizado. Consulta ⓘ para más detalles.</p>
<h3>Reconocer fotos</h3>
<p>En Ultra o Lite, <b>Reconocer todas</b> procesa las fotos sin reconocer en orden y conserva los resultados y el trabajo manual. Mantén la página abierta; <b>Detener tras esta imagen</b> detiene el proceso al terminar la foto actual.</p>
<p><b>Reconocer actual</b> procesa la foto seleccionada. Ultra guarda directamente los resultados nuevos; si ya existen resultados, muestra una vista previa. <b>Adoptar resultado</b> reemplaza las marcas guardadas y permite deshacer; <b>Cancelar vista previa</b> las conserva. Lite recalcula directamente y pide confirmación antes de reemplazar ediciones manuales. En Lite, <b>Revisión detallada · SAM</b>, cuando está disponible, ofrece una vista previa de SAM que puedes adoptar o cancelar.</p>
<h3>Ajustes personalizados</h3>
<p>Mueve los deslizadores o pulsa un número para escribirlo. El verde menta de <b>Vista previa del primer plano</b> muestra píxeles seleccionados, no colonias finales. <b>Aplicar</b> conserva los ajustes durante esta sesión de página y cierra el panel; no reconoce fotos. Después elige <b>Reconocer actual</b> o <b>Reconocer todas</b>. <b>Ajustar</b> abre el panel; los cambios sin aplicar no se usan. Los parámetros ajustan el algoritmo, no SAM. El lote personalizado recalcula resultados solo de máquina, pero omite ediciones manuales, notas, registros de verificación y modo manual. El recálculo individual pide confirmación antes de reemplazar trabajo protegido.</p>
<h3>Revisar marcas</h3>
<p>Las marcas de máquina son rosa apagado; las manuales, azul apagado, ambas continuas. Los círculos indican centros, no contornos exactos. Clic para añadir, clic derecho para borrar; arrastra rápidamente un recuadro para borrar varias. Mantén pulsado y arrastra para mover; rueda para ampliar; <b>F</b> para encajar. <b>← / →</b> cambia de foto; <b>Cmd/Ctrl Z</b> deshace. Las flechas actúan sobre el campo, deslizador o selector que tenga el foco. <b>Marcas manuales</b> cambia solo el tamaño de marcas nuevas. Usa <b>Más → Ajustar límite del medio</b> cuando sea necesario.</p>
<h3>Estado y eliminación</h3>
<p>Punto vacío: sin reconocer. Gris claro: resultado de máquina. Gris oscuro: vista o editada, sin implicar verificación. <b>Eliminar en lote</b> permite elegir fotos; <b>Seleccionar todas</b> alterna entre todas y ninguna. <b>Eliminar seleccionadas</b> pide confirmación y elimina las fotos y registros del espacio de trabajo. Los originales permanecen; no se puede deshacer.</p>
<h3>Notas y exportación</h3>
<p>Las notas se guardan automáticamente para la foto actual. <b>Exportar</b> guarda recuentos CSV o un ZIP con imágenes anotadas y archivos de estado. La versión web sube las fotos a una sesión temporal del servidor; exporta antes de salir.</p>
<section class="review-help"><h3>Colas de revisión</h3><p>Corrige las marcas, confirma expresamente en <b>Verificación de precisión</b> y pulsa <b>Guardar verificación de colonias</b>. Mirar una foto no la verifica. Las ediciones posteriores pueden invalidar la confirmación. Confirma el límite del medio solo si lo has revisado.</p></section>`,
  fr: `<h3>Importer et choisir un mode</h3>
<p>Utilisez <b>Ajouter des images</b> ou déposez des photos ou dossiers dans la barre latérale. En local, vous pouvez aussi <b>Importer le chemin</b>. L’importation ne lance pas la reconnaissance. <b>Ultra</b> associe l’algorithme amélioré à SAM et demande plus de calcul ; <b>Lite</b> utilise l’algorithme léger. <b>Personnalisé</b> permet d’en régler les paramètres. La version web propose Lite et Personnalisé. Consultez ⓘ pour les détails.</p>
<h3>Reconnaître les photos</h3>
<p>En Ultra ou Lite, <b>Tout reconnaître</b> traite les photos non reconnues une à une, en conservant les résultats et le travail manuel. Gardez la page ouverte ; <b>Arrêter après cette image</b> arrête le traitement après la photo en cours.</p>
<p><b>Reconnaître l’image actuelle</b> traite la photo sélectionnée. Ultra enregistre directement les nouveaux résultats ; s’il existe déjà un résultat, un aperçu s’affiche. <b>Adopter le résultat</b> remplace les marques enregistrées et reste réversible ; <b>Annuler l’aperçu</b> les conserve. Lite recompte directement et demande confirmation avant de remplacer des modifications manuelles. En Lite, <b>Vérification détaillée · SAM</b>, si disponible, propose un aperçu SAM à adopter ou à annuler.</p>
<h3>Réglages personnalisés</h3>
<p>Déplacez les curseurs ou cliquez sur un nombre pour le saisir. Le vert menthe de l’<b>Aperçu du premier plan</b> indique les pixels sélectionnés, pas les colonies finales. <b>Appliquer</b> conserve les réglages pour cette session de page et ferme le panneau, sans lancer la reconnaissance. Choisissez ensuite <b>Reconnaître l’image actuelle</b> ou <b>Tout reconnaître</b>. <b>Ajuster</b> rouvre le panneau ; les changements non appliqués ne sont pas utilisés. Ces réglages concernent l’algorithme, pas SAM. Le traitement personnalisé recalcule les résultats uniquement automatiques, mais ignore les modifications manuelles, notes, validations et images en mode manuel. Le recomptage individuel demande confirmation avant de remplacer un travail protégé.</p>
<h3>Vérifier les marques</h3>
<p>Les marques automatiques sont rose grisé, les manuelles bleu grisé, toutes en trait plein. Les cercles indiquent les centres, pas les contours exacts. Cliquez pour ajouter, faites un clic droit pour supprimer, ou tracez rapidement un rectangle pour en supprimer plusieurs. Maintenez puis glissez pour déplacer ; molette pour zoomer ; <b>F</b> pour cadrer. <b>← / →</b> change de photo ; <b>Cmd/Ctrl Z</b> annule une modification. Les flèches agissent sur le champ, curseur ou sélecteur qui a le focus. <b>Marques manuelles</b> ne règle que la taille des nouvelles marques. Au besoin, utilisez <b>Plus → Ajuster la limite du milieu</b>.</p>
<h3>État et suppression</h3>
<p>Point vide : non reconnue. Gris clair : résultat automatique. Gris foncé : consultée ou modifiée, sans validation de précision. <b>Supprimer par lot</b> permet de choisir les photos ; <b>Tout sélectionner</b> bascule entre toutes et aucune. <b>Supprimer la sélection</b> demande confirmation, puis retire les photos et leurs relevés de l’espace de travail. Les originaux restent intacts ; la suppression est irréversible.</p>
<h3>Notes et export</h3>
<p>Les notes sont enregistrées automatiquement pour la photo actuelle. <b>Exporter</b> produit les comptages CSV ou un ZIP avec images annotées et fichiers d’état. La version web envoie les photos à une session temporaire sur le serveur ; exportez avant de quitter.</p>
<section class="review-help"><h3>Files de vérification</h3><p>Corrigez les marques, confirmez explicitement dans <b>Vérification de précision</b>, puis choisissez <b>Enregistrer la vérification des colonies</b>. Consulter ne vaut pas confirmer. Des modifications ultérieures peuvent invalider la confirmation. Ne confirmez la limite du milieu que si vous l’avez vérifiée.</p></section>`,
};
for (const [language, content] of Object.entries(HELP_CONTENT)) {
  const authors = {en: 'Authors', 'zh-CN': '作者', ja: '著者', es: 'Autores', fr: 'Auteurs'}[language];
  I18N[language].helpBody = content + AUTHORS_FOOTER.replace('<b>Authors</b>', `<b>${authors}</b>`);
}

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
  Object.assign(I18N.en, {
    recognizeAll: 'Recognize all', defaultBatchHint: 'Processes unrecognized photos. Existing work is kept.',
    batchRemaining: 'not started', batchUncertain: 'Save not confirmed — reload this photo before editing',
    batchAlreadyCounted: 'Already recognized', batchProtected: 'Existing edits or reference kept',
    batchStopping: 'Stopping after the current photo is saved…',
    defaultBatchCustomOnly: 'Use Recognize all to process unrecognized photos.',
  });
  Object.assign(I18N['zh-CN'], {
    recognizeAll: '识别全部', defaultBatchHint: '识别尚未处理的照片，保留已有结果和修改。',
    batchRemaining: '未开始', batchUncertain: '保存结果待核对，请重新打开此照片后再编辑',
    batchAlreadyCounted: '已有识别结果', batchProtected: '保留已有修改或核验记录',
    batchStopping: '当前照片保存后停止…',
    defaultBatchCustomOnly: '点击「识别全部」处理未识别照片。',
  });
  Object.assign(I18N.en, {
    bulkDeleteMode: 'Batch delete', finishSelection: 'Exit selection',
    selectAllImages: 'Select all', selectNoImages: 'Clear', deleteSelectedImages: 'Delete selected',
    imagesSelected: '{count} selected',
    bulkDeleteConfirm: 'Remove {count} selected photos and their counting records from this list? Your original photos are not deleted. This cannot be undone.',
    bulkDeleting: 'Removing {current}/{total}…', bulkDeleteDone: 'Removed {count} photos',
    bulkDeleteFailed: '{count} removals not confirmed', bulkRefreshFailed: 'Please refresh to check the list',
  });
  Object.assign(I18N['zh-CN'], {
    bulkDeleteMode: '批量删除', finishSelection: '退出选择',
    selectAllImages: '全选', selectNoImages: '清空选择', deleteSelectedImages: '删除所选',
    imagesSelected: '已选 {count} 张',
    bulkDeleteConfirm: '从列表删除选中的 {count} 张照片及其计数记录？原始照片不会删除，此操作无法撤销。',
    bulkDeleting: '正在移除 {current}/{total}…', bulkDeleteDone: '已移除 {count} 张照片',
    bulkDeleteFailed: '{count} 张未确认移除', bulkRefreshFailed: '请刷新后核对列表',
  });
Object.assign(I18N.en, {
  profileClassical: 'Lite',
  defaultRoute: 'Default: algorithm + SAM', defaultRouteHint: 'Uses the fixed algorithm + SAM recipe, without DINO.',
  classicalRoute: 'Lite', classicalRouteHint: 'Uses the improved algorithm without SAM. Lower resource use; complex colonies may need more manual correction.',
  classicalBatchHint: 'Algorithm only for unrecognized photos. Existing work is kept.',
  customRoute: 'Custom: enhanced algorithm', customRouteHint: 'Uses the retained, adjustable traditional algorithm.',
  recognitionSourceUnavailable: 'Reload the photo before recognizing it.',
  samPreview: 'SAM preview', modelCurrent: 'Currently saved', currentSavedSource: 'Saved result · ', samSavedSource: 'Algorithm + SAM', enhancedSavedSource: 'Enhanced algorithm',
  refineCurrent: 'Detailed check · SAM', refineCurrentHint: 'Runs algorithm + SAM for this photo. No DINO. Preview first; apply only if useful.',
  defaultBatchHint: 'Algorithm + SAM for unrecognized photos. Existing work is kept.',
  fusionV2SavedSource: 'Algorithm + SAM + DINO', sourceViewRequired: 'Recognition supports front and blank plates. Set the photo type under More.',
  modelUnavailable: 'This recognition method is unavailable.',
});
Object.assign(I18N['zh-CN'], {
  profileClassical: 'Lite',
  defaultRoute: '默认：算法 + SAM', defaultRouteHint: '使用固定的算法 + SAM 方案，不运行 DINO。',
  classicalRoute: 'Lite', classicalRouteHint: '使用已改进的传统算法，不加载 SAM。资源占用较低，复杂菌落可能需要更多人工校正。',
  classicalBatchHint: '用纯算法识别未处理照片，保留已有结果。',
  customRoute: '自定义：增强算法', customRouteHint: '保留已改进的传统算法，可调参数。',
  recognitionSourceUnavailable: '请重新打开照片后识别。',
  samPreview: 'SAM 预览', modelCurrent: '当前已保存', currentSavedSource: '当前结果 · ', samSavedSource: '算法 + SAM', enhancedSavedSource: '增强算法',
  refineCurrent: '精细补检 · SAM', refineCurrentHint: '当前照片使用算法 + SAM，不运行 DINO。先预览，再决定是否采用。',
  defaultBatchHint: '用算法 + SAM 识别未处理照片，保留已有结果。',
  fusionV2SavedSource: '算法 + SAM + DINO', sourceViewRequired: '识别支持正面与空白皿，请在「更多」中指定照片类型。',
  modelUnavailable: '此识别方法暂不可用。',
});
Object.assign(I18N.en, {
  openAdjustments: 'Adjust', collapseAdjustments: 'Close adjustments', adjustmentsPending: 'Adjust · unapplied',
  customSettingsApplied: 'Settings applied. Recognize the current photo or all photos.',
  customDraftHint: 'Apply to keep these settings and close the panel. Then choose which photos to recognize.',
  previewExplanation: 'Bright mint shows selected pixels, not final colonies.',
  customBatchScopeHint: 'Uses applied settings. Batch recognition keeps manual edits, notes and verification records.',
  customBatchProtectedHint: 'Manual edits, notes and verification records are kept in batch recognition.',
});
Object.assign(I18N['zh-CN'], {
  openAdjustments: '调整', collapseAdjustments: '收起调整', adjustmentsPending: '调整 · 待应用',
  customSettingsApplied: '设置已应用，可识别当前或全部照片。',
  customDraftHint: '应用后收起，再选择要识别的照片。参数跨图保留。',
  previewExplanation: '亮青绿为选中像素，并非最终菌落。',
  customBatchScopeHint: '使用已应用参数，保留人工修改、备注及核验记录。',
  customBatchProtectedHint: '批量保留人工修改、备注及核验记录。',
});
Object.assign(I18N.en, {
  modeInfo: 'About this mode',
  modeInfoUltra: 'Algorithm + SAM for detailed recognition. Uses more time and memory.',
  modeInfoLite: 'The improved algorithm without SAM. Faster and lighter; complex colonies may need more manual correction.',
  modeInfoCustom: 'Adjust the algorithm parameters, apply them, then recognize the current photo or all photos. These controls do not tune SAM.',
});
Object.assign(I18N['zh-CN'], {
  modeInfo: '模式说明',
  modeInfoUltra: '算法 + SAM，适合细致识别。耗时和内存占用相对较高。',
  modeInfoLite: '使用已改进的传统算法，不加载 SAM。速度更快、占用更低；复杂菌落可能需要更多人工校正。',
  modeInfoCustom: '调整算法参数，应用后识别当前或全部照片。这些参数不调整 SAM。',
});
// Labels used by the localized help must match the actions users see.
Object.assign(I18N.en, {
  paramsChanged: 'Settings changed. Apply them, then choose which photos to recognize.',
  defaultRouteHint: 'Uses the fixed algorithm + SAM settings.',
  refineCurrentHint: 'Preview algorithm + SAM on this photo, then decide whether to adopt the result.',
});
Object.assign(I18N['zh-CN'], {
  paramsChanged: '参数已修改，应用后再选择要识别的照片。',
  defaultRouteHint: '使用固定的算法 + SAM 设置。',
  refineCurrentHint: '预览当前照片的算法 + SAM 结果，再决定是否采用。',
});
Object.assign(I18N.ja, {
  addImages: '画像を追加', dropHint: '画像やフォルダをドロップして追加', dropSubHint: '元の画像は変更されません。',
  importPath: 'パスから取り込む', pasteHint: 'フォルダまたは画像のパス',
  recognitionProfile: '認識設定', profileDefault: 'Ultra', profileClassical: 'Lite', profileCustom: 'カスタム',
  recognizeCurrent: '現在の画像を認識', recognizeAll: 'すべて認識', countAll: 'すべて認識', countOne: '再認識', customRunAll: 'すべて認識',
  stopCounting: 'この画像の完了後に停止',
  modeInfo: 'モードの説明',
  modeInfoUltra: 'アルゴリズムと SAM を組み合わせた認識です。時間とメモリをより多く使います。',
  modeInfoLite: 'SAM を使わず改良アルゴリズムで処理します。軽量で高速ですが、複雑なコロニーは手動修正が増える場合があります。',
  modeInfoCustom: 'アルゴリズムの設定を調整して適用し、現在の画像または全画像を認識します。SAM の設定は変わりません。',
  modelApply: '結果を採用', modelDiscard: 'プレビューを取消', refineCurrent: '詳細確認 · SAM',
  refineCurrentHint: '現在の画像の SAM 結果をプレビューし、採用するか選びます。',
  applyParams: '適用', resetDefaults: 'リセット', customSettings: '調整', openAdjustments: '調整', collapseAdjustments: '調整を閉じる', adjustmentsPending: '調整 · 未適用',
  customSettingsApplied: '設定を適用しました。現在の画像または全画像を認識できます。',
  customDraftHint: '適用すると設定を保持してパネルを閉じます。その後、認識する画像を選びます。',
  customBatchScopeHint: '適用済みの設定を使用し、手動編集・メモ・検証記録を保持します。',
  customBatchProtectedHint: '一括処理では手動編集・メモ・検証記録を保持します。',
  paramsChanged: '設定を変更しました。適用してから認識する画像を選んでください。',
  livePreview: '前景のライブプレビュー', previewReady: '明るいミント色 = 選択画素', previewExplanation: '明るいミント色は選択画素で、最終的なコロニーではありません。',
  manualMarkSettings: '手動マーク', manualMarkRadius: '半径（px）', manualMarkHint: '新しく追加するマークだけに反映されます。',
  legendAuto: '機械 · ローズ', legendManual: '手動 · ブルー',
  flagUnprocessed: '未認識', flagCounted: '機械認識済み', flagViewed: '閲覧・編集済み · 精度検証とは別',
  imageActions: 'その他', adjustCrop: '培地の境界を調整',
  bulkDeleteMode: '一括削除', finishSelection: '選択を終了', selectAllImages: 'すべて選択', selectNoImages: '選択を解除', deleteSelectedImages: '選択した画像を削除', imagesSelected: '{count} 枚を選択',
  bulkDeleteConfirm: '選択した {count} 枚の画像と計数記録を一覧から削除しますか？元の画像は削除されません。この操作は元に戻せません。',
  exportMenu: '書き出し', referenceTitle: '精度検証', referenceSave: 'コロニーの検証を保存',
  sidebarPhotos: '画像', sidebarAdjustments: '調整', sidebarTabs: '作業領域',
});
Object.assign(I18N.es, {
  addImages: 'Añadir imágenes', dropHint: 'Arrastra fotos o carpetas para añadirlas', dropSubHint: 'Las fotos originales no se modifican.',
  importPath: 'Importar desde una ruta', pasteHint: 'Ruta de carpeta o imagen',
  recognitionProfile: 'Ajustes de reconocimiento', profileDefault: 'Ultra', profileClassical: 'Lite', profileCustom: 'Personalizado',
  recognizeCurrent: 'Reconocer actual', recognizeAll: 'Reconocer todas', countAll: 'Reconocer todas', countOne: 'Reconocer de nuevo', customRunAll: 'Reconocer todas',
  stopCounting: 'Detener tras esta imagen',
  modeInfo: 'Acerca de este modo',
  modeInfoUltra: 'Reconocimiento con el algoritmo y SAM. Requiere más tiempo y memoria.',
  modeInfoLite: 'Usa el algoritmo mejorado sin SAM. Es más rápido y ligero; las colonias complejas pueden necesitar más correcciones manuales.',
  modeInfoCustom: 'Ajusta y aplica los parámetros del algoritmo; después reconoce la foto actual o todas. Estos controles no ajustan SAM.',
  modelApply: 'Adoptar resultado', modelDiscard: 'Cancelar vista previa', refineCurrent: 'Revisión detallada · SAM',
  refineCurrentHint: 'Previsualiza el resultado de SAM para esta foto y decide si adoptarlo.',
  applyParams: 'Aplicar', resetDefaults: 'Restablecer', customSettings: 'Ajustes', openAdjustments: 'Ajustar', collapseAdjustments: 'Cerrar ajustes', adjustmentsPending: 'Ajustar · sin aplicar',
  customSettingsApplied: 'Ajustes aplicados. Reconoce la foto actual o todas.',
  customDraftHint: 'Aplica para conservar estos ajustes y cerrar el panel. Después elige las fotos que quieras reconocer.',
  customBatchScopeHint: 'Usa los ajustes aplicados y conserva ediciones manuales, notas y verificaciones.',
  customBatchProtectedHint: 'El lote conserva ediciones manuales, notas y verificaciones.',
  paramsChanged: 'Ajustes modificados. Aplícalos y elige las fotos que quieras reconocer.',
  livePreview: 'Vista previa del primer plano', previewReady: 'Verde menta = píxeles seleccionados', previewExplanation: 'El verde menta muestra píxeles seleccionados, no colonias finales.',
  manualMarkSettings: 'Marcas manuales', manualMarkRadius: 'Radio (px)', manualMarkHint: 'Solo afecta a las marcas manuales nuevas.',
  legendAuto: 'Máquina · rosa', legendManual: 'Manual · azul',
  flagUnprocessed: 'Sin reconocer', flagCounted: 'Reconocimiento automático completado', flagViewed: 'Vista o editada · no es verificación',
  imageActions: 'Más', adjustCrop: 'Ajustar límite del medio',
  bulkDeleteMode: 'Eliminar en lote', finishSelection: 'Salir de la selección', selectAllImages: 'Seleccionar todas', selectNoImages: 'Quitar selección', deleteSelectedImages: 'Eliminar seleccionadas', imagesSelected: '{count} seleccionadas',
  bulkDeleteConfirm: '¿Eliminar de la lista las {count} fotos seleccionadas y sus registros? Los originales no se borran. No se puede deshacer.',
  exportMenu: 'Exportar', referenceTitle: 'Verificación de precisión', referenceSave: 'Guardar verificación de colonias',
  sidebarPhotos: 'Fotos', sidebarAdjustments: 'Ajustes', sidebarTabs: 'Espacio de trabajo',
});
Object.assign(I18N.fr, {
  addImages: 'Ajouter des images', dropHint: 'Déposez des photos ou dossiers pour les ajouter', dropSubHint: 'Les photos originales restent inchangées.',
  importPath: 'Importer depuis un chemin', pasteHint: 'Chemin du dossier ou de l’image',
  recognitionProfile: 'Réglages de reconnaissance', profileDefault: 'Ultra', profileClassical: 'Lite', profileCustom: 'Personnalisé',
  recognizeCurrent: 'Reconnaître l’image actuelle', recognizeAll: 'Tout reconnaître', countAll: 'Tout reconnaître', countOne: 'Reconnaître à nouveau', customRunAll: 'Tout reconnaître',
  stopCounting: 'Arrêter après cette image',
  modeInfo: 'À propos de ce mode',
  modeInfoUltra: 'Reconnaissance avec l’algorithme et SAM. Demande plus de temps et de mémoire.',
  modeInfoLite: 'Utilise l’algorithme amélioré sans SAM. Plus rapide et léger ; les colonies complexes peuvent demander davantage de corrections manuelles.',
  modeInfoCustom: 'Réglez et appliquez les paramètres de l’algorithme, puis reconnaissez la photo actuelle ou toutes les photos. Ces contrôles ne règlent pas SAM.',
  modelApply: 'Adopter le résultat', modelDiscard: 'Annuler l’aperçu', refineCurrent: 'Vérification détaillée · SAM',
  refineCurrentHint: 'Prévisualisez le résultat SAM pour cette photo, puis décidez de l’adopter ou non.',
  applyParams: 'Appliquer', resetDefaults: 'Réinitialiser', customSettings: 'Réglages', openAdjustments: 'Ajuster', collapseAdjustments: 'Fermer les réglages', adjustmentsPending: 'Ajuster · non appliqué',
  customSettingsApplied: 'Réglages appliqués. Vous pouvez reconnaître la photo actuelle ou toutes les photos.',
  customDraftHint: 'Appliquez pour conserver ces réglages et fermer le panneau. Choisissez ensuite les photos à reconnaître.',
  customBatchScopeHint: 'Utilise les réglages appliqués et conserve modifications manuelles, notes et validations.',
  customBatchProtectedHint: 'Le traitement par lot conserve modifications manuelles, notes et validations.',
  paramsChanged: 'Réglages modifiés. Appliquez-les, puis choisissez les photos à reconnaître.',
  livePreview: 'Aperçu du premier plan', previewReady: 'Vert menthe = pixels sélectionnés', previewExplanation: 'Le vert menthe indique les pixels sélectionnés, pas les colonies finales.',
  manualMarkSettings: 'Marques manuelles', manualMarkRadius: 'Rayon (px)', manualMarkHint: 'Concerne uniquement les nouvelles marques manuelles.',
  legendAuto: 'Machine · rose', legendManual: 'Manuel · bleu',
  flagUnprocessed: 'Non reconnue', flagCounted: 'Reconnaissance automatique terminée', flagViewed: 'Consultée ou modifiée · sans validation',
  imageActions: 'Plus', adjustCrop: 'Ajuster la limite du milieu',
  bulkDeleteMode: 'Supprimer par lot', finishSelection: 'Quitter la sélection', selectAllImages: 'Tout sélectionner', selectNoImages: 'Désélectionner', deleteSelectedImages: 'Supprimer la sélection', imagesSelected: '{count} sélectionnées',
  bulkDeleteConfirm: 'Retirer de la liste les {count} photos sélectionnées et leurs relevés ? Les originaux ne sont pas supprimés. Cette action est irréversible.',
  exportMenu: 'Exporter', referenceTitle: 'Vérification de précision', referenceSave: 'Enregistrer la vérification des colonies',
  sidebarPhotos: 'Photos', sidebarAdjustments: 'Réglages', sidebarTabs: 'Espace de travail',
});

})();
