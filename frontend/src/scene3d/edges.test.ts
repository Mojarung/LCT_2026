import { describe, expect, it } from 'vitest';

import {
  apronGeometry,
  crossingTest,
  curbProfile,
  groundCutRings,
  gutterGeometry,
  roadEdges,
  type RoadEdge,
} from './edges';
import { ribbonBox, type MaskInfo, type SurfaceAreas } from './ground';
import { ASPHALT, GRASS, PAVERS, ROAD } from './surfaceMask';
import type { Flat } from './types';

/* Край проезжей части как в жизни (пользователь, 17.10.2026): на съезде и переходе борт
 * понижен с переходными камнями по метру, тротуар спускается к нему пандусом, вдоль
 * полного борта по асфальту тёмная полоса лотка. */

// Проезд 60 x 6 м в координатах чертежа; начало сцены в (0, 0): x сцены = X, z сцены = -Y.
const ROAD_RING = [
  [0, 0],
  [60, 0],
  [60, 6],
  [0, 6],
  [0, 0],
];
const AREAS: SurfaceAreas = {
  soil: [],
  paved: [[ROAD_RING]],
  paved_kind: ['road'],
};

/** Покрытие по точке сцены: севернее проезда (z < -6) плитка на x 20..24, иначе газон. */
function kindAt(p: Flat): number {
  if (p.z > -6 && p.z < 0 && p.x > 0 && p.x < 60) return ROAD;
  if (p.z <= -6 && p.x >= 20 && p.x <= 24) return PAVERS;
  return GRASS;
}

const crossing = (a: Flat, b: Flat): boolean => {
  const dx = b.x - a.x;
  const dz = b.z - a.z;
  const len = Math.hypot(dx, dz) || 1;
  const nx = (-dz / len) * 0.4;
  const nz = (dx / len) * 0.4;
  const mx = (a.x + b.x) / 2;
  const mz = (a.z + b.z) / 2;
  const left = kindAt({ x: mx + nx, z: mz + nz });
  const right = kindAt({ x: mx - nx, z: mz - nz });
  const paved = (k: number) => k === PAVERS || k === ASPHALT;
  return (left === ROAD && paved(right)) || (right === ROAD && paved(left));
};

function edge(): RoadEdge {
  const edges = roadEdges(AREAS, [0, 0], crossing);
  expect(edges).toHaveLength(1);
  return edges[0] as RoadEdge;
}

function pointAt(points: Flat[], x: number, z: number): number {
  const i = points.findIndex((p) => Math.abs(p.x - x) < 1e-6 && Math.abs(p.z - z) < 1e-6);
  expect(i, `точка (${x}, ${z})`).toBeGreaterThanOrEqual(0);
  return i;
}

describe('край проезжей части: съезды и переходы', () => {
  it('пролёты нарезаны по метру, понижен только короткий ряд против плитки', () => {
    const e = edge();
    // Северный край y = 6: точки через метр, против плитки x 20..24 - пониженный борт.
    const ends = [pointAt(e.points, 20, -6), pointAt(e.points, 24, -6)];
    const lo = Math.min(...ends);
    const hi = Math.max(...ends);
    expect(hi - lo).toBe(4);
    for (let i = lo; i < hi; i++) expect(e.lowered[i], `пролёт ${i}`).toBe(true);
    expect(e.lowered[lo - 1]).toBe(false);
    expect(e.lowered[hi]).toBe(false);
    // Южный край и торцы - газон: борт полный.
    const i10 = pointAt(e.points, 10, 0);
    expect(e.lowered[i10]).toBe(false);
    expect(e.lowered.filter(Boolean)).toHaveLength(4);
  });

  it('пропуск в ряду короче 1,5 м (стойка знака) съезд не рвёт: один ряд', () => {
    // Плитка на x 19..21 и 22..24, между ними метр газона.
    const gapped = (a: Flat, b: Flat) => {
      const mx = (a.x + b.x) / 2;
      return (
        crossing(a, b) ||
        (a.z === -6 && b.z === -6 && ((mx > 19 && mx < 20) || (mx > 23 && mx < 24)))
      );
    };
    const withGap = (a: Flat, b: Flat) => {
      const mx = (a.x + b.x) / 2;
      return gapped(a, b) && !(mx > 21 && mx < 22);
    };
    const e = roadEdges(AREAS, [0, 0], withGap)[0] as RoadEdge;
    expect(e.lowered.filter(Boolean)).toHaveLength(5);
  });

  it('ряд короче 2 м и длиннее 12 м бортом не понижается', () => {
    const narrow = (a: Flat, b: Flat) => crossing(a, b) && (a.x + b.x) / 2 < 21;
    const wide = (a: Flat, b: Flat) => a.z === -6 && b.z === -6;
    expect(roadEdges(AREAS, [0, 0], narrow)[0]?.lowered.some(Boolean)).toBe(false);
    expect(roadEdges(AREAS, [0, 0], wide)[0]?.lowered.some(Boolean)).toBe(false);
  });
});

