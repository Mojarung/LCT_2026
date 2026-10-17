/* Город вокруг съёмки: дома, дороги и стоянки OpenStreetMap для 3D-вида. Чистая логика.
 *
 * Ответ сервиса (GET /runs/{id}/context) - в метрах чертежа, как scene.json; здесь он
 * переводится в координаты сцены. Внутри съёмки решает чертёж: дороги и стоянки карты на
 * снятые места не ложатся. Дом без этажности в карте получает её по типу и площади.
 * Деревьев из карты в сцене нет намеренно: 3D показывает итоговые посадки плана и
 * существующие насаждения чертежа, а не догадку о зелени квартала. */

import { insideRing, mainAxis, simplifyRing } from './facades';
import type { CarSpot } from './parking';
import { floorsByArea, type Frame, hashOf, heightOf } from './world';
import type { Building, Flat, Line, Ring } from './types';

export interface ContextJson {
  version: number;
  source: string;
  buildings: { ring: [number, number][]; levels: number | null; kind: string }[];
  trees: [number, number][];
  roads: { line: [number, number][]; width_m: number; kind: string }[];
  greens?: { ring: [number, number][]; kind: string }[];
  parkings?: { ring: [number, number][]; kind: string }[];
  notes: string[];
}

export interface ContextRoads {
  width: number;
  paved: 'asphalt' | 'pavers';
  lines: Line[];
}

export interface ContextScene {
  buildings: Building[];
  roads: ContextRoads[];
  /** Открытые стоянки за краем съёмки: асфальт и ряды машин. */
  parkings: Ring[];
  cars: CarSpot[];
  source: string;
}

/** Ряды стоянки: место 2,6 м, глубина машины 5 м, проезд 6 м; занято примерно 70% мест. */
const SLOT_M = 2.6;
const ROW_M = 5;
const AISLE_M = 6;
const PARKED = 0.7;

/** Машины на стоянке рядами поперёк её главной оси, только целиком внутри контура. */
export function parkingCars(ring: Ring, surveyed: Surveyed): CarSpot[] {
  const axis = mainAxis(ring);
  if (axis.width < ROW_M + 1) return [];
  const ux = axis.dx;
  const uz = axis.dz;
  const vx = -uz;
  const vz = ux;
  const out: CarSpot[] = [];
  const inside = (u: number, v: number) =>
    insideRing({ x: axis.cx + ux * u + vx * v, z: axis.cz + uz * u + vz * v }, ring);
  // Пара рядов «носом к проезду»: ряд, проезд, ряд, ряд, проезд, ряд...
  for (let v = -axis.width / 2 + ROW_M / 2 + 0.5, k = 0; v < axis.width / 2 - ROW_M / 2; k++) {
    for (
      let u = -axis.length / 2 + SLOT_M / 2 + 0.5;
      u < axis.length / 2 - SLOT_M / 2;
      u += SLOT_M
    ) {
      const corners = [
        [u - 1, v - 2.3],
        [u + 1, v - 2.3],
        [u - 1, v + 2.3],
        [u + 1, v + 2.3],
      ];
      if (!corners.every(([a = 0, b = 0]) => inside(a, b))) continue;
      const p = { x: axis.cx + ux * u + vx * v, z: axis.cz + uz * u + vz * v };
      const seed = hashOf(`park:${p.x.toFixed(1)}:${p.z.toFixed(1)}`);
      if ((seed % 1000) / 1000 > PARKED || surveyed(p)) continue;
      // Машина стоит поперёк ряда: её ось - вдоль v.
      out.push({ ...p, angle: Math.atan2(-vz, vx) + (k % 2 ? Math.PI : 0), seed });
    }
    v += k % 2 ? ROW_M + AISLE_M : ROW_M;
  }
  return out;
}

const RESIDENTIAL = new Set(['apartments', 'residential', 'house', 'dormitory', 'detached']);
const METAL = new Set(['industrial', 'warehouse', 'garages', 'garage', 'service', 'hangar']);
/** Этажность по типу дома карты, когда тега этажности нет. */
const FLOORS_BY_KIND: Record<string, number> = {
  apartments: 9,
  residential: 9,
  dormitory: 5,
  house: 2,
  detached: 2,
  school: 3,
  kindergarten: 2,
  hospital: 5,
  retail: 2,
  commercial: 3,
  office: 5,
  garages: 1,
  garage: 1,
  shed: 1,
  kiosk: 1,
  service: 1,
};

