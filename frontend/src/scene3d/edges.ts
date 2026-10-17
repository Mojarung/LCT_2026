/** Край проезжей части как в жизни (пользователь, 17.10.2026): на съезде во двор и на
 *  переходе борт понижен, с переходными камнями по метру с каждой стороны; тротуар к
 *  пониженному борту спускается пандусом; вдоль полного борта по асфальту тёмная полоса лотка.
 *
 *  Съезд - короткий ряд пролётов контура проезда (2-12 м, почти прямой), по другую сторону
 *  которых лежит тротуар (асфальт или плитка), а не газон. Контур нарезается по метру, чтобы
 *  съезд в середине длинного пролёта не тянул борт на весь пролёт. */

import * as THREE from 'three';

import { CURB_ABOVE_WALK_M, type MaskInfo, withoutHairpins, type SurfaceAreas } from './ground';
import { ASPHALT, EMPTY, PAVERS, ROAD } from './surfaceMask';
import type { Flat, Line } from './types';

/** Замкнутый контур проезжей части в координатах сцены (последняя точка равна первой):
 *  признак пониженного борта по каждому пролёту, сторона тротуара и островок (дыра проезда:
 *  тротуар внутри кольца). Пролёт 0 - всегда с полным бортом, съезд не переходит через начало. */
export interface RoadEdge {
  points: Flat[];
  lowered: boolean[];
  /** Сторона тротуара: 1 - слева от хода контура, -1 - справа. */
  side: 1 | -1;
  island: boolean;
}

/** Ширина пандуса тротуара к пониженному борту (уклон 1:10 при перепаде 11 см). */
export const APRON_W_M = 1.2;
/** Пониженный борт над асфальтом проезда: 4 см, как на съездах и переходах в Москве. */
export const LOW_CURB_M = 0.04;
/** Переходный камень: понижение борта на метре до и после съезда. */
export const TRANSITION_M = 1.0;
/** Полоса лотка по асфальту вдоль полного борта. */
export const GUTTER_W_M = 0.35;

/** Контур проезда режется на пролёты не длиннее метра. */
const PIECE_M = 1.0;
/** Пропуск в ряду съезда короче этого (стойка знака, люк) съезд не рвёт. */
const GAP_M = 1.5;
const CROSSING_MIN_M = 2.0;
const CROSSING_MAX_M = 12.0;
/** Съезд почти прямой: поворот контура внутри ряда суммарно не больше этого. */
const CROSSING_TURN_DEG = 60;

interface Run {
  start: number;
  end: number;
}

function dist(a: Flat, b: Flat): number {
  return Math.hypot(b.x - a.x, b.z - a.z);
}

/** Замкнутый контур с пролётами не длиннее PIECE_M. */
function resample(ring: readonly Flat[]): Flat[] {
  const out: Flat[] = [];
  for (let i = 0; i + 1 < ring.length; i++) {
    const p = ring[i] as Flat;
    const q = ring[i + 1] as Flat;
    const pieces = Math.max(1, Math.ceil(dist(p, q) / PIECE_M - 1e-9));
    for (let k = 0; k < pieces; k++) {
      const t = k / pieces;
      out.push({ x: p.x + (q.x - p.x) * t, z: p.z + (q.z - p.z) * t });
    }
  }
  const first = out[0];
  if (first) out.push({ ...first });
  return out;
}

/** Внутренность кольца слева от хода (площадь по формуле шнурков больше нуля). */
function insideIsLeft(ring: readonly Flat[]): boolean {
  let area = 0;
  for (let i = 0; i + 1 < ring.length; i++) {
    const p = ring[i] as Flat;
    const q = ring[i + 1] as Flat;
    area += p.x * q.z - q.x * p.z;
  }
  return area > 0;
}

function turnDeg(a: Flat, b: Flat, c: Flat): number {
  const ax = b.x - a.x;
  const az = b.z - a.z;
  const bx = c.x - b.x;
  const bz = c.z - b.z;
  const la = Math.hypot(ax, az);
  const lb = Math.hypot(bx, bz);
  if (la < 1e-9 || lb < 1e-9) return 0;
  const cos = Math.max(-1, Math.min(1, (ax * bx + az * bz) / (la * lb)));
  return (Math.acos(cos) * 180) / Math.PI;
}

/** Ряды пониженного борта по пролётам: ряд не переходит через начало кольца. */
function runsOf(lowered: readonly boolean[]): Run[] {
  const runs: Run[] = [];
  let i = 0;
  while (i < lowered.length) {
    if (!lowered[i]) {
      i++;
      continue;
    }
    let j = i;
    while (j < lowered.length && lowered[j]) j++;
    runs.push({ start: i, end: j });
    i = j;
  }
  return runs;
}

