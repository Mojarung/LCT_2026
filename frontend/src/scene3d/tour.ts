/* Автоматический облёт участка: камера идёт над улицей по её оси, туда и обратно.
 *
 * Ось улицы берётся из самого плана. Посадки собираются в скопления по сетке, между ними
 * строится минимальное остовное дерево, и его самая длинная цепь (диаметр дерева) - это
 * хребет улицы: он проходит изгиб Кустанайской так же, как прямую Берзарина, а боковые
 * дворы остаются ветками и в маршрут не попадают. Хребет сглаживается и размечается по
 * длине, чтобы скорость облёта была в метрах в секунду, а не в точках маршрута. */

import type { Flat } from './types';

/** Размер клетки скопления, метры: мельче - маршрут петляет по кустам, крупнее - режет углы. */
export const CLUSTER_M = 30;
/** Высота полёта над землёй и насколько вперёд по маршруту смотрит камера, метры. */
export const TOUR_HEIGHT_M = 30;
export const LOOK_AHEAD_M = 70;
/** Шаг разметки маршрута после сглаживания, метры. */
const STEP_M = 5;

/** Центры скоплений точек по клеткам сетки: средняя точка каждой непустой клетки. */
export function clusters(points: readonly Flat[], cell = CLUSTER_M): Flat[] {
  const sums = new Map<string, { x: number; z: number; n: number }>();
  for (const p of points) {
    const key = `${Math.floor(p.x / cell)}:${Math.floor(p.z / cell)}`;
    const s = sums.get(key);
    if (s) {
      s.x += p.x;
      s.z += p.z;
      s.n += 1;
    } else {
      sums.set(key, { x: p.x, z: p.z, n: 1 });
    }
  }
  return [...sums.values()].map((s) => ({ x: s.x / s.n, z: s.z / s.n }));
}

const dist = (a: Flat, b: Flat) => Math.hypot(a.x - b.x, a.z - b.z);

/** Минимальное остовное дерево (Прим, O(n^2): скоплений сотни, не тысячи) - соседи вершин. */
export function spanningTree(nodes: readonly Flat[]): number[][] {
  const n = nodes.length;
  const adj: number[][] = nodes.map(() => []);
  if (n < 2) return adj;
  const inTree = new Array<boolean>(n).fill(false);
  const best = new Array<number>(n).fill(Infinity);
  const parent = new Array<number>(n).fill(-1);
  best[0] = 0;
  for (let k = 0; k < n; k++) {
    let u = -1;
    for (let i = 0; i < n; i++) {
      if (!inTree[i] && (u < 0 || (best[i] ?? Infinity) < (best[u] ?? Infinity))) u = i;
    }
    inTree[u] = true;
    const p = parent[u] ?? -1;
    if (p >= 0) {
      adj[u]?.push(p);
      adj[p]?.push(u);
    }
    const nu = nodes[u];
    if (!nu) continue;
    for (let v = 0; v < n; v++) {
      const nv = nodes[v];
      if (inTree[v] || !nv) continue;
      const d = dist(nu, nv);
      if (d < (best[v] ?? Infinity)) {
        best[v] = d;
        parent[v] = u;
      }
    }
  }
  return adj;
}

/** Путь по дереву от start до самой далёкой от неё вершины. */
function farthest(nodes: readonly Flat[], adj: number[][], start: number): number[] {
  const far = new Array<number>(nodes.length).fill(-1);
  const prev = new Array<number>(nodes.length).fill(-1);
  far[start] = 0;
  const stack = [start];
  while (stack.length) {
    const u = stack.pop() ?? start;
    for (const v of adj[u] ?? []) {
      if ((far[v] ?? -1) >= 0) continue;
      const a = nodes[u];
      const b = nodes[v];
      far[v] = (far[u] ?? 0) + (a && b ? dist(a, b) : 0);
      prev[v] = u;
      stack.push(v);
    }
  }
  let end = start;
  for (let i = 0; i < nodes.length; i++) if ((far[i] ?? -1) > (far[end] ?? -1)) end = i;
  const path: number[] = [];
  for (let v = end; v >= 0; v = prev[v] ?? -1) path.push(v);
  return path.reverse();
}

