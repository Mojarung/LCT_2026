/* Input interpretation only. Everything stays in this browser until JSON download. */
const root = document.querySelector('.input-review');
const id = root.dataset.runId;
const $ = name => document.getElementById(`review-${name}`);
const canvas = $('canvas'), ctx = canvas.getContext('2d');
let data, report, record, groups, paths, groupPaths, assignments = {}, labelAssignments = {};
let layerAssignments = {}, layerSummary = new Map();
let view = { x: 0, y: 0, scale: 1 }, drawing = false, drag;
const UNKNOWN = new Set(['unknown', 'utility.unknown']);
const LARGE_REVIEW_FEATURES = 50000;
const LABEL_ROLES = {auto: 'по тексту и контексту', ignore: 'не использовать для покрытия', soil: 'грунт / газон', paved: 'твёрдое покрытие'};
const EVIDENCE_NAMES = {
  unmatched: 'имя не распознано', conflict: 'правила противоречат друг другу',
  material_context: 'требуется уточнить материал и стадию работ', name_rule: 'совпало правило имени',
  explicit_feature: 'объект уточнён', explicit_layer: 'слой уточнён', explicit_block: 'блок уточнён',
  annotation_label: 'подпись оформления', explicit_label: 'роль подписи уточнена',
  entity_type: 'тип чертёжной маски',
  bounded_unreadable_geometry: 'неоднозначный объект ограничен неизвестной областью',
  raster_review_required: 'содержимое внешнего растра не прочитано',
};
const CLASS_NAMES = {
  'utility.water': 'Водопровод', 'utility.sewer': 'Канализация',
  'utility.storm': 'Водосток', 'utility.drain': 'Дренаж', 'utility.heat': 'Теплосеть',
  'utility.gas': 'Газопровод', 'utility.power_cable': 'Силовой кабель',
  'utility.telecom': 'Кабель связи', 'utility.access': 'Люк, колодец, решётка',
  power_line_overhead: 'Воздушная линия', pole: 'Опора', curb: 'Бортовой камень',
  pavement_edge: 'Граница покрытия', fence: 'Ограда', road: 'Проезжая часть',
  sidewalk: 'Тротуар', tram: 'Трамвай', railway: 'Железная дорога', building: 'Здание',
  structure: 'Сооружение', slope: 'Откос', work_boundary: 'Граница работ',
  existing_tree: 'Существующее дерево', existing_shrub: 'Существующий кустарник',
  lawn: 'Газон / грунт для выбранной стадии', ignore: 'Оформление — исключить из расчёта',
  drawing_mask: 'Маска чертежа — неизвестная поверхность',
  uncertain_area: 'Непрочитанная область — посадка запрещена',
  unknown: 'Неизвестно', 'utility.unknown': 'Неуточнённая сеть',
};
for (const select of [$('class'), $('layer-class')]) {
  for (const option of select.options) {
    if (option.value) option.textContent = CLASS_NAMES[option.value] || option.value;
  }
}

