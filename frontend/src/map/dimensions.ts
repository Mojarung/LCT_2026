/* Размерные выноски у посадки, как на слайде «Объяснение»: от ствола до объекта каждой нормы
 * из списка «Ближе всего к норме» (lib/checks.ts, splitChecks) - тот же список и тот же
 * порядок, что в панели. Раньше у карты был свой порог и свой отбор, и эксперт видел в панели
 * борт, а на карте - кабель (жюри дизайна, итерация 7).
 *
 * Число в подписи - то, что намерил сервис (до наружной стенки сети, с её диаметром); линия
 * ведёт к ближайшей точке объекта этого класса на подоснове карты. Подоснова упрощена на
 * сантиметры, поэтому длина линии может разойтись с подписью на эту величину - решает подпись.
 * Если объекта класса на подоснове нет, выноска - пунктирная окружность радиусом замера:
 * ближайший такой объект где-то на ней. */

import type { BasemapFeature, Geometry, Position, RuleCheck } from '../api/artifacts';
import { splitChecks } from '../lib/checks';
import type { MapItem, ViewState } from './types';
import { toScreen } from './view';

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
  obstacle: 'препятствие',
  'utility.water': 'водопровод',
  'utility.sewer': 'канализация',
  'utility.storm': 'водосток',
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
 *  а не элементы интерфейса. Белый текст 12 px на заливке - не ниже 4,5:1 (WCAG AA): синий
 *  #3b7dd8 и бирюзовый #2f8a82 давали 4,1:1 (жюри по дизайну, итерация 8), сейчас 5,6 и 5,9;
 *  проверка - dimensions.test.ts. */
export const TONES = {
  surface: { fill: '#2d68b8', text: '#ffffff' },
  utility: { fill: '#256f69', text: '#ffffff' },
  other: { fill: '#e8b33c', text: '#2b2620' },
  fail: { fill: '#d6336c', text: '#ffffff' },
} as const;

type Tone = keyof typeof TONES;