/** Хребет - диаметр дерева: от любой вершины к самой далёкой и от неё снова к самой далёкой. */
export function spine(nodes: readonly Flat[]): Flat[] {
  if (nodes.length < 2) return [...nodes];
  const adj = spanningTree(nodes);
  const first = farthest(nodes, adj, 0);
  const path = farthest(nodes, adj, first[first.length - 1] ?? 0);
  return path.map((i) => nodes[i]).filter((p): p is Flat => Boolean(p));
}

/** Сглаживание скользящим средним: ступеньки клеток сетки уходят, концы остаются на месте. */
export function smooth(line: readonly Flat[], radius = 2): Flat[] {
  return line.map((p, i) => {
    if (i === 0 || i === line.length - 1) return p;
    let sx = 0;
    let sz = 0;
    let n = 0;
    for (let k = Math.max(0, i - radius); k <= Math.min(line.length - 1, i + radius); k++) {
      const q = line[k];
      if (!q) continue;
      sx += q.x;
      sz += q.z;
      n += 1;
    }
    return { x: sx / n, z: sz / n };
  });
}

/** Маршрут с разметкой по длине: точки и накопленная длина до каждой. */
export interface Route {
  points: Flat[];
  along: number[];
  length: number;
}

export function route(line: readonly Flat[]): Route {
  const points: Flat[] = [];
  for (let i = 0; i + 1 < line.length; i++) {
    const a = line[i];
    const b = line[i + 1];
    if (!a || !b) continue;
    const n = Math.max(1, Math.ceil(dist(a, b) / STEP_M));
    for (let k = 0; k < n; k++) {
      points.push({ x: a.x + ((b.x - a.x) * k) / n, z: a.z + ((b.z - a.z) * k) / n });
    }
  }
  const last = line[line.length - 1];
  if (last) points.push(last);
  const along = [0];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1];
    const b = points[i];
    along.push((along[i - 1] ?? 0) + (a && b ? dist(a, b) : 0));
  }
  return { points, along, length: along[along.length - 1] ?? 0 };
}

/** Точка маршрута на расстоянии s от начала; s за концами прижимается к концу. */
export function pointAt(r: Route, s: number): Flat {
  const t = Math.max(0, Math.min(r.length, s));
  let lo = 0;
  let hi = r.along.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if ((r.along[mid] ?? 0) <= t) lo = mid;
    else hi = mid;
  }
  const a = r.points[lo] ?? { x: 0, z: 0 };
  const b = r.points[hi] ?? a;
  const span = (r.along[hi] ?? 0) - (r.along[lo] ?? 0);
  const k = span > 0 ? (t - (r.along[lo] ?? 0)) / span : 0;
  return { x: a.x + (b.x - a.x) * k, z: a.z + (b.z - a.z) * k };
}

/** Маршрут облёта по точкам посадок; null, если облетать нечего. */
export function tourRoute(points: readonly Flat[]): Route | null {
  const line = smooth(spine(clusters(points)));
  if (line.length < 2) return null;
  const r = route(line);
  return r.length > 20 ? r : null;
}

/** Здание для облёта: габарит основания и высота. */
export interface Obstacle {
  minX: number;
  minZ: number;
  maxX: number;
  maxZ: number;
  height: number;
}

/** Запас над крышей и радиус, в котором здание считается «под маршрутом», метры. */
const ROOF_CLEARANCE_M = 10;
const OBSTACLE_REACH_M = 20;
/** Окно сглаживания высоты, точек маршрута: набор высоты начинается заранее, а не у стены. */
const CLIMB_WINDOW = 12;

/** Высота полёта в каждой точке маршрута: не ниже базовой и выше крыш рядом с маршрутом.
 *  Сначала максимум в окне (подъём до здания, а не над ним), потом среднее - плавность. */
