import { describe, expect, it } from 'vitest';

import { insideRings, scatterInRings } from './flowerbeds';
import type { Ring } from './types';

const square = (x0: number, z0: number, size: number): Ring => [
  { x: x0, z: z0 },
  { x: x0 + size, z: z0 },
  { x: x0 + size, z: z0 + size },
  { x: x0, z: z0 + size },
];

describe('цветник: россыпь растений по контуру', () => {
  it('кладёт растения только внутри контура и не в дыре, с плотностью на квадратный метр', () => {
    const bed = [square(0, 0, 4), square(1, 1, 2)]; // 16 м² минус дыра 4 м²
    const points = scatterInRings(bed, 10, 10_000, 3);
    expect(points.length).toBeGreaterThan(100);
    expect(points.length).toBeLessThan(140);
    expect(points.every((p) => insideRings(bed, p))).toBe(true);
    expect(points.some((p) => p.x > 1 && p.x < 3 && p.z > 1 && p.z < 3)).toBe(false);
  });

  it('ограничивает число растений', () => {
    expect(scatterInRings([square(0, 0, 100)], 25, 500, 3)).toHaveLength(500);
  });
});
