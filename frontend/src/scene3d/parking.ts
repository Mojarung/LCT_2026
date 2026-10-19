/* Где в 3D стоят машины. Чистая логика без three.js.
 *
 * Машин в подоснове нет, а на фото улиц пилота они вдоль каждого борта проезда. Поэтому
 * это условное наполнение, и правила у него осторожные: машина встаёт только на асфальт
 * у борта, если проезд с этой стороны не уже 5 м (иначе она перегородит въезд во двор),
 * с шагом парковочного места, с пропусками, не на изломе борта, не у опоры и не у посадки. */

import { distanceInside } from './surfaceMask';
import type { Flat, Line } from './types';

export const CAR_LENGTH_M = 4.6;
export const CAR_WIDTH_M = 1.8;
/** Шаг парковочного места вдоль борта. */
const SLOT_M = 5.6;
/** Ось машины от линии борта: полкорпуса и зазор до камня. */
const OFFSET_M = CAR_WIDTH_M / 2 + 0.25;
/** Проезд с этой стороны борта должен быть не уже, чтобы машина не перегородила его. */
const LANE_M = 5;
/** Доля занятых мест: на фото дворов днём свободно примерно каждое третье. */
const OCCUPANCY = 0.55;
const MAX_CARS = 1500;

export interface CarSpot {
  x: number;
  z: number;
  /** Угол поворота вокруг вертикали: локальная +x машины смотрит вдоль борта. */
  angle: number;
  /** Номер модели кузова и цвета: устойчивы к прогону. */
  seed: number;
}

export interface ParkingInput {
  curbs: readonly Line[];
  /** Контуры зданий: машина не встаёт вплотную к стене и внутрь дома. */
  walls?: readonly Flat[][];
  /** Ограды: машина не стоит сквозь забор. */
  fences?: readonly Line[];
  /** Асфальт ли в точке сцены (карта покрытий). */
  asphaltAt: (x: number, z: number) => boolean;
  poles: readonly Flat[];
  plants: readonly Flat[];
}

function hash(x: number, z: number): number {
  let h = Math.imul(Math.round(x * 10) ^ 0x9e3779b9, 0x85ebca6b);
  h = Math.imul(h ^ Math.round(z * 10), 0xc2b2ae35);
  h ^= h >>> 15;
  return (h >>> 0) / 4294967296;
}

/** Есть ли рядом с точкой что-то из списка ближе r: сетка ячеек, чтобы не перебирать всё. */
class Near {
  private readonly cells = new Map<string, Flat[]>();
  constructor(
    points: readonly Flat[],
    private readonly cell = 8,
  ) {
    for (const p of points) this.add(p);
  }
  add(p: Flat): void {
    const key = `${Math.floor(p.x / this.cell)}:${Math.floor(p.z / this.cell)}`;
    const list = this.cells.get(key);
    if (list) list.push(p);
    else this.cells.set(key, [p]);
  }
  within(p: Flat, r: number): boolean {
    const cx = Math.floor(p.x / this.cell);
    const cz = Math.floor(p.z / this.cell);
    for (let dx = -1; dx <= 1; dx++) {
      for (let dz = -1; dz <= 1; dz++) {
        for (const q of this.cells.get(`${cx + dx}:${cz + dz}`) ?? []) {
          if (Math.hypot(q.x - p.x, q.z - p.z) < r) return true;
        }
      }
    }
    return false;
  }
}

/** Пятно машины целиком на асфальте: углы и середины сторон корпуса с зазором 20 см. */
function footprintOnRoad(
  x: number,
  z: number,
  angle: number,
  road: (x: number, z: number) => boolean,
): boolean {
  const ux = Math.cos(angle);
  const uz = -Math.sin(angle);
  const half = CAR_LENGTH_M / 2 + 0.2;
  const side = CAR_WIDTH_M / 2 + 0.2;
  for (const [a, b] of [
    [half, side],
    [half, -side],
    [-half, side],
    [-half, -side],
    [0, side],
    [0, -side],
    [half, 0],
    [-half, 0],
  ] as const) {
    if (!road(x + ux * a - uz * b, z + uz * a + ux * b)) return false;
  }
  return true;
}

