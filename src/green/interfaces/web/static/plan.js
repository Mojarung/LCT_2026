/* Карта плана: подоснова, посадки и отказы на канве, с объяснением по клику.
 *
 * Две вещи определяют всю конструкцию:
 * 1. На настоящем чертеже десятки тысяч объектов, поэтому геометрия собирается в Path2D
 *    один раз в координатах чертежа, а зум и панорама делаются трансформацией канвы.
 *    Перестраивать пути на каждый кадр нельзя - это единственное, что тут может тормозить.
 * 2. Цвета берутся из CSS-переменных, а не хардкодятся: тема переключается в одном месте,
 *    и карта обязана следовать за ней.
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

const state = {
  buckets: [],        // { group, strokeVar, fillVar, width, dash, path }
  placements: [],
  rejections: [],
  rules: {},
  bbox: null,
  scale: 1,
  tx: 0,
  ty: 0,
  selected: null,
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

const css = (token) =>
  getComputedStyle(document.documentElement).getPropertyValue(token).trim() || '#888';

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

function buildBuckets(features) {
  const byKey = new Map();
  for (const feature of features) {
    const style = STYLES[feature.properties.class];
    if (!style) continue;
    const key = feature.properties.class;
    let bucket = byKey.get(key);
    if (!bucket) {
      bucket = {
        group: style.group,
        strokeVar: style.stroke,
        fillVar: style.fill,
        width: style.width,
        dash: style.dash || [],
        path: new Path2D(),
      };
      byKey.set(key, bucket);
    }
    addGeometry(bucket.path, feature.geometry);
  }
  // Заливки рисуются первыми, иначе газон и здания закрашивают линии поверх себя.
  return [...byKey.values()].sort((a, b) => (b.fillVar ? 1 : 0) - (a.fillVar ? 1 : 0));
}

/* ---------- вид ---------- */

/** Свободная область канвы: панели лежат поверх плана и закрывают его края, поэтому
 *  «вписать» считается по тому прямоугольнику, который действительно видно. */
function clearArea() {
  const rect = canvas.getBoundingClientRect();
  let left = 0;
  let right = rect.width;
  for (const panel of document.querySelectorAll('.hud-left, .hud-right')) {
    const box = panel.getBoundingClientRect();
    if (box.width === 0 || getComputedStyle(panel).position !== 'absolute') continue;
    if (box.left - rect.left < rect.width / 2) left = Math.max(left, box.right - rect.left + 14);
    else right = Math.min(right, box.left - rect.left - 14);
  }
  const width = Math.max(right - left, 240);
  return { left, width, height: rect.height, rect };
}

function fitToBbox() {
  const [minX, minY, maxX, maxY] = state.bbox;
  const w = Math.max(maxX - minX, 1);
  const h = Math.max(maxY - minY, 1);
  const area = clearArea();
  state.scale = Math.min(area.width / w, area.height / h) * 0.92;
  state.tx = area.left + area.width / 2 - ((minX + maxX) / 2) * state.scale;
  state.ty = area.height / 2 + ((minY + maxY) / 2) * state.scale;
}

function resize() {
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  draw();
}

let frame = 0;
function schedule() {
  if (frame) return;
  frame = requestAnimationFrame(() => { frame = 0; draw(); });
}

function draw() {
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!state.bbox) return;

  // Y в чертеже направлен вверх, на канве вниз: отражаем масштабом.
  ctx.setTransform(state.scale * dpr, 0, 0, -state.scale * dpr, state.tx * dpr, state.ty * dpr);
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';

  for (const bucket of state.buckets) {
    if (!state.visible[bucket.group]) continue;
    if (bucket.fillVar) {
      ctx.fillStyle = css(bucket.fillVar);
      ctx.fill(bucket.path);
    }
    if (bucket.strokeVar && bucket.width) {
      ctx.strokeStyle = css(bucket.strokeVar);
      ctx.lineWidth = bucket.width / state.scale;
      ctx.setLineDash(bucket.dash.map((d) => d / state.scale));
      ctx.stroke(bucket.path);
      ctx.setLineDash([]);
    }
  }

  if (state.visible.rejections) drawRejections(ctx);
  if (state.visible.placements) drawPlacements(ctx);
  drawSelection(ctx);
}

function drawPlacements(ctx) {
  const byVerdict = new Map();
  for (const p of state.placements) {
    if (!byVerdict.has(p.verdict)) byVerdict.set(p.verdict, []);
    byVerdict.get(p.verdict).push(p);
  }
  for (const [verdict, items] of byVerdict) {
    const color = css(VERDICT_TOKEN[verdict] || '--text-dim');
    const path = new Path2D();
    for (const p of items) {
      const r = Math.max(p.radius, 0.6);
      path.moveTo(p.x + r, p.y);
      path.arc(p.x, p.y, r, 0, Math.PI * 2);
    }
    ctx.fillStyle = color + '33';
    ctx.fill(path);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.2 / state.scale;
    ctx.stroke(path);
  }
}

