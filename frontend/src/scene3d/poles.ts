/* Где стоят опоры: позиции фонарей из частей условных знаков подосновы.
 *
 * Знак опоры в чертеже часто разобран на примитивы: ромб основания, его заливка, стойка,
 * консоль, табличка - каждый примитив приходит отдельным объектом класса pole. Раньше каждый
 * давал свой фонарь, и на месте одной опоры вставала гроздь из 6-11 мачт. Здесь части
 * собираются обратно в знаки, и опора ставится на основание знака.
 *
 * Правило не зависит от масштаба знака (в одном чертеже бывают знаки 0,4 и 1,5 м):
 *  - основание - точка вставки или компактный замкнутый контур (ромб, кружок);
 *  - части, которые касаются друг друга, - один знак; знак с основаниями даёт опору на
 *    каждом основании, поэтому два настоящих знака рядом (фонарь и табличка в 0,7 м)
 *    остаются двумя, даже если их штрихи соприкасаются;
 *  - знак без основания даёт одну опору в середине, если он размером со знак или в нём есть
 *    замкнутый контур; одиночная длинная линия опорой не становится.
 * Проверено на подосновах «02565tp» (336 частей -> 51 опора, у каждого ромба одна) и улицы
 * Берзарина (881 -> 834: там знаки в основном пришли точками вставки). */

import type { Geometry, Position } from '../api/artifacts';

/** Основание знака не крупнее: ромб опоры в крупном масштабе бывает 1,5 м. */
const ANCHOR_MAX_M = 2.0;
/** Основание компактное: ромб и кружок, а не табличка 0,4 x 0,8 м. */
const ANCHOR_ASPECT = 1.4;
/** Контур и заливка одного основания и сдвиг копии знака - ближе этого. */
const SAME_M = 0.15;
/** Части одного знака касаются: стойка упирается в ромб, консоль в стойку. */
const JOIN_M = 0.3;
/** Знак без основания и без замкнутых контуров не длиннее этого, иначе это провод. */
const SYMBOL_MAX_M = 2.5;
/** Замкнутая линия: последняя вершина совпадает с первой. */
const CLOSED_M = 0.02;

type Box = [number, number, number, number];

interface Part {
  lines: Position[][];
  box: Box;
  anchor: Position | null;
  closed: boolean;
}

function linesOf(geometry: Geometry): Position[][] {
  switch (geometry.type) {
    case 'Point':
      return [[geometry.coordinates]];
    case 'MultiPoint':
      return geometry.coordinates.map((p) => [p]);
    case 'LineString':
      return [geometry.coordinates];
    case 'MultiLineString':
    case 'Polygon':
      return geometry.coordinates;
    case 'MultiPolygon':
      return geometry.coordinates.flat();
    case 'GeometryCollection':
      return geometry.geometries.flatMap(linesOf);
    default:
      return [];
  }
}

function boxOf(lines: Position[][]): Box {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const line of lines) {
    for (const [x, y] of line) {
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  }
  return [minX, minY, maxX, maxY];
}

function isClosed(line: Position[]): boolean {
  const first = line[0];
  const last = line[line.length - 1];
  return (
    line.length > 3 &&
    !!first &&
    !!last &&
    Math.hypot(first[0] - last[0], first[1] - last[1]) < CLOSED_M
  );
}

function isArea(geometry: Geometry): boolean {
  return geometry.type === 'Polygon' || geometry.type === 'MultiPolygon';
}

/** Основание знака: точка вставки или компактный малый замкнутый контур, его центр. */
function anchorOf(geometry: Geometry, lines: Position[][]): Position | null {
  if (geometry.type === 'Point') return geometry.coordinates;
  const outer = lines[0];
  if (!outer || !(isArea(geometry) || isClosed(outer))) return null;
  const [x0, y0, x1, y1] = boxOf([outer]);
  const long = Math.max(x1 - x0, y1 - y0);
  const short = Math.min(x1 - x0, y1 - y0);
  if (long > ANCHOR_MAX_M || short <= 0 || long / short > ANCHOR_ASPECT) return null;
  return [(x0 + x1) / 2, (y0 + y1) / 2];
}