export function clearance(
  r: Route,
  obstacles: readonly Obstacle[],
  base = TOUR_HEIGHT_M,
): number[] {
  const need = r.points.map((p) => {
    let h = base;
    for (const o of obstacles) {
      const dx = Math.max(o.minX - p.x, 0, p.x - o.maxX);
      const dz = Math.max(o.minZ - p.z, 0, p.z - o.maxZ);
      if (Math.hypot(dx, dz) <= OBSTACLE_REACH_M) h = Math.max(h, o.height + ROOF_CLEARANCE_M);
    }
    return h;
  });
  const window = (values: number[], pick: (xs: number[]) => number) =>
    values.map((_, i) => pick(values.slice(Math.max(0, i - CLIMB_WINDOW), i + CLIMB_WINDOW + 1)));
  const peaks = window(need, (xs) => Math.max(...xs));
  return window(peaks, (xs) => xs.reduce((a, b) => a + b, 0) / xs.length);
}

/** Откуда начинать облёт: середина самого длинного участка маршрута с наименьшей высотой
 *  полёта. Хребет улицы часто начинается у высотки, и первые секунды облёта кадр занимали её
 *  крыша и стена; над открытым местом первый кадр показывает посадки. */
export function tourStart(r: Route, heights: readonly number[]): number {
  if (!heights.length) return 0;
  const low = Math.min(...heights) + 0.5;
  let best = { from: 0, to: 0 };
  let from = -1;
  for (let i = 0; i <= heights.length; i++) {
    const open = i < heights.length && (heights[i] ?? Infinity) <= low;
    if (open && from < 0) from = i;
    if (!open && from >= 0) {
      if (i - 1 - from > best.to - best.from) best = { from, to: i - 1 };
      from = -1;
    }
  }
  const start = r.along[best.from] ?? 0;
  const end = r.along[best.to] ?? start;
  return (start + end) / 2;
}

function heightAt(r: Route, heights: readonly number[], s: number): number {
  const t = Math.max(0, Math.min(r.length, s));
  let i = 0;
  while (i + 1 < r.along.length && (r.along[i + 1] ?? 0) < t) i++;
  const a = heights[i] ?? TOUR_HEIGHT_M;
  const b = heights[i + 1] ?? a;
  const span = (r.along[i + 1] ?? 0) - (r.along[i] ?? 0);
  return span > 0 ? a + (b - a) * ((t - (r.along[i] ?? 0)) / span) : a;
}

export interface TourPose {
  x: number;
  y: number;
  z: number;
  yaw: number;
  pitch: number;
}

/** Поза камеры в облёте: над маршрутом, взгляд вперёд и вниз на LOOK_AHEAD_M.
 *  Облёт идёт туда и обратно: пройденный путь растёт, направление меняется на концах. */
export function tourPose(r: Route, travelled: number, heights?: readonly number[]): TourPose {
  const lap = r.length * 2;
  const s = ((travelled % lap) + lap) % lap;
  const forward = s <= r.length;
  const at = forward ? s : lap - s;
  const here = pointAt(r, at);
  const height = heights ? heightAt(r, heights, at) : TOUR_HEIGHT_M;
  // Направление берётся по участку перед камерой, у конца - по участку за ней: иначе на
  // развороте точка «впереди» совпадает с текущей и камера дёргается.
  const step = forward ? 1 : -1;
  let ahead = pointAt(r, at + step * LOOK_AHEAD_M);
  let from = here;
  if (Math.hypot(ahead.x - here.x, ahead.z - here.z) < LOOK_AHEAD_M * 0.3) {
    from = pointAt(r, at - step * LOOK_AHEAD_M);
    ahead = here;
  }
  const dx = ahead.x - from.x;
  const dz = ahead.z - from.z;
  const yaw = Math.atan2(-dx, -dz);
  const pitch = -Math.atan2(height, LOOK_AHEAD_M);
  return { x: here.x, y: height, z: here.z, yaw, pitch };
}