function drawRejections(ctx) {
  const path = new Path2D();
  const r = 1.2;
  for (const p of state.rejections) {
    path.moveTo(p.x - r, p.y - r); path.lineTo(p.x + r, p.y + r);
    path.moveTo(p.x - r, p.y + r); path.lineTo(p.x + r, p.y - r);
  }
  ctx.strokeStyle = css('--bad');
  ctx.lineWidth = 1 / state.scale;
  ctx.stroke(path);
}

function drawSelection(ctx) {
  // Перетаскиваемая посадка рисуется цветом живого вердикта: пользователь видит запрет
  // до того, как отпустит кнопку, а не после.
  if (state.dragging) {
    const { x, y, radius } = state.dragging;
    ctx.strokeStyle = css(VERDICT_TOKEN[state.dragVerdict] || '--accent');
    ctx.lineWidth = 2.5 / state.scale;
    ctx.beginPath();
    ctx.arc(x, y, Math.max(radius || 1, 1), 0, Math.PI * 2);
    ctx.stroke();
  }
  if (!state.selected) return;
  const { x, y, radius } = state.selected;
  ctx.strokeStyle = css('--accent');
  ctx.lineWidth = 2 / state.scale;
  ctx.beginPath();
  ctx.arc(x, y, Math.max(radius || 1, 1) + 2.5 / state.scale, 0, Math.PI * 2);
  ctx.stroke();
}

/* ---------- выбор объекта ---------- */

function toWorld(event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: (event.clientX - rect.left - state.tx) / state.scale,
    y: -(event.clientY - rect.top - state.ty) / state.scale,
  };
}

function pick(world) {
  const tolerance = 8 / state.scale;
  let best = null;
  let bestDistance = Infinity;
  const search = [
    ...(state.visible.placements ? state.placements : []),
    ...(state.visible.rejections ? state.rejections : []),
  ];
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

function checkRow(check) {
  const rule = state.rules[check.rule_id] || {};
  const measured = check.measured_m == null ? null : check.measured_m.toFixed(2);
  const threshold = check.threshold_m == null ? null : check.threshold_m.toFixed(2);
  const distance = measured && threshold
    ? `${measured} / ${threshold} м`
    : (threshold ? `норма ${threshold} м` : '');
  const act = [rule.act_short || rule.act_id, rule.clause].filter(Boolean).join(', ');
  const failed = check.outcome === 'fail';
  return `
    <li class="check-item${failed ? ' failed' : ''}">
      <div class="check-rule">
        <span class="check-id">${escape(check.rule_id)}</span>
        <span class="check-dist">${escape(distance)}</span>
      </div>
      ${act ? `<p class="check-clause">${escape(act)}</p>` : ''}
      ${rule.quote ? `<p class="check-quote">${escape(rule.quote)}</p>` : ''}
    </li>`;
}

/** Нормы, у которых в чертеже нет объекта, проверены, но решение не определяли. Смешанные
 *  в один список с действующими ограничениями, они прячут главное: двадцать строк «5,00 м»
 *  без замера выглядят так же весомо, как единственное нарушенное правило. */
function splitChecks(checks) {
  const binding = [];
  const measured = [];
  const absent = [];
  for (const check of checks) {
    if (check.outcome === 'fail' || check.outcome === 'barrier') binding.push(check);
    else if (check.measured_m != null) measured.push(check);
    else absent.push(check);
  }
  measured.sort((a, b) => (a.measured_m ?? 0) - (b.measured_m ?? 0));
  return { binding, measured, absent };
}

/** Панель без выбранного объекта показывает состав плана: пустая колонка во всю высоту карты
 *  ничего не сообщает, а «что посажено» - первый вопрос, который задаёт эксперт. */
function composition() {
  const byName = new Map();
  for (const item of state.placements) {
    const name = item.species_ru || 'вид не назначен';
    const row = byName.get(name) || { name, lat: item.species_lat, count: 0 };
    row.count += 1;
    byName.set(name, row);
  }
  const rows = [...byName.values()].sort((a, b) => b.count - a.count);
  const total = state.placements.length;
  if (!rows.length) {
    return `<div class="detail-empty"><p>В этом прогоне посадок нет.</p></div>`;
  }
  return `
    <div class="detail-empty">
      <p>Кликните посадку или отклонённое место на карте, чтобы увидеть норму, по которой
         принято решение. Колесо - масштаб, перетаскивание - панорама.</p>
    </div>
    <h2 class="detail-heading">Состав плана · ${total}</h2>
    <ul class="composition">
      ${rows.map((row) => `
        <li>
          <span class="composition-bar" style="--share: ${(row.count / total * 100).toFixed(1)}%"></span>
          <span class="composition-name">${escape(row.name)}</span>
          <span class="composition-count">${row.count}</span>
        </li>`).join('')}
    </ul>`;
}

function checksBlock(checks) {
  if (!checks.length) return '<p class="hint detail-heading">Проверенных правил не записано.</p>';
  const { binding, measured, absent } = splitChecks(checks);
  const parts = [];
  if (binding.length) {
    parts.push(
      `<h2 class="detail-heading">Ограничивают решение</h2>
       <ul class="checks">${binding.map(checkRow).join('')}</ul>`);
  }
  if (measured.length) {
    parts.push(
      `<h2 class="detail-heading">Отступы выдержаны, от ближайшего</h2>
       <ul class="checks">${measured.map(checkRow).join('')}</ul>`);
  }
  if (absent.length) {
    parts.push(
      `<details class="detail-full">
         <summary>Ещё ${absent.length} норм проверено: таких объектов в чертеже нет</summary>
         <ul class="checks" style="margin-top:12px">${absent.map(checkRow).join('')}</ul>
       </details>`);
  }
  return parts.join('');
}

function showDetail(item) {
  if (!item) {
    detail.innerHTML = composition();
    return;
  }
  const checks = item.checks || [];
  const title = item.kind === 'placement'
    ? `№ ${escape(item.number)}. ${escape(item.species_ru || 'вид не назначен')}`
    : `Отказ № ${escape(item.number)}`;
  const kind = KIND_RU[item.planting_type] || '';
  const verdict = VERDICT_RU[item.verdict] || item.verdict;
  detail.innerHTML = `
    <h3>${title}</h3>
    ${item.species_lat ? `<p class="detail-lat">${escape(item.species_lat)}</p>` : ''}
    <span class="verdict verdict-${escape(item.verdict)}">${escape(verdict)}</span>
    <p class="hint mono">${kind ? escape(kind) + ', ' : ''}x ${item.x.toFixed(2)}, y ${item.y.toFixed(2)}</p>
    ${item.note ? `<p class="detail-explain">${escape(item.note)}</p>` : ''}
    ${checksBlock(checks)}
    ${item.explanation
      ? `<details class="detail-full">
           <summary>Объяснение целиком, как в выгрузке</summary>
           <p class="detail-explain">${escape(item.explanation)}</p>
         </details>`
      : ''}`;
}

/* ---------- ввод ---------- */

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
  item.note = result.note;
  if (state.selected === item) showDetail(item);
  schedule();
}

