/* Карта плана: подоснова, посадки и отказы на канве, с объяснением по клику.
 *
 * Три вещи определяют всю конструкцию:
 * 1. На настоящем чертеже десятки тысяч объектов, поэтому геометрия собирается в Path2D
 *    один раз в координатах чертежа, а зум, панорама и разворот делаются трансформацией
 *    канвы. Перестраивать пути на каждый кадр нельзя - это единственное, что тут тормозит.
 * 2. Цвета берутся из CSS-переменных, а не хардкодятся: тема переключается в одном месте,
 *    и карта обязана следовать за ней.
 * 3. Вид разворачивается вдоль улицы. Участок работ - лента: на Берзарина 552 x 88 м под
 *    углом 23 градуса, и её прямоугольная обёртка вчетверо больше самой ленты по площади.
 *    Без разворота план занимает четверть экрана и деревья вырождаются в точки.
 */

const RUN_ID = document.querySelector('.page-run')?.dataset.runId;
const canvas = document.getElementById('plan-canvas');
const loading = document.getElementById('map-loading');
const detail = document.getElementById('detail');

/* Класс объекта подосновы -> как его рисовать. width в экранных пикселях. */
const STYLES = {
  'lawn':                  { group: 'surfaces',  fill: '--c-lawn', width: 0 },
  'building':              { group: 'buildings', fill: '--c-building-fill', stroke: '--c-building', width: 1 },
  'structure':             { group: 'buildings', stroke: '--c-building', width: 1 },
  'road':                  { group: 'surfaces',  stroke: '--c-road', width: 1 },
  'sidewalk':              { group: 'surfaces',  stroke: '--c-pavement', width: 1 },
  'pavement_edge':         { group: 'surfaces',  stroke: '--c-pavement', width: 1 },
  'curb':                  { group: 'surfaces',  stroke: '--c-curb', width: 1.4 },
  'tram':                  { group: 'surfaces',  stroke: '--c-road', width: 1.2 },
  'railway':               { group: 'surfaces',  stroke: '--c-road', width: 1.2 },
  'slope':                 { group: 'surfaces',  stroke: '--c-slope', width: 1 },
  'fence':                 { group: 'surfaces',  stroke: '--c-fence', width: 1, dash: [4, 3] },
  'work_boundary':         { group: 'surfaces',  stroke: '--c-boundary', width: 1.6, dash: [8, 4] },
  'utility.water':         { group: 'utilities', stroke: '--c-water', width: 1.3 },
  'utility.sewer':         { group: 'utilities', stroke: '--c-sewer', width: 1.3 },
  'utility.storm':         { group: 'utilities', stroke: '--c-storm', width: 1.3 },
  'utility.drain':         { group: 'utilities', stroke: '--c-storm', width: 1.1 },
  'utility.heat':          { group: 'utilities', stroke: '--c-heat', width: 1.3 },
  'utility.gas':           { group: 'utilities', stroke: '--c-gas', width: 1.3 },
  'utility.power_cable':   { group: 'utilities', stroke: '--c-power', width: 1.3 },
  'utility.telecom':       { group: 'utilities', stroke: '--c-telecom', width: 1.3 },
  'utility.unknown':       { group: 'utilities', stroke: '--c-utility', width: 1 },
  'utility.access':        { group: 'utilities', stroke: '--c-utility', width: 1 },
  'power_line_overhead':   { group: 'utilities', stroke: '--c-overhead', width: 1.4, dash: [10, 4] },
  'pole':                  { group: 'utilities', stroke: '--c-pole', width: 2 },
  'existing_tree':         { group: 'existing',  stroke: '--c-existing', width: 1.2 },
  'existing_shrub':        { group: 'existing',  stroke: '--c-existing', width: 1 },
};

const VERDICT_TOKEN = {
  allowed: '--ok',
  needs_approval: '--warn',
  rejected: '--bad',
  forbidden: '--bad',
};

/* Вердикт в панели пишется по-русски: карту смотрят эксперты ДПиООС, а не разработчики. */
const VERDICT_RU = {
  allowed: 'допускается',
  needs_approval: 'требует согласования',
  rejected: 'не допускается',
  forbidden: 'запрещено нормой',
};

const KIND_RU = { tree: 'дерево', shrub: 'кустарник' };

/* Родительный падеж: подставляется в «до ...». Без этого в панели стоит `utility.power_cable`,
   и объяснение читает разработчик, а не эксперт. */
const CLASS_RU = {
  'building': 'здания',
  'structure': 'сооружения',
  'road': 'проезжей части',
  'curb': 'бортового камня',
  'sidewalk': 'тротуара',
  'pavement_edge': 'края покрытия',
  'tram': 'трамвайных путей',
  'railway': 'железнодорожных путей',
  'slope': 'откоса',
  'pole': 'опоры',
  'fence': 'ограды',
  'utility.water': 'водопровода',
  'utility.sewer': 'канализации',
  'utility.storm': 'ливневой канализации',
  'utility.drain': 'дренажа',
  'utility.heat': 'теплосети',
  'utility.gas': 'газопровода',
  'utility.power_cable': 'силового кабеля',
  'utility.telecom': 'сети связи',
  'utility.unknown': 'неопознанной сети',
  'utility.access': 'колодца',
  'power_line_overhead': 'воздушной линии',
  'existing_tree': 'существующего дерева',
  'existing_shrub': 'существующего кустарника',
};

/** Во сколько раз фактический отступ больше нормы. Правила, где запас меньше двукратного,
 *  реально участвуют в решении; остальные проверены и молчат. */
const TIGHT = 2;
/** Крона мельче этого на экране не рисуется: иначе на виде «вписать» план вырождается в
 *  россыпь точек, и о трёхстах деревьях можно узнать только из числа в панели. */
const MIN_CROWN_PX = 4;

const state = {
  chunks: [],         // куски подосновы: класс x ячейка сетки x размерная полка
  placements: [],
  rejections: [],
  outline: [],        // опорные точки подосновы: по ним вписывается чертёж, пока плана нет
  ordered: [],        // посадки и отказы в порядке вдоль улицы - для клавиатуры
  rules: {},
  bbox: null,
  scale: 1,
  tx: 0,
  ty: 0,
  rot: 0,             // разворот вида, радианы
  axis: 0,            // ось участка: к ней разворачивается вид по умолчанию
  selected: null,
  highlight: null,    // код вида, подсвеченного из состава плана
  // Виды, снятые галочкой в составе плана: их не видно на карте и по ним не кликается.
  // Тринадцать видов в одном кадре сливаются, и вопрос «где именно липы» иначе не задать.
  speciesOff: new Set(),
  fitScale: 0,        // масштаб вида «вписать»: от него считается шкала ползунка
  hovered: false,
  // Пользователь сам трогал вид: после этого при изменении размера окна вид не
  // пересобирается, а только удерживается по центру.
  touched: false,
  // Режим правки выключен по умолчанию: случайно сдвинуть дерево во время осмотра плана
  // не должно быть возможно.
  editing: false,
  // Файлы результата отстали от плана на экране.
  stale: false,
  dragging: null,
  dragVerdict: null,
  visible: {
    utilities: true, surfaces: true, buildings: true,
    existing: true, placements: true, rejections: false,
  },
};

/** Цвет из CSS-переменной. Значения кэшируются: `getComputedStyle` в цикле отрисовки -
 *  это форсированный пересчёт стилей на каждый кусок геометрии. Сброс - при смене темы. */
const colors = new Map();
function css(token) {
  let value = colors.get(token);
  if (value === undefined) {
    value = getComputedStyle(document.documentElement).getPropertyValue(token).trim() || '#888';
    colors.set(token, value);
  }
  return value;
}

/* ---------- загрузка ---------- */

/** Не force-cache: он переиспользует и ошибочные ответы, поэтому 404, полученный до конца
 *  прогона, залипал в кэше навсегда и карта у этого прогона больше не загружалась. */
async function loadJson(name) {
  const url = `/api/v1/runs/${RUN_ID}/artifacts/${name}`;
  const response = await fetch(url, { cache: 'default' });
  if (!response.ok) throw new Error(`${name}: ${response.status}`);
  return response.json();
}

function addRing(path, ring, close) {
  ring.forEach(([x, y], i) => (i ? path.lineTo(x, y) : path.moveTo(x, y)));
  if (close) path.closePath();
}

function addGeometry(path, geometry) {
  const { type, coordinates } = geometry;
  if (type === 'Point') {
    // Точка рисуется коротким крестом: круг на малом зуме сливается в пятно.
    const [x, y] = coordinates;
    path.moveTo(x - 0.4, y); path.lineTo(x + 0.4, y);
    path.moveTo(x, y - 0.4); path.lineTo(x, y + 0.4);
  } else if (type === 'MultiPoint') {
    coordinates.forEach((c) => addGeometry(path, { type: 'Point', coordinates: c }));
  } else if (type === 'LineString') {
    addRing(path, coordinates, false);
  } else if (type === 'MultiLineString') {
    coordinates.forEach((line) => addRing(path, line, false));
  } else if (type === 'Polygon') {
    coordinates.forEach((ring) => addRing(path, ring, true));
  } else if (type === 'MultiPolygon') {
    coordinates.forEach((poly) => poly.forEach((ring) => addRing(path, ring, true)));
  } else if (type === 'GeometryCollection') {
    geometry.geometries.forEach((g) => addGeometry(path, g));
  }
}

/** Сетка отсечения: чертёж режется на ячейки, чтобы при приближении не обходить всю улицу.
 *  На Камчатской (56 тыс. объектов) в кадре при масштабе 5 px/m остаётся около 4% ячеек. */
const GRID = 24;
/** Размерные полки объекта в метрах. Полка целиком пропускается, когда её объекты мельче
 *  MIN_PX на экране: на общем виде это две трети объектов, и они всё равно невидимы. */
const BANDS = [0.5, 1, 2, 4, 8, 16, Infinity];
const MIN_PX = 1.5;

