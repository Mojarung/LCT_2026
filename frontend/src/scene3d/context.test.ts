import { describe, expect, it } from 'vitest';

import { type ContextJson, contextScene, outsideParts, parkingCars } from './context';
import { frameAt } from './world';

const frame = frameAt([1000, 2000]);
/** Снято всё к западу от x = 1050 чертежа (x < 50 сцены). */
const surveyed = (p: { x: number }) => p.x < 50;

const json: ContextJson = {
  version: 1,
  source: '© участники OpenStreetMap, ODbL',
  buildings: [
    {
      ring: [
        [1100, 2000],
        [1160, 2000],
        [1160, 2012],
        [1100, 2012],
      ],
      levels: null,
      kind: 'apartments',
    },
    {
      ring: [
        [1200, 2000],
        [1206, 2000],
        [1206, 2005],
        [1200, 2005],
      ],
      levels: 1,
      kind: 'garages',
    },
  ],
  trees: [
    [1010, 2010],
    [1300, 2100],
    [1130, 2006],
  ],
  roads: [
    {
      line: [
        [1000, 1980],
        [1400, 1980],
      ],
      width_m: 6.5,
      kind: 'residential',
    },
  ],
  greens: [],
  notes: [],
};

describe('город вокруг съёмки', () => {
  it('дом карты без этажности получает её по типу, гаражи - металл', () => {
    const city = contextScene(json, frame, surveyed);
    const [flats, garages] = city.buildings;
    expect(flats?.floors).toBe(9);
    expect(flats?.use).toBe('residential');
    expect(flats?.source).toBe('assumed');
    expect(garages?.wall).toBe('metal');
    expect(garages?.floors).toBe(1);
  });

  it('дорога карты не заходит на снятое место, деревьев из карты нет', () => {
    const city = contextScene(json, frame, surveyed);
    const xs = city.roads.flatMap((g) => g.lines.flatMap((l) => l.points.map((p) => p.x)));
    expect(Math.min(...xs)).toBeGreaterThanOrEqual(48);
    expect('trees' in city).toBe(false);
  });

  it('ломаная режется на части вне снятого места', () => {
    const parts = outsideParts(
      [
        { x: 0, z: 0 },
        { x: 100, z: 0 },
      ],
      (p) => p.x > 40 && p.x < 60,
    );
    expect(parts).toHaveLength(2);
  });
});

describe('стоянки карты', () => {
  it('машины рядами целиком внутри стоянки и не на снятом месте', () => {
    const lot = [
      { x: 0, z: 0 },
      { x: 40, z: 0 },
      { x: 40, z: 20 },
      { x: 0, z: 20 },
    ];
    const cars = parkingCars(lot, () => false);
    expect(cars.length).toBeGreaterThan(10);
    for (const c of cars) {
      expect(c.x).toBeGreaterThan(0.9);
      expect(c.x).toBeLessThan(39.1);
      expect(c.z).toBeGreaterThan(2.2);
      expect(c.z).toBeLessThan(17.8);
    }
    expect(parkingCars(lot, (p) => p.x < 20).every((c) => c.x >= 20)).toBe(true);
  });
});
