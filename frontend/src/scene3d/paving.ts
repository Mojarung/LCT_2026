/* Покрытия вектором и садовый борт по их краю.
 *
 * Маска земли - растр 0,25 м с линейным фильтром: край плитки на ней шёл волной, а садовый
 * борт ставился по отдельно выпрямленному контуру маски газона - две разные границы, и где-то
 * ровный борт стоял у волнистой плитки, где-то наоборот (пользователь, 19.10.2026). Теперь
 * плитка и асфальт тротуаров - плоские сетки по контурам частей surface.json (сервис уже
 * выпрямил их по линиям чертежа), а борт идёт ровно по тому же контуру там, где снаружи газон.
 * Проезжая часть по-прежнему опущена и обведена дорожным бортом (edges.ts), резина площадок -
 * своя сетка (ground.specialGeometry). */

import * as THREE from 'three';

import { insideRings } from './flowerbeds';
import type { AreaPolygon, SurfaceAreas } from './ground';
import type { Flat, Line, Ring } from './types';

/** Сетка тротуара над землёй, м: маска под ней та же плитка, сетка лишь даёт ровный край. */
export const PAVING_LIFT_M = 0.01;
/** Насколько наружу от края части смотреть, газон ли там, м. */
const PROBE_M = 0.35;

const SIDEWALK_KINDS: Record<'pavers' | 'asphalt', ReadonlySet<string>> = {
  // Покрытие без известного материала сервис уже отнёс к плитке или асфальту; старые прогоны
  // его ещё присылают - тротуар плиткой, как и делил 3D.
  pavers: new Set(['pavers', 'paved']),
  asphalt: new Set(['asphalt']),
};

function sceneRings(polygon: AreaPolygon, origin: [number, number]): Ring[] {
  const [ox, oy] = origin;
  return polygon.map((ring) => {
    const out = ring.map(([x = 0, y = 0]) => ({ x: x - ox, z: -(y - oy) }));
    const first = out[0];
    const last = out.at(-1);
    if (first && last && out.length > 1 && first.x === last.x && first.z === last.z) out.pop();
    return out;
  });
}

/** Плоская сетка частей покрытия одного вида на высоте PAVING_LIFT_M. */
export function pavingGeometry(
  areas: SurfaceAreas,
  origin: [number, number],
  kind: 'pavers' | 'asphalt',
): THREE.BufferGeometry | null {
  const wanted = SIDEWALK_KINDS[kind];
  const toVec = (ring: Ring) => ring.map((p) => new THREE.Vector2(p.x, -p.z));
  const shapes = areas.paved
    .filter((_, i) => wanted.has(areas.paved_kind?.[i] ?? 'paved'))
    .map((polygon) => sceneRings(polygon, origin))
    .filter((rings) => (rings[0]?.length ?? 0) >= 3)
    .map((rings) => {
      const shape = new THREE.Shape(toVec(rings[0] ?? []));
      shape.holes = rings.slice(1).map((ring) => new THREE.Path(toVec(ring)));
      return shape;
    });
  if (!shapes.length) return null;
  const geometry = new THREE.ShapeGeometry(shapes);
  geometry.rotateX(-Math.PI / 2);
  geometry.translate(0, PAVING_LIFT_M, 0);
  return geometry;
}

/** Садовый борт: куски контуров частей покрытия (кроме проезжей части), снаружи которых газон.
 *  Линия ориентирована покрытием влево - как ждёт ribbonBox (фаска со стороны покрытия). */
export function edgeCurbs(
  areas: SurfaceAreas,
  origin: [number, number],
  lawnAt: (p: Flat) => boolean,
): Line[] {
  const out: Line[] = [];
  areas.paved.forEach((polygon, index) => {
    if (areas.paved_kind?.[index] === 'road') return;
    const rings = sceneRings(polygon, origin);
    for (const raw of rings) {
      if (raw.length < 3) continue;
      const ring = pavedOnLeftRing(raw, rings);
      const n = ring.length;
      const curb: boolean[] = [];
      for (let i = 0; i < n; i++) {
        const p = ring[i] as Flat;
        const q = ring[(i + 1) % n] as Flat;
        const len = Math.hypot(q.x - p.x, q.z - p.z);
        if (len < 1e-6) {
          curb.push(false);
          continue;
        }
        // Справа от пролёта - снаружи части.
        const nx = (q.z - p.z) / len;
        const nz = -(q.x - p.x) / len;
        curb.push(lawnAt({ x: (p.x + q.x) / 2 + nx * PROBE_M, z: (p.z + q.z) / 2 + nz * PROBE_M }));
      }
      if (curb.every(Boolean)) {
        out.push({ points: [...ring, ring[0] as Flat] });
        continue;
      }
      // Пробеги подряд идущих пролётов с газоном снаружи, начиная после первого разрыва.
      const start = curb.findIndex((c) => !c);
      let run: Flat[] = [];
      for (let k = 1; k <= n; k++) {
        const i = (start + k) % n;
        if (curb[i]) {
          if (!run.length) run.push(ring[i] as Flat);
          run.push(ring[(i + 1) % n] as Flat);
        } else if (run.length) {
          out.push({ points: run });
          run = [];
        }
      }
      if (run.length) out.push({ points: run });
    }
  });
  return out;
}

/** Кольцо, обходящее часть так, чтобы покрытие было слева от каждого пролёта. */
function pavedOnLeftRing(ring: Ring, rings: readonly Ring[]): Ring {
  let best = 0;
  let at = 0;
  for (let i = 0; i < ring.length; i++) {
    const p = ring[i] as Flat;
    const q = ring[(i + 1) % ring.length] as Flat;
    const len = Math.hypot(q.x - p.x, q.z - p.z);
    if (len > best) {
      best = len;
      at = i;
    }
  }
  const p = ring[at] as Flat;
  const q = ring[(at + 1) % ring.length] as Flat;
  const left = {
    x: (p.x + q.x) / 2 - ((q.z - p.z) / best) * 0.05,
    z: (p.z + q.z) / 2 + ((q.x - p.x) / best) * 0.05,
  };
  return insideRings(rings, left) ? ring : [...ring].reverse();
}