/** Габарит геометрии без выделения массивов: функция зовётся на каждый объект подосновы. */
function measure(geometry, box) {
  const { type, coordinates } = geometry;
  const put = (x, y) => {
    if (x < box[0]) box[0] = x;
    if (y < box[1]) box[1] = y;
    if (x > box[2]) box[2] = x;
    if (y > box[3]) box[3] = y;
  };
  if (type === 'Point') put(coordinates[0], coordinates[1]);
  else if (type === 'MultiPoint' || type === 'LineString') for (const [x, y] of coordinates) put(x, y);
  else if (type === 'MultiLineString' || type === 'Polygon') {
    for (const ring of coordinates) for (const [x, y] of ring) put(x, y);
  } else if (type === 'MultiPolygon') {
    for (const poly of coordinates) for (const ring of poly) for (const [x, y] of ring) put(x, y);
  } else if (type === 'GeometryCollection') {
    for (const part of geometry.geometries) measure(part, box);
  }
}

/** Разобрать подоснову на куски: один Path2D на класс, ячейку сетки и размерную полку.
 *
 *  Единый путь на класс выглядит экономнее, но он же и дороже: браузер отбрасывает путь
 *  целиком по его габариту, поэтому один большой путь на всю улицу рисуется дольше (190 мс
 *  против 110 мс на Камчатской), а мелко нарезанный позволяет не трогать то, чего нет в
 *  кадре, и то, что мельче пикселя.
 */
function buildChunks(features, bbox) {
  const [x0, y0, x1, y1] = bbox && bbox.length === 4 ? bbox : [0, 0, 0, 0];
  const cell = Math.max(x1 - x0, y1 - y0) / GRID || 1;
  const byKey = new Map();
  const box = [0, 0, 0, 0];
  for (const feature of features) {
    const style = STYLES[feature.properties.class];
    if (!style) continue;
    box[0] = Infinity; box[1] = Infinity; box[2] = -Infinity; box[3] = -Infinity;
    measure(feature.geometry, box);
    if (!Number.isFinite(box[0])) continue;
    // Точка - это условный знак (опора, колодец, существующее дерево), он читается на любом
    // масштабе и по размеру не отбрасывается.
    const point = feature.geometry.type === 'Point' || feature.geometry.type === 'MultiPoint';
    const span = point ? Infinity : Math.max(box[2] - box[0], box[3] - box[1]);
    let band = 0;
    while (BANDS[band] <= span) band += 1;
    const cx = Math.floor((box[0] - x0) / cell);
    const cy = Math.floor((box[1] - y0) / cell);
    const key = `${feature.properties.class}|${band}|${cx}|${cy}`;
    let chunk = byKey.get(key);
    if (!chunk) {
      chunk = {
        group: style.group,
        strokeVar: style.stroke,
        fillVar: style.fill,
        width: style.width,
        dash: style.dash || [],
        path: new Path2D(),
        span: 0,
        minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity,
      };
      byKey.set(key, chunk);
    }
    addGeometry(chunk.path, feature.geometry);
    chunk.span = Math.max(chunk.span, span);
    chunk.minX = Math.min(chunk.minX, box[0]);
    chunk.minY = Math.min(chunk.minY, box[1]);
    chunk.maxX = Math.max(chunk.maxX, box[2]);
    chunk.maxY = Math.max(chunk.maxY, box[3]);
  }
  // Заливки рисуются первыми, иначе газон и здания закрашивают линии поверх себя.
  return [...byKey.values()].sort((a, b) => (b.fillVar ? 1 : 0) - (a.fillVar ? 1 : 0));
}

/* ---------- вид ---------- */

/** Координаты вида: горизонталь экрана - вдоль улицы, вертикаль - поперёк. */
function toView(x, y) {
  const c = Math.cos(state.rot);
  const s = Math.sin(state.rot);
  return { u: c * x + s * y, v: s * x - c * y };
}

function toScreen(x, y) {
  const { u, v } = toView(x, y);
  return { sx: u * state.scale + state.tx, sy: v * state.scale + state.ty };
}

/** Главная ось облака точек. Считается один раз по плану: разворачивать вид по подоснове
 *  нельзя - она тянется на километры вдоль совсем других улиц. */
function principalAxis(items) {
  if (items.length < 3) return 0;
  let mx = 0;
  let my = 0;
  for (const item of items) { mx += item.x; my += item.y; }
  mx /= items.length;
  my /= items.length;
  let sxx = 0;
  let syy = 0;
  let sxy = 0;
  for (const item of items) {
    const dx = item.x - mx;
    const dy = item.y - my;
    sxx += dx * dx; syy += dy * dy; sxy += dx * dy;
  }
  return 0.5 * Math.atan2(2 * sxy, sxx - syy);
}

/** Свободная область канвы: панели лежат поверх плана и закрывают его края, поэтому
 *  «вписать» считается по тому прямоугольнику, который действительно видно. */
function clearArea() {
  const rect = canvas.getBoundingClientRect();
  let left = 0;
  let right = rect.width;
  let top = 0;
  let bottom = rect.height;
  for (const panel of document.querySelectorAll('.hud-left, .hud-right, .hud-legend')) {
    const box = panel.getBoundingClientRect();
    if (box.width === 0 || getComputedStyle(panel).position !== 'absolute') continue;
    if (box.left - rect.left < rect.width / 2) left = Math.max(left, box.right - rect.left + 14);
    else right = Math.min(right, box.left - rect.left - 14);
  }
  // Кнопки масштаба и полоса хода расчёта лежат по нижней кромке: план не должен
  // прятаться под ними.
  for (const strip of document.querySelectorAll('.hud-bottom, .hud-progress')) {
    if (strip.hidden || getComputedStyle(strip).position !== 'absolute') continue;
    bottom = Math.min(bottom, strip.getBoundingClientRect().top - rect.top - 14);
  }
  // Значки шапки висят над правой панелью и в свободную зону не заходят. Отступ сверху
  // нужен только там, где шапка действительно накрывает план, - иначе «вписать» зря
  // отдаёт полсотни пикселей высоты пустоте.
  const bar = document.querySelector('.topbar');
  if (bar && getComputedStyle(bar).position === 'fixed') {
    const box = bar.getBoundingClientRect();
    if (box.left - rect.left < right) top = Math.max(top, box.bottom - rect.top + 12);
  }
  return {
    left,
    width: Math.max(right - left, 240),
    top,
    height: Math.max(bottom - top, 200),
    rect,
  };
}

const FIT_MARGIN_M = 8;

/** Габарит плана в координатах вида.
 *
 *  Считается по самим посадкам, а не по углам их bbox: прямоугольник, повёрнутый вместе
 *  с лентой, снова становится большим, и разворот не даёт ничего. Для прогона без посадок
 *  остаётся bbox подосновы.
 */
function viewExtent() {
  const [minX, minY, maxX, maxY] = state.bbox;
  const corners = [{ x: minX, y: minY }, { x: minX, y: maxY }, { x: maxX, y: minY }, { x: maxX, y: maxY }];
  const points = state.placements.length || state.rejections.length
    ? [...state.placements, ...state.rejections]
    : (state.outline.length ? state.outline : corners);

  let minU = Infinity;
  let maxU = -Infinity;
  let minV = Infinity;
  let maxV = -Infinity;
  for (const { x, y } of points) {
    const { u, v } = toView(x, y);
    minU = Math.min(minU, u); maxU = Math.max(maxU, u);
    minV = Math.min(minV, v); maxV = Math.max(maxV, v);
  }
  return {
    minU: minU - FIT_MARGIN_M, maxU: maxU + FIT_MARGIN_M,
    minV: minV - FIT_MARGIN_M, maxV: maxV + FIT_MARGIN_M,
    w: Math.max(maxU - minU + 2 * FIT_MARGIN_M, 1),
    h: Math.max(maxV - minV + 2 * FIT_MARGIN_M, 1),
  };
}

/** Границы ползунка масштаба: от вида «вписать» вчетверо мельче и в шестьдесят раз крупнее.
 *  Шкала логарифмическая - иначе весь полезный диапазон сидит в первых процентах хода. */
const ZOOM_OUT = 0.25;
const ZOOM_IN = 64;

function zoomBounds() {
  const base = state.fitScale || state.scale || 1;
  return { lo: base * ZOOM_OUT, hi: base * ZOOM_IN };
}

/** Подвинуть ползунок под текущий масштаб. Пока его тянут, не трогаем: иначе бегунок
 *  дёргается от округления в обратную сторону. */
function syncZoom() {
  const input = document.getElementById('zoom-range');
  if (!input || document.activeElement === input) return;
  const { lo, hi } = zoomBounds();
  const share = Math.log(state.scale / lo) / Math.log(hi / lo);
  input.value = String(Math.round(Math.min(Math.max(share, 0), 1) * 1000));
}

function fitToBbox() {
  if (!state.bbox) return;
  const ext = viewExtent();
  const area = clearArea();
  state.scale = Math.min(area.width / ext.w, area.height / ext.h);
  state.fitScale = state.scale;
  state.tx = area.left + area.width / 2 - ((ext.minU + ext.maxU) / 2) * state.scale;
  state.ty = area.top + area.height / 2 - ((ext.minV + ext.maxV) / 2) * state.scale;
}

/** На узком экране высота карты подгоняется под форму участка.
 *
 *  Улица - лента 6:1. В колодце 375 x 558 она занимает десятую часть площади, и первый
 *  экран телефона показывает пустое поле с ниткой посередине. На широком экране высоту
 *  задаёт рабочее место, и вмешиваться не надо.
 */
function sizeHolder() {
  const holder = canvas.parentElement;
  if (!holder) return;
  if (getComputedStyle(holder).position === 'absolute' || !state.bbox) {
    holder.style.height = '';
    return;
  }
  const ext = viewExtent();
  const width = holder.getBoundingClientRect().width;
  const wanted = (width * ext.h) / ext.w + 90;
  const limit = window.innerHeight * 0.62;
  holder.style.height = `${Math.round(Math.min(Math.max(wanted, 260), limit))}px`;
}

function resize() {
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  invalidate();
  draw();
}

/** При изменении размера окна нетронутый вид пересобирается, а настроенный удерживается
 *  за ту же точку: иначе план после ресайза висит за краем холста. */
function keepView(previous) {
  if (!state.bbox) return;
  if (!state.touched) { fitToBbox(); return; }
  const area = clearArea();
  state.tx += (area.left + area.width / 2) - previous.cx;
  state.ty += (area.top + area.height / 2) - previous.cy;

  // Сдвиг по центру сохраняет масштаб, а он мог стать великоват для нового окна: при
  // сильном изменении размера план уезжает за оба края и выглядит как пустой холст.
  // Если от него не осталось ничего видимого - собираем вид заново.
  const ext = viewExtent();
  const left = ext.minU * state.scale + state.tx;
  const right = ext.maxU * state.scale + state.tx;
  const top = ext.minV * state.scale + state.ty;
  const bottom = ext.maxV * state.scale + state.ty;
  const visible = right > area.left + 40 && left < area.left + area.width - 40
    && bottom > area.top + 40 && top < area.top + area.height - 40;
  if (!visible) fitToBbox();
}