/** Признаки съезда по пролётам кольца: пропуски короче GAP_M заделываются, ряд вне 2-12 м
 *  или с крутым поворотом - не съезд. Кольцо повёрнуто так, что пролёт 0 - без съезда. */
function crossingRuns(
  pts: Flat[],
  crossingAt: (a: Flat, b: Flat) => boolean,
): { points: Flat[]; lowered: boolean[] } {
  const n = pts.length - 1;
  const flags = Array.from({ length: n }, (_, i) => crossingAt(pts[i] as Flat, pts[i + 1] as Flat));
  const lengths = Array.from({ length: n }, (_, i) => dist(pts[i] as Flat, pts[i + 1] as Flat));
  const start = flags.indexOf(false);
  if (start < 0 || !flags.some(Boolean)) {
    return { points: pts, lowered: flags.map(() => false) };
  }
  // Поворот кольца: пролёт 0 без съезда, ряды не переходят через начало.
  const rot = (k: number) => (start + k) % n;
  const points = Array.from({ length: n }, (_, k) => pts[rot(k)] as Flat);
  points.push({ ...(points[0] as Flat) });
  const lowered = Array.from({ length: n }, (_, k) => flags[rot(k)] as boolean);
  const len = Array.from({ length: n }, (_, k) => lengths[rot(k)] as number);
  // Заделать короткие пропуски между рядами.
  const runs = runsOf(lowered);
  for (let r = 0; r + 1 < runs.length; r++) {
    const a = runs[r] as Run;
    const b = runs[r + 1] as Run;
    const gap = len.slice(a.end, b.start).reduce((s, v) => s + v, 0);
    if (gap < GAP_M) for (let k = a.end; k < b.start; k++) lowered[k] = true;
  }
  for (const run of runsOf(lowered)) {
    const total = len.slice(run.start, run.end).reduce((s, v) => s + v, 0);
    let turn = 0;
    for (let k = run.start + 1; k < run.end; k++) {
      turn += turnDeg(points[k - 1] as Flat, points[k] as Flat, points[k + 1] as Flat);
    }
    if (total < CROSSING_MIN_M || total > CROSSING_MAX_M || turn > CROSSING_TURN_DEG) {
      for (let k = run.start; k < run.end; k++) lowered[k] = false;
    }
  }
  return { points, lowered };
}

export function roadEdges(
  areas: SurfaceAreas,
  origin: [number, number],
  crossingAt: (a: Flat, b: Flat) => boolean,
): RoadEdge[] {
  const [ox, oy] = origin;
  const out: RoadEdge[] = [];
  areas.paved.forEach((rings, i) => {
    if (areas.paved_kind?.[i] !== 'road') return;
    rings.forEach((ring, k) => {
      const clean = withoutHairpins(ring.map(([x = 0, y = 0]): Flat => ({ x: x - ox, z: oy - y })));
      if (clean.length < 4) return;
      const island = k > 0;
      const { points, lowered } = crossingRuns(resample(clean), crossingAt);
      // Тротуар - снаружи внешнего кольца и внутри островка.
      const inside = insideIsLeft(points);
      const side: 1 | -1 = inside === island ? 1 : -1;
      out.push({ points, lowered, side, island });
    });
  });
  return out;
}

/** Съезд по маске покрытий: со стороны проезда асфальт проезда, с другой - тротуар
 *  (асфальт или плитка) на глубину до CROSSING_DEPTH_M, а не полуметровая кромка, которой маска
 *  закрывает шов у газона. */
const CROSSING_DEPTH_M = 1.6;
const PROBE_M = 0.4;

export function crossingTest(mask: MaskInfo): (a: Flat, b: Flat) => boolean {
  const [minX, minZ] = mask.rect;
  const kindAt = (x: number, z: number): number => {
    const col = Math.floor((x - minX) / mask.metresPerPx);
    const row = Math.floor((z - minZ) / mask.metresPerPx);
    if (col < 0 || row < 0 || col >= mask.width || row >= mask.height) return EMPTY;
    return mask.kinds[row * mask.width + col] ?? EMPTY;
  };
  const paved = (k: number) => k === ASPHALT || k === PAVERS;
  return (a, b) => {
    const dx = b.x - a.x;
    const dz = b.z - a.z;
    const len = Math.hypot(dx, dz);
    if (!len) return false;
    const nx = -dz / len;
    const nz = dx / len;
    const mx = (a.x + b.x) / 2;
    const mz = (a.z + b.z) / 2;
    for (const sign of [1, -1]) {
      if (kindAt(mx - sign * nx * PROBE_M, mz - sign * nz * PROBE_M) !== ROAD) continue;
      let deep = true;
      for (let d = PROBE_M; d <= CROSSING_DEPTH_M; d += PROBE_M) {
        if (!paved(kindAt(mx + sign * nx * d, mz + sign * nz * d))) deep = false;
      }
      if (deep) return true;
    }
    return false;
  };
}

