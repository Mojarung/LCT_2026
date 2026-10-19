/* Ограда детской площадки - низкий деревянный штакетник, а не металлическая решётка: так
 * она выглядит на панораме Харьковской у дома 1А (Яндекс, 2023), а решётка делала площадку
 * похожей на вольер. Ограда считается оградой площадки, если большая часть её длины идёт не
 * дальше PLAYGROUND_FENCE_M от резины площадки (контур special в surface.json). */

import type { Flat, Line } from './types';

export const PLAYGROUND_FENCE_M = 1.5;
/** Доля длины ограды у площадки, с которой она - ограда площадки. */
const PLAYGROUND_SHARE = 0.5;
const SAMPLE_M = 0.5;

type Ring = readonly Flat[];

export interface FenceKinds {
  playground: Line[];
  other: Line[];
}

export function splitPlaygroundFences(
  lines: readonly Line[],
  playgrounds: readonly (readonly Ring[])[],
): FenceKinds {
  const out: FenceKinds = { playground: [], other: [] };
  const boxes = playgrounds.map((rings) => bounds(rings[0] ?? [], PLAYGROUND_FENCE_M));
  for (const line of lines) {
    const samples = sample(line.points, SAMPLE_M);
    const near = samples.filter((p) =>
      playgrounds.some(
        (rings, i) => inBox(boxes[i], p) && distanceToArea(rings, p) <= PLAYGROUND_FENCE_M,
      ),
    ).length;
    (samples.length && near / samples.length >= PLAYGROUND_SHARE ? out.playground : out.other).push(
      line,
    );
  }
  return out;
}

/** Штакетины вдоль линий: точка и поворот доски по ходу пролёта. */
export function picketSpots(
  lines: readonly Line[],
  step: number,
): { x: number; z: number; yaw: number }[] {
  const out: { x: number; z: number; yaw: number }[] = [];
  for (const line of lines) {
    let carry = step / 2;
    for (let i = 0; i + 1 < line.points.length; i++) {
      const a = line.points[i];
      const b = line.points[i + 1];
      if (!a || !b) continue;
      const len = Math.hypot(b.x - a.x, b.z - a.z);
      const yaw = -Math.atan2(b.z - a.z, b.x - a.x);
      let u = carry;
      for (; u < len; u += step) {
        out.push({ x: a.x + ((b.x - a.x) * u) / len, z: a.z + ((b.z - a.z) * u) / len, yaw });
      }
      carry = u - len;
    }
  }
  return out;
}

function sample(points: readonly Flat[], step: number): Flat[] {
  const out: Flat[] = [];
  for (let i = 0; i + 1 < points.length; i++) {
    const a = points[i];
    const b = points[i + 1];
    if (!a || !b) continue;
    const n = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.z - a.z) / step));
    for (let k = 0; k < n; k++) {
      out.push({ x: a.x + ((b.x - a.x) * k) / n, z: a.z + ((b.z - a.z) * k) / n });
    }
  }
  const last = points.at(-1);
  if (last) out.push(last);
  return out;
}

function bounds(ring: Ring, pad: number): [number, number, number, number] {
  let x0 = Infinity;
  let z0 = Infinity;
  let x1 = -Infinity;
  let z1 = -Infinity;
  for (const p of ring) {
    x0 = Math.min(x0, p.x);
    z0 = Math.min(z0, p.z);
    x1 = Math.max(x1, p.x);
    z1 = Math.max(z1, p.z);
  }
  return [x0 - pad, z0 - pad, x1 + pad, z1 + pad];
}

function inBox(box: [number, number, number, number] | undefined, p: Flat): boolean {
  return !!box && p.x >= box[0] && p.x <= box[2] && p.z >= box[1] && p.z <= box[3];
}

/** Расстояние от точки до многоугольника с дырами: 0 внутри. */
export function distanceToArea(rings: readonly Ring[], p: Flat): number {
  let inside = false;
  let best = Infinity;
  for (const ring of rings) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const a = ring[i] as Flat;
      const b = ring[j] as Flat;
      if (a.z > p.z !== b.z > p.z && p.x < ((b.x - a.x) * (p.z - a.z)) / (b.z - a.z) + a.x) {
        inside = !inside;
      }
      best = Math.min(best, segmentDistance(p, a, b));
    }
  }
  return inside ? 0 : best;
}

function segmentDistance(p: Flat, a: Flat, b: Flat): number {
  const vx = b.x - a.x;
  const vz = b.z - a.z;
  const len2 = vx * vx + vz * vz;
  const t = len2 > 0 ? Math.max(0, Math.min(1, ((p.x - a.x) * vx + (p.z - a.z) * vz) / len2)) : 0;
  return Math.hypot(p.x - (a.x + vx * t), p.z - (a.z + vz * t));
}