/** Пометить панель, у которой содержимое не помещается. Без пометки переполнение
 *  молчаливое: на высоте 720 панель прячет полторы сотни пикселей ровной кромкой, и это
 *  читается как «здесь всё». */
function markOverflow() {
  for (const box of document.querySelectorAll('.hud-scroll, .detail-scroll')) {
    box.dataset.overflow = box.scrollHeight - box.clientHeight > 4 ? '1' : '0';
  }
}

let frame = 0;
function schedule() {
  if (frame) return;
  frame = requestAnimationFrame(() => { frame = 0; draw(); });
}

/* ---------- растровый кэш подосновы ----------
 *
 * Подоснова настоящей улицы - это десятки тысяч отдельных кусков геометрии, и обходить их
 * на каждый кадр нельзя: замер на Камчатской (56 тыс. объектов) - 110 мс на кадр, то есть
 * девять кадров в секунду, карта не едет за рукой. Причина не в пикселях: тот же чертёж на
 * холсте вчетверо меньшего разрешения рисуется 102 мс.
 *
 * Поэтому подоснова рисуется один раз в скрытый холст с запасом вокруг окна, а движение
 * показывает уже готовую картинку - перенос стоит 4 мс. Начисто карта перерисовывается,
 * когда рука остановилась. Посадки и отказы остаются живыми: их двигают и подсвечивают.
 */
const PAD = 260;
const SETTLE_MS = 110;
const base = document.createElement('canvas');
let cache = null;
let settleTimer = 0;

function invalidate() {
  cache = null;
}

/** Перерисовать карту начисто: вместе с подосновой могли смениться цвета темы. */
function repaint() {
  colors.clear();
  invalidate();
  schedule();
}

/** Габарит прямоугольника экрана в координатах чертежа.
 *
 *  Матрица разворота вида совпадает со своей обратной, поэтому обратный переход считается
 *  теми же косинусом и синусом. Для повёрнутого вида берётся габарит четырёх углов - он
 *  шире самого прямоугольника, и это правильно: отсечение обязано ошибаться в плюс.
 */
function worldBounds(left, top, width, height) {
  const c = Math.cos(state.rot);
  const s = Math.sin(state.rot);
  const box = [Infinity, Infinity, -Infinity, -Infinity];
  const corners = [[left, top], [left + width, top], [left, top + height], [left + width, top + height]];
  for (const [sx, sy] of corners) {
    const u = (sx - state.tx) / state.scale;
    const v = (sy - state.ty) / state.scale;
    const x = c * u + s * v;
    const y = s * u - c * v;
    if (x < box[0]) box[0] = x;
    if (y < box[1]) box[1] = y;
    if (x > box[2]) box[2] = x;
    if (y > box[3]) box[3] = y;
  }
  return box;
}

function renderBase(rect, dpr) {
  const width = rect.width + PAD * 2;
  const height = rect.height + PAD * 2;
  if (base.width !== Math.round(width * dpr) || base.height !== Math.round(height * dpr)) {
    base.width = Math.round(width * dpr);
    base.height = Math.round(height * dpr);
  }
  const ctx = base.getContext('2d');
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, base.width, base.height);

  // Y в чертеже направлен вверх, на канве вниз; плюс разворот вида вдоль улицы и сдвиг на
  // запас, с которым рисуется картинка.
  const s = state.scale * dpr;
  const c = Math.cos(state.rot);
  const sn = Math.sin(state.rot);
  ctx.setTransform(s * c, s * sn, s * sn, -s * c, (state.tx + PAD) * dpr, (state.ty + PAD) * dpr);
  // Скошенные стыки вместо круглых: на линии в полтора пикселя разницы не видно, а обход
  // геометрии дешевле почти вдвое (62 мс против 110 мс на Камчатской).
  ctx.lineJoin = 'bevel';
  ctx.lineCap = 'butt';

  const view = worldBounds(-PAD, -PAD, width, height);
  for (const chunk of state.chunks) {
    if (!state.visible[chunk.group]) continue;
    if (chunk.span * state.scale < MIN_PX) continue;
    if (chunk.maxX < view[0] || chunk.minX > view[2]) continue;
    if (chunk.maxY < view[1] || chunk.minY > view[3]) continue;
    if (chunk.fillVar) {
      ctx.fillStyle = css(chunk.fillVar);
      ctx.fill(chunk.path);
    }
    if (chunk.strokeVar && chunk.width) {
      ctx.strokeStyle = css(chunk.strokeVar);
      ctx.lineWidth = chunk.width / state.scale;
      if (chunk.dash.length) ctx.setLineDash(chunk.dash.map((d) => d / state.scale));
      ctx.stroke(chunk.path);
      if (chunk.dash.length) ctx.setLineDash([]);
    }
  }
  cache = {
    scale: state.scale, rot: state.rot, tx: state.tx, ty: state.ty,
    dpr, width: rect.width, height: rect.height,
  };
}

/** Картинка кэша больше не закрывает окно: запас израсходован панорамой или зумом. */
function uncovered(rect, k) {
  const left = (-PAD - cache.tx) * k + state.tx;
  const right = (cache.width + PAD - cache.tx) * k + state.tx;
  const top = (-PAD - cache.ty) * k + state.ty;
  const bottom = (cache.height + PAD - cache.ty) * k + state.ty;
  return left > 0 || top > 0 || right < rect.width || bottom < rect.height;
}

function settleLater() {
  clearTimeout(settleTimer);
  settleTimer = setTimeout(() => { invalidate(); schedule(); }, SETTLE_MS);
}

function draw() {
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const rect = canvas.getBoundingClientRect();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Сетка листа рисуется и пустой карте: пока чертёж читается, под полосой хода лежит
  // не чёрный экран, а лист, на котором он появится.
  drawGrid(ctx, dpr);
  if (!state.bbox) return;

  const stale = !cache || cache.rot !== state.rot || cache.dpr !== dpr
    || cache.width !== rect.width || cache.height !== rect.height;
  if (stale) renderBase(rect, dpr);

  // Перенос картинки: разницу масштаба между кадром и кэшем отрабатывает растяжение,
  // поэтому зум идёт гладко, а чёткость возвращается перерисовкой после остановки.
  const k = state.scale / cache.scale;
  ctx.setTransform(k * dpr, 0, 0, k * dpr,
    (state.tx - cache.tx * k) * dpr, (state.ty - cache.ty * k) * dpr);
  ctx.drawImage(base, -PAD, -PAD, base.width / cache.dpr, base.height / cache.dpr);

  const s = state.scale * dpr;
  const c = Math.cos(state.rot);
  const sn = Math.sin(state.rot);
  ctx.setTransform(s * c, s * sn, s * sn, -s * c, state.tx * dpr, state.ty * dpr);
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  const view = worldBounds(0, 0, rect.width, rect.height);
  if (state.visible.rejections) drawRejections(ctx, view);
  if (state.visible.placements) drawPlacements(ctx, view);

  // Отметка выбранного и стрелка севера рисуются в экранных пикселях: их размер не должен
  // зависеть от масштаба, иначе на общем виде обводка вырождается в волос.
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  drawSelection(ctx);
  drawNorth(ctx);
  drawScaleBar(ctx);
  syncZoom();

  if (k !== 1 || uncovered(rect, k)) settleLater();
}

/** Координатная сетка под планом.
 *
 *  Участок - лента 6:1, и на широком экране вокруг него остаётся пустое поле, по которому
 *  нельзя сказать ни где ты, ни какой сейчас масштаб. Сетка в круглых метрах отвечает на
 *  оба вопроса и превращает фон в чертёжный лист. Она привязана к осям экрана, а не к
 *  осям чертежа: при развороте вида вдоль улицы наклонная сетка спорила бы с самим планом.
 */
function drawGrid(ctx, dpr) {
  const stepM = niceLength(90 / state.scale);
  const step = stepM * state.scale;
  const rect = canvas.getBoundingClientRect();
  if (step < 14 || !Number.isFinite(step)) return;

  ctx.save();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.strokeStyle = css('--grid');
  ctx.lineWidth = 1;
  ctx.beginPath();
  // Остаток от деления берётся с приведением к положительному: при отрицательном сдвиге
  // первая линия иначе уезжает за левый край и сетка съезжает на шаг.
  for (let x = ((state.tx % step) + step) % step; x < rect.width; x += step) {
    ctx.moveTo(Math.round(x) + 0.5, 0);
    ctx.lineTo(Math.round(x) + 0.5, rect.height);
  }
  for (let y = ((state.ty % step) + step) % step; y < rect.height; y += step) {
    ctx.moveTo(0, Math.round(y) + 0.5);
    ctx.lineTo(rect.width, Math.round(y) + 0.5);
  }
  ctx.stroke();
  ctx.restore();
}

/** Круглая длина для масштабной линейки: 1, 2 или 5 на порядок. */
function niceLength(meters) {
  const power = 10 ** Math.floor(Math.log10(meters));
  const head = meters / power;
  return (head >= 5 ? 5 : head >= 2 ? 2 : 1) * power;
}

/** Масштабная линейка. На чертеже она есть всегда, и без неё по карте нельзя сказать
 *  ничего о расстояниях - а весь спор в этом кейсе именно про метры. */
