/* Геометрия подосновы: пути, габариты, главная ось, опорные точки. Перенос из plan.js. */

import type { BasemapFeature, Geometry, Position } from '../api/artifacts';

export interface Point {
  x: number;
  y: number;
}

export type Box = [number, number, number, number];

function addRing(path: Path2D, ring: Position[], close: boolean): void {
  ring.forEach(([x, y], i) => {
    if (i) path.lineTo(x, y);
    else path.moveTo(x, y);
  });
  if (close) path.closePath();
}

export function addGeometry(path: Path2D, geometry: Geometry): void {
  switch (geometry.type) {
    case 'Point': {
      // Точка рисуется коротким крестом: круг на малом зуме сливается в пятно.
      const [x, y] = geometry.coordinates;
      path.moveTo(x - 0.4, y);
      path.lineTo(x + 0.4, y);
      path.moveTo(x, y - 0.4);
      path.lineTo(x, y + 0.4);
      break;
    }
    case 'MultiPoint':
      for (const coordinates of geometry.coordinates) {
        addGeometry(path, { type: 'Point', coordinates });
      }
      break;
    case 'LineString':
      addRing(path, geometry.coordinates, false);
      break;
    case 'MultiLineString':
      for (const line of geometry.coordinates) addRing(path, line, false);
      break;
    case 'Polygon':
      for (const ring of geometry.coordinates) addRing(path, ring, true);
      break;
    case 'MultiPolygon':
      for (const polygon of geometry.coordinates) {
        for (const ring of polygon) addRing(path, ring, true);
      }
      break;
    case 'GeometryCollection':
      for (const part of geometry.geometries) addGeometry(path, part);
      break;
  }
}

/** Габарит геометрии без выделения массивов: функция зовётся на каждый объект подосновы. */
export function measure(geometry: Geometry, box: Box): void {
  const put = (x: number, y: number) => {
    if (x < box[0]) box[0] = x;
    if (y < box[1]) box[1] = y;
    if (x > box[2]) box[2] = x;
    if (y > box[3]) box[3] = y;
  };
  switch (geometry.type) {
    case 'Point':
      put(geometry.coordinates[0], geometry.coordinates[1]);
      break;
    case 'MultiPoint':
    case 'LineString':
      for (const [x, y] of geometry.coordinates) put(x, y);
      break;
    case 'MultiLineString':
    case 'Polygon':
      for (const ring of geometry.coordinates) for (const [x, y] of ring) put(x, y);
      break;
    case 'MultiPolygon':
      for (const polygon of geometry.coordinates) {
        for (const ring of polygon) for (const [x, y] of ring) put(x, y);
      }
      break;
    case 'GeometryCollection':
      for (const part of geometry.geometries) measure(part, box);
      break;
  }
}

/** Главная ось облака точек. Считается по плану: разворачивать вид по подоснове нельзя - она
 *  тянется на километры вдоль совсем других улиц. */
export function principalAxis(items: readonly Point[]): number {
  if (items.length < 3) return 0;
  let mx = 0;
  let my = 0;
  for (const item of items) {
    mx += item.x;
    my += item.y;
  }
  mx /= items.length;
  my /= items.length;
  let sxx = 0;
  let syy = 0;
  let sxy = 0;
  for (const item of items) {
    const dx = item.x - mx;
    const dy = item.y - my;
    sxx += dx * dx;
    syy += dy * dy;
    sxy += dx * dy;
  }
  return 0.5 * Math.atan2(2 * sxy, sxx - syy);
}

export function geometryPoints(geometry: Geometry): Point[] {
  switch (geometry.type) {
    case 'Point':
      return [{ x: geometry.coordinates[0], y: geometry.coordinates[1] }];
    case 'MultiPoint':
    case 'LineString':
      return geometry.coordinates.map(([x, y]) => ({ x, y }));
    case 'MultiLineString':
    case 'Polygon':
      return geometry.coordinates.flat().map(([x, y]) => ({ x, y }));
    case 'MultiPolygon':
      return geometry.coordinates.flat(2).map(([x, y]) => ({ x, y }));
    case 'GeometryCollection':
      return geometry.geometries.flatMap(geometryPoints);
  }
}

