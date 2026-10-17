/* Ограды подосновы - сплошными линиями. Чистая логика.
 *
 * В съёмке ограда часто нарисована пунктиром: отрезки по метру-два с разрывами (блоки
 * MicroStation), и в 3D забор шёл кусками - «то есть, то нет». Куски, концы которых сходятся
 * ближе GAP_M и которые продолжают друг друга по направлению (поворот до TURN_DEG), сшиваются
 * в одну ломаную. Настоящие калитки и проходы шире GAP_M остаются разрывами. */

import type { Flat, Line } from './types';

export const GAP_M = 2.6;
const TURN_DEG = 35;

function direction(a: Flat, b: Flat): [number, number] {
  const len = Math.hypot(b.x - a.x, b.z - a.z) || 1;
  return [(b.x - a.x) / len, (b.z - a.z) / len];
}

/** Можно ли продолжить ломаную line (её конец end) ломаной next (её начало start). */
function continues(tail: [Flat, Flat], head: [Flat, Flat]): boolean {
  const [p, end] = tail;
  const [start, q] = head;
  const gap = Math.hypot(start.x - end.x, start.z - end.z);
  if (gap > GAP_M) return false;
  const d1 = direction(p, end);
  const d2 = direction(start, q);
  const cos = d1[0] * d2[0] + d1[1] * d2[1];
  if (cos < Math.cos((TURN_DEG * Math.PI) / 180)) return false;
  if (gap < 0.05) return true;
  // Разрыв должен лежать по ходу ограды, а не сбоку: иначе сошьются две параллельные.
  const dg = direction(end, start);
  return dg[0] * d1[0] + dg[1] * d1[1] > Math.cos((TURN_DEG * Math.PI) / 180);
}

const ORIGIN: Flat = { x: 0, z: 0 };
const at = (pts: readonly Flat[], i: number): Flat => pts[i < 0 ? pts.length + i : i] ?? ORIGIN;
const first = (pts: readonly Flat[]): [Flat, Flat] => [at(pts, 0), at(pts, 1)];
const last = (pts: readonly Flat[]): [Flat, Flat] => [at(pts, -2), at(pts, -1)];

export function chainFences(lines: readonly Line[]): Line[] {
  const pool = lines.map((l) => [...l.points]).filter((pts) => pts.length >= 2);
  const used = new Uint8Array(pool.length);
  const out: Line[] = [];
  for (let i = 0; i < pool.length; i++) {
    if (used[i]) continue;
    used[i] = 1;
    let chain = pool[i] ?? [];
    for (let grew = true; grew;) {
      grew = false;
      for (let j = 0; j < pool.length && !grew; j++) {
        if (used[j]) continue;
        const other = pool[j] ?? [];
        for (const candidate of [other, [...other].reverse()]) {
          if (continues(last(chain), first(candidate))) {
            chain = [...chain, ...candidate];
          } else if (continues(last(candidate), first(chain))) {
            chain = [...candidate, ...chain];
          } else {
            continue;
          }
          used[j] = 1;
          grew = true;
          break;
        }
      }
    }
    out.push({ points: chain });
  }
  return out;
}

/** Ограда, нарисованная двумя параллельными линиями (обе стороны условного знака), в 3D
 *  вставала двумя рядами решётки. Линии разбираются от длинной к короткой; отрезок, который
 *  целиком лежит ближе TWIN_M к уже принятой ограде и идёт вдоль неё, отбрасывается. */
export const TWIN_M = 0.9;

function segmentDistance(p: Flat, a: Flat, b: Flat): number {
  const vx = b.x - a.x;
  const vz = b.z - a.z;
  const len2 = vx * vx + vz * vz;
  const t = len2 ? Math.max(0, Math.min(1, ((p.x - a.x) * vx + (p.z - a.z) * vz) / len2)) : 0;
  return Math.hypot(a.x + vx * t - p.x, a.z + vz * t - p.z);
}

function lengthOf(line: Line): number {
  let s = 0;
  for (let i = 1; i < line.points.length; i++) {
    const a = line.points[i - 1] ?? ORIGIN;
    const b = line.points[i] ?? ORIGIN;
    s += Math.hypot(b.x - a.x, b.z - a.z);
  }
  return s;
}

export function dropTwinFences(lines: readonly Line[]): Line[] {
  const kept: [Flat, Flat][] = [];
  const out: Line[] = [];
  const parallelCos = Math.cos((TURN_DEG * Math.PI) / 180);
  const covered = (a: Flat, b: Flat): boolean => {
    const [dx, dz] = direction(a, b);
    const len = Math.hypot(b.x - a.x, b.z - a.z);
    const steps = Math.max(2, Math.ceil(len / 0.5));
    for (let k = 0; k <= steps; k++) {
      const p = { x: a.x + ((b.x - a.x) * k) / steps, z: a.z + ((b.z - a.z) * k) / steps };
      const near = kept.some(([s0, s1]) => {
        const [ex, ez] = direction(s0, s1);
        if (Math.abs(dx * ex + dz * ez) < parallelCos) return false;
        return segmentDistance(p, s0, s1) < TWIN_M;
      });
      if (!near) return false;
    }
    return true;
  };
  const order = [...lines].sort((x, y) => lengthOf(y) - lengthOf(x));
  for (const line of order) {
    let run: Flat[] = [];
    const runs: Flat[][] = [];
    for (let i = 0; i + 1 < line.points.length; i++) {
      const a = line.points[i] ?? ORIGIN;
      const b = line.points[i + 1] ?? ORIGIN;
      if (covered(a, b)) {
        if (run.length > 1) runs.push(run);
        run = [];
        continue;
      }
      if (!run.length) run.push(a);
      run.push(b);
    }
    if (run.length > 1) runs.push(run);
    for (const pts of runs) {
      out.push({ points: pts });
      for (let i = 0; i + 1 < pts.length; i++) kept.push([pts[i] ?? ORIGIN, pts[i + 1] ?? ORIGIN]);
    }
  }
  return out;
}
