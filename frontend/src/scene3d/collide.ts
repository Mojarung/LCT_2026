/* Тело камеры не проходит сквозь объекты: точка с радиусом тела выталкивается из стен домов,
 * оград, стволов, опор и машин. Препятствие держит, пока камера ниже его верха: над оградой
 * перелететь можно, сквозь неё - нет (пользователь, 19.10.2026: «сделай, чтобы летать сквозь
 * объекты мы не могли, чтобы всё было физично»). Над домом и машиной пол поднимается до их
 * верха (roofAt): сквозь крышу вниз не провалиться. Контуров на улице тысячи, поэтому они
 * разложены по сетке ячеек, и на шаг проверяются только соседние. Ниже колена (крыльцо,
 * мусорная площадка) не мешает: на них пешеход просто стоит глазами на прежней высоте. */

import type { Building, Flat, Line } from './types';

export const BODY_M = 0.35;
const CELL_M = 16;
const STEP_OVER_M = 0.6;
/** Запас над верхом препятствия, при котором камера его уже не задевает, м. */
const CLEAR_M = 0.3;

interface Segment {
  ax: number;
  az: number;
  bx: number;
  bz: number;
  height: number;
}

interface Footprint {
  ring: readonly Flat[];
  height: number;
  box: [number, number, number, number];
}

/** Сетка пикселей маски земли: прямоугольник x0, z0, ширина, высота и шаг. */
export interface GridFrame {
  width: number;
  height: number;
  metresPerPx: number;
  rect: readonly [number, number, number, number];
}

/** Площадь контура, начиная с которой его внутренность не размечается клетками (дома: их
 *  стены и так размечены, а внутри дома людей не ставят по маске). */
const FILL_MAX_M2 = 200;

export class Walls {
  private readonly cells = new Map<string, Segment[]>();
  private readonly roofs = new Map<string, Footprint[]>();
  private readonly all: Segment[] = [];
  private readonly footprints: Footprint[] = [];
  private count = 0;

  constructor(buildings: readonly Building[]) {
    this.addRings(
      buildings.flatMap((b) => b.rings),
      0,
      buildings.flatMap((b) => b.rings.map(() => b.height)),
    );
  }

  get size(): number {
    return this.count;
  }

  /** Замкнутые контуры высотой height (или своей высотой каждого из heights): стена и крыша. */
  addRings(rings: readonly (readonly Flat[])[], height: number, heights?: readonly number[]): void {
    rings.forEach((ring, index) => {
      const h = heights?.[index] ?? height;
      if (h <= STEP_OVER_M || ring.length < 3) return;
      this.count += 1;
      for (let i = 0; i < ring.length; i++) {
        const a = ring[i];
        const c = ring[(i + 1) % ring.length];
        if (a && c) this.add({ ax: a.x, az: a.z, bx: c.x, bz: c.z, height: h });
      }
      const xs = ring.map((p) => p.x);
      const zs = ring.map((p) => p.z);
      const fp: Footprint = {
        ring,
        height: h,
        box: [Math.min(...xs), Math.min(...zs), Math.max(...xs), Math.max(...zs)],
      };
      this.footprints.push(fp);
      for (const key of this.keys(fp.box[0], fp.box[1], fp.box[2], fp.box[3])) {
        const list = this.roofs.get(key);
        if (list) list.push(fp);
        else this.roofs.set(key, [fp]);
      }
    });
  }

  /** Клетки сетки, где стоит препятствие или ближе radius к нему: людям туда не встать и не
   *  пройти (пользователь, 19.10.2026: «чтобы они чувствовали забор, площадку и т. д.»). */
  blockedCells(grid: GridFrame, radius: number): Uint8Array {
    const { width, height, metresPerPx: m, rect } = grid;
    const out = new Uint8Array(width * height);
    const reach = Math.ceil(radius / m);
    const mark = (x: number, z: number) => {
      const cx = Math.floor((x - rect[0]) / m);
      const cz = Math.floor((z - rect[1]) / m);
      for (let dz = -reach; dz <= reach; dz++) {
        const pz = cz + dz;
        if (pz < 0 || pz >= height) continue;
        for (let dx = -reach; dx <= reach; dx++) {
          const px = cx + dx;
          if (px < 0 || px >= width) continue;
          const qx = rect[0] + (px + 0.5) * m;
          const qz = rect[1] + (pz + 0.5) * m;
          if (Math.hypot(qx - x, qz - z) <= radius + m * 0.5) out[pz * width + px] = 1;
        }
      }
    };
    for (const s of this.all) {
      const len = Math.hypot(s.bx - s.ax, s.bz - s.az);
      const steps = Math.max(1, Math.ceil(len / (m * 0.5)));
      for (let k = 0; k <= steps; k++) {
        mark(s.ax + ((s.bx - s.ax) * k) / steps, s.az + ((s.bz - s.az) * k) / steps);
      }
    }
    for (const fp of this.footprints) {
      const [x0, z0, x1, z1] = fp.box;
      if ((x1 - x0) * (z1 - z0) > FILL_MAX_M2) continue;
      for (
        let pz = Math.max(0, Math.floor((z0 - rect[1]) / m));
        pz * m + rect[1] <= z1 && pz < height;
        pz++
      ) {
        for (
          let px = Math.max(0, Math.floor((x0 - rect[0]) / m));
          px * m + rect[0] <= x1 && px < width;
          px++
        ) {
          const p = { x: rect[0] + (px + 0.5) * m, z: rect[1] + (pz + 0.5) * m };
          if (insideRing(fp.ring, p)) out[pz * width + px] = 1;
        }
      }
    }
    return out;
  }

