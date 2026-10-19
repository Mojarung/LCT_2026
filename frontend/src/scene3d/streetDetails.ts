/* Мелочи улицы, привязанные к данным: лунка у каждого дерева плана, люки колодцев на трассах
 * сетей под покрытием, скамейки и урны вдоль пешеходных дорожек. Чистая логика расстановки;
 * геометрия - в streetDetailsMesh.ts.
 *
 * Лунка показывает, где посадка стоит в покрытии: в плитке и асфальте - чугунная приствольная
 * решётка 1,5 x 1,5 м, на газоне - круг мульчи. Люки ставятся по линиям сетей подосновы через
 * MANHOLE_STEP_M, только там, где трасса под покрытием (на газоне люк скрыт дёрном). Скамейки -
 * на плитке у края газона через BENCH_STEP_M, спинкой к газону, урна рядом. */

import type { Flat, Line, Plant } from './types';

/** Что лежит в точке: газон, плитка, асфальт тротуара или проезд (ниже на высоту борта). */
export type Ground = 'grass' | 'pavers' | 'asphalt' | 'road';

export interface Spot {
  x: number;
  z: number;
  /** Поворот вокруг вертикали, рад: ось x модели - вдоль края. */
  angle: number;
  /** Скамейка со спинкой (только спиной к ограде, benchBack). */
  back?: boolean;
}

/** Ограда дальше этого за скамейкой - не опора для спинки, м. */
export const BENCH_FENCE_M = 1.3;
/** Участок ограды круче этого к скамейке - не за её спиной. */
const BENCH_FENCE_COS = Math.cos((35 * Math.PI) / 180);

/** Спинка у скамейки - только у ограды: скамейка встаёт спиной к ней. Без ограды рядом -
 *  скамейка без спинки, как длинные лавки вдоль живой изгороди на панорамах (пользователь,
 *  19.10.2026: «если рядом есть забор, ставить спинкой к забору, а где нет - без спинки»).
 *  Ограда считается, если её участок ближе reach и почти параллелен скамейке. */
export function benchBack(
  bench: Spot,
  fences: readonly Line[],
  reach = BENCH_FENCE_M,
): { angle: number; back: boolean } {
  const ax = Math.cos(bench.angle);
  const az = -Math.sin(bench.angle);
  let best = reach;
  let normal: Flat | null = null;
  for (const line of fences) {
    for (let i = 0; i + 1 < line.points.length; i++) {
      const a = line.points[i];
      const c = line.points[i + 1];
      if (!a || !c) continue;
      const vx = c.x - a.x;
      const vz = c.z - a.z;
      const len = Math.hypot(vx, vz);
      if (len < 1e-6) continue;
      const t = Math.max(
        0,
        Math.min(1, ((bench.x - a.x) * vx + (bench.z - a.z) * vz) / (len * len)),
      );
      const qx = a.x + vx * t;
      const qz = a.z + vz * t;
      const d = Math.hypot(bench.x - qx, bench.z - qz);
      if (d >= best || d < 1e-6) continue;
      if (Math.abs((vx * ax + vz * az) / len) < BENCH_FENCE_COS) continue;
      best = d;
      normal = { x: (bench.x - qx) / d, z: (bench.z - qz) / d };
    }
  }
  if (!normal) return { angle: bench.angle, back: false };
  // Сиденье смотрит от ограды: +z модели - по нормали от ограды к скамейке.
  return { angle: Math.atan2(normal.x, normal.z), back: true };
}

export const MANHOLE_STEP_M = 40;
export const BENCH_STEP_M = 32;
/** Сети с колодцами: у кабелей связи и силовых тоже бывают, но реже - их не ставим. */
const WELL_KINDS = new Set([
  'utility.water',
  'utility.sewer',
  'utility.storm',
  'utility.drain',
  'utility.heat',
  'utility.telecom',
]);
/** Ближе этого два люка не ставятся: сети идут пучком, колодцы на соседних трассах слипаются. */
const MANHOLE_GAP_M = 8;

export function treePits(
  plants: readonly Plant[],
  groundAt: (x: number, z: number) => Ground,
): { grates: Flat[]; mulch: Flat[] } {
  const grates: Flat[] = [];
  const mulch: Flat[] = [];
  for (const p of plants) {
    if (p.existing || p.type !== 'tree' || p.strip) continue;
    (groundAt(p.x, p.z) === 'grass' ? mulch : grates).push({ x: p.x, z: p.z });
  }
  return { grates, mulch };
}

/** Точки вдоль ломаной через step метров, с направлением отрезка. */
function along(line: Line, step: number, offset: number): Spot[] {
  const out: Spot[] = [];
  let next = offset;
  let walked = 0;
  for (let i = 0; i + 1 < line.points.length; i++) {
    const a = line.points[i];
    const b = line.points[i + 1];
    if (!a || !b) continue;
    const len = Math.hypot(b.x - a.x, b.z - a.z);
    if (len < 1e-6) continue;
    const angle = Math.atan2(-(b.z - a.z), b.x - a.x);
    while (next <= walked + len) {
      const t = (next - walked) / len;
      out.push({ x: a.x + (b.x - a.x) * t, z: a.z + (b.z - a.z) * t, angle });
      next += step;
    }
    walked += len;
  }
  return out;
}

/** Штрихи одного знака колодца съёмки (круг, засечки) - не дальше этого друг от друга, м. */
const WELL_SIGN_M = 1.2;