/** Единичные нормали пролётов в сторону тротуара. */
function sideNormals(edge: RoadEdge): [number, number][] {
  const out: [number, number][] = [];
  for (let i = 0; i + 1 < edge.points.length; i++) {
    const p = edge.points[i] as Flat;
    const q = edge.points[i + 1] as Flat;
    const len = dist(p, q) || 1;
    out.push([(-(q.z - p.z) / len) * edge.side, ((q.x - p.x) / len) * edge.side]);
  }
  return out;
}

/** Смещение вершины k на w по биссектрисе нормалей пролётов before и after (срез угла не
 *  длиннее 2w); на краю ряда берётся нормаль одного пролёта: нога пандуса перпендикулярна. */
function offsetAt(
  normals: readonly [number, number][],
  before: number | null,
  after: number | null,
  w: number,
): [number, number] {
  const a = before === null ? null : normals[before];
  const b = after === null ? null : normals[after];
  const [ax, az] = a ?? b ?? [0, 0];
  const [bx, bz] = b ?? a ?? [0, 0];
  let mx = ax + bx;
  let mz = az + bz;
  const ml = Math.hypot(mx, mz);
  if (ml < 1e-6) return [bx * w, bz * w];
  mx /= ml;
  mz /= ml;
  const scale = Math.min(w / Math.max(mx * bx + mz * bz, 1e-6), 2 * w);
  return [mx * scale, mz * scale];
}

/** Ряды пандусов: ряды съезда, продлённые на переходные камни (rampM) в обе стороны в
 *  пределах кольца; соседние ряды, сошедшиеся вплотную, сливаются в один. */
function apronRuns(edge: RoadEdge, rampM: number): Run[] {
  const n = edge.points.length - 1;
  const out: Run[] = [];
  for (const run of runsOf(edge.lowered)) {
    let start = run.start;
    let reach = 0;
    while (start > 0 && reach < rampM - 1e-9) {
      reach += dist(edge.points[start - 1] as Flat, edge.points[start] as Flat);
      start--;
    }
    let end = run.end;
    reach = 0;
    while (end < n && reach < rampM - 1e-9) {
      reach += dist(edge.points[end] as Flat, edge.points[end + 1] as Flat);
      end++;
    }
    const last = out.at(-1);
    if (last && start <= last.end) last.end = Math.max(last.end, end);
    else out.push({ start, end });
  }
  return out;
}

/** Линия пандуса: точки ряда, отодвинутые на apronW в сторону тротуара. */
function apronLine(edge: RoadEdge, run: Run, apronW: number): Flat[] {
  const normals = sideNormals(edge);
  const out: Flat[] = [];
  for (let k = run.start; k <= run.end; k++) {
    const [dx, dz] = offsetAt(
      normals,
      k > run.start ? k - 1 : null,
      k < run.end ? k : null,
      apronW,
    );
    const p = edge.points[k] as Flat;
    out.push({ x: p.x + dx, z: p.z + dz });
  }
  return out;
}

/** Контуры выреза земли под проезд: на съездах контур обходит пандус, чтобы лента пандуса
 *  лежала в вырезе, а не под землёй. */
export function groundCutRings(
  edges: readonly RoadEdge[],
  apronW: number,
  rampM: number,
): { points: Flat[]; island: boolean }[] {
  return edges.map((edge) => {
    const n = edge.points.length - 1;
    const runs = apronRuns(edge, rampM);
    const points: Flat[] = [];
    let i = 0;
    while (i < n) {
      const run = runs.find((r) => r.start === i);
      if (!run) {
        points.push(edge.points[i] as Flat);
        i++;
        continue;
      }
      points.push(edge.points[run.start] as Flat, ...apronLine(edge, run, apronW));
      i = run.end;
      if (i < n) points.push(edge.points[i] as Flat);
    }
    const first = points[0] as Flat;
    const last = points.at(-1) as Flat;
    if (dist(first, last) > 1e-9) points.push({ ...first });
    return { points, island: edge.island };
  });
}

/** Полоса между двумя ломаными одной длины на отметках yNear и yFar: лицом вверх, u - метры
 *  вдоль, v - 0 у near и 1 у far. */