/** Точки внутри 2-98-го процентиля по каждой оси: далёкие объекты не растягивают вид. */
export function trimmed(points: Point[], share = 0.02): Point[] {
  if (points.length < 20) return points;
  const xs = points.map((p) => p.x).sort((a, b) => a - b);
  const ys = points.map((p) => p.y).sort((a, b) => a - b);
  const low = Math.floor(points.length * share);
  const high = Math.ceil(points.length * (1 - share)) - 1;
  const [x0, x1, y0, y1] = [
    xs[low] ?? -Infinity,
    xs[high] ?? Infinity,
    ys[low] ?? -Infinity,
    ys[high] ?? Infinity,
  ];
  return points.filter((p) => p.x >= x0 && p.x <= x1 && p.y >= y0 && p.y <= y1);
}

/** Опорные точки подосновы - центры объектов без границы работ: пока плана нет, по ним
 *  вписывается и разворачивается чертёж. Граница работ не годится - у встроенного фрагмента
 *  она осталась от целой улицы и в разы длиннее самого чертежа. */
export function contentPoints(features: readonly BasemapFeature[]): Point[] {
  const points: Point[] = [];
  for (const feature of features) {
    if (feature.properties.class === 'work_boundary') continue;
    const vertices = geometryPoints(feature.geometry);
    if (!vertices.length) continue;
    let sx = 0;
    let sy = 0;
    for (const { x, y } of vertices) {
      sx += x;
      sy += y;
    }
    points.push({ x: sx / vertices.length, y: sy / vertices.length });
  }
  return trimmed(points);
}

/** Внешние контуры границы работ: полигоны и замкнутые линии, все против часовой стрелки.
 *  Открытые отрезки слоя границы (обрывки, выноски) контуром не считаются. Обход один на
 *  всех: заливка по правилу ненулевого числа оборотов тогда даёт объединение контуров, а не
 *  дыру там, где два контура с разным обходом накрывают друг друга. Дыры полигонов не
 *  берутся: участок - всё, что внутри внешнего контура. */
export function boundaryRings(features: readonly BasemapFeature[]): Position[][] {
  const rings: Position[][] = [];
  const take = (ring: Position[] | undefined) => {
    if (!ring || ring.length < 4 || !closed(ring)) return;
    rings.push(signedArea(ring) < 0 ? [...ring].reverse() : ring);
  };
  const walk = (geometry: Geometry) => {
    switch (geometry.type) {
      case 'Polygon':
        take(geometry.coordinates[0]);
        break;
      case 'MultiPolygon':
        for (const polygon of geometry.coordinates) take(polygon[0]);
        break;
      case 'LineString':
        take(geometry.coordinates);
        break;
      case 'MultiLineString':
        for (const line of geometry.coordinates) take(line);
        break;
      case 'GeometryCollection':
        for (const part of geometry.geometries) walk(part);
        break;
      default:
        break;
    }
  };
  for (const feature of features) {
    if (feature.properties.class === 'work_boundary') walk(feature.geometry);
  }
  return rings;
}

/** Замкнута ли линия: последняя точка совпадает с первой с точностью до сантиметра. */
function closed(ring: Position[]): boolean {
  const first = ring[0];
  const last = ring[ring.length - 1];
  return Boolean(first && last && Math.hypot(first[0] - last[0], first[1] - last[1]) < 0.01);
}

function signedArea(ring: Position[]): number {
  let sum = 0;
  for (let i = 0; i + 1 < ring.length; i += 1) {
    const [x0, y0] = ring[i] ?? [0, 0];
    const [x1, y1] = ring[i + 1] ?? [0, 0];
    sum += x0 * y1 - x1 * y0;
  }
  return sum / 2;
}

/** Точка внутри контура (луч вправо, чётность пересечений). */
export function insideRing(x: number, y: number, ring: Position[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [xi, yi] = ring[i] ?? [0, 0];
    const [xj, yj] = ring[j] ?? [0, 0];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Контуры границы - это участок плана, если внутри них почти все посадки. Слой границы
 *  бывает сборным (рамка листа, обрывки), и бледнеть от такой «границы» стал бы сам план. */
export function coversPlan(
  rings: readonly Position[][],
  points: readonly Point[],
  share = 0.95,
): boolean {
  if (!rings.length || !points.length) return false;
  const inside = points.filter((p) => rings.some((ring) => insideRing(p.x, p.y, ring))).length;
  return inside >= points.length * share;
}

export function boundsOfPoints(items: readonly Point[], margin = 10): Box | null {
  if (!items.length) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const item of items) {
    minX = Math.min(minX, item.x);
    maxX = Math.max(maxX, item.x);
    minY = Math.min(minY, item.y);
    maxY = Math.max(maxY, item.y);
  }
  return [minX - margin, minY - margin, maxX + margin, maxY + margin];
}
