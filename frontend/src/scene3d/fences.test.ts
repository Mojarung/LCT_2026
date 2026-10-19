import { describe, expect, it } from 'vitest';

import { chainFences, dropTwinFences, FENCE_CORNER_M, roundFenceCorners } from './fences';
import type { Line } from './types';

const seg = (x0: number, z0: number, x1: number, z1: number): Line => ({
  points: [
    { x: x0, z: z0 },
    { x: x1, z: z1 },
  ],
});

describe('ограды пунктиром', () => {
  it('куски пунктира по ходу ограды сшиваются в одну линию, порядок и направление не важны', () => {
    const dashed = [seg(4, 0, 5.5, 0), seg(0, 0, 1.5, 0), seg(9.5, 0, 8, 0)];
    const lines = chainFences(dashed);
    expect(lines).toHaveLength(1);
    const xs = (lines[0]?.points ?? []).map((p) => p.x);
    expect(Math.min(...xs)).toBe(0);
    expect(Math.max(...xs)).toBe(9.5);
  });

  it('широкий проход и параллельная ограда остаются отдельными', () => {
    expect(chainFences([seg(0, 0, 2, 0), seg(6, 0, 8, 0)])).toHaveLength(2);
    expect(chainFences([seg(0, 0, 4, 0), seg(0, 1.5, 4, 1.5)])).toHaveLength(2);
  });

  it('угол ограды под прямым углом не сшивается через разрыв', () => {
    expect(chainFences([seg(0, 0, 4, 0), seg(5, 1, 5, 5)])).toHaveLength(2);
  });
});

describe('сдвоенная ограда', () => {
  it('две параллельные линии в 0,5 м - один ряд, дальняя параллель остаётся', () => {
    const line = (z: number, x1 = 20) => ({
      points: [
        { x: 0, z },
        { x: x1, z },
      ],
    });
    const out = dropTwinFences([line(0), line(0.5, 18), line(5)]);
    expect(out).toHaveLength(2);
    expect(out.map((l) => l.points[0]?.z).sort()).toEqual([0, 5]);
  });

  it('поперечная ограда у края не теряется', () => {
    const out = dropTwinFences([
      {
        points: [
          { x: 0, z: 0 },
          { x: 20, z: 0 },
        ],
      },
      {
        points: [
          { x: 10, z: 0.3 },
          { x: 10, z: 10 },
        ],
      },
    ]);
    expect(out).toHaveLength(2);
  });
});

describe('углы ограды', () => {
  it('прямой угол и угол с фаской скругляются одной дугой, прямые участки не трогаются', () => {
    const square: Line = {
      points: [
        { x: 0, z: 0 },
        { x: 10, z: 0 },
        { x: 10, z: 10 },
      ],
    };
    const [round] = roundFenceCorners([square]);
    const pts = round?.points ?? [];
    expect(pts[0]).toEqual({ x: 0, z: 0 });
    expect(pts[pts.length - 1]).toEqual({ x: 10, z: 10 });
    // Вершина угла срезана: ближайшая точка в 0,6 x (sqrt2 - 1) от неё.
    const corner = Math.min(...pts.map((p) => Math.hypot(p.x - 10, p.z)));
    expect(corner).toBeCloseTo(FENCE_CORNER_M * (Math.SQRT2 - 1), 1);
    // Все точки дуги - на расстоянии радиуса от центра (9,4; 0,6).
    for (const p of pts.slice(1, -1)) {
      expect(Math.hypot(p.x - (10 - FENCE_CORNER_M), p.z - FENCE_CORNER_M)).toBeCloseTo(
        FENCE_CORNER_M,
        3,
      );
    }
  });

  it('излом меньше 20 градусов не скругляется, замкнутая ограда скругляется во всех углах', () => {
    const bend: Line = {
      points: [
        { x: 0, z: 0 },
        { x: 10, z: 0 },
        { x: 20, z: 1 },
      ],
    };
    expect(roundFenceCorners([bend])[0]?.points).toHaveLength(3);
    const closed: Line = {
      points: [
        { x: 0, z: 0 },
        { x: 8, z: 0 },
        { x: 8, z: 6 },
        { x: 0, z: 6 },
        { x: 0, z: 0 },
      ],
    };
    const pts = roundFenceCorners([closed])[0]?.points ?? [];
    for (const [cx, cz] of [
      [0, 0],
      [8, 0],
      [8, 6],
      [0, 6],
    ] as const) {
      expect(Math.min(...pts.map((p) => Math.hypot(p.x - cx, p.z - cz)))).toBeGreaterThan(0.2);
    }
    expect(pts[0]).toEqual(pts[pts.length - 1]);
  });
});
