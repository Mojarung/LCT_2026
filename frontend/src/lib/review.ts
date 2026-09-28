/* Уточнение объектов чертежа: разбор артефактов проверки и сборка JSON для повторного прогона.
 *
 * Перенос static/review.js тиммейта без изменения логики. Страница только толкует вход: всё,
 * что назначил человек, живёт в браузере до скачивания JSON, сервер о назначениях не знает.
 * Повторный прогон с этим JSON и есть единственный способ, которым уточнение попадает в план. */

import type { Geometry } from '../api/artifacts';

/** Объект подосновы в геометрии проверки: координаты местные, в метрах, без упрощения. */
export interface ReviewFeature {
  id: string;
  geometry: Geometry;
  properties: {
    /** Номер группы в classification.json (слой, блок, тип геометрии, класс, основание). */
    group: number;
    class: string;
    error_m: number | null;
    source_entity_type?: string | null;
    bounds: number[];
  };
}

export interface ReviewLabel {
  id: string;
  layer: string;
  block?: string | null;
  block_chain?: string[] | null;
  x: number;
  y: number;
  text: string;
  surface_role: string;
  evidence?: { method: string } | null;
}

/** semantic-review.geojson: геометрия и подписи того самого DXF, по которому считали. */
export interface ReviewGeometry {
  source_sha256: string;
  features: ReviewFeature[];
  labels?: ReviewLabel[];
}

export interface ReviewGroup {
  layer: string;
  block: string | null;
  geometry: string;
  object_class: string;
  evidence: { method: string };
  features: number;
}

/** classification.json: группы объектов с классом и основанием классификации. */
export interface ClassificationJson {
  source_sha256: string;
  ready?: boolean;
  groups: ReviewGroup[];
}

export const UNKNOWN: ReadonlySet<string> = new Set(['unknown', 'utility.unknown']);

export const LABEL_ROLES: Record<string, string> = {
  auto: 'по тексту и контексту',
  ignore: 'не использовать для покрытия',
  soil: 'грунт / газон',
  paved: 'твёрдое покрытие',
};

/** Классы в порядке ObjectClass сервиса. Неизвестные человек назначить не может: смысл
 *  уточнения - как раз убрать их. */
export const CLASS_NAMES: Record<string, string> = {
  'utility.water': 'Водопровод',
  'utility.sewer': 'Канализация',
  'utility.storm': 'Водосток',
  'utility.drain': 'Дренаж',
  'utility.heat': 'Теплосеть',
  'utility.gas': 'Газопровод',
  'utility.power_cable': 'Силовой кабель',
  'utility.telecom': 'Кабель связи',
  'utility.unknown': 'Неуточнённая сеть',
  'utility.access': 'Люк, колодец, решётка',
  power_line_overhead: 'Воздушная линия',
  pole: 'Опора',
  curb: 'Бортовой камень',
  pavement_edge: 'Граница покрытия',
  fence: 'Ограда',
  road: 'Проезжая часть',
  sidewalk: 'Тротуар',
  tram: 'Трамвайные пути',
  railway: 'Железная дорога',
  building: 'Здание',
  structure: 'Сооружение',
  slope: 'Откос',
  work_boundary: 'Граница работ',
  existing_tree: 'Существующее дерево',
  existing_shrub: 'Существующий кустарник',
  existing_woodland: 'Древесный массив',
  obstacle: 'Препятствие',
  lawn: 'Газон / грунт для выбранной стадии',
  contour: 'Контур между покрытиями',
  ignore: 'Оформление, вне расчёта',
  unknown: 'Неизвестно',
};

export const ASSIGNABLE: readonly string[] = Object.keys(CLASS_NAMES).filter(
  (kind) => !UNKNOWN.has(kind),
);

export const className = (kind: string): string => CLASS_NAMES[kind] ?? kind;

const EVIDENCE_NAMES: Record<string, string> = {
  unmatched: 'имя не распознано',
  conflict: 'правила противоречат',
  material_context: 'нужно уточнить материал и стадию работ',
  name_rule: 'совпало правило имени',
  explicit_feature: 'объект уточнён',
  explicit_layer: 'слой уточнён',
  explicit_block: 'блок уточнён',
  annotation_label: 'подпись оформления',
  explicit_label: 'роль подписи уточнена',
  symbol_assumed: 'незнакомый условный знак принят за препятствие',
};

const ASSUMED: Record<string, string> = {
  point: 'точка',
  sheet_frame: 'рамка листа',
  small_circle: 'малый круг',
  contour: 'контур',
};

