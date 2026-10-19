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

/** Радиус скругления углов ограды, м: как у резины площадок по чертежу (0,5-0,6 м). */
export const FENCE_CORNER_M = 0.6;
/** Поворот меньше этого - не угол, а излом линии съёмки: не скругляется, рад. */
const CORNER_MIN_TURN = (20 * Math.PI) / 180;

/** Углы ограды - дугой одного радиуса везде. Ось ограды из съёмки то с острым углом, то с
 *  фаской из двух близких вершин, и рядом стояли прямой угол и скруглённый (пользователь,
 *  19.10.2026: «если ты закругляешь забор, то закругляй везде»). Радиус ограничен половиной
 *  соседних отрезков: короткий отрезок не выворачивается. Замкнутая линия скругляется и в
 *  точке замыкания. */
export function roundFenceCorners(lines: readonly Line[], radius = FENCE_CORNER_M): Line[] {
  return lines.map((line) => {
    const pts = line.points;
    if (pts.length < 3) return line;
    const first = pts[0] as Flat;
    const last = pts[pts.length - 1] as Flat;
    const closed = Math.hypot(first.x - last.x, first.z - last.z) < 1e-6;
    const ring = closed ? pts.slice(0, -1) : [...pts];
    const n = ring.length;
    const out: Flat[] = [];
    for (let i = 0; i < n; i++) {
      const p = ring[i] as Flat;
      const inner = closed || (i > 0 && i < n - 1);
      if (!inner) {
        out.push(p);
        continue;
      }
      const a = ring[(i - 1 + n) % n] as Flat;
      const c = ring[(i + 1) % n] as Flat;
      const la = Math.hypot(p.x - a.x, p.z - a.z);
      const lc = Math.hypot(c.x - p.x, c.z - p.z);
      if (la < 1e-6 || lc < 1e-6) {
        out.push(p);
        continue;
      }
      const ux = (a.x - p.x) / la;
      const uz = (a.z - p.z) / la;
      const vx = (c.x - p.x) / lc;
      const vz = (c.z - p.z) / lc;
      // Угол между отрезками в вершине: pi - прямо, меньше - поворот.
      const inside = Math.acos(Math.max(-1, Math.min(1, ux * vx + uz * vz)));
      const turn = Math.PI - inside;
      if (turn < CORNER_MIN_TURN || inside < 1e-3) {
        out.push(p);
        continue;
      }
      // Точки касания дуги на отрезках: на расстоянии r / tan(inside / 2) от вершины.
      const tan = Math.tan(inside / 2);
      const cut = Math.min(radius / tan, la / 2, lc / 2);
      const r = cut * tan;
      const t1 = { x: p.x + ux * cut, z: p.z + uz * cut };
      const t2 = { x: p.x + vx * cut, z: p.z + vz * cut };
      // Центр дуги - по биссектрисе на r / sin(inside / 2) от вершины.
      const bx = ux + vx;
      const bz = uz + vz;
      const bl = Math.hypot(bx, bz) || 1;
      const d = r / Math.sin(inside / 2);
      const cx = p.x + (bx / bl) * d;
      const cz = p.z + (bz / bl) * d;
      const a1 = Math.atan2(t1.z - cz, t1.x - cx);
      let a2 = Math.atan2(t2.z - cz, t2.x - cx);
      // Короткая дуга: разворот не больше pi.
      while (a2 - a1 > Math.PI) a2 -= 2 * Math.PI;
      while (a2 - a1 < -Math.PI) a2 += 2 * Math.PI;
      const steps = Math.max(2, Math.ceil(Math.abs(a2 - a1) / (Math.PI / 12)));
      for (let k = 0; k <= steps; k++) {
        const t = a1 + ((a2 - a1) * k) / steps;
        out.push({ x: cx + Math.cos(t) * r, z: cz + Math.sin(t) * r });
      }
    }
    if (closed && out[0]) out.push({ ...out[0] });
    return { ...line, points: out };
  });
}