export interface Dimension {
  /** Ближайшая точка объекта, координаты чертежа; null - объекта класса на подоснове нет,
   *  и выноска - окружность радиусом замера. */
  to: [number, number] | null;
  /** Замер сервиса, метры. */
  measured: number;
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

function toneOf(cls: string): Tone {
  if (cls.startsWith('utility.') || cls === 'power_line_overhead') return 'utility';
  if (['curb', 'sidewalk', 'pavement_edge', 'road', 'tram', 'railway'].includes(cls)) {
    return 'surface';
  }
  return 'other';
}

const number = (value: number) => value.toFixed(2).replace('.', ',');

/** Выноски посадки в точке (x, y) по проверкам checks: у выбранной - её трасса правил, при
 *  переносе - ответ живой проверки точки. Нормы без замера и без расстояния (порог 0)
 *  линией не покажешь: они остаются только в панели. */
export function dimensionsFor(
  at: Pick<MapItem, 'x' | 'y'>,
  checks: readonly RuleCheck[],
  index: ClassIndex,
): Dimension[] {
  const dimensions: Dimension[] = [];
  // Два правила на один замер до одного объекта (теплосеть: СП 42 и 743-ПП) - одна плашка:
  // вторая с тем же числом ложилась рядом и читалась как второй объект.
  const seen = new Set<string>();
  for (const check of splitChecks(checks).lead) {
    const measured = check.measured_m;
    const threshold = check.threshold_m;
    if (measured == null || threshold == null || threshold <= 0) continue;
    const cls = check.object_class ?? '';
    const key = `${cls}:${Math.round(measured * 100)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    // Нарушение - всегда малиновым и со знаком «<»: цвет и знак говорят одно и то же.
    const broken = check.outcome === 'fail' || measured < threshold;
    // Сервис мерит до стенки сети, подоснова - это ось: ищем с запасом на половину диаметра.
    const to = cls ? index.nearest(cls, at.x, at.y, measured + 2) : null;
    const sign = broken ? '<' : '≥';
    dimensions.push({
      to,
      measured,
      label: `${SHORT[cls] ?? 'объект'} ${number(measured)} ${sign} ${number(threshold)}`,
      tone: broken ? 'fail' : toneOf(cls),
    });
  }
  return dimensions;
}

/** Зазор между целью выноски и её плашкой, пикселей. */
const LABEL_GAP = 8;
const LABEL_HEIGHT = 20;
/** Сдвиги плашки поперёк выноски, когда место занято соседкой. */
const LABEL_SHIFTS = [0, 23, -23, 46, -46, 69, -69];

/** Прямоугольник экрана: x, y левого верхнего угла, ширина, высота. */
export type Rect = readonly [number, number, number, number];

/** Плашка подписи - за целью по направлению выноски и всем телом по ту сторону: на цели она
 *  закрывала то, к чему ведёт (жюри, итерация 7). (ux, uy) - единичный вектор от ствола к
 *  цели в пикселях экрана; shift сдвигает плашку поперёк выноски, то есть вдоль самого
 *  объекта, и цель остаётся открытой. */
export function labelBox(
  tx: number,
  ty: number,
  ux: number,
  uy: number,
  width: number,
  shift = 0,
): Rect {
  const reach = LABEL_GAP + (Math.abs(ux) * width) / 2 + (Math.abs(uy) * LABEL_HEIGHT) / 2;
  const cx = tx + ux * reach - uy * shift;
  const cy = ty + uy * reach + ux * shift;
  return [Math.round(cx - width / 2), Math.round(cy - LABEL_HEIGHT / 2), width, LABEL_HEIGHT];
}

/** Ближайшая к цели точка плашки: к ней ведёт тонкая линия, когда плашка сдвинута от своей
 *  выноски, - иначе она висела в 40-70 px от стрелки и читалась как чужая (жюри, итерация 8).
 *  null - плашка у самой цели, линия не нужна. */
export function leaderEnd(tx: number, ty: number, [x, y, w, h]: Rect): [number, number] | null {
  const nx = Math.min(Math.max(tx, x), x + w);
  const ny = Math.min(Math.max(ty, y), y + h);
  return Math.hypot(nx - tx, ny - ty) > LABEL_GAP + 4 ? [nx, ny] : null;
}

const overlaps = ([x0, y0, w0, h0]: Rect, [x1, y1, w1, h1]: Rect): boolean =>
  x0 < x1 + w1 && x0 + w0 > x1 && y0 < y1 + h1 && y0 + h0 > y1;

/** Выноски в экранных пикселях: линия со стрелкой к объекту, засечки на концах, плашка за
 *  целью. Объекта нет на подоснове - пунктирная окружность радиусом замера и радиус-выноска
 *  к ней. Плашки не налезают друг на друга и на кольцо выбора. */
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
  const labels: { dimension: Dimension; tx: number; ty: number; ux: number; uy: number }[] = [];
  dimensions.forEach((dimension, index) => {
    const tone = TONES[dimension.tone];
    ctx.strokeStyle = tone.fill;
    ctx.fillStyle = tone.fill;
    ctx.lineWidth = 1.6;
    let tx: number;
    let ty: number;
    if (dimension.to) {
      ({ sx: tx, sy: ty } = toScreen(view, dimension.to[0], dimension.to[1]));
    } else {
      const radius = dimension.measured * view.scale;
      if (radius < 6) return;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.arc(sx, sy, radius, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      // Радиус-выноска первой окружности смотрит вверх-вправо, у следующих - с поворотом:
      // плашки не собираются в один угол.
      const angle = -Math.PI / 4 + index * (Math.PI / 3);
      tx = sx + Math.cos(angle) * radius;
      ty = sy + Math.sin(angle) * radius;
    }
    const length = Math.hypot(tx - sx, ty - sy);
    if (length < 6) return;
    const ux = (tx - sx) / length;
    const uy = (ty - sy) / length;
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
    labels.push({ dimension, tx, ty, ux, uy });
  });
  // Плашки - вторым проходом, поверх всех линий.
  const boxes: Rect[] = [[sx - clear + 6, sy - clear + 6, (clear - 6) * 2, (clear - 6) * 2]];
  for (const { dimension, tx, ty, ux, uy } of labels) {
    const tone = TONES[dimension.tone];
    const width = ctx.measureText(dimension.label).width + 14;
    const box =
      LABEL_SHIFTS.map((shift) => labelBox(tx, ty, ux, uy, width, shift)).find(
        (candidate) => !boxes.some((other) => overlaps(candidate, other)),
      ) ?? labelBox(tx, ty, ux, uy, width);
    boxes.push(box);
    const [bx, by] = box;
    const end = leaderEnd(tx, ty, box);
    if (end) {
      ctx.strokeStyle = tone.fill;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(tx, ty);
      ctx.lineTo(end[0], end[1]);
      ctx.stroke();
    }
    ctx.fillStyle = tone.fill;
    ctx.beginPath();
    ctx.roundRect(bx, by, width, LABEL_HEIGHT, 3);
    ctx.fill();
    ctx.fillStyle = tone.text;
    ctx.fillText(dimension.label, bx + 7, by + LABEL_HEIGHT / 2 + 0.5);
  }
  ctx.restore();
}