function strip(
  near: readonly Flat[],
  far: readonly Flat[],
  yNear: number | readonly number[],
  yFar: number,
  pos: number[],
  nor: number[],
  uv: number[],
): void {
  const nearY = (k: number) => (typeof yNear === 'number' ? yNear : (yNear[k] ?? 0));
  let along = 0;
  for (let k = 0; k + 1 < near.length; k++) {
    const a = near[k] as Flat;
    const b = near[k + 1] as Flat;
    const c = far[k + 1] as Flat;
    const d = far[k] as Flat;
    const u0 = along;
    const u1 = along + dist(a, b);
    along = u1;
    const A = [a.x, nearY(k), a.z, u0, 0];
    const B = [b.x, nearY(k + 1), b.z, u1, 0];
    const C = [c.x, yFar, c.z, u1, 1];
    const D = [d.x, yFar, d.z, u0, 1];
    // Лицо вверх: обход против часовой, если смотреть сверху.
    const up = (b.x - a.x) * (d.z - a.z) - (b.z - a.z) * (d.x - a.x) < 0;
    const tris = up ? [A, B, C, A, C, D] : [A, C, B, A, D, C];
    for (const v of tris) {
      pos.push(v[0] ?? 0, v[1] ?? 0, v[2] ?? 0);
      nor.push(0, 1, 0);
      uv.push(v[3] ?? 0, v[4] ?? 0);
    }
  }
}

function geometryOf(pos: number[], nor: number[], uv: number[]): THREE.BufferGeometry {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.computeBoundingSphere();
  return g;
}

/** Пандусы тротуара к пониженному борту: лента от края проезда до линии выреза земли
 *  (уровень тротуара, 0). У борта лента на CURB_ABOVE_WALK_M ниже его верха по профилю
 *  curbProfile, то есть над переходными камнями поднимается до тротуара: концы ленты
 *  сходятся с землёй без вертикальной щели. */
export function apronGeometry(
  edges: readonly RoadEdge[],
  apronW: number,
  topFull: number,
  topLow: number,
  rampM: number,
): THREE.BufferGeometry {
  const pos: number[] = [];
  const nor: number[] = [];
  const uv: number[] = [];
  for (const edge of edges) {
    const tops = curbProfile(edge, topFull, topLow, rampM).tops ?? [];
    for (const run of apronRuns(edge, rampM)) {
      const near = edge.points.slice(run.start, run.end + 1);
      const yNear = near.map((_, k) => (tops[run.start + k] ?? topFull) - CURB_ABOVE_WALK_M);
      strip(near, apronLine(edge, run, apronW), yNear, 0, pos, nor, uv);
    }
  }
  return geometryOf(pos, nor, uv);
}

/** Верх борта по точкам контура: topFull, на съезде topLow, за rampM до и после съезда -
 *  переходный камень с линейным понижением. */
export function curbProfile(edge: RoadEdge, topFull: number, topLow: number, rampM: number): Line {
  const n = edge.points.length - 1;
  const s: number[] = [0];
  for (let i = 0; i < n; i++) {
    s.push((s[i] ?? 0) + dist(edge.points[i] as Flat, edge.points[i + 1] as Flat));
  }
  const total = s[n] ?? 0;
  const runs = runsOf(edge.lowered);
  const circular = (a: number, b: number) => {
    const d = Math.abs(a - b) % total;
    return Math.min(d, total - d);
  };
  const tops = edge.points.map((_, k) => {
    const sk = s[k] ?? 0;
    let top = topFull;
    for (const run of runs) {
      const sa = s[run.start] ?? 0;
      const sb = s[run.end] ?? 0;
      let share = 0;
      if (sk >= sa && sk <= sb) share = 1;
      else {
        const d = Math.min(circular(sk, sa), circular(sk, sb));
        if (d < rampM) share = 1 - d / rampM;
      }
      top = Math.min(top, topFull + (topLow - topFull) * share);
    }
    return top;
  });
  return { points: edge.points, tops };
}

/** Лоток: полоса шириной width по асфальту со стороны проезда вдоль полного борта. */
export function gutterGeometry(
  edges: readonly RoadEdge[],
  width: number,
  y: number,
): THREE.BufferGeometry {
  const pos: number[] = [];
  const nor: number[] = [];
  const uv: number[] = [];
  for (const edge of edges) {
    const normals = sideNormals(edge);
    const n = edge.points.length - 1;
    // Ряды полного борта (между съездами), с обходом через начало кольца.
    const full = edge.lowered.map((v) => !v);
    for (const run of runsOf(full)) {
      const near: Flat[] = [];
      const far: Flat[] = [];
      for (let k = run.start; k <= run.end; k++) {
        const p = edge.points[k] as Flat;
        const before = k > run.start ? k - 1 : k === 0 ? (full[n - 1] ? n - 1 : null) : null;
        const after = k < run.end ? k : k === n ? (full[0] ? 0 : null) : null;
        const [dx, dz] = offsetAt(normals, before, after, width);
        near.push(p);
        far.push({ x: p.x - dx, z: p.z - dz });
      }
      strip(near, far, y, y, pos, nor, uv);
    }
  }
  return geometryOf(pos, nor, uv);
}
