import { describe, expect, it } from 'vitest';

import { chainFences, dropTwinFences } from './fences';
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