/** Колодцы съёмки (слой «Колодцы», знак KOLOD - класс utility.access): каждый знак рисуется
 *  несколькими штрихами, они собираются в один люк по центру. На газоне люк скрыт дёрном. */
export function surveyManholes(
  utilities: readonly { kind: string; lines: Line[] }[],
  groundAt: (x: number, z: number) => Ground,
): Spot[] {
  const centres: Flat[] = [];
  for (const group of utilities) {
    if (group.kind !== 'utility.access') continue;
    for (const line of group.lines) {
      const pts = line.points;
      if (!pts.length) continue;
      centres.push({
        x: pts.reduce((sum, p) => sum + p.x, 0) / pts.length,
        z: pts.reduce((sum, p) => sum + p.z, 0) / pts.length,
      });
    }
  }
  // Склейка штрихов: сетка в шаг склейки, сосед ищется в девяти клетках.
  const clusters: { x: number; z: number; n: number }[] = [];
  const grid = new Map<string, number[]>();
  const key = (x: number, z: number) =>
    `${String(Math.floor(x / WELL_SIGN_M))}:${String(Math.floor(z / WELL_SIGN_M))}`;
  for (const c of centres) {
    const cx = Math.floor(c.x / WELL_SIGN_M);
    const cz = Math.floor(c.z / WELL_SIGN_M);
    let found = -1;
    for (let dx = -1; dx <= 1 && found < 0; dx++) {
      for (let dz = -1; dz <= 1 && found < 0; dz++) {
        for (const k of grid.get(`${String(cx + dx)}:${String(cz + dz)}`) ?? []) {
          const q = clusters[k];
          if (q && Math.hypot(q.x - c.x, q.z - c.z) < WELL_SIGN_M) {
            found = k;
            break;
          }
        }
      }
    }
    if (found >= 0) {
      const q = clusters[found];
      if (q) {
        q.x = (q.x * q.n + c.x) / (q.n + 1);
        q.z = (q.z * q.n + c.z) / (q.n + 1);
        q.n += 1;
      }
      continue;
    }
    clusters.push({ ...c, n: 1 });
    const k = key(c.x, c.z);
    grid.set(k, [...(grid.get(k) ?? []), clusters.length - 1]);
  }
  return clusters
    .filter((c) => groundAt(c.x, c.z) !== 'grass')
    .map((c) => ({ x: c.x, z: c.z, angle: 0 }));
}

/** Люки: колодцы съёмки, где они нарисованы; без них - условно по трассам сетей через
 *  MANHOLE_STEP_M (пользователь, 19.10.2026: брать из чертежа, а не раскидывать). */
export function manholeSpots(
  utilities: readonly { kind: string; lines: Line[] }[],
  groundAt: (x: number, z: number) => Ground,
): Spot[] {
  if (utilities.some((g) => g.kind === 'utility.access' && g.lines.length)) {
    return surveyManholes(utilities, groundAt);
  }
  const out: Spot[] = [];
  for (const group of utilities) {
    if (!WELL_KINDS.has(group.kind)) continue;
    for (const line of group.lines) {
      for (const s of along(line, MANHOLE_STEP_M, MANHOLE_STEP_M / 2)) {
        if (groundAt(s.x, s.z) === 'grass') continue;
        if (out.some((q) => Math.hypot(q.x - s.x, q.z - s.z) < MANHOLE_GAP_M)) continue;
        out.push(s);
      }
    }
  }
  return out;
}

/** Скамейки на плитке у края газона: спинкой к газону, сиденьем к дорожке. Урна - справа
 *  от скамейки. Места у столбов и стволов пропускаются. */
export function benchSpots(
  gardenEdges: readonly Line[],
  groundAt: (x: number, z: number) => Ground,
  obstacles: readonly Flat[],
): { benches: Spot[]; bins: Spot[] } {
  const benches: Spot[] = [];
  const bins: Spot[] = [];
  const clear = (x: number, z: number, r: number) =>
    obstacles.every((o) => Math.hypot(o.x - x, o.z - z) >= r) &&
    benches.every((b) => Math.hypot(b.x - x, b.z - z) >= BENCH_STEP_M / 2);
  for (const line of gardenEdges) {
    for (const s of along(line, BENCH_STEP_M, BENCH_STEP_M / 2)) {
      // Нормаль к краю (влево по ходу линии) и её сторона с плиткой.
      const nx = -Math.sin(s.angle);
      const nz = -Math.cos(s.angle);
      // Тротуар - плитка или асфальт: с подписью «А» тротуары съёмки асфальтовые.
      const walk = (g: Ground) => g === 'pavers' || g === 'asphalt';
      const side = [1, -1].find(
        (k) =>
          walk(groundAt(s.x + nx * k * 0.9, s.z + nz * k * 0.9)) &&
          walk(groundAt(s.x + nx * k * 2.2, s.z + nz * k * 2.2)) &&
          groundAt(s.x - nx * k * 0.9, s.z - nz * k * 0.9) === 'grass',
      );
      if (side === undefined) continue;
      const x = s.x + nx * side * 0.55;
      const z = s.z + nz * side * 0.55;
      if (!clear(x, z, 2)) continue;
      // Модель смотрит сиденьем в +z своей системы: поворот к дорожке.
      const facing = Math.atan2(nx * side, nz * side);
      benches.push({ x, z, angle: facing });
      const tx = Math.cos(s.angle);
      const tz = -Math.sin(s.angle);
      bins.push({ x: x + tx * 1.4, z: z + tz * 1.4, angle: facing });
    }
  }
  return { benches, bins };
}