describe('вырез земли с пандусом', () => {
  it('на съезде контур выреза отступает от проезда на ширину пандуса в сторону тротуара', () => {
    const [cut] = groundCutRings([edge()], 1.2, 1);
    expect(cut?.island).toBe(false);
    const pts = cut?.points ?? [];
    // Пандус - к северу от края y = 6, то есть z = -7.2, на съезде x 20..24 и над
    // переходными камнями по метру с каждой стороны: x 19..25.
    const far = pts.filter((p) => Math.abs(p.z + 7.2) < 1e-6);
    expect(far.length).toBeGreaterThanOrEqual(2);
    expect(Math.min(...far.map((p) => p.x))).toBeCloseTo(19);
    expect(Math.max(...far.map((p) => p.x))).toBeCloseTo(25);
    expect(Math.min(...pts.map((p) => p.z))).toBeCloseTo(-7.2);
    // Вне съезда край выреза - сам контур проезда.
    expect(pts.some((p) => Math.abs(p.x - 10) < 1e-6 && Math.abs(p.z + 6) < 1e-6)).toBe(true);
    // Кольцо замкнуто.
    expect(pts[0]).toEqual(pts.at(-1));
  });

  it('пандус - лента от края проезда до линии выреза: у борта на 2 см ниже его верха', () => {
    const g = apronGeometry([edge()], 1.2, 0.02, -0.11, 1);
    g.computeBoundingBox();
    const box = g.boundingBox;
    expect(box?.min.y).toBeCloseTo(-0.13);
    expect(box?.max.y).toBeCloseTo(0);
    expect(box?.min.x).toBeCloseTo(19);
    expect(box?.max.x).toBeCloseTo(25);
    expect(box?.min.z).toBeCloseTo(-7.2);
    expect(box?.max.z).toBeCloseTo(-6);
    const pos = g.getAttribute('position');
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const atCurb = Math.abs(pos.getZ(i) + 6) < 1e-6;
      // Верх у линии выреза - уровень тротуара; у борта на съезде -0,13, над переходным
      // камнем поднимается до тротуара: концы ленты без вертикальной щели.
      const want = !atCurb ? 0 : x >= 20 && x <= 24 ? -0.13 : x === 19 || x === 25 ? 0 : NaN;
      if (Number.isNaN(want)) throw new Error(`лишняя точка x=${x}`);
      expect(pos.getY(i), `x=${x}`).toBeCloseTo(want);
    }
  });
});

describe('профиль борта', () => {
  it('верх борта: полный, пониженный на съезде, переходный камень за метр до него', () => {
    const line = curbProfile(edge(), 0.02, -0.11, 2);
    const top = (x: number) => line.tops?.[pointAt(line.points, x, -6)];
    expect(top(18)).toBeCloseTo(0.02);
    expect(top(19)).toBeCloseTo(-0.045);
    expect(top(20)).toBeCloseTo(-0.11);
    expect(top(22)).toBeCloseTo(-0.11);
    expect(top(24)).toBeCloseTo(-0.11);
    expect(top(25)).toBeCloseTo(-0.045);
    expect(top(26)).toBeCloseTo(0.02);
    expect(line.tops?.[pointAt(line.points, 10, 0)]).toBeCloseTo(0.02);
  });

  it('брус борта с профилем: верх идёт по заданным отметкам, низ - по подошве', () => {
    const line = curbProfile(edge(), 0.02, -0.11, 1);
    const g = ribbonBox([line], 0.15, 0.17, -0.15, 0.02);
    g.computeBoundingBox();
    expect(g.boundingBox?.max.y).toBeCloseTo(0.02);
    expect(g.boundingBox?.min.y).toBeCloseTo(-0.15);
    // На съезде верх не выше пониженной отметки.
    const pos = g.getAttribute('position');
    let highest = -1;
    for (let i = 0; i < pos.count; i++) {
      if (pos.getX(i) > 21 && pos.getX(i) < 23 && pos.getZ(i) < -5.5) {
        highest = Math.max(highest, pos.getY(i));
      }
    }
    expect(highest).toBeCloseTo(-0.11);
  });
});

describe('признак съезда по маске', () => {
  // Маска 10 x 10 м по полметра: строки z < 5 - проезд, дальше тротуар или газон.
  function maskWith(sidewalkDepthM: number): MaskInfo {
    const kinds = new Uint8Array(400);
    for (let i = 0; i < 400; i++) {
      const z = Math.floor(i / 20) * 0.5;
      kinds[i] = z < 5 ? ROAD : z < 5 + sidewalkDepthM ? ASPHALT : GRASS;
    }
    return {
      kinds,
      width: 20,
      height: 20,
      metresPerPx: 0.5,
      rect: [0, 0, 10, 10],
    } as unknown as MaskInfo;
  }
  const seg: [Flat, Flat] = [
    { x: 2, z: 5 },
    { x: 8, z: 5 },
  ];

  it('тротуар в два метра от края - съезд', () => {
    expect(crossingTest(maskWith(2))(...seg)).toBe(true);
  });

  it('полуметровая кромка асфальта у газона (шов маски) - не съезд', () => {
    expect(crossingTest(maskWith(0.5))(...seg)).toBe(false);
  });

  it('газон по обе стороны - не съезд', () => {
    expect(crossingTest(maskWith(0))(...seg)).toBe(false);
  });
});

describe('лоток у борта', () => {
  it('полоса по асфальту со стороны проезда вдоль полного борта, на съезде её нет', () => {
    const g = gutterGeometry([edge()], 0.35, -0.146);
    const pos = g.getAttribute('position');
    const uv = g.getAttribute('uv');
    expect(pos.count).toBeGreaterThan(0);
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const z = pos.getZ(i);
      expect(x).toBeGreaterThanOrEqual(-1e-6);
      expect(x).toBeLessThanOrEqual(60 + 1e-6);
      expect(z).toBeGreaterThanOrEqual(-6 - 1e-6);
      expect(z).toBeLessThanOrEqual(1e-6);
      expect(pos.getY(i)).toBeCloseTo(-0.146);
      // v: 0 у борта, 1 на дальнем краю полосы.
      expect([0, 1]).toContain(uv.getY(i));
      // На съезде (x 20..24 у северного края) полосы нет.
      if (z < -5.5 && x > 20.01 && x < 23.99) throw new Error(`лоток на съезде: ${x}`);
    }
  });
});
