/* Размерные выноски у выбранной посадки, как на слайде «Объяснение»: от ствола до ближайшего
 * объекта каждой нормы, которая реально решала, с подписью «борт 2,00 ≥ 2,00». Число в
 * подписи - то, что намерил сервис (до наружной стенки сети, с её диаметром); линия ведёт к
 * ближайшей точке объекта на подоснове карты. Подоснова упрощена на сантиметры, поэтому
 * длина линии может разойтись с подписью на эту величину - решает подпись. */

import type { BasemapFeature, Geometry, Position, RuleCheck } from '../api/artifacts';
import type { MapItem, ViewState } from './types';
import { toScreen } from './view';

/** Выносок не больше этого: на слайде их четыре, больше - и они закрывают саму крону. */
const MAX_DIMENSIONS = 4;
/** Норма показывается, если запас меньше этого множителя: дальние объекты проверены и молчат. */
const TIGHT = 2.5;
/** Дальше этого выноска не рисуется: линия через пол-улицы не объясняет, а мешает. */
const MAX_REACH_M = 20;

/** Короткие имена объектов для подписи на карте: полное родительное - в панели. */
const SHORT: Record<string, string> = {
  building: 'здание',
  structure: 'сооружение',
  road: 'проезжая часть',
  curb: 'борт',
  sidewalk: 'тротуар',
  pavement_edge: 'покрытие',
  tram: 'трамвай',
  railway: 'ж/д',
  slope: 'откос',
  pole: 'опора',
  fence: 'ограда',
  'utility.water': 'водопровод',
  'utility.sewer': 'канализация',
  'utility.storm': 'ливнёвка',
  'utility.drain': 'дренаж',
  'utility.heat': 'теплосеть',
  'utility.gas': 'газ',
  'utility.power_cable': 'силовой кабель',
  'utility.telecom': 'связь',
  'utility.unknown': 'сеть',
  'utility.access': 'колодец',
  power_line_overhead: 'ВЛ',
  existing_tree: 'дерево',
  existing_shrub: 'кустарник',
};

/** Цвета подписей со слайда: покрытия и борт - синие, сети - бирюзовые, здания и прочее -
 *  янтарные, нарушение нормы - малиновое. Одинаковые в обеих темах: это чертёжные выноски,
 *  а не элементы интерфейса. */
const TONES = {
  surface: { fill: '#3b7dd8', text: '#ffffff' },
  utility: { fill: '#2f8a82', text: '#ffffff' },
  other: { fill: '#e8b33c', text: '#2b2620' },
  fail: { fill: '#d6336c', text: '#ffffff' },
} as const;

type Tone = keyof typeof TONES;

export interface Dimension {
  /** Ближайшая точка объекта, координаты чертежа. */
  to: [number, number];
  label: string;
  tone: Tone;
}

/** Геометрия подосновы по классам: плоские ломаные [x0, y0, x1, y1, ...] и точки. */
export class ClassIndex {
  private readonly lines = new Map<string, Float64Array[]>();

  constructor(features: readonly BasemapFeature[]) {
    for (const feature of features) {
      const cls = feature.properties.class;
      if (!(cls in SHORT)) continue;
      let list = this.lines.get(cls);
      if (!list) {
        list = [];
        this.lines.set(cls, list);
      }
      collect(feature.geometry, list);
    }
  }

  /** Ближайшая точка объектов класса к (x, y) не дальше within или null. */
  nearest(cls: string, x: number, y: number, within: number): [number, number] | null {
    const list = this.lines.get(cls);
    if (!list) return null;
    let best = within * within;
    let found: [number, number] | null = null;
    for (const line of list) {
      if (line.length === 2) {
        const d = ((line[0] ?? 0) - x) ** 2 + ((line[1] ?? 0) - y) ** 2;
        if (d < best) {
          best = d;
          found = [line[0] ?? 0, line[1] ?? 0];
        }
        continue;
      }
      for (let i = 0; i + 3 < line.length; i += 2) {
        const ax = line[i] ?? 0;
        const ay = line[i + 1] ?? 0;
        const bx = line[i + 2] ?? 0;
        const by = line[i + 3] ?? 0;
        const dx = bx - ax;
        const dy = by - ay;
        const len = dx * dx + dy * dy;
        const t = len ? Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / len)) : 0;
        const px = ax + dx * t;
        const py = ay + dy * t;
        const d = (px - x) ** 2 + (py - y) ** 2;
        if (d < best) {
          best = d;
          found = [px, py];
        }
      }
    }
    return found;
  }
}

function collect(geometry: Geometry, out: Float64Array[]): void {
  const flat = (points: Position[]) => {
    const line = new Float64Array(points.length * 2);
    points.forEach(([x, y], i) => {
      line[i * 2] = x;
      line[i * 2 + 1] = y;
    });
    out.push(line);
  };
  switch (geometry.type) {
    case 'Point':
      flat([geometry.coordinates]);
      break;
    case 'MultiPoint':
      for (const point of geometry.coordinates) flat([point]);
      break;
    case 'LineString':
      flat(geometry.coordinates);
      break;
    case 'MultiLineString':
    case 'Polygon':
      for (const ring of geometry.coordinates) flat(ring);
      break;
    case 'MultiPolygon':
      for (const polygon of geometry.coordinates) for (const ring of polygon) flat(ring);
      break;
    case 'GeometryCollection':
      for (const part of geometry.geometries) collect(part, out);
      break;
  }
}