function drawScaleBar(ctx) {
  const area = clearArea();
  const meters = niceLength(150 / state.scale);
  const width = meters * state.scale;
  if (width < 30 || width > area.width / 2) return;
  const right = area.left + area.width - 64;
  const left = right - width;
  const y = area.top + area.height - 26;

  const bar = new Path2D();
  bar.moveTo(left, y);
  bar.lineTo(right, y);
  for (const x of [left, (left + right) / 2, right]) {
    bar.moveTo(x, y - 4);
    bar.lineTo(x, y + 4);
  }
  const label = `${meters} м`;
  const cx = (left + right) / 2;

  ctx.save();
  ctx.lineCap = 'butt';
  ctx.lineJoin = 'round';
  ctx.font = `500 12px ${getComputedStyle(document.body).fontFamily}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'bottom';
  // Подложка цвета фона: линейка лежит поверх чертежа и обязана читаться над любой линией.
  ctx.strokeStyle = css('--accent-halo');
  ctx.lineWidth = 4;
  ctx.stroke(bar);
  ctx.strokeText(label, cx, y - 7);
  ctx.strokeStyle = css('--bone-3');
  ctx.fillStyle = css('--bone-3');
  ctx.lineWidth = 1.5;
  ctx.stroke(bar);
  ctx.fillText(label, cx, y - 7);
  ctx.restore();
}

/** Виден ли объект в кадре. Запас - крона: центр бывает за краем, а крона в кадре. */
function inView(item, view, pad) {
  return item.x >= view[0] - pad && item.x <= view[2] + pad
    && item.y >= view[1] - pad && item.y <= view[3] + pad;
}

function drawPlacements(ctx, view) {
  const minRadius = MIN_CROWN_PX / state.scale;
  // При подсветке вида его кроны заодно подрастают: на общем виде разница одной лишь
  // прозрачности на кружке в четыре пикселя почти не читается.
  const liftRadius = (MIN_CROWN_PX + 2.5) / state.scale;
  const byVerdict = new Map();
  for (const p of state.placements) {
    if (state.speciesOff.has(p.species_code || '')) continue;
    if (!inView(p, view, p.radius + minRadius)) continue;
    const dim = state.highlight && p.species_code !== state.highlight;
    const key = `${p.verdict}|${dim ? 'dim' : 'on'}`;
    if (!byVerdict.has(key)) byVerdict.set(key, { verdict: p.verdict, dim, items: [] });
    byVerdict.get(key).items.push(p);
  }
  // Приглушённые рисуются первыми, чтобы подсвеченный вид лёг поверх.
  const groups = [...byVerdict.values()].sort((a, b) => (b.dim ? 1 : 0) - (a.dim ? 1 : 0));
  for (const group of groups) {
    const color = css(VERDICT_TOKEN[group.verdict] || '--bone-3');
    const lifted = !group.dim && state.highlight;
    const path = new Path2D();
    for (const p of group.items) {
      const r = Math.max(p.radius, lifted ? liftRadius : minRadius);
      path.moveTo(p.x + r, p.y);
      path.arc(p.x, p.y, r, 0, Math.PI * 2);
    }
    // Приглушённые не должны исчезать: подсветка вида обязана оставлять план на месте,
    // иначе вместо «где эти тридцать» получается «где остальные двести семьдесят».
    ctx.fillStyle = color + (group.dim ? '22' : lifted ? '88' : '55');
    ctx.fill(path);
    ctx.strokeStyle = color + (group.dim ? '55' : 'ff');
    ctx.lineWidth = (group.dim ? 1 : lifted ? 2.2 : 1.4) / state.scale;
    ctx.stroke(path);
  }
}

function drawRejections(ctx, view) {
  const path = new Path2D();
  const r = Math.max(1.2, 3 / state.scale);
  for (const p of state.rejections) {
    if (!inView(p, view, r)) continue;
    path.moveTo(p.x - r, p.y - r); path.lineTo(p.x + r, p.y + r);
    path.moveTo(p.x - r, p.y + r); path.lineTo(p.x + r, p.y - r);
  }
  ctx.strokeStyle = css('--bad');
  ctx.lineWidth = 1 / state.scale;
  ctx.stroke(path);
}

/** Кольцо с подложкой цвета фона и четыре засечки: на общем виде среди трёхсот одинаковых
 *  кружков выбранный иначе не найти, и панель объясняет норму для дерева, которого не видно. */
function ring(ctx, item, color, width) {
  const { sx, sy } = toScreen(item.x, item.y);
  const radius = Math.max((item.radius || 1) * state.scale, 9) + 4;
  ctx.lineWidth = width + 3;
  ctx.strokeStyle = css('--accent-halo');
  ctx.beginPath();
  ctx.arc(sx, sy, radius, 0, Math.PI * 2);
  ctx.stroke();
  ctx.lineWidth = width;
  ctx.strokeStyle = color;
  ctx.stroke();

  ctx.beginPath();
  for (const [dx, dy] of [[0, -1], [0, 1], [-1, 0], [1, 0]]) {
    ctx.moveTo(sx + dx * (radius + 3), sy + dy * (radius + 3));
    ctx.lineTo(sx + dx * (radius + 9), sy + dy * (radius + 9));
  }
  ctx.lineWidth = width + 3;
  ctx.strokeStyle = css('--accent-halo');
  ctx.stroke();
  ctx.lineWidth = width;
  ctx.strokeStyle = color;
  ctx.stroke();
}

function drawSelection(ctx) {
  ctx.lineCap = 'round';
  // Перетаскиваемая посадка рисуется цветом живого вердикта: пользователь видит запрет
  // до того, как отпустит кнопку, а не после.
  if (state.dragging) {
    ring(ctx, state.dragging, css(VERDICT_TOKEN[state.dragVerdict] || '--accent'), 2.5);
  }
  if (state.selected) ring(ctx, state.selected, css('--accent'), 2);
}

/** Стрелка севера. В чертеже север - это +Y, и после разворота вида он больше не наверху:
 *  без стрелки план читается как произвольно повёрнутая картинка. */
function drawNorth(ctx) {
  // Угол берётся из той же свободной области, что и вписывание: иначе стрелка уезжает
  // под боковую панель на низком окне и под полосу кнопок на телефоне.
  const area = clearArea();
  const x = area.left + area.width - 26;
  const y = area.top + area.height - 44;
  const c = Math.cos(state.rot);
  const s = Math.sin(state.rot);
  // Направление мировой оси +Y на экране.
  const nx = s;
  const ny = -c;
  const len = 15;
  ctx.save();
  ctx.translate(x, y);
  ctx.strokeStyle = css('--bone-3');
  ctx.fillStyle = css('--bone-3');
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(-nx * len, -ny * len);
  ctx.lineTo(nx * len, ny * len);
  ctx.stroke();
  // Наконечник.
  ctx.beginPath();
  ctx.moveTo(nx * len, ny * len);
  ctx.lineTo(nx * (len - 7) - ny * 4, ny * (len - 7) + nx * 4);
  ctx.lineTo(nx * (len - 7) + ny * 4, ny * (len - 7) - nx * 4);
  ctx.closePath();
  ctx.fill();
  ctx.font = `500 12px ${getComputedStyle(document.body).fontFamily}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('С', nx * (len + 10), ny * (len + 10));
  ctx.restore();
}

/* ---------- выбор объекта ---------- */

function toWorld(event) {
  const rect = canvas.getBoundingClientRect();
  const dx = event.clientX - rect.left - state.tx;
  const dy = event.clientY - rect.top - state.ty;
  const c = Math.cos(state.rot);
  const s = Math.sin(state.rot);
  return { x: (dx * c + dy * s) / state.scale, y: (dx * s - dy * c) / state.scale };
}

function pick(world) {
  const tolerance = 8 / state.scale;
  let best = null;
  let bestDistance = Infinity;
  const search = [...state.placements, ...state.rejections].filter(shown);
  for (const item of search) {
    const dx = item.x - world.x;
    const dy = item.y - world.y;
    const distance = Math.hypot(dx, dy);
    const reach = Math.max(item.radius || 0, tolerance);
    if (distance <= reach && distance < bestDistance) {
      best = item;
      bestDistance = distance;
    }
  }
  return best;
}

const escape = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** Запятая вместо точки: панель читает эксперт, а не отладчик. */
const meters = (value) => value.toFixed(2).replace('.', ',');

/** Русское числительное. Без него подписи приходится строить так, чтобы обойти падеж. */
function plural(count, one, few, many) {
  const tail = count % 10;
  const hundred = count % 100;
  if (tail === 1 && hundred !== 11) return one;
  if (tail >= 2 && tail <= 4 && (hundred < 12 || hundred > 14)) return few;
  return many;
}

function whatFor(check) {
  const rule = state.rules[check.rule_id] || {};
  return CLASS_RU[check.object_class || rule.object_class] || check.object_class || 'объекта';
}

/** Номер пункта без текста: `clause` в своде норм содержит и то и другое, поэтому цитата
 *  под ним дословно повторяла строку над собой. */
function clauseNumber(rule) {
  const clause = rule.clause || '';
  const cut = clause.indexOf(': ');
  return cut > 0 ? clause.slice(0, cut) : clause;
}

function quoteOf(rule) {
  if (rule.quote) return rule.quote;
  const clause = rule.clause || '';
  const cut = clause.indexOf(': ');
  return cut > 0 ? clause.slice(cut + 2) : '';
}

/** Разобрать строку таблицы норм на колонки.
 *
 *  В своде строка табл. 9.1 хранится как «объект | до ствола дерева | до кустарника»,
 *  иногда с примечанием в хвосте. Напечатанная палками, она читается как невычищенный
 *  дамп: эксперт видит два числа и должен угадать, какое из них про ствол. А это ровно
 *  тот текст, на котором держится интерпретируемость.
 */
function tableQuote(text) {
  // Точка с запятой означает перечень строк другой таблицы, а не примечание: разбор
  // «объект | дерево | кустарник» на нём давал «до ствола дерева не нормируется» там,
  // где в акте стоит 5-6 м. Чужой формат должен не разбираться, а не разбираться неверно.
  if (text.includes(';')) return null;
  const cells = text.split('|').map((cell) => cell.trim());
  if (cells.length !== 3) return null;
  if (!/^([\d,.]+|[-—])$/.test(cells[1])) return null;
  const tail = cells[2].match(/^([\d,.]+|[-—])\s*\.?\s*([^]*)$/);
  if (!tail) return null;
  const value = (raw) => (/^[\d,.]+$/.test(raw) ? `${raw} м` : 'не нормируется');
  return {
    what: cells[0].replace(/^[-–—]\s*/, ''),
    tree: value(cells[1]),
    shrub: value(tail[1]),
    note: tail[2].trim(),
  };
}

/** Разобрать цитату-перечень «вариант | значение; вариант | значение».
 *
 *  Так устроена табл. 3.6.2 743-ПП: расстояния между деревьями по типу посадки. Колонок
 *  в ней две, а строк несколько, и печатать её палками так же плохо, как табл. 9.1.
 */