/** Прямые участки борта длиннее машины: на изломе (поворот больше 20°) участок рвётся. */
function straightRuns(line: Line): Flat[][] {
  const runs: Flat[][] = [];
  let run: Flat[] = [];
  const pts = line.points;
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i];
    if (!p) continue;
    run.push(p);
    const a = pts[i - 1];
    const b = pts[i + 1];
    if (a && b) {
      const t1 = Math.atan2(p.z - a.z, p.x - a.x);
      const t2 = Math.atan2(b.z - p.z, b.x - p.x);
      const turn = Math.abs(Math.atan2(Math.sin(t2 - t1), Math.cos(t2 - t1)));
      if (turn > (20 * Math.PI) / 180) {
        runs.push(run);
        run = [p];
      }
    }
  }
  if (run.length > 1) runs.push(run);
  return runs;
}

/** Карта асфальта: пиксель - асфальт ли, угол растра и метров на пиксель. */
export interface AsphaltGrid {
  paved: Uint8Array;
  width: number;
  height: number;
  minX: number;
  minZ: number;
  metresPerPx: number;
}

export function parkingSpots(
  { curbs, asphaltAt, poles, plants, walls = [], fences = [] }: ParkingInput,
  grid?: AsphaltGrid,
): CarSpot[] {
  const spots: CarSpot[] = [];
  const blockers = new Near([...poles, ...plants]);
  const cars = new Near([]);
  const houses = new Houses(walls, fences);
  curbSpots(curbs, asphaltAt, blockers, cars, spots, houses);
  if (grid) edgeSpots(grid, blockers, cars, spots, houses);
  return spots;
}

/** Здания для проверки места: внутри контура или ближе WALL_M к стене - нельзя. */
const WALL_M = 1.6;
/** Машина не ближе этого к стене дома: у фасада вход, крыльцо и газон за оградой, а машина
 *  вплотную к ним выглядела брошенной (магазин в доме 1А на Харьковской, 19.10.2026). */
const EDGE_WALL_M = 6;

class Houses {
  private readonly items: { ring: readonly Flat[]; box: [number, number, number, number] }[];
  private readonly fenceSegments: [Flat, Flat][] = [];
  constructor(rings: readonly (readonly Flat[])[], fences: readonly Line[] = []) {
    for (const line of fences) {
      for (let i = 0; i + 1 < line.points.length; i++) {
        const a = line.points[i];
        const b = line.points[i + 1];
        if (a && b) this.fenceSegments.push([a, b]);
      }
    }
    this.items = rings
      .filter((ring) => ring.length >= 3)
      .map((ring) => {
        const xs = ring.map((p) => p.x);
        const zs = ring.map((p) => p.z);
        return {
          ring,
          box: [
            Math.min(...xs) - WALL_M,
            Math.min(...zs) - WALL_M,
            Math.max(...xs) + WALL_M,
            Math.max(...zs) + WALL_M,
          ],
        };
      });
  }
  /** Пятно машины ближе 30 см к ограде: по 15 точкам корпуса. */
  crossesFence(x: number, z: number, angle: number): boolean {
    if (!this.fenceSegments.length) return false;
    const ux = Math.cos(angle);
    const uz = -Math.sin(angle);
    for (let a = -1; a <= 1; a += 0.5) {
      for (let b = -1; b <= 1; b += 1) {
        const px = x + ux * a * (CAR_LENGTH_M / 2) - uz * b * (CAR_WIDTH_M / 2);
        const pz = z + uz * a * (CAR_LENGTH_M / 2) + ux * b * (CAR_WIDTH_M / 2);
        for (const [s0, s1] of this.fenceSegments) {
          if (Math.min(s0.x, s1.x) - 1 > px || Math.max(s0.x, s1.x) + 1 < px) continue;
          if (Math.min(s0.z, s1.z) - 1 > pz || Math.max(s0.z, s1.z) + 1 < pz) continue;
          const vx = s1.x - s0.x;
          const vz = s1.z - s0.z;
          const len2 = vx * vx + vz * vz;
          const t = len2
            ? Math.max(0, Math.min(1, ((px - s0.x) * vx + (pz - s0.z) * vz) / len2))
            : 0;
          if (Math.hypot(s0.x + vx * t - px, s0.z + vz * t - pz) < 0.3) return true;
        }
      }
    }
    return false;
  }