function toneOf(cls: string, check: RuleCheck): Tone {
  if (check.outcome === 'fail') return 'fail';
  if (cls.startsWith('utility.') || cls === 'power_line_overhead') return 'utility';
  if (['curb', 'sidewalk', 'pavement_edge', 'road', 'tram', 'railway'].includes(cls)) {
    return 'surface';
  }
  return 'other';
}

const number = (value: number) => value.toFixed(2).replace('.', ',');

/** Выноски посадки: нормы с наименьшим запасом, у которых на подоснове нашёлся объект. */
export function dimensionsFor(item: MapItem, index: ClassIndex): Dimension[] {
  const tight = item.checks
    .filter(
      (check) =>
        check.object_class &&
        check.measured_m != null &&
        check.threshold_m != null &&
        check.threshold_m > 0 &&
        check.measured_m <= MAX_REACH_M &&
        check.measured_m < check.threshold_m * TIGHT,
    )
    .sort(
      (a, b) =>
        (a.measured_m ?? 0) / (a.threshold_m ?? 1) - (b.measured_m ?? 0) / (b.threshold_m ?? 1),
    );
  const dimensions: Dimension[] = [];
  const seen = new Set<string>();
  for (const check of tight) {
    const cls = check.object_class ?? '';
    if (seen.has(cls)) continue;
    // Сервис мерит до стенки сети, подоснова - это ось: ищем с запасом на половину диаметра.
    const to = index.nearest(cls, item.x, item.y, (check.measured_m ?? 0) + 2);
    if (!to) continue;
    seen.add(cls);
    const measured = check.measured_m ?? 0;
    const threshold = check.threshold_m ?? 0;
    const sign = measured >= threshold ? '≥' : '<';
    dimensions.push({
      to,
      label: `${SHORT[cls] ?? cls} ${number(measured)} ${sign} ${number(threshold)}`,
      tone: toneOf(cls, check),
    });
    if (dimensions.length >= MAX_DIMENSIONS) break;
  }
  return dimensions;
}

/** Выноски в экранных пикселях: линия со стрелкой к объекту, засечка у ствола, плашка
 *  с подписью посередине. Плашки не налезают друг на друга: занятая полоса сдвигает
 *  следующую вниз. */
export function drawDimensions(
  ctx: CanvasRenderingContext2D,
  view: ViewState,
  item: MapItem,
  dimensions: readonly Dimension[],
  font: string,
): void {
  if (!dimensions.length) return;
  const { sx, sy } = toScreen(view, item.x, item.y);
  // Кольцо выбора (render.ts, ring): плашки ставятся за ним, чтобы не лечь на саму крону.
  const clear = Math.max((item.radius || 1) * view.scale, 9) + 16;
  ctx.save();
  ctx.font = `600 12px ${font}`;
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'left';
  ctx.lineCap = 'round';
  const labels: { dimension: Dimension; ax: number; ay: number; right: boolean }[] = [];
  for (const dimension of dimensions) {
    const tone = TONES[dimension.tone];
    const { sx: tx, sy: ty } = toScreen(view, dimension.to[0], dimension.to[1]);
    const length = Math.hypot(tx - sx, ty - sy);
    if (length < 6) continue;
    const ux = (tx - sx) / length;
    const uy = (ty - sy) / length;
    ctx.strokeStyle = tone.fill;
    ctx.fillStyle = tone.fill;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(tx, ty);
    // Засечки поперёк линии на обоих концах, как у размерной линии чертежа.
    for (const [px, py] of [
      [sx, sy],
      [tx, ty],
    ] as const) {
      ctx.moveTo(px - uy * 5, py + ux * 5);
      ctx.lineTo(px + uy * 5, py - ux * 5);
    }
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(tx - ux * 8 - uy * 4, ty - uy * 8 + ux * 4);
    ctx.lineTo(tx - ux * 8 + uy * 4, ty - uy * 8 - ux * 4);
    ctx.closePath();
    ctx.fill();
    const reach = Math.max(length * 0.6, clear);
    labels.push({ dimension, ax: sx + ux * reach, ay: sy + uy * reach, right: ux >= -0.2 });
  }
  // Плашки - вторым проходом, поверх всех линий. Занятое место сдвигает следующую плашку
  // вверх или вниз, попеременно: так они не налезают друг на друга и на кольцо выбора.
  const height = 20;
  const boxes: [number, number, number, number][] = [
    [sx - clear + 6, sy - clear + 6, (clear - 6) * 2, (clear - 6) * 2],
  ];
  for (const { dimension, ax, ay, right } of labels) {
    const tone = TONES[dimension.tone];
    const width = ctx.measureText(dimension.label).width + 14;
    const bx = Math.round(right ? ax + 6 : ax - width - 6);
    let by = Math.round(ay - height / 2);
    for (const shift of [0, 23, -23, 46, -46, 69, -69]) {
      const y = Math.round(ay - height / 2 + shift);
      const hit = boxes.some(
        ([x0, y0, w, h]) => bx < x0 + w && bx + width > x0 && y < y0 + h && y + height > y0,
      );
      by = y;
      if (!hit) break;
    }
    boxes.push([bx, by, width, height]);
    ctx.fillStyle = tone.fill;
    ctx.beginPath();
    ctx.roundRect(bx, by, width, height, 3);
    ctx.fill();
    ctx.fillStyle = tone.text;
    ctx.fillText(dimension.label, bx + 7, by + height / 2 + 0.5);
  }
  ctx.restore();
}