function listQuote(text) {
  const rows = text.split(';').map((row) => row.trim()).filter(Boolean);
  if (rows.length < 2) return null;
  const pairs = [];
  for (const row of rows) {
    const cells = row.split('|').map((cell) => cell.trim());
    if (cells.length !== 2 || !cells[0] || !cells[1]) return null;
    // Единица приписывается только числу или диапазону: в перечне попадаются и слова.
    const numeric = /^[\d,.]+(\s*[-–]\s*[\d,.]+)?$/.test(cells[1]);
    pairs.push({ what: cells[0], value: numeric ? `${cells[1]} м` : cells[1] });
  }
  return pairs;
}

function quoteBlock(rule) {
  const text = quoteOf(rule);
  if (!text) return '';
  const pairs = listQuote(text);
  if (pairs) {
    return `
      <div class="check-quote">
        <ul class="quote-rows">
          ${pairs.map((pair) => `<li><span>${escape(pair.what)}</span><b>${escape(pair.value)}</b></li>`).join('')}
        </ul>
      </div>`;
  }
  const table = tableQuote(text);
  if (!table) return `<p class="check-quote">${escape(text)}</p>`;
  return `
    <div class="check-quote">
      ${escape(table.what)}
      <p class="quote-cols">
        <span>до ствола дерева <b>${escape(table.tree)}</b></span>
        <span>до кустарника <b>${escape(table.shrub)}</b></span>
      </p>
      ${table.note ? `<p class="quote-note">${escape(table.note)}</p>` : ''}
    </div>`;
}

function checkRow(check, { quote = false } = {}) {
  const rule = state.rules[check.rule_id] || {};
  const measured = check.measured_m == null ? null : meters(check.measured_m);
  const threshold = check.threshold_m == null ? null : meters(check.threshold_m);
  const failed = check.outcome === 'fail';
  const act = [rule.act_short || rule.act_id, clauseNumber(rule)].filter(Boolean).join(', ');
  const norm = threshold ? `норма ${threshold} м` : '';
  return `
    <li class="check-item${failed ? ' failed' : ''}">
      <div class="check-rule">
        <span class="check-what">до ${escape(whatFor(check))}</span>
        <span class="check-dist">${measured ? `${measured} м` : escape(norm)}</span>
      </div>
      <p class="check-clause">
        <span class="check-id">${escape(check.rule_id)}</span>${measured && norm ? ` · ${norm}` : ''}${act ? ` · ${escape(act)}` : ''}
      </p>
      ${quote ? quoteBlock(rule) : ''}
    </li>`;
}

/** Что показать в теле панели, а что убрать под раскрытие.
 *
 *  У посадки 23 проверенных правила, и медианный запас по ним - сорокакратный. Напечатанные
 *  подряд, они прячут единственное, что действительно ограничивало решение: двадцать строк
 *  «49,10 при норме 2,00» весят на экране столько же, сколько нарушенная норма.
 */
function splitChecks(checks) {
  const binding = [];
  const rest = [];
  for (const check of checks) {
    if (check.outcome === 'fail' || check.outcome === 'barrier') binding.push(check);
    else rest.push(check);
  }
  const measured = rest
    .filter((c) => c.measured_m != null && c.threshold_m)
    .sort((a, b) => a.measured_m / a.threshold_m - b.measured_m / b.threshold_m);
  const tight = measured.filter((c) => c.measured_m / c.threshold_m < TIGHT).slice(0, 3);
  // Нарушений нет - показываем одну ближайшую норму: она и есть доказательство того,
  // что отступ проверен, а не объявлен.
  const lead = binding.length ? binding : (tight.length ? tight : measured.slice(0, 1));
  const shown = new Set(lead);
  const hidden = checks.filter((c) => !shown.has(c));
  // Запас считается по самой тугой из СКРЫТЫХ норм: иначе строка «остальные выдержаны
  // с запасом» повторяет запас той нормы, которая уже напечатана выше.
  const tail = measured.filter((c) => !shown.has(c));
  return { lead, hidden, restSlack: tail.length ? tail[0].measured_m / tail[0].threshold_m : null };
}

function checksBlock(checks) {
  if (!checks.length) return '<p class="detail-slack">Проверенных правил не записано.</p>';
  const { lead, hidden, restSlack } = splitChecks(checks);
  const failing = lead.some((c) => c.outcome === 'fail');
  const parts = [
    // «Ближе всего к норме», а не «ближайшее»: это правило с наименьшим запасом, и оно
    // может относиться к объекту за полсотни метров - важно отношение, а не расстояние.
    `<h3 class="detail-heading">${failing ? 'Нарушено' : 'Ближе всего к норме'}</h3>
     <ul class="checks">${lead.map((c) => checkRow(c, { quote: true })).join('')}</ul>`,
  ];
  if (!failing && hidden.length) {
    const slack = restSlack ? Math.round(restSlack) : 0;
    const word = plural(hidden.length, 'норма', 'нормы', 'норм');
    parts.push(
      `<p class="detail-slack">Проверено ещё ${hidden.length} ${word}${
        slack > 1 ? `, наименьший запас у них — <b>${slack}</b>-кратный` : ''}.</p>`);
  }
  if (hidden.length) {
    // Правила без замера («до трамвайных путей норма 5,00 м») в списке не печатаются:
    // объекта нет в чертеже, ограничивать нечему, и строка не сообщает ничего. Но из
    // счёта они не исчезают - иначе «проверено 22» и список из 14 строк спорят друг с другом.
    const withFact = hidden.filter((c) => c.measured_m != null);
    const absent = hidden.length - withFact.length;
    parts.push(
      `<details class="detail-full">
         <summary>Ещё ${hidden.length} ${plural(hidden.length, 'проверка', 'проверки', 'проверок')}</summary>
         <ul class="checks" style="margin-top:12px">${withFact.map((c) => checkRow(c)).join('')}</ul>
         ${absent
           ? `<p class="detail-slack">Из них ${absent}: такого объекта в чертеже нет, норма
              проверена, ограничивать нечему.</p>`
           : ''}
       </details>`);
  }
  return parts.join('');
}

/** Панель без выбранного объекта показывает состав плана: пустая колонка во всю высоту карты
 *  ничего не сообщает, а «что посажено» - первый вопрос, который задаёт эксперт.
 *  Строка состава - кнопка: она подсвечивает свой вид на карте, и список видов перестаёт
 *  быть подписью ни к чему. */
function decimal(value) {
  return Number(value).toFixed(2).replace('.', ',');
}

/** Индекс качества плана: оценка, слагаемые с тем, что измерено, и основание каждого. */
function qualityBlock() {
  const q = state.quality;
  if (!q || !q.terms) return '';
  const head = q.index == null
    ? `<p class="quality-gate">${escape(q.gate)}</p>`
    : `<p class="quality-index"><b>${decimal(q.index)}</b> из 1</p>`;
  const terms = q.terms.map((t) => `
    <li>
      <details class="term${t.score == null ? ' term-none' : ''}">
        <summary>
          <span class="term-name">${escape(t.title)}</span>
          <span class="term-score">${t.score == null ? 'нет' : decimal(t.score)}</span>
          <span class="term-bar" aria-hidden="true"><i style="width: ${Math.round((t.score || 0) * 100)}%"></i></span>
        </summary>
        <p class="term-note">${escape(t.note)}</p>
        <p class="term-basis">${escape(t.basis)}${t.score == null ? '' : ` · вес ${Math.round(t.weight * 100)}%`}</p>
      </details>
    </li>`).join('');
  // Первая строка сводки - оценка или причина, по которой её нет: она уже стоит выше.
  const lines = (q.summary || []).slice(1).map((line) => `<p>${escape(line)}</p>`).join('');
  return `
    <section class="quality" aria-label="Качество плана">
      <h2 class="detail-heading">Качество плана</h2>
      ${head}
      <ul class="quality-terms">${terms}</ul>
      ${lines
        ? `<details class="fold quality-summary">
             <summary>Сводка: сильное, слабое, что поднимет</summary>${lines}
           </details>`
        : ''}
    </section>`;
}

function composition() {
  const byCode = new Map();
  for (const item of state.placements) {
    const code = item.species_code || '';
    const row = byCode.get(code) || { code, name: item.species_ru || 'вид не назначен', count: 0 };
    row.count += 1;
    byCode.set(code, row);
  }
  const rows = [...byCode.values()].sort((a, b) => b.count - a.count);
  const total = state.placements.length;
  if (!rows.length) {
    return `<div class="detail-empty"><p>В этом прогоне посадок нет.</p></div>`;
  }
  // Полоса меряется самым частым видом, а не суммой: при тринадцати видах доли от суммы
  // укладываются в 10% и все полосы выглядят одинаково короткими.
  const top = rows[0].count;
  return `
    ${qualityBlock()}
    <h2 class="detail-heading">Состав плана · ${total}</h2>
    <p class="detail-note" id="species-note">${speciesNote()}</p>
    <ul class="composition">
      ${rows.map((row) => `
        <li class="${state.speciesOff.has(row.code) ? 'off' : ''}">
          <input type="checkbox" class="composition-see" data-species-see="${escape(row.code)}"
                 ${state.speciesOff.has(row.code) ? '' : 'checked'}
                 aria-label="Показывать на карте: ${escape(row.name)}">
          <button type="button" data-species="${escape(row.code)}"
                  aria-pressed="${state.highlight === row.code}">
            <span class="composition-bar" style="--share: ${(row.count / top * 100).toFixed(1)}%"></span>
            <span class="composition-name">${escape(row.name)}</span>
            <span class="composition-count">${row.count}</span>
          </button>
        </li>`).join('')}
    </ul>
    <p class="detail-empty" style="margin-top:14px">Клик по посадке — норма, по которой она стоит.</p>`;
}

/** Подсказка над списком видов. Считается отдельно от самого списка: список при снятии
 *  галочки не перестраивается (уехала бы прокрутка), а эта строка обязана успевать - в ней
 *  и живёт возврат «показать все». */
function speciesNote() {
  const total = state.placements.length;
  const visible = state.placements.filter((item) => !state.speciesOff.has(item.species_code || '')).length;
  const tail = visible === total
    ? ''
    : ` Показано ${visible} из ${total}. <button type="button" class="linkish" id="species-all">показать все</button>`;
  return `Галочка оставляет вид на карте, клик по строке подсвечивает его.${tail}`;
}

function refreshSpeciesNote() {
  const note = document.getElementById('species-note');
  if (note) note.innerHTML = speciesNote();
}

