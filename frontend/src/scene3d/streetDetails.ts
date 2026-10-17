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

export function manholeSpots(
  utilities: readonly { kind: string; lines: Line[] }[],
  groundAt: (x: number, z: number) => Ground,
): Spot[] {
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
      const side = [1, -1].find(
        (k) =>
          groundAt(s.x + nx * k * 0.9, s.z + nz * k * 0.9) === 'pavers' &&
          groundAt(s.x + nx * k * 2.2, s.z + nz * k * 2.2) === 'pavers' &&
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
