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

describe('город вокруг: края данных', () => {
  const ring = (x: number, y: number, w: number, d: number): [number, number][] => [
    [x, y],
    [x + w, y],
    [x + w, y + d],
    [x, y + d],
  ];

  it('дом без этажности и известного типа - этажность по площади; вырожденный контур пропускается', () => {
    const scene = contextScene(
      {
        ...json,
        buildings: [
          { ring: ring(1100, 2000, 60, 40), levels: null, kind: 'yes' },
          { ring: ring(1300, 2000, 6, 5), levels: null, kind: 'yes' },
          {
            ring: [
              [1400, 2000],
              [1401, 2000],
            ],
            levels: 3,
            kind: 'yes',
          },
        ],
        roads: [],
      },
      frame,
      surveyed,
    );
    expect(scene.buildings).toHaveLength(2);
    const [big, small] = scene.buildings;
    expect(big?.use).toBeNull();
    expect(big?.source).toBe('assumed');
    expect(big?.floors ?? 0).toBeGreaterThan(small?.floors ?? 0);
    expect(big?.height ?? 0).toBeGreaterThan(small?.height ?? 0);
  });

  it('стоянка на снятом месте и вырожденная не кладутся, за краем - асфальт и машины', () => {
    const scene = contextScene(
      {
        ...json,
        buildings: [],
        roads: [],
        parkings: [
          { ring: ring(1100, 1900, 40, 30), kind: 'surface' },
          { ring: ring(1000, 1900, 20, 20), kind: 'surface' },
          {
            ring: [
              [1200, 1900],
              [1210, 1900],
            ],
            kind: 'surface',
          },
        ],
      },
      frame,
      surveyed,
    );
    expect(scene.parkings).toHaveLength(1);
    expect(scene.cars.length).toBeGreaterThan(0);
    for (const car of scene.cars) expect(car.x).toBeGreaterThan(50);
    expect(scene.source).toBe(json.source);
  });

  it('узкая полоса - не стоянка: ряд машин в неё не помещается', () => {
    const strip = [
      { x: 100, z: 0 },
      { x: 140, z: 0 },
      { x: 140, z: 4 },
      { x: 100, z: 4 },
    ];
    expect(parkingCars(strip, () => false)).toEqual([]);
  });

  it('ломаная из одной точки и целиком на снятом месте - без частей', () => {
    expect(outsideParts([{ x: 100, z: 0 }], surveyed)).toEqual([]);
    expect(
      outsideParts(
        [
          { x: 0, z: 0 },
          { x: 40, z: 0 },
        ],
        surveyed,
      ),
    ).toEqual([]);
  });
});