/** Чем ценна посадка: насколько упадёт индекс качества без неё и за счёт чего. */
function valueBlock(value) {
  if (!value) return '';
  // Вклад одной посадки - десятитысячные доли индекса: показываем в тысячных (‰), а
  // меньше половины сотой промилле называем нулём, а не «без неё лучше».
  const permille = (Number(value.delta) || 0) * 1000;
  const zero = Math.abs(permille) < 0.005;
  const shown = `${permille < 0 ? '−' : '+'}${Math.abs(permille).toFixed(2).replace('.', ',')} ‰`;
  const reasons = (value.reasons || []).map((r) => `<li>${escape(r)}</li>`).join('');
  const rank = permille > 0 && !zero && value.percentile
    ? ` Больше, чем у ${Math.round(value.percentile * 100)}% посадок плана.`
    : '';
  const worse = permille < 0 && !zero;
  const head = worse ? 'Отрицательный вклад в оценку' : 'Чем ценна посадка';
  const line = zero
    ? 'Вклад в индекс качества около нуля.'
    : `Вклад в индекс качества <b>${shown}</b>.${rank}`;
  return `<h3 class="detail-heading">${head}</h3>
    <p class="value-delta${worse ? ' bad' : ''}">${line}</p>
    <p class="hint">${escape(value.scope || 'Перед удалением нужно заново проверить квоты видов и остальные ограничения; вклады не складываются.')}</p>
    ${reasons ? `<ul class="value-reasons">${reasons}</ul>` : ''}`;
}

function showDetail(item) {
  const body = detail.querySelector('.detail-scroll') || detail;
  if (!item) {
    body.innerHTML = composition();
    markOverflow();
    return;
  }
  const checks = item.checks || [];
  const title = item.kind === 'placement'
    ? `№ ${escape(item.number)}. ${escape(item.species_ru || 'вид не назначен')}`
    : `Отказ № ${escape(item.number)}`;
  const kind = KIND_RU[item.planting_type] || '';
  const verdict = VERDICT_RU[item.verdict] || item.verdict;
  body.innerHTML = `
    <h2 class="detail-name">${title}</h2>
    ${item.species_lat ? `<p class="detail-lat">${escape(item.species_lat)}</p>` : ''}
    <span class="verdict verdict-${escape(item.verdict)}">${escape(verdict)}</span>
    <p class="hint mono">${kind ? escape(kind) + ', ' : ''}x ${meters(item.x)}, y ${meters(item.y)}</p>
    ${item.note ? `<p class="detail-explain">${escape(item.note)}</p>` : ''}
    ${valueBlock(item.value)}
    ${checksBlock(checks)}
    ${item.explanation
      ? `<details class="detail-full">
           <summary>Объяснение целиком, как в выгрузке</summary>
           <p class="detail-explain">${escape(item.explanation)}</p>
         </details>`
      : ''}`;
  body.scrollTop = 0;
  markOverflow();
}

/* ---------- правка ---------- */

