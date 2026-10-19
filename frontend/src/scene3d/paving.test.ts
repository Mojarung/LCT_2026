import { describe, expect, it } from 'vitest';

import type { SurfaceAreas } from './ground';
import { edgeCurbs, pavingGeometry, PAVING_LIFT_M } from './paving';

const square = (x: number, y: number, size: number) => [
  [
    [x, y],
    [x + size, y],
    [x + size, y + size],
    [x, y + size],
    [x, y],
  ],
];

const AREAS: SurfaceAreas = {
  soil: [],
  paved: [square(0, 0, 10), square(20, 0, 10), square(40, 0, 10), square(60, 0, 10)],
  paved_kind: ['pavers', 'asphalt', 'road', 'special'],
};

describe('покрытия вектором: плитка и асфальт по контурам surface.json', () => {
  it('сетка плитки - только части вида pavers, чуть выше земли, в координатах сцены', () => {
    const geometry = pavingGeometry(AREAS, [0, 0], 'pavers');
    expect(geometry).not.toBeNull();
    geometry?.computeBoundingBox();
    const box = geometry?.boundingBox;
    expect(box?.min.y).toBeCloseTo(PAVING_LIFT_M);
    expect(box?.min.x).toBeCloseTo(0);
    expect(box?.max.x).toBeCloseTo(10);
    // z сцены = -(Y - 0): квадрат чертежа 0..10 по Y - это z от -10 до 0.
    expect(box?.min.z).toBeCloseTo(-10);
    expect(box?.max.z).toBeCloseTo(0);
  });

  it('асфальт - своя сетка; проезжая часть и резина сюда не входят', () => {
    const asphalt = pavingGeometry(AREAS, [0, 0], 'asphalt');
    asphalt?.computeBoundingBox();
    expect(asphalt?.boundingBox?.min.x).toBeCloseTo(20);
    expect(asphalt?.boundingBox?.max.x).toBeCloseTo(30);
  });
});

describe('садовый борт по краю части покрытия', () => {
  it('идёт по контуру части там, где снаружи газон, и прерывается у соседнего покрытия', () => {
    // Снаружи плиточного квадрата 0..10 газон везде, кроме восточной стороны (x > 10).
    const lawnAt = (x: number) => x < 10;
    const lines = edgeCurbs(
      { ...AREAS, paved: [square(0, 0, 10)], paved_kind: ['pavers'] },
      [0, 0],
      (p) => lawnAt(p.x),
    );
    const points = lines.flatMap((l) => l.points);
    expect(lines.length).toBeGreaterThan(0);
    // Борт - ровно по сторонам квадрата: каждая точка на его контуре.
    for (const p of points) {
      const onEdge =
        Math.abs(p.x) < 1e-6 ||
        Math.abs(p.x - 10) < 1e-6 ||
        Math.abs(p.z) < 1e-6 ||
        Math.abs(p.z + 10) < 1e-6;
      expect(onEdge).toBe(true);
    }
    // На восточной стороне (x = 10) борта нет: там соседнее покрытие.
    const east = lines.some((l) =>
      l.points.some((p, i) => {
        const q = l.points[i + 1];
        return q && Math.abs(p.x - 10) < 1e-6 && Math.abs(q.x - 10) < 1e-6;
      }),
    );
    expect(east).toBe(false);
  });

  it('проезжая часть своим бортом: у неё садового борта нет', () => {
    expect(
      edgeCurbs({ ...AREAS, paved: [square(0, 0, 10)], paved_kind: ['road'] }, [0, 0], () => true),
    ).toHaveLength(0);
  });
});
