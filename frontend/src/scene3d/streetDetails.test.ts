import { describe, expect, it } from 'vitest';

import { benchSpots, type Ground, manholeSpots, treePits } from './streetDetails';
import type { Plant } from './types';

function tree(x: number, z: number, extra: Partial<Plant> = {}): Plant {
  return {
    id: `t${String(x)}`,
    x,
    z,
    type: 'tree',
    code: 'TC',
    name: 'Липа',
    species: {} as Plant['species'],
    existing: false,
    seed: 1,
    ...extra,
  };
}

/** Газон при z < 0, плитка при 0 <= z < 4, проезд дальше. */
const strip = (_x: number, z: number): Ground => (z < 0 ? 'grass' : z < 4 ? 'pavers' : 'road');

describe('лунки посадок', () => {
  it('в плитке - решётка, на газоне - мульча, существующие и полосы без лунки', () => {
    const pits = treePits(
      [tree(0, -2), tree(5, 2), tree(9, 2, { existing: true }), tree(12, 2, { strip: true })],
      strip,
    );
    expect(pits.mulch).toEqual([{ x: 0, z: -2 }]);
    expect(pits.grates).toEqual([{ x: 5, z: 2 }]);
  });
});

describe('люки', () => {
  it('на трассе под покрытием через шаг, на газоне и у соседней трассы - нет', () => {
    const line = {
      points: [
        { x: 0, z: 6 },
        { x: 200, z: 6 },
      ],
    };
    const twin = {
      points: [
        { x: 0, z: 7 },
        { x: 200, z: 7 },
      ],
    };
    const lawn = {
      points: [
        { x: 0, z: -5 },
        { x: 200, z: -5 },
      ],
    };
    const spots = manholeSpots(
      [
        { kind: 'utility.water', lines: [line] },
        { kind: 'utility.sewer', lines: [twin, lawn] },
        { kind: 'utility.power_cable', lines: [line] },
      ],
      strip,
    );
    expect(spots.map((s) => s.x)).toEqual([20, 60, 100, 140, 180]);
  });
});

describe('скамейки', () => {
  it('на плитке спинкой к газону, урна рядом, у ствола не ставится', () => {
    const edge = {
      points: [
        { x: 0, z: 0 },
        { x: 100, z: 0 },
      ],
    };
    const { benches, bins } = benchSpots([edge], strip, [{ x: 48, z: 0.5 }]);
    expect(benches.length).toBe(2);
    for (const b of benches) {
      expect(b.z).toBeGreaterThan(0.3);
      expect(b.z).toBeLessThan(1);
      // Сиденьем к плитке (+z): поворот вокруг вертикали - ноль.
      expect(Math.cos(b.angle)).toBeCloseTo(1, 5);
      expect(Math.abs(b.x - 48)).toBeGreaterThan(2);
    }
    expect(bins).toHaveLength(2);
  });
});