async function post(path, body) {
  const response = await fetch(`/api/v1/runs/${RUN_ID}/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `${path}: ${response.status}`);
  }
  return payload;
}

function setStale(stale) {
  state.stale = stale;
  const bar = document.getElementById('edit-bar');
  if (bar) bar.dataset.stale = stale ? '1' : '0';
}

function say(text, kind = 'info') {
  const slot = document.getElementById('edit-message');
  if (!slot) return;
  slot.textContent = text;
  slot.dataset.kind = kind;
}

/** Живой вердикт под курсором во время перетаскивания: ответ приходит с задержкой, поэтому
 *  устаревшие ответы отбрасываются по счётчику - иначе кружок мигает чужим цветом. */
let probeTicket = 0;
async function probe(item, x, y) {
  const ticket = ++probeTicket;
  try {
    const result = await post('check', { x, y, species: item.species_code || null });
    if (ticket !== probeTicket) return;
    state.dragVerdict = result.plantable ? result.verdict : 'rejected';
    schedule();
  } catch (error) {
    if (ticket === probeTicket) say(error.message, 'error');
  }
}

async function commitMove(item, x, y) {
  try {
    const summary = await post('edits', {
      edits: [{ kind: 'move', placement_id: item.id, x, y }],
    });
    item.x = x;
    item.y = y;
    await refreshOne(item);
    setStale(summary.stale);
    say(`Посадка №${item.number} перенесена. Нормы пересчитаны.`);
  } catch (error) {
    say(error.message, 'error');
  }
}

async function commitDelete(item) {
  try {
    const summary = await post('edits', {
      edits: [{ kind: 'delete', placement_id: item.id }],
    });
    state.placements = state.placements.filter((p) => p !== item);
    orderItems();
    state.selected = null;
    showDetail(null);
    setStale(summary.stale);
    say(`Посадка №${item.number} удалена. В плане осталось ${summary.placements}.`);
    schedule();
  } catch (error) {
    say(error.message, 'error');
  }
}

/** После переноса вердикт и трасса правил берутся у сервиса, а не досочиняются на клиенте. */
async function refreshOne(item) {
  const result = await post('check', {
    x: item.x,
    y: item.y,
    species: item.species_code || null,
  });
  item.verdict = result.plantable ? result.verdict : 'rejected';
  item.checks = result.checks;
  item.explanation = '';
  // Ценность считается по плану целиком: после переноса она известна только после пересборки.
  item.value = null;
  item.note = result.note;
  if (state.selected === item) showDetail(item);
  schedule();
}

/* ---------- ввод ---------- */

/** Порядок обхода с клавиатуры - вдоль улицы, как читают чертёж. */
function orderItems() {
  state.ordered = [...state.placements, ...state.rejections]
    .sort((a, b) => toView(a.x, a.y).u - toView(b.x, b.y).u);
}

/** Видна ли отметка: галочка слоя плюс фильтр по видам в составе плана.
 *
 *  Один источник правды для отрисовки, клика и клавиатуры: спрятанная посадка не должна
 *  находиться под курсором и не должна попадаться при переходе стрелками.
 */
function shown(item) {
  if (!item) return false;
  if (item.kind !== 'placement') return state.visible.rejections;
  return state.visible.placements && !state.speciesOff.has(item.species_code || '');
}

function selectable(item) {
  return shown(item);
}

/** Довезти вид до новой точки за 220 мс.
 *
 *  Единственная анимация на странице, и она служебная: при выборе с клавиатуры скачок
 *  карты неотличим от перезагрузки - непонятно, тот же это участок или другой.
 */
let pan = 0;
function panTo(tx, ty) {
  cancelAnimationFrame(pan);
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduced || (Math.abs(tx - state.tx) < 2 && Math.abs(ty - state.ty) < 2)) {
    state.tx = tx;
    state.ty = ty;
    schedule();
    return;
  }
  const from = { tx: state.tx, ty: state.ty };
  const started = performance.now();
  const tick = (now) => {
    const k = Math.min((now - started) / 220, 1);
    const eased = 1 - (1 - k) ** 3;
    state.tx = from.tx + (tx - from.tx) * eased;
    state.ty = from.ty + (ty - from.ty) * eased;
    draw();
    if (k < 1) pan = requestAnimationFrame(tick);
  };
  pan = requestAnimationFrame(tick);
}

/** Довести выбранное до видимой области, не меняя масштаб: выбор с клавиатуры иначе
 *  уезжает за край и выглядит как «ничего не произошло». */
function revealSelected() {
  if (!state.selected) return;
  const area = clearArea();
  const { sx, sy } = toScreen(state.selected.x, state.selected.y);
  const pad = 60;
  let { tx, ty } = state;
  if (sx < area.left + pad) tx += area.left + pad - sx;
  if (sx > area.left + area.width - pad) tx += area.left + area.width - pad - sx;
  if (sy < area.top + pad) ty += area.top + pad - sy;
  if (sy > area.top + area.height - pad) ty += area.top + area.height - pad - sy;
  panTo(tx, ty);
}

function step(delta) {
  const list = state.ordered.filter(selectable);
  if (!list.length) return;
  const at = state.selected ? list.indexOf(state.selected) : -1;
  const next = at < 0
    ? (delta > 0 ? 0 : list.length - 1)
    : (at + delta + list.length) % list.length;
  state.selected = list[next];
  showDetail(state.selected);
  revealSelected();
  schedule();
}

function centerSelected() {
  if (!state.selected) return;
  const area = clearArea();
  const { sx, sy } = toScreen(state.selected.x, state.selected.y);
  state.touched = true;
  panTo(state.tx + area.left + area.width / 2 - sx, state.ty + area.top + area.height / 2 - sy);
}

function zoomAt(px, py, factor) {
  const next = Math.min(Math.max(state.scale * factor, 0.002), 400);
  const applied = next / state.scale;
  state.tx = px - (px - state.tx) * applied;
  state.ty = py - (py - state.ty) * applied;
  state.scale = next;
  state.touched = true;
  schedule();
}

function setHighlight(code) {
  state.highlight = state.highlight === code ? null : code;
  showDetail(null);
  schedule();
}

function bindInput() {
  let dragging = false;
  let moved = 0;
  let last = null;
  let grabbed = null;

  canvas.addEventListener('pointerdown', (event) => {
    dragging = true;
    moved = 0;
    last = { x: event.clientX, y: event.clientY };
    grabbed = state.editing ? pick(toWorld(event)) : null;
    if (grabbed && grabbed.kind !== 'placement') grabbed = null;
    canvas.setPointerCapture(event.pointerId);
    canvas.classList.add('dragging');
  });

  canvas.addEventListener('pointermove', (event) => {
    if (!dragging) {
      // Курсор-указатель над посадкой: подсказка про клик без единого слова в панели.
      const over = Boolean(pick(toWorld(event)));
      if (over !== state.hovered) {
        state.hovered = over;
        canvas.style.cursor = over ? 'pointer' : '';
      }
      return;
    }
    const dx = event.clientX - last.x;
    const dy = event.clientY - last.y;
    moved += Math.abs(dx) + Math.abs(dy);
    last = { x: event.clientX, y: event.clientY };
    if (grabbed) {
      const world = toWorld(event);
      grabbed.x = world.x;
      grabbed.y = world.y;
      state.dragging = grabbed;
      if (moved % 3 < 1) probe(grabbed, world.x, world.y);
    } else {
      state.tx += dx;
      state.ty += dy;
      state.touched = true;
    }
    schedule();
  });

  canvas.addEventListener('pointerup', (event) => {
    dragging = false;
    canvas.classList.remove('dragging');
    if (grabbed && moved >= 4) {
      const world = toWorld(event);
      state.dragging = null;
      state.dragVerdict = null;
      commitMove(grabbed, world.x, world.y);
      grabbed = null;
      return;
    }
    grabbed = null;
    state.dragging = null;
    state.dragVerdict = null;
    if (moved < 4) {
      state.selected = pick(toWorld(event));
      showDetail(state.selected);
      schedule();
    }
  });

  // Карта доступна с клавиатуры: требование заказчика - увидеть норму по посадке - иначе
  // выполнимо только мышью, а это отказ по WCAG 2.1.1.
  canvas.addEventListener('keydown', (event) => {
    const keys = {
      ArrowRight: () => step(1), ArrowDown: () => step(1),
      ArrowLeft: () => step(-1), ArrowUp: () => step(-1),
      Home: () => { state.selected = null; step(1); },
      End: () => { state.selected = null; step(-1); },
      Enter: centerSelected, ' ': centerSelected,
      Escape: () => { state.selected = null; showDetail(null); schedule(); },
      '+': () => zoomAt(canvas.clientWidth / 2, canvas.clientHeight / 2, 1.4),
      '=': () => zoomAt(canvas.clientWidth / 2, canvas.clientHeight / 2, 1.4),
      '-': () => zoomAt(canvas.clientWidth / 2, canvas.clientHeight / 2, 1 / 1.4),
    };
    if (event.key === 'Delete' && state.editing && state.selected?.kind === 'placement') {
      event.preventDefault();
      commitDelete(state.selected);
      return;
    }
    const action = keys[event.key];
    if (!action) return;
    event.preventDefault();
    action();
  });

  canvas.addEventListener('wheel', (event) => {
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    zoomAt(event.clientX - rect.left, event.clientY - rect.top, Math.exp(-event.deltaY * 0.0015));
  }, { passive: false });

  const zoomBy = (factor) =>
    zoomAt(canvas.clientWidth / 2, canvas.clientHeight / 2, factor);
  const range = document.getElementById('zoom-range');
  range?.addEventListener('input', () => {
    const { lo, hi } = zoomBounds();
    const wanted = lo * (hi / lo) ** (Number(range.value) / 1000);
    const area = clearArea();
    zoomAt(area.left + area.width / 2, area.top + area.height / 2, wanted / state.scale);
  });
  document.getElementById('zoom-in')?.addEventListener('click', () => zoomBy(1.4));
  document.getElementById('zoom-out')?.addEventListener('click', () => zoomBy(1 / 1.4));
  document.getElementById('fit')?.addEventListener('click', () => {
    state.touched = false;
    fitToBbox();
    schedule();
  });

  const orient = document.getElementById('orient');
  orient?.addEventListener('click', () => {
    const alongStreet = state.rot !== 0;
    state.rot = alongStreet ? 0 : state.axis;
    orient.setAttribute('aria-pressed', String(!alongStreet));
    orient.textContent = alongStreet ? 'по северу' : 'по улице';
    state.touched = false;
    orderItems();
    sizeHolder();
    resize();
    fitToBbox();
    schedule();
  });

  document.getElementById('layer-toggles')?.addEventListener('change', (event) => {
    const input = event.target;
    if (!input.dataset.layer) return;
    state.visible[input.dataset.layer] = input.checked;
    if (state.selected && !selectable(state.selected)) {
      state.selected = null;
      showDetail(null);
    }
    invalidate();
    schedule();
  });

  detail?.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-species]');
    if (button) {
      setHighlight(button.dataset.species);
      return;
    }
    if (event.target.closest('#species-all')) {
      state.speciesOff.clear();
      showDetail(null);
      schedule();
    }
  });

  // Галочка вида: перестраивать список целиком нельзя - уедет прокрутка, а человек как раз
  // идёт по нему сверху вниз и снимает лишнее.
  detail?.addEventListener('change', (event) => {
    const box = event.target.closest('input[data-species-see]');
    if (!box) return;
    const code = box.dataset.speciesSee;
    if (box.checked) state.speciesOff.delete(code);
    else state.speciesOff.add(code);
    box.closest('li')?.classList.toggle('off', !box.checked);
    if (state.selected && !selectable(state.selected)) {
      state.selected = null;
      showDetail(null);
    } else {
      refreshSpeciesNote();
    }
    orderItems();
    schedule();
  });

  const editToggle = document.getElementById('edit-toggle');
  editToggle?.addEventListener('change', () => {
    state.editing = editToggle.checked;
    canvas.classList.toggle('editable', state.editing);
    say(state.editing ? 'Тяните посадку мышью. Delete удаляет выбранную.' : '');
  });

  document.getElementById('rebuild')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    say('Пересобираем DXF и объяснения, это занимает до минуты...');
    try {
      await post('rebuild', {});
      say('Файлы результата пересобраны по исправленному плану. Обновляем страницу.');
      setStale(false);
      setTimeout(() => window.location.reload(), 1200);
    } catch (error) {
      say(error.message, 'error');
      button.disabled = false;
    }
  });

  for (const button of document.querySelectorAll('.panel-toggle')) {
    button.addEventListener('click', () => {
      const panel = button.closest('.hud');
      // Центр свободной области до сворачивания: вид сдвигается за ним и сохраняет масштаб.
      // Раньше панель сворачивали ради ширины, а получали сброс приближения - и место,
      // которое человек разглядывал, приходилось искать заново.
      const area = clearArea();
      const previous = { cx: area.left + area.width / 2, cy: area.top + area.height / 2 };
      const collapsed = panel.classList.toggle('collapsed');
      button.setAttribute('aria-expanded', String(!collapsed));
      button.title = collapsed ? 'Развернуть панель' : 'Свернуть панель';
      try {
        localStorage.setItem(`green-panel-${button.dataset.panel}`, collapsed ? '1' : '0');
      } catch (error) { /* приватный режим: состояние не переживёт перезагрузку */ }
      sizeHolder();
      resize();
      keepView(previous);
      markOverflow();
      schedule();
    });
  }

  window.addEventListener('resize', () => {
    const area = clearArea();
    const previous = { cx: area.left + area.width / 2, cy: area.top + area.height / 2 };
    sizeHolder();
    resize();
    keepView(previous);
    markOverflow();
    schedule();
  });
  // Тема меняет цвета, взятые из CSS-переменных: сбросить их кэш и перерисовать карту.
  new MutationObserver(repaint).observe(document.documentElement, {
    attributes: true, attributeFilter: ['data-theme'],
  });
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', repaint);
}

/* ---------- запуск ---------- */

/* ---------- условные обозначения ---------- */

const legendBox = document.getElementById('legend');

/** Показать или спрятать обозначения. Панель занимает нижний левый угол, поэтому свободная
 *  область меняется, и вид надо удержать - как при сворачивании пульта. */
function setLegend(open, { keep = true } = {}) {
  if (!legendBox) return;
  const area = keep ? clearArea() : null;
  const previous = area && { cx: area.left + area.width / 2, cy: area.top + area.height / 2 };
  legendBox.hidden = !open;
  const workspace = document.querySelector('.workspace');
  workspace?.classList.toggle('legend-on', open);
  // Высота панели зависит от содержимого, а пульт обязан под неё ужаться: измеряем после
  // показа и кладём в переменную, на которую смотрит его max-height.
  workspace?.style.setProperty(
    '--legend-h', open ? `${Math.round(legendBox.getBoundingClientRect().height)}px` : '0px'
  );
  document.getElementById('legend-toggle')?.setAttribute('aria-pressed', String(open));
  try {
    localStorage.setItem('green-legend', open ? '1' : '0');
  } catch (error) { /* приватный режим: состояние не переживёт перезагрузку */ }
  if (!previous) return;
  resize();
  keepView(previous);
  schedule();
}

function bindLegend() {
  document.getElementById('legend-toggle')?.addEventListener('click', () => {
    setLegend(Boolean(legendBox?.hidden));
  });
  document.getElementById('legend-close')?.addEventListener('click', () => setLegend(false));
  // Высота панели меняется и без переключения: окно растянули, и её потолок вырос с 300 до
  // 420 px. Замер, сделанный один раз при загрузке, оставлял пульт наезжать на её шапку.
  if (legendBox && 'ResizeObserver' in window) {
    new ResizeObserver(() => {
      if (legendBox.hidden) return;
      document.querySelector('.workspace')?.style.setProperty(
        '--legend-h', `${Math.round(legendBox.getBoundingClientRect().height)}px`
      );
    }).observe(legendBox);
  }
}

/** Вернуть панели в то состояние, в котором их оставили. Делается до первой отрисовки:
 *  свёрнутая панель меняет свободную область, а вид собирается по ней один раз. */
function restorePanels() {
  for (const button of document.querySelectorAll('.panel-toggle')) {
    let saved = null;
    try {
      saved = localStorage.getItem(`green-panel-${button.dataset.panel}`);
    } catch (error) { /* приватный режим: панели останутся развёрнутыми */ }
    if (saved !== '1') continue;
    button.closest('.hud').classList.add('collapsed');
    button.setAttribute('aria-expanded', 'false');
    button.title = 'Развернуть панель';
  }
  // Обозначения по умолчанию открыты: без них цвет на карте не значит ничего. На узком
  // экране - закрыты: там панель накрывает половину карты, и первым делом человеку нужен
  // сам чертёж. Свой выбор человека сильнее обоих умолчаний.
  let legendSaved = null;
  try {
    legendSaved = localStorage.getItem('green-legend');
  } catch (error) { /* приватный режим: обозначения останутся открытыми */ }
  const narrow = window.matchMedia('(max-width: 1080px)').matches;
  setLegend(legendSaved === null ? !narrow : legendSaved !== '0', { keep: false });
  bindLegend();
}

/** Габарит участка по подоснове, пока плана ещё нет.
 *
 *  Опора - центры самих объектов без двух процентов выбросов с каждого края: bbox всей
 *  подосновы на генплане раскинут на километры из-за нескольких далёких объектов, а
 *  граница работ не годится - у встроенного фрагмента она осталась от целой улицы и в
 *  восемь раз длиннее самого чертежа. Если опоры нет, остаётся bbox подосновы: лучше
 *  показать много, чем ничего, до участка можно доехать колёсиком.
 */
function siteBox(basemap) {
  const box = boundsOfPoints(state.outline, 25);
  if (box) return box;
  const map = basemap.bbox;
  return map && (map[2] - map[0] > 0 || map[3] - map[1] > 0) ? map : null;
}

function contentPoints(features) {
  const points = [];
  for (const feature of features || []) {
    if (feature.properties.class === 'work_boundary') continue;
    const vertices = geometryPoints(feature.geometry);
    if (!vertices.length) continue;
    let sx = 0;
    let sy = 0;
    for (const { x, y } of vertices) { sx += x; sy += y; }
    points.push({ x: sx / vertices.length, y: sy / vertices.length });
  }
  return trimmed(points);
}

/** Точки внутри 2-98-го процентиля по каждой оси: далёкие объекты не растягивают вид. */
function trimmed(points, share = 0.02) {
  if (points.length < 20) return points;
  const xs = points.map((p) => p.x).sort((a, b) => a - b);
  const ys = points.map((p) => p.y).sort((a, b) => a - b);
  const low = Math.floor(points.length * share);
  const high = Math.ceil(points.length * (1 - share)) - 1;
  return points.filter((p) => p.x >= xs[low] && p.x <= xs[high] && p.y >= ys[low] && p.y <= ys[high]);
}

function geometryPoints(geometry) {
  const { type, coordinates } = geometry;
  if (type === 'Point') return [{ x: coordinates[0], y: coordinates[1] }];
  if (type === 'MultiPoint' || type === 'LineString') return coordinates.map(([x, y]) => ({ x, y }));
  if (type === 'MultiLineString' || type === 'Polygon') return coordinates.flat().map(([x, y]) => ({ x, y }));
  if (type === 'MultiPolygon') return coordinates.flat(2).map(([x, y]) => ({ x, y }));
  if (type === 'GeometryCollection') return geometry.geometries.flatMap(geometryPoints);
  return [];
}

/* ---------- вид переживает перезагрузку ---------- */

const VIEW_KEY = `green-view-${RUN_ID}`;

/** Страница перезагружается, когда план готов: панели с результатом рисует сервер. Вид,
 *  который человек настроил руками, при этом не должен сброситься - он его разглядывал. */
function rememberView() {
  if (!state.touched || !state.bbox) return;
  try {
    sessionStorage.setItem(VIEW_KEY, JSON.stringify({
      scale: state.scale, tx: state.tx, ty: state.ty, rot: state.rot,
    }));
  } catch (error) { /* приватный режим: вид соберётся заново */ }
}

function restoreView() {
  let saved = null;
  try {
    saved = JSON.parse(sessionStorage.getItem(VIEW_KEY) || 'null');
    sessionStorage.removeItem(VIEW_KEY);
  } catch (error) {
    return false;
  }
  if (!saved || !Number.isFinite(saved.scale)) return false;
  Object.assign(state, { scale: saved.scale, tx: saved.tx, ty: saved.ty, rot: saved.rot, touched: true });
  const orient = document.getElementById('orient');
  if (orient) {
    orient.setAttribute('aria-pressed', String(saved.rot !== 0));
    orient.textContent = saved.rot !== 0 ? 'по улице' : 'по северу';
  }
  return true;
}

/* ---------- ход расчёта ---------- */

const POLL_MS = 2000;
const progressBox = document.getElementById('progress');
// Часы между опросами идут локально: секунды «прошло» и «осталось» тикают каждую секунду,
// а не раз в два опроса.
let clock = null;

function setText(id, text) {
  const node = document.getElementById(id);
  if (node && node.textContent !== text) node.textContent = text;
}

function clockText(seconds) {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function aboutText(seconds) {
  if (seconds < 10) return 'несколько секунд';
  if (seconds < 60) return `около ${Math.ceil(seconds / 10) * 10} с`;
  const minutes = Math.round(seconds / 60);
  return minutes <= 1 ? 'около минуты' : `около ${minutes} мин`;
}

function renderClock() {
  if (!clock) return;
  const passed = (performance.now() - clock.at) / 1000;
  const elapsed = clock.elapsed + passed;
  const eta = clock.eta == null ? null : Math.max(clock.eta - passed, 0);
  const tail = eta == null ? '' : ` · осталось ${aboutText(eta)}`;
  setText('progress-time', `прошло ${clockText(elapsed)}${tail}`);
}

function renderProgress(run) {
  if (!progressBox) return;
  const p = run.progress;
  const queued = run.state === 'queued';
  const title = queued ? 'В очереди' : (p?.title || 'Готовимся к расчёту');
  const pct = Math.round((p?.fraction || 0) * 100);
  setText('progress-title', title);
  setText('progress-pct', `${pct} %`);
  const bar = document.getElementById('progress-bar');
  if (bar) {
    bar.setAttribute('aria-valuenow', String(pct));
    bar.firstElementChild.style.width = `${pct}%`;
  }
  const steps = p?.steps || [];
  const index = steps.findIndex((s) => s.state === 'active');
  setText('progress-step', index >= 0
    ? `этап ${index + 1} из ${steps.length}`
    : (queued ? 'ждём свободного места' : ''));
  // Подложка до чертежа повторяет этап: у человека один источник правды, а не два.
  setText('status-title', queued ? 'В очереди' : (p?.stage ? title : 'Читаем чертёж'));
  const elapsed = p ? p.elapsed_s : Math.max(0, (Date.now() - Date.parse(run.created_at)) / 1000);
  clock = { at: performance.now(), elapsed, eta: p ? p.eta_s : null };
  renderClock();
}

/** Показать подоснову, как только прогон её отдал: чертёж становится картой, по которой
 *  можно ездить, пока считаются посадки. */
function showDrawing(basemap) {
  state.chunks = buildChunks(basemap.features || [], basemap.bbox);
  // Пока посадок, по которым вписывается и разворачивается готовый план, ещё нет, ту же
  // роль играют центры объектов подосновы.
  state.outline = contentPoints(basemap.features);
  state.bbox = siteBox(basemap);
  if (!state.bbox) return;
  state.axis = principalAxis(state.outline);
  state.rot = state.axis;
  loading.hidden = true;
  sizeHolder();
  resize();
  fitToBbox();
  draw();
}

/** Идущий прогон: опрос статуса, полоса хода, чертёж на карте до конца расчёта. */
async function live() {
  restorePanels();
  resize();
  bindInput();
  setInterval(renderClock, 1000);

  let drawn = false;
  let timer = null;
  const tick = async () => {
    let run;
    try {
      const response = await fetch(`/api/v1/runs/${RUN_ID}`, { cache: 'no-store' });
      if (!response.ok) return;
      run = await response.json();
    } catch (error) {
      return; // сеть моргнула: следующий тик попробует снова
    }
    renderProgress(run);
    if (!drawn && run.artifacts.some((a) => a.name === 'basemap.geojson')) {
      drawn = true;
      try {
        showDrawing(await loadJson('basemap.geojson'));
      } catch (error) {
        drawn = false; // файл ещё дописывается: заберём на следующем тике
      }
    }
    if (run.state !== 'queued' && run.state !== 'running') {
      clearInterval(timer);
      rememberView();
      window.location.reload();
    }
  };
  timer = setInterval(tick, POLL_MS);
  tick();
}

async function mount() {
  restorePanels();
  try {
    const [basemap, plan, rules, quality] = await Promise.all([
      loadJson('basemap.geojson'),
      loadJson('plan.json'),
      loadJson('rules.json'),
      // У прогонов до появления индекса файла нет: карта от этого не должна ломаться.
      loadJson('quality.json').catch(() => null),
    ]);

    state.quality = quality;

    state.rules = rules.rules || {};
    state.chunks = buildChunks(basemap.features || [], basemap.bbox);
    state.placements = (plan.placements || []).map((p) => ({
      kind: "placement",
      id: p.id,
      number: p.number,
      planting_type: p.planting_type,
      x: p.x,
      y: p.y,
      radius: (p.species?.crown_diameter_m || 3) / 2,
      verdict: p.verdict,
      species_code: p.species?.code,
      species_ru: p.species?.name_ru,
      species_lat: p.species?.name_lat,
      explanation: p.explanation,
      value: p.value,
      checks: p.checks,
    }));
    state.rejections = (plan.rejections || []).map((r) => ({
      kind: "rejection",
      id: r.id,
      number: r.number,
      planting_type: r.planting_type,
      x: r.x,
      y: r.y,
      radius: 1.2,
      verdict: r.verdict,
      explanation: r.explanation,
      note: r.note,
      checks: r.blocking,
    }));

    // Вид подгоняется под план, а не под всю подоснову. На генплане Берзарина подоснова
    // раскинута на 5,5 x 14,5 км из-за нескольких далёких объектов, и участок работ в таком
    // окне превращается в точку. Подоснова остаётся целиком, до неё можно отъехать.
    const planBox = boundsOfPoints([...state.placements, ...state.rejections], 25);
    const mapBox = basemap.bbox;
    state.bbox = planBox
      || (mapBox && (mapBox[2] - mapBox[0] > 0 || mapBox[3] - mapBox[1] > 0) ? mapBox : null);

    if (!state.bbox) {
      loading.textContent = 'В этом прогоне нечего показать на карте.';
      return;
    }

    state.axis = principalAxis(state.placements.length ? state.placements : state.rejections);
    state.rot = state.axis;
    orderItems();

    loading.hidden = true;
    sizeHolder();
    resize();
    fitToBbox();
    restoreView();
    bindInput();
    showDetail(null);
    markOverflow();
    draw();
  } catch (error) {
    loading.innerHTML = `<span>Карта не загрузилась: ${escape(error.message)}</span>`;
  }
}

function boundsOfPoints(items, margin = 10) {
  if (!items.length) return null;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const item of items) {
    minX = Math.min(minX, item.x); maxX = Math.max(maxX, item.x);
    minY = Math.min(minY, item.y); maxY = Math.max(maxY, item.y);
  }
  return [minX - margin, minY - margin, maxX + margin, maxY + margin];
}

// Готовый прогон монтирует карту целиком; идущий - следит за ходом и показывает чертёж,
// как только прогон его отдал. Неудавшийся оставляет подложку с причиной.
const runState = document.querySelector('.page-run')?.dataset.state;
if (canvas && RUN_ID && runState === 'succeeded') {
  mount();
} else if (canvas && RUN_ID && (runState === 'queued' || runState === 'running')) {
  live();
}
