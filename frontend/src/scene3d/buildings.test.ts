/* Здания «не простейшими формами» (чекпоинт финала 16.10.2026, п. 1): двускатная крыша у
 * малоэтажного дома, парапет у плоской крыши (facadeModules.ts). */

import { describe, expect, it } from 'vitest';

import { buildingGeometry, hipRoof, pitchedRoof } from './buildings';
import { parapetGeometry } from './facadeModules';
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
  it('малоэтажный жилой дом получает двускатную крышу выше стен, высотка - плоскую', () => {
    const house = building(rotatedRect(), { floors: 2, height: 7, use: 'residential' });
    const tower = building(rotatedRect(), { floors: 16, height: 50, use: 'residential' });
    expect(pitchedRoof(house)).toBe(true);
    expect(pitchedRoof(tower)).toBe(false);
    expect(maxY(buildingGeometry([house]).roofs)).toBeGreaterThan(7 + 1.5);
    expect(maxY(buildingGeometry([tower]).roofs)).toBeCloseTo(50, 3);
  });

  it('у плоской крыши парапет над краем, у двускатной - нет', () => {
    const mid = building(rotatedRect(), { floors: 5, height: 16.2, use: 'residential' });
    const house = building(rotatedRect(), { floors: 2, height: 7, use: 'residential' });
    expect(maxY(parapetGeometry([mid]))).toBeGreaterThan(16.2 + 0.4);
    expect(maxY(parapetGeometry([mid]))).toBeLessThan(16.2 + 1.5);
    expect(parapetGeometry([house]).getAttribute('position').count).toBe(0);
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

  it('низкий кирпичный дом сложного плана - под вальмовой крышей, как дом 1А на панораме', () => {
    const ell: Flat[] = [
      { x: 0, z: 0 },
      { x: 20, z: 0 },
      { x: 20, z: 7 },
      { x: 7, z: 7 },
      { x: 7, z: 20 },
      { x: 0, z: 20 },
    ];
    const shop = building(ell, { floors: 1, height: 4, wall: 'brick', use: 'non_residential' });
    expect(pitchedRoof(shop)).toBe(false);
    const hip = hipRoof(shop);
    expect(hip).not.toBeNull();
    const inset = hip?.inset ?? [];
    expect(inset.every((p) => p.x > 0.5 && p.z > 0.5 && (p.x < 6.5 || p.z < 6.5))).toBe(true);
    const top = maxY(buildingGeometry([shop]).roofs);
    expect(top).toBeGreaterThan(4.4);
    expect(top).toBeLessThan(6);
  });

  it('высокий дом сложного плана остаётся с плоской крышей', () => {
    const ell: Flat[] = [
      { x: 0, z: 0 },
      { x: 30, z: 0 },
      { x: 30, z: 12 },
      { x: 12, z: 12 },
      { x: 12, z: 30 },
      { x: 0, z: 30 },
    ];
    expect(hipRoof(building(ell, { floors: 9, height: 28, wall: 'brick' }))).toBeNull();
  });
});