  /** Открытые линии высотой height: ограды. */
  addLines(lines: readonly Line[], height: number): void {
    if (height <= STEP_OVER_M) return;
    for (const line of lines) {
      for (let i = 0; i + 1 < line.points.length; i++) {
        const a = line.points[i];
        const c = line.points[i + 1];
        if (a && c) this.add({ ax: a.x, az: a.z, bx: c.x, bz: c.z, height });
      }
    }
  }

  /** Верх дома или машины над точкой; 0 - над землёй. */
  roofAt(p: Flat): number {
    let top = 0;
    for (const fp of this.roofs.get(this.key(p.x, p.z)) ?? []) {
      if (fp.height <= top) continue;
      const [x0, z0, x1, z1] = fp.box;
      if (p.x < x0 || p.x > x1 || p.z < z0 || p.z > z1) continue;
      if (insideRing(fp.ring, p)) top = fp.height;
    }
    return top;
  }

  private key(x: number, z: number): string {
    return `${Math.floor(x / CELL_M)}:${Math.floor(z / CELL_M)}`;
  }

  private keys(x0: number, z0: number, x1: number, z1: number): string[] {
    const out: string[] = [];
    for (let x = Math.floor(x0 / CELL_M); x <= Math.floor(x1 / CELL_M); x++) {
      for (let z = Math.floor(z0 / CELL_M); z <= Math.floor(z1 / CELL_M); z++)
        out.push(`${x}:${z}`);
    }
    return out;
  }

  private add(s: Segment): void {
    this.all.push(s);
    for (const key of this.keys(
      Math.min(s.ax, s.bx) - BODY_M,
      Math.min(s.az, s.bz) - BODY_M,
      Math.max(s.ax, s.bx) + BODY_M,
      Math.max(s.az, s.bz) + BODY_M,
    )) {
      const list = this.cells.get(key);
      if (list) list.push(s);
      else this.cells.set(key, [s]);
    }
  }

  /** Стены рядом с точкой, которые держат тело на высоте y. */
  near(p: Flat, y = 0): Segment[] {
    return (this.cells.get(this.key(p.x, p.z)) ?? []).filter((s) => y < s.height + CLEAR_M);
  }

  /** Шаг пересекает стену: за один кадр тело не должно оказаться по ту её сторону. */
  private crosses(from: Flat, to: Flat, y: number): boolean {
    const cells = new Set([...this.near(from, y), ...this.near(to, y)]);
    for (const s of cells) {
      if (segmentsCross(from, to, { x: s.ax, z: s.az }, { x: s.bx, z: s.bz })) return true;
    }
    return false;
  }

  /** Сдвинуть шаг from -> to на высоте y так, чтобы тело не вошло в стену: скольжение вдоль
   *  неё. y - низ тела: у пешехода 0, у камеры в полёте - её высота. */
  resolve(from: Flat, to: Flat, y = 0): Flat {
    let p = { ...to };
    if (this.crosses(from, p, y)) {
      // Сквозь стену нельзя: пробуем шаг по одной оси - это и есть скольжение вдоль стены.
      const alongX = { x: to.x, z: from.z };
      const alongZ = { x: from.x, z: to.z };
      if (!this.crosses(from, alongX, y)) p = alongX;
      else if (!this.crosses(from, alongZ, y)) p = alongZ;
      else return { ...from };
    }
    // Три прохода: в углу тело упирается в две стены сразу.
    for (let pass = 0; pass < 3; pass++) {
      let pushed = false;
      for (const s of this.near(p, y)) {
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

function insideRing(ring: readonly Flat[], p: Flat): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[i] as Flat;
    const b = ring[j] as Flat;
    if (a.z > p.z !== b.z > p.z && p.x < ((b.x - a.x) * (p.z - a.z)) / (b.z - a.z) + a.x) {
      inside = !inside;
    }
  }
  return inside;
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