/** Основание классификации словами. Сервис пишет и составные основания («по слову имени»,
 *  «знак с кодом»): их тоже надо прочесть человеку, а не выдать сырую строку. */
export function evidenceName(method: string | undefined | null): string {
  if (!method) return 'не уточнено';
  const known = EVIDENCE_NAMES[method];
  if (known) return known;
  const [head = '', tail = ''] = method.split(':', 2);
  if (head.startsWith('inferred_') && tail) return `выведено по слову «${tail}» в имени`;
  if (head === 'assumed_geometry') return `замена по геометрии: ${ASSUMED[tail] ?? tail}`;
  if (head === 'symbol_stroke') return `штрих условного знака ${tail}`;
  if (head === 'symbol_geometry') return `условный знак ${tail}`;
  if (head === 'symbol_unknown') return `незнакомый условный знак ${tail}`;
  return method;
}

/** Индексы объектов по группам classification.json. */
export function groupMembers(data: ReviewGeometry, groups: number): number[][] {
  const members: number[][] = Array.from({ length: groups }, () => []);
  data.features.forEach((feature, index) => {
    members[feature.properties.group]?.push(index);
  });
  return members;
}

/** Порядок групп в списке: сначала неизвестные - ради них страницу и открывают. */
export function groupOrder(report: ClassificationJson): number[] {
  return report.groups
    .map((group, index) => ({ unknown: UNKNOWN.has(group.object_class), index }))
    .sort((a, b) => Number(b.unknown) - Number(a.unknown))
    .map((entry) => entry.index);
}

/** Выбранные объекты группы: 0 - вся группа, N - N-й объект, пусто или мимо - ничего. */
export function selectedIndices(members: readonly number[], objectValue: string): number[] {
  if (objectValue.trim() === '') return [];
  const n = Number(objectValue);
  if (n === 0) return [...members];
  const one = Number.isInteger(n) && n > 0 && n <= members.length ? members[n - 1] : undefined;
  return one === undefined ? [] : [one];
}

/** Выбранная подпись: номер на карте с единицы, 0 и мимо - нет подписи. */
export function selectedLabel(data: ReviewGeometry, labelValue: string): ReviewLabel | null {
  const n = Number(labelValue);
  return Number.isInteger(n) && n > 0 ? (data.labels?.[n - 1] ?? null) : null;
}

export type Box = [number, number, number, number];

export function boundsOf(data: ReviewGeometry, indices: readonly number[]): Box {
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const index of indices) {
    const box = data.features[index]?.properties.bounds;
    if (box?.length !== 4) continue;
    const [bx0 = 0, by0 = 0, bx1 = 0, by1 = 0] = box;
    x0 = Math.min(x0, bx0);
    y0 = Math.min(y0, by0);
    x1 = Math.max(x1, bx1);
    y1 = Math.max(y1, by1);
  }
  return Number.isFinite(x0) ? [x0, y0, x1, y1] : [0, 0, 1, 1];
}

export function unresolvedCount(
  data: ReviewGeometry,
  assignments: Readonly<Record<string, string>>,
): number {
  return data.features.filter((f) => UNKNOWN.has(assignments[f.id] ?? f.properties.class)).length;
}

/** JSON уточнений для повторного прогона. Несмысловые параметры прогона сохраняются, широкие
 *  назначения слоёв и блоков заменяются точными ссылками на объекты: уточнение привязано к
 *  этому самому DXF через его хеш. */
export function reviewJson(
  overrides: Readonly<Record<string, unknown>>,
  data: ReviewGeometry,
  report: ClassificationJson,
  assignments: Readonly<Record<string, string>>,
  labelAssignments: Readonly<Record<string, string>>,
): string {
  const values: Record<string, unknown> = { ...overrides };
  delete values.layer_classes;
  delete values.block_classes;
  delete values.feature_classes;
  delete values.label_roles;
  const explicit: Record<string, string> = {};
  for (const feature of data.features) {
    const method = report.groups[feature.properties.group]?.evidence.method ?? '';
    if (method.startsWith('explicit_')) explicit[feature.id] = feature.properties.class;
  }
  values.feature_classes = { ...explicit, ...assignments };
  const explicitLabels: Record<string, string> = {};
  for (const label of data.labels ?? []) {
    if (label.evidence?.method === 'explicit_label') explicitLabels[label.id] = label.surface_role;
  }
  values.label_roles = { ...explicitLabels, ...labelAssignments };
  values.semantic_source_sha256 = data.source_sha256;
  values.require_known_objects = true;
  return `${JSON.stringify(values, null, 2)}\n`;
}
