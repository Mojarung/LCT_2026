import { describe, expect, it } from 'vitest';

import { clearance, route, TOUR_HEIGHT_M, tourStart } from './tour';

// Прямая улица 400 м вдоль x.
const street = route([
  { x: 0, z: 0 },
  { x: 400, z: 0 },
]);

describe('старт облёта', () => {
  it('начинается над открытым местом, а не у высотки в начале маршрута', () => {
    const tower = { minX: -10, minZ: 5, maxX: 30, maxZ: 25, height: 48 };
    const heights = clearance(street, [tower]);

    // У начала маршрута камера идёт над крышей высотки.
    expect(heights[0]).toBeGreaterThan(TOUR_HEIGHT_M + 20);
    const start = tourStart(street, heights);
    expect(start).toBeGreaterThan(150);
    expect(start).toBeLessThan(street.length);
  });

  it('без зданий начинается с середины маршрута', () => {
    const heights = clearance(street, []);

    expect(tourStart(street, heights)).toBeCloseTo(street.length / 2, 0);
  });
});
