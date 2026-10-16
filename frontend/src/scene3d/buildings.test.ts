/* Здания «не простейшими формами» (чекпоинт финала 16.10.2026, п. 1): двускатная крыша у
 * малоэтажного дома, парапет у плоской крыши, цоколь, машинные помещения на крыше высотки. */

import { describe, expect, it } from 'vitest';

import { buildingGeometry, facadeAccentsGeometry, minRect, pitchedRoof } from './buildings';
import type { Building, Flat } from './types';

function building(ring: Flat[], extra: Partial<Building> = {}): Building {
  return {
    rings: [ring],
    height: 10,
    floors: 3,
    source: 'label',
    kind: 'building',
    wall: null,
    use: null,
    seed: 4,
    ...extra,
  };
}

/** Прямоугольник 24 x 10 м, повёрнутый на 30°: длинная сторона вдоль (cos30, sin30). */
function rotatedRect(): Flat[] {
  const c = Math.cos(Math.PI / 6);
  const s = Math.sin(Math.PI / 6);
  return [
    [0, 0],
    [24, 0],
    [24, 10],
    [0, 10],
  ].map(([x = 0, z = 0]) => ({ x: x * c - z * s, z: x * s + z * c }));
}

function maxY(geometry: {
  getAttribute(name: string): { count: number; getY(i: number): number };
}): number {
  const pos = geometry.getAttribute('position');
  let top = -Infinity;
  for (let i = 0; i < pos.count; i++) top = Math.max(top, pos.getY(i));
  return top;
}

describe('здания', () => {
  it('минимальный прямоугольник находит длину и ширину повёрнутого дома', () => {
    const rect = minRect(rotatedRect());
    expect(rect.length).toBeCloseTo(24, 3);
    expect(rect.width).toBeCloseTo(10, 3);
    expect(Math.abs(rect.ux)).toBeCloseTo(Math.cos(Math.PI / 6), 3);
  });

  it('малоэтажный жилой дом получает двускатную крышу выше стен, высотка - плоскую', () => {
    const house = building(rotatedRect(), { floors: 2, height: 7, use: 'residential' });
    const tower = building(rotatedRect(), { floors: 16, height: 50, use: 'residential' });
    expect(pitchedRoof(house)).toBe(true);
    expect(pitchedRoof(tower)).toBe(false);
    expect(maxY(buildingGeometry([house]).roofs)).toBeGreaterThan(7 + 1.5);
    expect(maxY(buildingGeometry([tower]).roofs)).toBeCloseTo(50, 3);
  });

  it('у плоской крыши парапет, у высотки машинные помещения над крышей', () => {
    const mid = building(rotatedRect(), { floors: 5, height: 16.2, use: 'residential' });
    const tower = building(rotatedRect(), { floors: 16, height: 50, use: 'residential' });
    expect(maxY(facadeAccentsGeometry([mid]))).toBeGreaterThan(16.2 + 0.5);
    expect(maxY(facadeAccentsGeometry([mid]))).toBeLessThan(16.2 + 1.5);
    expect(maxY(facadeAccentsGeometry([tower]))).toBeGreaterThan(50 + 2.5);
  });

  it('Г-образный контур не накрывается прямоугольной двускатной крышей', () => {
    const ell: Flat[] = [
      { x: 0, z: 0 },
      { x: 20, z: 0 },
      { x: 20, z: 6 },
      { x: 6, z: 6 },
      { x: 6, z: 20 },
      { x: 0, z: 20 },
    ];
    expect(pitchedRoof(building(ell, { floors: 2, height: 7, use: 'residential' }))).toBe(false);
  });
});