  blocks(p: Flat, wall = WALL_M): boolean {
    for (const { ring, box } of this.items) {
      const pad = wall - WALL_M;
      if (p.x < box[0] - pad || p.x > box[2] + pad || p.z < box[1] - pad || p.z > box[3] + pad) {
        continue;
      }
      let inside = false;
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const a = ring[i];
        const b = ring[j];
        if (!a || !b) continue;
        if (a.z > p.z !== b.z > p.z && p.x < ((b.x - a.x) * (p.z - a.z)) / (b.z - a.z) + a.x) {
          inside = !inside;
        }
        const vx = b.x - a.x;
        const vz = b.z - a.z;
        const len2 = vx * vx + vz * vz;
        const t =
          len2 > 0 ? Math.max(0, Math.min(1, ((p.x - a.x) * vx + (p.z - a.z) * vz) / len2)) : 0;
        if (Math.hypot(a.x + vx * t - p.x, a.z + vz * t - p.z) < wall) return true;
      }
      if (inside) return true;
    }
    return false;
  }
}

/** Места вдоль линий борта подосновы. */
function curbSpots(
  curbs: readonly Line[],
  asphaltAt: (x: number, z: number) => boolean,
  blockers: Near,
  cars: Near,
  spots: CarSpot[],
  houses: Houses,
): void {
  for (const line of curbs) {
    for (const run of straightRuns(line)) {
      for (let i = 0; i + 1 < run.length; i++) {
        const a = run[i];
        const b = run[i + 1];
        if (!a || !b) continue;
        const len = Math.hypot(b.x - a.x, b.z - a.z);
        if (len < CAR_LENGTH_M + 0.6) continue;
        const tx = (b.x - a.x) / len;
        const tz = (b.z - a.z) / len;
        const slots = Math.floor((len - 0.6) / SLOT_M);
        const start = (len - slots * SLOT_M) / 2 + SLOT_M / 2;
        for (let k = 0; k < slots; k++) {
          const u = start + k * SLOT_M;
          const px = a.x + tx * u;
          const pz = a.z + tz * u;
          for (const side of [1, -1]) {
            const nx = -tz * side;
            const nz = tx * side;
            const lane = [1.2, 2.6, LANE_M].every((d) => asphaltAt(px + nx * d, pz + nz * d));
            if (!lane) continue;
            const car = { x: px + nx * OFFSET_M, z: pz + nz * OFFSET_M };
            if (hash(car.x, car.z) > OCCUPANCY) continue;
            if (blockers.within(car, 2.2) || cars.within(car, CAR_LENGTH_M + 0.3)) continue;
            if (houses.blocks(car, EDGE_WALL_M)) continue;
            if (!footprintOnRoad(car.x, car.z, Math.atan2(-tz, tx), asphaltAt)) continue;
            if (houses.crossesFence(car.x, car.z, Math.atan2(-tz, tx))) continue;
            spots.push({
              ...car,
              angle: Math.atan2(-tz, tx),
              seed: Math.floor(hash(car.z, car.x) * 1e9),
            });
            cars.add(car);
            if (spots.length >= MAX_CARS) return;
          }
        }
      }
    }
  }
}