/* ---------- ввод ---------- */

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
    if (!dragging) return;
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

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Delete' || !state.editing) return;
    if (state.selected?.kind !== 'placement') return;
    event.preventDefault();
    commitDelete(state.selected);
  });

  canvas.addEventListener('wheel', (event) => {
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    const factor = Math.exp(-event.deltaY * 0.0015);
    const next = Math.min(Math.max(state.scale * factor, 0.002), 400);
    const applied = next / state.scale;
    state.tx = px - (px - state.tx) * applied;
    state.ty = py - (py - state.ty) * applied;
    state.scale = next;
    schedule();
  }, { passive: false });

  const zoomBy = (factor) => {
    const rect = canvas.getBoundingClientRect();
    const px = rect.width / 2;
    const py = rect.height / 2;
    const next = Math.min(Math.max(state.scale * factor, 0.002), 400);
    const applied = next / state.scale;
    state.tx = px - (px - state.tx) * applied;
    state.ty = py - (py - state.ty) * applied;
    state.scale = next;
    schedule();
  };
  document.getElementById('zoom-in')?.addEventListener('click', () => zoomBy(1.4));
  document.getElementById('zoom-out')?.addEventListener('click', () => zoomBy(1 / 1.4));
  document.getElementById('fit')?.addEventListener('click', () => { fitToBbox(); schedule(); });

  document.getElementById('layer-toggles')?.addEventListener('change', (event) => {
    const input = event.target;
    if (!input.dataset.layer) return;
    state.visible[input.dataset.layer] = input.checked;
    schedule();
  });

  const editToggle = document.getElementById('edit-toggle');
  editToggle?.addEventListener('change', () => {
    state.editing = editToggle.checked;
    canvas.classList.toggle('editable', state.editing);
    say(state.editing
      ? 'Правка включена: тяните посадку мышью, Delete удаляет выбранную.'
      : 'Правка выключена.');
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

  window.addEventListener('resize', resize);
  // Тема меняет цвета, взятые из CSS-переменных: карту надо перерисовать.
  new MutationObserver(schedule).observe(document.documentElement, {
    attributes: true, attributeFilter: ['data-theme'],
  });
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', schedule);
}

/* ---------- запуск ---------- */

async function mount() {
  try {
    const [basemap, plan, rules] = await Promise.all([
      loadJson('basemap.geojson'),
      loadJson('plan.json'),
      loadJson('rules.json'),
    ]);

    state.rules = rules.rules || {};
    state.buckets = buildBuckets(basemap.features || []);
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

    loading.hidden = true;
    resize();
    fitToBbox();
    bindInput();
    showDetail(null);
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

// Монтируем карту только у завершённого прогона: канва есть всегда (под ней лежит
// блок статуса), но артефактов до конца прогона ещё нет.
if (canvas && RUN_ID && document.querySelector(".page-run")?.dataset.state === "succeeded") {
  mount();
}