function partOf(geometry: Geometry): Part | null {
  const lines = linesOf(geometry).filter((line) => line.length > 0);
  if (!lines.length) return null;
  return {
    lines,
    box: boxOf(lines),
    anchor: anchorOf(geometry, lines),
    closed: geometry.type === 'Point' || isArea(geometry) || lines.some(isClosed),
  };
}

function pointToSegment(p: Position, a: Position, b: Position): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = dx * dx + dy * dy;
  const t =
    len === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len));
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
}

function segmentsOf(part: Part): [Position, Position][] {
  const out: [Position, Position][] = [];
  for (const line of part.lines) {
    const first = line[0];
    if (line.length === 1 && first) out.push([first, first]);
    for (let i = 1; i < line.length; i++) {
      const a = line[i - 1];
      const b = line[i];
      if (a && b) out.push([a, b]);
    }
  }
  return out;
}

/** Части касаются: расстояние между их отрезками не больше JOIN_M. */
function touches(a: Part, b: Part): boolean {
  if (
    a.box[0] - JOIN_M > b.box[2] ||
    b.box[0] - JOIN_M > a.box[2] ||
    a.box[1] - JOIN_M > b.box[3] ||
    b.box[1] - JOIN_M > a.box[3]
  )
    return false;
  const sb = segmentsOf(b);
  for (const [a1, a2] of segmentsOf(a)) {
    for (const [b1, b2] of sb) {
      if (
        pointToSegment(a1, b1, b2) <= JOIN_M ||
        pointToSegment(a2, b1, b2) <= JOIN_M ||
        pointToSegment(b1, a1, a2) <= JOIN_M ||
        pointToSegment(b2, a1, a2) <= JOIN_M
      )
        return true;
    }
  }
  return false;
}

/** Группы касающихся частей; кандидаты в пары - через сетку, чтобы не сравнивать всё со всем. */
function symbols(parts: Part[]): Part[][] {
  const parent = parts.map((_, i) => i);
  const root = (i: number): number => {
    let r = i;
    while ((parent[r] ?? r) !== r) r = parent[r] ?? r;
    parent[i] = r;
    return r;
  };
  const cell = (v: number) => Math.floor(v / SYMBOL_MAX_M);
  const grid = new Map<string, number[]>();
  parts.forEach((part, i) => {
    const seen = new Set<number>();
    for (let cx = cell(part.box[0] - JOIN_M); cx <= cell(part.box[2] + JOIN_M); cx++) {
      for (let cy = cell(part.box[1] - JOIN_M); cy <= cell(part.box[3] + JOIN_M); cy++) {
        const key = `${cx}:${cy}`;
        const list = grid.get(key);
        for (const j of list ?? []) {
          if (seen.has(j)) continue;
          seen.add(j);
          const other = parts[j];
          if (other && root(i) !== root(j) && touches(part, other)) parent[root(i)] = root(j);
        }
        if (list) list.push(i);
        else grid.set(key, [i]);
      }
    }
  });
  const groups = new Map<number, Part[]>();
  parts.forEach((part, i) => {
    const r = root(i);
    const list = groups.get(r);
    if (list) list.push(part);
    else groups.set(r, [part]);
  });
  return [...groups.values()];
}

function near(a: Position, b: Position): boolean {
  return Math.hypot(a[0] - b[0], a[1] - b[1]) <= SAME_M;
}

/** Позиции опор по частям знаков класса pole, координаты чертежа. */
export function poleSites(geometries: readonly Geometry[]): Position[] {
  const parts = geometries.map(partOf).filter((part): part is Part => part !== null);
  const sites: Position[] = [];
  const add = (p: Position) => {
    if (!sites.some((s) => near(s, p))) sites.push(p);
  };
  for (const group of symbols(parts)) {
    const anchors = group.flatMap((part) => (part.anchor ? [part.anchor] : []));
    if (anchors.length) {
      for (const anchor of anchors) add(anchor);
      continue;
    }
    const [x0, y0, x1, y1] = boxOf(group.flatMap((part) => part.lines));
    if (Math.max(x1 - x0, y1 - y0) <= SYMBOL_MAX_M || group.some((part) => part.closed)) {
      add([(x0 + x1) / 2, (y0 + y1) / 2]);
    }
  }
  return sites;
}
