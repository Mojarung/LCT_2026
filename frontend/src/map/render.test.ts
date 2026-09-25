import { describe, expect, it } from 'vitest';

import { cornerMarks, NORTH_RADIUS } from './render';

describe('знаки в углу карты', () => {
  it.each([
    ['1440 между панелями', { left: 326, top: 70, width: 730, height: 760 }],
    ['768, карта во всю ширину', { left: 0, top: 0, width: 768, height: 520 }],
    ['375', { left: 0, top: 0, width: 375, height: 340 }],
  ])('%s: диск севера целиком в свободной области, линейка его не касается', (_, area) => {
    const { north, scaleRight, scaleY } = cornerMarks(area);
    expect(north.x + NORTH_RADIUS).toBeLessThanOrEqual(area.left + area.width);
    expect(north.y + NORTH_RADIUS).toBeLessThanOrEqual(area.top + area.height);
    expect(north.x - NORTH_RADIUS).toBeGreaterThanOrEqual(area.left);
    // Плашка линейки: 12 пикселей полей справа от штриха, между ней и диском есть зазор.
    expect(scaleRight + 12).toBeLessThan(north.x - NORTH_RADIUS);
    // Плашка линейки (25 над линией, 10 под ней) - по высоте в пределах диска.
    expect(scaleY - 25).toBeGreaterThanOrEqual(north.y - NORTH_RADIUS);
    expect(scaleY + 10).toBeLessThanOrEqual(north.y + NORTH_RADIUS);
  });
});
