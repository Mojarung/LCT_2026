import { describe, expect, it } from 'vitest';

import { MIN_NEAR_M, nearPlane, TALL_M } from './depth';
import { ROAD_DROP_M } from './ground';

/** Шаг 24-битного буфера глубины на расстоянии d при ближней плоскости n. */
const depthStep = (d: number, n: number) => (d * d) / (n * 2 ** 24);

describe('nearPlane', () => {
  it('keeps the pedestrian near plane', () => {
    expect(nearPlane(1.7)).toBe(MIN_NEAR_M);
    expect(nearPlane(-3)).toBe(MIN_NEAR_M);
  });

  it('separates the road plane from the lawn at the far edge from any height', () => {
    // Высота камеры и расстояние до дальнего края участка (Харьковская: ~1,5 км по диагонали).
    for (const [height, distance] of [
      [20, 800],
      [100, 1500],
      [300, 2500],
      [800, 4000],
    ] as const) {
      expect(depthStep(distance, nearPlane(height))).toBeLessThan(ROAD_DROP_M / 3);
    }
  });

  it('never clips the tallest objects under the camera', () => {
    for (const height of [10, 50, 150, 400, 1200]) {
      expect(nearPlane(height)).toBeLessThan(Math.max(height - TALL_M, height * 0.3));
    }
  });
});