function area(ring: Ring): number {
  let sum = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i];
    const b = ring[(i + 1) % ring.length];
    if (a && b) sum += a.x * b.z - b.x * a.z;
  }
  return Math.abs(sum) / 2;
}

/** Снята ли точка: там решает чертёж, карта туда дорог и деревьев не ставит. */
export type Surveyed = (p: Flat) => boolean;

/** Ломаная без кусков на снятом месте: режется на отрезки по 2 м. */
export function outsideParts(points: readonly Flat[], surveyed: Surveyed): Flat[][] {
  const parts: Flat[][] = [];
  let current: Flat[] = [];
  const flush = () => {
    if (current.length > 1) parts.push(current);
    current = [];
  };
  for (let i = 0; i + 1 < points.length; i++) {
    const a = points[i];
    const b = points[i + 1];
    if (!a || !b) continue;
    const steps = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.z - a.z) / 2));
    for (let k = 0; k < steps; k++) {
      const p = { x: a.x + ((b.x - a.x) * k) / steps, z: a.z + ((b.z - a.z) * k) / steps };
      const q = {
        x: a.x + ((b.x - a.x) * (k + 1)) / steps,
        z: a.z + ((b.z - a.z) * (k + 1)) / steps,
      };
      const mid = { x: (p.x + q.x) / 2, z: (p.z + q.z) / 2 };
      if (surveyed(mid)) {
        flush();
        continue;
      }
      if (!current.length) current.push(p);
      current.push(q);
    }
  }
  flush();
  return parts;
}

export function contextScene(json: ContextJson, frame: Frame, surveyed: Surveyed): ContextScene {
  const flat = (ring: [number, number][]): Ring => ring.map(([x, y]) => frame.toFlat(x, y));
  const buildings: Building[] = [];
  for (const b of json.buildings) {
    const ring = simplifyRing(flat(b.ring));
    if (ring.length < 3) continue;
    const kind = b.kind.toLowerCase();
    const floors = b.levels ?? FLOORS_BY_KIND[kind] ?? floorsByArea(area(ring));
    const first = b.ring[0] ?? [0, 0];
    buildings.push({
      rings: [ring],
      height: heightOf(floors),
      floors,
      source: b.levels ? 'label' : 'assumed',
      kind: 'building',
      wall: METAL.has(kind) ? 'metal' : null,
      use: RESIDENTIAL.has(kind) ? 'residential' : kind === 'yes' ? null : 'non_residential',
      seed: hashOf(`osm:${first[0].toFixed(1)}:${first[1].toFixed(1)}`),
    });
  }
  const byWidth = new Map<string, ContextRoads>();
  for (const road of json.roads) {
    const line = road.line.map(([x, y]) => frame.toFlat(x, y));
    const paved = road.kind === 'footway' || road.kind === 'pedestrian' ? 'pavers' : 'asphalt';
    const key = `${String(road.width_m)}:${paved}`;
    let group = byWidth.get(key);
    if (!group) {
      group = { width: road.width_m, paved, lines: [] };
      byWidth.set(key, group);
    }
    for (const part of outsideParts(line, surveyed)) group.lines.push({ points: part });
  }
  const parkings: Ring[] = [];
  const cars: CarSpot[] = [];
  for (const area of json.parkings ?? []) {
    const ring = flat(area.ring);
    if (ring.length < 3) continue;
    const xs = ring.map((p) => p.x);
    const zs = ring.map((p) => p.z);
    const mid = {
      x: (Math.min(...xs) + Math.max(...xs)) / 2,
      z: (Math.min(...zs) + Math.max(...zs)) / 2,
    };
    if (surveyed(mid)) continue;
    parkings.push(ring);
    cars.push(...parkingCars(ring, surveyed));
  }
  return {
    buildings,
    roads: [...byWidth.values()].filter((g) => g.lines.length),
    parkings,
    cars: cars.slice(0, 2500),
    source: json.source,
  };
}
