import { describe, expect, it } from 'vitest';

import type { BasemapFeature } from '../api/artifacts';
import { boundsOfPoints, contentPoints, principalAxis, trimmed } from './geometry';

describe('геометрия подосновы', () => {
  it('главная ось точек вдоль прямой под 30 градусов - 30 градусов', () => {
    const angle = Math.PI / 6;
    const points = Array.from({ length: 50 }, (_, i) => ({
      x: i * Math.cos(angle) + ((i % 3) - 1) * 0.01,
      y: i * Math.sin(angle),
    }));
    expect(principalAxis(points)).toBeCloseTo(angle, 3);
  });

  it('меньше трёх точек - без разворота', () => {
    expect(
      principalAxis([
        { x: 0, y: 0 },
        { x: 5, y: 5 },
      ]),
    ).toBe(0);
  });

  it('далёкий выброс отрезается 2-98-м процентилем', () => {
    const points = Array.from({ length: 100 }, (_, i) => ({ x: i, y: i % 10 }));
    points.push({ x: 50_000, y: 3 });
    const kept = trimmed(points);
    expect(kept.some((p) => p.x === 50_000)).toBe(false);
    expect(kept.length).toBeGreaterThan(90);
  });

  it('граница работ в опору вписывания не входит', () => {
    const features: BasemapFeature[] = [
      {
        type: 'Feature',
        properties: { class: 'work_boundary' },
        geometry: {
          type: 'LineString',
          coordinates: [
            [-5000, 0],
            [5000, 0],
          ],
        },
      },
      {
        type: 'Feature',
        properties: { class: 'curb' },
        geometry: {
          type: 'LineString',
          coordinates: [
            [0, 0],
            [10, 0],
          ],
        },
      },
    ];
    expect(contentPoints(features)).toEqual([{ x: 5, y: 0 }]);
  });

  it('габарит точек с запасом', () => {
    expect(
      boundsOfPoints(
        [
          { x: 1, y: 2 },
          { x: 3, y: -4 },
        ],
        10,
      ),
    ).toEqual([-9, -14, 13, 12]);
    expect(boundsOfPoints([], 10)).toBeNull();
  });
});
