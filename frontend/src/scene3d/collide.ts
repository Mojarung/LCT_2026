/* Пешеход не проходит сквозь стены: точка на земле с радиусом тела выталкивается из контуров
 * зданий. Контуров на улице тысячи, поэтому они разложены по сетке ячеек, и на шаг
 * проверяются только соседние стены. Ниже колена (крыльцо, мусорная площадка) не мешает:
 * на них пешеход просто стоит глазами на прежней высоте, это честнее, чем стена в полметра. */

import type { Building, Flat } from './types';

export const BODY_M = 0.35;
const CELL_M = 16;
const STEP_OVER_M = 0.6;

interface Segment {
  ax: number;
  az: number;
  bx: number;
  bz: number;
}

export class Walls {
  private readonly cells = new Map<string, Segment[]>();
  private readonly rings: Flat[][] = [];

  constructor(buildings: readonly Building[]) {
    for (const b of buildings) {
      if (b.height <= STEP_OVER_M) continue;
      for (const ring of b.rings) {
        this.rings.push(ring);
        for (let i = 0; i < ring.length; i++) {
          const a = ring[i];
          const c = ring[(i + 1) % ring.length];
          if (a && c) this.add({ ax: a.x, az: a.z, bx: c.x, bz: c.z });
        }
      }
    }
  }

  get size(): number {
    return this.rings.length;
  }

  private add(s: Segment): void {
    const x0 = Math.floor((Math.min(s.ax, s.bx) - BODY_M) / CELL_M);
    const x1 = Math.floor((Math.max(s.ax, s.bx) + BODY_M) / CELL_M);
    const z0 = Math.floor((Math.min(s.az, s.bz) - BODY_M) / CELL_M);
    const z1 = Math.floor((Math.max(s.az, s.bz) + BODY_M) / CELL_M);
    for (let x = x0; x <= x1; x++) {
      for (let z = z0; z <= z1; z++) {
        const key = `${x}:${z}`;
        const list = this.cells.get(key);
        if (list) list.push(s);
        else this.cells.set(key, [s]);
      }
    }
  }

  near(p: Flat): Segment[] {
    return this.cells.get(`${Math.floor(p.x / CELL_M)}:${Math.floor(p.z / CELL_M)}`) ?? [];
  }

  /** Шаг пересекает стену: за один кадр тело не должно оказаться по ту её сторону. */
  private crosses(from: Flat, to: Flat): boolean {
    const cells = new Set([...this.near(from), ...this.near(to)]);
    for (const s of cells) {
      if (segmentsCross(from, to, { x: s.ax, z: s.az }, { x: s.bx, z: s.bz })) return true;
    }
    return false;
  }

  /** Сдвинуть шаг from -> to так, чтобы тело не вошло в стену: скольжение вдоль неё. */
  resolve(from: Flat, to: Flat): Flat {
    let p = { ...to };
    if (this.crosses(from, p)) {
      // Сквозь стену нельзя: пробуем шаг по одной оси - это и есть скольжение вдоль стены.
      const alongX = { x: to.x, z: from.z };
      const alongZ = { x: from.x, z: to.z };
      if (!this.crosses(from, alongX)) p = alongX;
      else if (!this.crosses(from, alongZ)) p = alongZ;
      else return { ...from };
    }
    // Три прохода: в углу тело упирается в две стены сразу.
    for (let pass = 0; pass < 3; pass++) {
      let pushed = false;
      for (const s of this.near(p)) {
        const q = closest(p, s);
        const dx = p.x - q.x;
        const dz = p.z - q.z;
        const d = Math.hypot(dx, dz);
        if (d >= BODY_M) continue;
        if (d < 1e-6) {
          p = { ...from };
          return p;
        }
        const push = (BODY_M - d) / d;
        p = { x: p.x + dx * push, z: p.z + dz * push };
        pushed = true;
      }
      if (!pushed) break;
    }
    return p;
  }
}

function closest(p: Flat, s: Segment): Flat {
  const vx = s.bx - s.ax;
  const vz = s.bz - s.az;
  const len2 = vx * vx + vz * vz;
  const t = len2 > 0 ? Math.max(0, Math.min(1, ((p.x - s.ax) * vx + (p.z - s.az) * vz) / len2)) : 0;
  return { x: s.ax + vx * t, z: s.az + vz * t };
}

function orient(a: Flat, b: Flat, c: Flat): number {
  return (b.x - a.x) * (c.z - a.z) - (b.z - a.z) * (c.x - a.x);
}

/** Отрезки пересекаются по внутренним точкам: касание концом не считается. */
export function segmentsCross(a: Flat, b: Flat, c: Flat, d: Flat): boolean {
  const d1 = orient(c, d, a);
  const d2 = orient(c, d, b);
  const d3 = orient(a, b, c);
  const d4 = orient(a, b, d);
  return d1 * d2 < 0 && d3 * d4 < 0;
}
