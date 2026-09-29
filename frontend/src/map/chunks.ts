/* Подоснова, разрезанная на куски: один Path2D на класс, ячейку сетки и размерную полку.
 *
 * Единый путь на класс выглядит экономнее, но он же и дороже: браузер отбрасывает путь целиком
 * по его габариту, поэтому один большой путь на всю улицу рисуется дольше (190 мс против 110 мс
 * на Камчатской), а мелко нарезанный позволяет не трогать то, чего нет в кадре, и то, что мельче
 * пикселя. */

import type { BasemapFeature, Geometry, Position } from '../api/artifacts';
import {
  type ExistingPlant,
  plantsOf,
  stripPoints,
  shrubStripLines,
  SHRUB_STRIP_WIDTH_M,
} from './existing';
import { addGeometry, type Box, measure } from './geometry';
import { STYLES, type ClassStyle } from './palette';

/** Сетка отсечения: на Камчатской (56 тыс. объектов) в кадре при 5 px/м остаётся ~4% ячеек. */
export const GRID = 24;
/** Размерные полки объекта в метрах. Полка пропускается целиком, когда её объекты мельче
 *  MIN_PX на экране: на общем виде это две трети объектов, и они всё равно невидимы. */
export const BANDS = [0.5, 1, 2, 4, 8, 16, Infinity];
export const MIN_PX = 1.5;

export interface Chunk {
  group: ClassStyle['group'];
  strokeVar: string | undefined;
  fillVar: string | undefined;
  width: number;
  dash: number[];
  texture: ClassStyle['texture'];
  shadow: boolean;
  /** Полоса кустарника съёмки: в стиле чертежа на приближении её рисует знак шаблона. */
  hedge: boolean;
  path: Path2D;
  /** Только замкнутые контуры: открытая линия здания остаётся в path для обводки. */
  fillPath: Path2D | null;
  span: number;
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/** Куски подосновы и существующие насаждения. Одиночная крона уходит в модели (existing.ts),
 *  а не в линии: иначе под бледной кроной модели проступал бы знак съёмки. Оси полос
 *  кустарника съёмки - ещё и в hedges: по ним стиль чертежа ставит знак живой изгороди. */
export function buildChunks(
  features: readonly BasemapFeature[],
  bbox: Box | null,
  existing: ExistingPlant[] = [],
  hedges: Position[][] = [],
): Chunk[] {
  const [x0, y0, x1, y1] = bbox ?? [0, 0, 0, 0];
  const cell = Math.max(x1 - x0, y1 - y0) / GRID || 1;
  const byKey = new Map<string, Chunk>();
  const box: Box = [0, 0, 0, 0];
  for (const feature of features) {
    const shrubLines = shrubStripLines(feature);
    const style = shrubLines.length
      ? { group: 'existing' as const, fill: '--c-existing', width: 0 }
      : STYLES[feature.properties.class];
    if (!style) continue;
    const plants = plantsOf(feature);
    if (plants) {
      existing.push(...plants);
      continue;
    }
    hedges.push(...shrubLines);
    box[0] = Infinity;
    box[1] = Infinity;
    box[2] = -Infinity;
    box[3] = -Infinity;
    measure(feature.geometry, box);
    if (!Number.isFinite(box[0])) continue;
    // Точка - условный знак (опора, колодец, существующее дерево): он читается на любом
    // масштабе и по размеру не отбрасывается.
    const point = feature.geometry.type === 'Point' || feature.geometry.type === 'MultiPoint';
    const span = point ? Infinity : Math.max(box[2] - box[0], box[3] - box[1]);
    // Точки (span бесконечен) уходят за последнюю полку - отдельным куском, как в plan.js.
    let band = 0;
    while (band < BANDS.length && (BANDS[band] ?? Infinity) <= span) band += 1;
    const cx = Math.floor((box[0] - x0) / cell);
    const cy = Math.floor((box[1] - y0) / cell);
    const key = `${feature.properties.class}|${feature.properties.vegetation_kind ?? ''}|${band}|${cx}|${cy}`;
    let chunk = byKey.get(key);
    if (!chunk) {
      chunk = {
        group: style.group,
        strokeVar: style.stroke,
        fillVar: style.fill,
        width: style.width,
        dash: style.dash ?? [],
        texture: style.texture,
        shadow: style.shadow ?? false,
        hedge: shrubLines.length > 0,
        path: new Path2D(),
        fillPath: null,
        span: 0,
        minX: Infinity,
        minY: Infinity,
        maxX: -Infinity,
        maxY: -Infinity,
      };
      byKey.set(key, chunk);
    }
    const strip = stripPoints(feature);
    if (shrubLines.length) {
      chunk.fillPath = chunk.path;
      const r = SHRUB_STRIP_WIDTH_M / 2;
      for (const line of shrubLines) {
        for (let i = 1; i < line.length; i++) {
          const a = line[i - 1];
          const b = line[i];
          if (!a || !b) continue;
          const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
          if (!length) continue;
          const dx = (-(b[1] - a[1]) * r) / length;
          const dy = ((b[0] - a[0]) * r) / length;
          chunk.path.moveTo(a[0] + dx, a[1] + dy);
          chunk.path.lineTo(b[0] + dx, b[1] + dy);
          chunk.path.lineTo(b[0] - dx, b[1] - dy);
          chunk.path.lineTo(a[0] - dx, a[1] - dy);
          chunk.path.closePath();
        }
      }
      box[0] -= r;
      box[1] -= r;
      box[2] += r;
      box[3] += r;
    } else if (strip) {
      // Условные кружки полосы, не кроны и не подтверждённые места стволов.
      for (const [x, y] of strip) {
        chunk.path.moveTo(x + 0.25, y);
        chunk.path.arc(x, y, 0.25, 0, Math.PI * 2);
      }
    } else {
      addGeometry(chunk.path, feature.geometry);
      if (style.fill) chunk.fillPath = addFillGeometry(chunk.fillPath, feature.geometry);
    }
    chunk.span = Math.max(chunk.span, span);
    chunk.minX = Math.min(chunk.minX, box[0]);
    chunk.minY = Math.min(chunk.minY, box[1]);
    chunk.maxX = Math.max(chunk.maxX, box[2]);
    chunk.maxY = Math.max(chunk.maxY, box[3]);
  }
  // Заливки рисуются первыми, иначе газон и здания закрашивают линии поверх себя.
  return [...byKey.values()].sort((a, b) => (b.fillVar ? 1 : 0) - (a.fillVar ? 1 : 0));
}

function closed(line: Position[]): boolean {
  const first = line[0];
  const last = line[line.length - 1];
  return Boolean(line.length >= 4 && first && last && first[0] === last[0] && first[1] === last[1]);
}

function addFillGeometry(path: Path2D | null, geometry: Geometry): Path2D | null {
  switch (geometry.type) {
    case 'LineString':
      if (closed(geometry.coordinates)) {
        path ??= new Path2D();
        addGeometry(path, geometry);
      }
      return path;
    case 'MultiLineString':
      for (const line of geometry.coordinates) {
        path = addFillGeometry(path, { type: 'LineString', coordinates: line });
      }
      return path;
    case 'Polygon':
    case 'MultiPolygon':
      path ??= new Path2D();
      addGeometry(path, geometry);
      return path;
    case 'GeometryCollection':
      for (const part of geometry.geometries) path = addFillGeometry(path, part);
      return path;
    default:
      return path;
  }
}