/** Места вдоль края асфальта по карте покрытий: борт в подоснове распознан не везде (на
 *  Кустанайской - 10 линий на всю улицу), а край проезда на карте есть всегда. Ось машины -
 *  в EDGE_M от края, вдоль края; проезд с этой стороны - не уже LANE_M с запасом. */
const EDGE_M = OFFSET_M;

function edgeSpots(
  grid: AsphaltGrid,
  blockers: Near,
  cars: Near,
  spots: CarSpot[],
  houses: Houses,
): void {
  const { paved, width: w, height: h, minX, minZ, metresPerPx: mpp } = grid;
  const dist = distanceInside(paved, w, h);
  const at = (x: number, y: number) =>
    x < 0 || y < 0 || x >= w || y >= h ? 0 : (dist[y * w + x] ?? 0);
  const band0 = (EDGE_M - 0.15) / mpp;
  const band1 = (EDGE_M + 0.15) / mpp;
  const reach = Math.round(1.8 / mpp);
  const need = (EDGE_M + 1.8 - 0.4) / mpp;
  const half = CAR_LENGTH_M / 2 / mpp;
  const normalAt = (x: number, y: number): [number, number] | null => {
    const xi = Math.round(x);
    const yi = Math.round(y);
    const gx = at(xi + 1, yi) - at(xi - 1, yi);
    const gy = at(xi, yi + 1) - at(xi, yi - 1);
    const g = Math.hypot(gx, gy);
    return g < 1.2 ? null : [gx / g, gy / g];
  };
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const d = dist[y * w + x] ?? 0;
      if (d < band0 || d > band1) continue;
      // Нормаль к краю - градиент карты расстояний, он смотрит вглубь проезда.
      const gx = at(x + 1, y) - at(x - 1, y);
      const gy = at(x, y + 1) - at(x, y - 1);
      const g = Math.hypot(gx, gy);
      if (g < 1.2) continue;
      const nx = gx / g;
      const ny = gy / g;
      if (at(Math.round(x + nx * reach), Math.round(y + ny * reach)) < need) continue;
      // Край прямой на две длины машины: у носа и у багажника и ещё на корпус дальше тот же
      // отступ и та же нормаль. На коротком косом куске края (съезд, излом у ограды) машина
      // вставала поперёк проезда (пользователь, 19.10.2026: «как будто раскидал объекты»).
      let straight = true;
      for (const k of [-2 * half, -half, half, 2 * half]) {
        const qx = x - ny * k;
        const qy = y + nx * k;
        const dq = at(Math.round(qx), Math.round(qy));
        const nq = normalAt(qx, qy);
        if (dq < band0 * 0.75 || dq > band1 * 1.25 || !nq || nq[0] * nx + nq[1] * ny < 0.96) {
          straight = false;
          break;
        }
      }
      if (!straight) continue;
      const car = { x: minX + (x + 0.5) * mpp, z: minZ + (y + 0.5) * mpp };
      const slot = hash(Math.floor(car.x / SLOT_M) * 7.3, Math.floor(car.z / SLOT_M) * 3.1);
      if (slot > OCCUPANCY) continue;
      if (blockers.within(car, 2.2) || cars.within(car, CAR_LENGTH_M + 0.4)) continue;
      if (houses.blocks(car, EDGE_WALL_M)) continue;
      const angle = Math.atan2(-nx, -ny);
      const onRoad = (qx: number, qz: number) =>
        at(Math.floor((qx - minX) / mpp), Math.floor((qz - minZ) / mpp)) > 0;
      if (!footprintOnRoad(car.x, car.z, angle, onRoad)) continue;
      if (houses.crossesFence(car.x, car.z, angle)) continue;
      spots.push({ ...car, angle, seed: Math.floor(hash(car.z, car.x) * 1e9) });
      cars.add(car);
      if (spots.length >= MAX_CARS) return;
    }
  }
}