async function json(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Не удалось получить данные (${response.status})`);
  return response.json();
}
function pathOf(geometry, path = new Path2D()) {
  const line = (coordinates, closed) => {
    coordinates.forEach(([x, y], index) => index ? path.lineTo(x, y) : path.moveTo(x, y));
    if (closed) path.closePath();
  };
  switch (geometry.type) {
    case 'Point': {
      const [x, y] = geometry.coordinates;
      path.moveTo(x + .2, y); path.arc(x, y, .2, 0, Math.PI * 2); break;
    }
    case 'MultiPoint': geometry.coordinates.forEach(c => pathOf({type: 'Point', coordinates: c}, path)); break;
    case 'LineString': line(geometry.coordinates, false); break;
    case 'MultiLineString': geometry.coordinates.forEach(c => line(c, false)); break;
    case 'Polygon': geometry.coordinates.forEach(c => line(c, true)); break;
    case 'MultiPolygon': geometry.coordinates.forEach(p => p.forEach(c => line(c, true))); break;
    case 'GeometryCollection': geometry.geometries.forEach(g => pathOf(g, path)); break;
  }
  return path;
}
function members() { return groups[Number($('group').value)] || []; }
function selected() {
  const indices = members(), n = Number($('object').value);
  if ($('object').value.trim() === '') return [];
  if (n === 0) return indices;
  return Number.isInteger(n) && n > 0 && n <= indices.length ? [indices[n - 1]] : [];
}
function selectedLabel() {
  const n = Number($('label-index').value);
  return Number.isInteger(n) && n > 0 ? data.labels?.[n - 1] : null;
}
function bounds(indices) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const i of indices) {
    const b = data.features[i].properties.bounds;
    if (b.length !== 4) continue;
    x0 = Math.min(x0, b[0]); y0 = Math.min(y0, b[1]);
    x1 = Math.max(x1, b[2]); y1 = Math.max(y1, b[3]);
  }
  return Number.isFinite(x0) ? [x0, y0, x1, y1] : [0, 0, 1, 1];
}
function fit(indices) {
  const [x0, y0, x1, y1] = bounds(indices), rect = canvas.getBoundingClientRect();
  view = {x: (x0 + x1) / 2, y: (y0 + y1) / 2,
          scale: .88 * Math.min(rect.width / Math.max(x1 - x0, 1), rect.height / Math.max(y1 - y0, 1))};
  draw();
}
function draw() {
  if (drawing || !data) return;
  drawing = true;
  requestAnimationFrame(() => {
    drawing = false;
    const rect = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(rect.width * dpr));
    canvas.height = Math.max(1, Math.round(rect.height * dpr));
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.setTransform(view.scale * dpr, 0, 0, -view.scale * dpr,
      (rect.width / 2 - view.x * view.scale) * dpr, (rect.height / 2 + view.y * view.scale) * dpr);
    ctx.strokeStyle = '#82918b'; ctx.lineWidth = .65 / view.scale;
    groupPaths.forEach(path => ctx.stroke(path));
    const current = Number($('group').value);
    ctx.strokeStyle = '#b66100'; ctx.lineWidth = 1.8 / view.scale;
    if (groupPaths[current]) ctx.stroke(groupPaths[current]);
    if (Number($('object').value) > 0) {
      ctx.strokeStyle = '#c41c2e'; ctx.lineWidth = 3 / view.scale;
      selected().forEach(i => ctx.stroke(paths[i]));
    }
    if ($('labels-visible').checked) {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.font = '11px sans-serif';
      const selectedText = selectedLabel();
      (data.labels || []).forEach((label, i) => {
        if (!Number.isFinite(label.x) || !Number.isFinite(label.y)) return;
        const x = rect.width / 2 + (label.x - view.x) * view.scale;
        const y = rect.height / 2 - (label.y - view.y) * view.scale;
        if (x < 0 || y < 0 || x > rect.width || y > rect.height) return;
        ctx.fillStyle = selectedText === label ? '#173eca' : '#384f43';
        ctx.fillText(`${i + 1}: ${label.text.slice(0, 80)}`, x + 4, y - 4);
      });
    }
  });
}
function refresh() {
  const indices = selected(), group = report.groups[Number($('group').value)];
  $('object').max = members().length;
  $('evidence').textContent = group ? `${group.layer} / ${group.block || 'без блока'} / ${group.geometry}. Основание: ${EVIDENCE_NAMES[group.evidence.method] || group.evidence.method}. ${typeof group.work_intersections !== 'number' ? 'Пересечение с границей работ не измерено.' : `Пересекают границу работ: ${group.work_intersections} из ${group.features}.`}` : 'Геометрических объектов нет.';
  const current = indices.length === 1 ? data.features[indices[0]] : null;
  $('detail').textContent = current
    ? `${current.id}\nОбъект DXF: ${current.properties.source_entity_type || 'тип не сохранён'}\nКласс: ${CLASS_NAMES[assignments[current.id] || layerAssignments[report.groups[current.properties.group].layer] || current.properties.class]}\nГраницы, м: ${current.properties.bounds.join(', ')}\n${current.properties.source_entity_type === 'IMAGE' ? 'Содержимое внешнего растра не прочитано. Исключайте только после проверки изображения и полноты векторных данных.' : (current.properties.uncertain_footprint ? 'Внутри ограничивающей области материал не подтверждён; назначение класса недоступно.' : `Резерв геометрии, м: ${current.properties.error_m}`)}`
    : `Выбрано объектов: ${indices.length}. Назначение применяется ко всем выбранным объектам.`;
  let unresolved = 0;
  for (const f of data.features) if (UNKNOWN.has(assignments[f.id] || layerAssignments[report.groups[f.properties.group].layer] || f.properties.class)) unresolved++;
  $('status').textContent = `Объектов: ${data.features.length}. Не уточнено: ${unresolved}.${typeof report.unresolved_work_intersections !== 'number' ? '' : ` Изначально не уточнено в границе работ: ${report.unresolved_work_intersections}.`} Ваших назначений: ${Object.keys(assignments).length}.`;
  $('assign').textContent = `Назначить класс (${indices.length} объектов)`;
  const readOnly = indices.some(i => data.features[i].properties.read_only);
  const includesRaster = indices.some(i => data.features[i].properties.source_entity_type === 'IMAGE');
  for (const option of $('class').options) option.disabled = includesRaster && option.value !== '' && option.value !== 'ignore';
  if (includesRaster && $('class').value !== 'ignore') $('class').value = '';
  $('assign').disabled = !indices.length || readOnly;
  $('reset').disabled = !indices.length || readOnly;
  const label = selectedLabel();
  $('label-assign').disabled = !label;
  $('label-reset').disabled = !label;
  $('label-detail').textContent = label
    ? `${label.text}\n${label.id}\n${label.layer}\n${(label.block_chain || []).join(' / ')}\nРоль: ${LABEL_ROLES[labelAssignments[label.id] || label.surface_role]}. Основание: ${labelAssignments[label.id] ? 'назначено вами' : (EVIDENCE_NAMES[label.evidence?.method] || label.evidence?.method || 'не уточнено')}.`
    : `Подписей: ${(data.labels || []).length}. На карте показаны номер и первые 80 символов; здесь — полный текст выбранной подписи.`;
  if (!$('output-label').hidden) $('output').value = reviewJSON();
  draw();
}
function summaryJSON() {
  const values = {...record.overrides};
  values.layer_classes = {...(values.layer_classes || {}), ...layerAssignments};
  values.semantic_source_sha256 = report.source_sha256;
  values.require_known_objects = true;
  return JSON.stringify(values, null, 2) + '\n';
}
function refreshLayer() {
  const layer = $('layer').value, info = layerSummary.get(layer);
  if (!info) return;
  const currentClass = layerAssignments[layer] || record.overrides.layer_classes?.[layer];
  const priorExact = Object.keys(record.overrides.feature_classes || {}).length > 0 ||
    Object.keys(record.overrides.block_classes || {}).length > 0;
  const reason = info.locked ? 'Слой содержит маску, неоднозначную область или растр: используйте подробную карту и точечное уточнение.'
    : (priorExact ? 'В исходных параметрах есть назначения блоков или отдельных объектов с более высоким приоритетом. Используйте подробную карту.' : 'Назначайте весь слой только после проверки исходника и легенды.');
  $('layer-detail').textContent = `Всего: ${info.features}; не уточнено: ${info.unknown}; ${info.measured ? `не уточнено в границе работ: ${info.work}` : 'граница работ не определена'}. ${currentClass ? `Класс в параметрах: ${CLASS_NAMES[currentClass] || currentClass}. ` : ''}${reason}`;
  $('layer-assign').disabled = info.locked || priorExact;
  $('layer-reset').disabled = !layerAssignments[layer];
}
function setupSummary() {
  layerSummary = new Map();
  for (const group of report.groups) {
    if (!layerSummary.has(group.layer)) layerSummary.set(group.layer, {
      features: 0, unknown: 0, work: 0, measured: report.work_boundary_present,
      locked: false,
    });
    const info = layerSummary.get(group.layer);
    info.features += group.features;
    if (UNKNOWN.has(group.object_class)) {
      info.unknown += group.features;
      info.work += group.work_intersections || 0;
    }
    info.locked ||= ['uncertain_area', 'drawing_mask'].includes(group.object_class) || group.evidence.method === 'raster_review_required';
  }
  [...layerSummary].sort((a, b) =>
    Number(b[1].unknown > 0) - Number(a[1].unknown > 0) ||
    b[1].work - a[1].work || b[1].unknown - a[1].unknown
  ).forEach(([name, info]) => {
    const option = document.createElement('option'); option.value = name;
    option.textContent = `${name} · не уточнено ${info.unknown}${info.measured ? ` · в работах ${info.work}` : ''}`;
    $('layer').append(option);
  });
  $('layer-summary').hidden = false;
  $('map-placeholder').hidden = false;
  $('status').textContent = `Объектов: ${report.features}. Не уточнено: ${report.unresolved_features}. Подробная карта большого чертежа пока не загружена.`;
  $('show').disabled = false; $('download').disabled = false;
  refreshLayer();
}
$('layer').addEventListener('change', refreshLayer);
$('layer-assign').addEventListener('click', () => {
  const layer = $('layer').value, kind = $('layer-class').value;
  if (!kind || !layer || $('layer-assign').disabled) return;
  layerAssignments[layer] = kind;
  refreshLayer();
  if (!$('output-label').hidden) $('output').value = reviewJSON();
  if (data) refresh();
});
$('layer-reset').addEventListener('click', () => {
  delete layerAssignments[$('layer').value];
  refreshLayer();
  if (!$('output-label').hidden) $('output').value = reviewJSON();
  if (data) refresh();
});
$('group').addEventListener('change', () => { $('object').value = 0; refresh(); fit(selected()); });
$('object').addEventListener('input', refresh);
$('object').addEventListener('change', () => {
  refresh(); if (selected().length) fit(selected());
});
$('assign').addEventListener('click', () => {
  const kind = $('class').value;
  if (!kind) return;
  if (kind !== 'ignore' && selected().some(i => data.features[i].properties.source_entity_type === 'IMAGE')) return;
  selected().forEach(i => { assignments[data.features[i].id] = kind; }); refresh();
});
$('reset').addEventListener('click', () => {
  selected().forEach(i => { delete assignments[data.features[i].id]; }); refresh();
});
$('labels-visible').addEventListener('change', draw);
$('label-index').addEventListener('input', refresh);
$('label-index').addEventListener('change', () => {
  const label = selectedLabel();
  if (label && Number.isFinite(label.x) && Number.isFinite(label.y)) {
    view.x = label.x; view.y = label.y;
    view.scale = Math.max(view.scale, canvas.getBoundingClientRect().width / 60); draw();
  }
});
$('label-assign').addEventListener('click', () => {
  const label = selectedLabel();
  if (label) labelAssignments[label.id] = $('label-role').value;
  refresh();
});
$('label-reset').addEventListener('click', () => {
  const label = selectedLabel();
  if (label) delete labelAssignments[label.id];
  refresh();
});
function reviewJSON() {
  if (!data) return summaryJSON();
  // Preserve non-semantic parameters. Exact refs replace broad layer/block maps.
  const values = {...record.overrides};
  delete values.layer_classes; delete values.block_classes; delete values.feature_classes;
  delete values.label_roles;
  const explicit = {};
  for (const f of data.features) {
    const group = report.groups[f.properties.group];
    if (group.evidence.method.startsWith('explicit_') && !layerAssignments[group.layer]) explicit[f.id] = f.properties.class;
  }
  values.layer_classes = {...layerAssignments};
  values.feature_classes = {...explicit, ...assignments};
  const explicitLabels = {};
  for (const label of data.labels || []) {
    if (label.evidence?.method === 'explicit_label') explicitLabels[label.id] = label.surface_role;
  }
  values.label_roles = {...explicitLabels, ...labelAssignments};
  values.semantic_source_sha256 = data.source_sha256;
  values.require_known_objects = true;
  return JSON.stringify(values, null, 2) + '\n';
}
$('show').addEventListener('click', () => {
  $('output').value = reviewJSON(); $('output-label').hidden = false;
});
$('download').addEventListener('click', () => {
  const blob = new Blob([reviewJSON()], {type: 'application/json'});
  const url = URL.createObjectURL(blob), anchor = document.createElement('a');
  anchor.href = url; anchor.download = 'input-review-overrides.json'; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$('fit').addEventListener('click', () => data && fit(data.features.map((_, i) => i)));
$('fit-group').addEventListener('click', () => data && fit(selected()));
for (const [name, factor] of [['minus', 1 / 1.5], ['plus', 1.5]]) {
  $(name).addEventListener('click', () => { view.scale = Math.max(1e-7, Math.min(1e7, view.scale * factor)); draw(); });
}
canvas.addEventListener('pointerdown', e => { drag = {x: e.clientX, y: e.clientY}; canvas.setPointerCapture(e.pointerId); });
canvas.addEventListener('pointerup', () => { drag = null; });
canvas.addEventListener('pointercancel', () => { drag = null; });
canvas.addEventListener('pointermove', e => {
  if (!drag) return;
  view.x -= (e.clientX - drag.x) / view.scale; view.y += (e.clientY - drag.y) / view.scale;
  drag = {x: e.clientX, y: e.clientY}; draw();
});
canvas.addEventListener('wheel', e => {
  e.preventDefault();
  const rect = canvas.getBoundingClientRect(), x = e.clientX - rect.left - rect.width / 2;
  const y = e.clientY - rect.top - rect.height / 2, old = view.scale;
  view.scale = Math.max(1e-7, Math.min(1e7, old * Math.exp(-e.deltaY * .001)));
  view.x += x / old - x / view.scale; view.y -= y / old - y / view.scale; draw();
}, {passive: false});
new ResizeObserver(draw).observe(canvas);

async function loadMap() {
  data = await json(`/api/v1/runs/${id}/artifacts/semantic-review.geojson`);
  if (data.source_sha256 !== report.source_sha256) throw new Error('Геометрия и отчёт относятся к разным исходникам.');
  groups = report.groups.map(() => []);
  paths = data.features.map((f, i) => { groups[f.properties.group].push(i); return pathOf(f.geometry); });
  groupPaths = groups.map(indices => { const path = new Path2D(); indices.forEach(i => path.addPath(paths[i])); return path; });
  report.groups.map((g, i) => ({g, i})).sort((a, b) =>
    Number(UNKNOWN.has(b.g.object_class)) - Number(UNKNOWN.has(a.g.object_class)) ||
    (b.g.work_intersections ?? b.g.features) - (a.g.work_intersections ?? a.g.features) ||
    b.g.features - a.g.features
  ).forEach(({g, i}) => {
    const option = document.createElement('option'); option.value = i;
    option.textContent = `${g.layer} · ${g.geometry} · ${g.features}${typeof g.work_intersections !== 'number' ? '' : ` · в работах ${g.work_intersections}`} · ${CLASS_NAMES[g.object_class]}`;
    $('group').append(option);
  });
  for (const name of ['group', 'object', 'assign', 'reset']) $(name).disabled = !data.features.length;
  for (const name of ['show', 'download']) $(name).disabled = !data.features.length && !data.labels?.length;
  $('label-index').disabled = !data.labels?.length;
  $('label-index').max = data.labels?.length || 0;
  refresh(); fit(selected());
  $('map-placeholder').hidden = true;
  $('load-map').disabled = true;
}
$('load-map').addEventListener('click', async () => {
  $('load-map').disabled = true;
  $('status').textContent = 'Загружаем полную геометрию чертежа…';
  try { await loadMap(); }
  catch (error) { $('status').textContent = error.message; $('load-map').disabled = false; }
});
try {
  const base = `/api/v1/runs/${id}`;
  [report, record] = await Promise.all([
    json(`${base}/artifacts/classification.json`), json(base),
  ]);
  if (report.features > LARGE_REVIEW_FEATURES) setupSummary();
  else await loadMap();
} catch (error) { $('status').textContent = error.message; }
