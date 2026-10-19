import { describe, expect, it } from 'vitest';

import { CAR_LENGTH_M, parkingSpots } from './parking';
import type { Line } from './types';

const curb: Line = {
  points: [
    { x: 0, z: 0 },
    { x: 200, z: 0 },
  ],
};

describe('машины вдоль бортов', () => {
  it('встают только на сторону проезда, вдоль борта и не налезают друг на друга', () => {
    // Проезд - z > 0, тротуар и газон - z < 0.
    const spots = parkingSpots({
      curbs: [curb],
      asphaltAt: (_x, z) => z > 0,
      poles: [],
      plants: [],
    });
    expect(spots.length).toBeGreaterThan(10);
    for (const s of spots) {
      expect(s.z).toBeGreaterThan(0.9);
      expect(s.z).toBeLessThan(1.5);
      expect(Math.cos(s.angle)).toBeCloseTo(1, 5);
    }
    const xs = spots.map((s) => s.x).sort((a, b) => a - b);
    for (let i = 1; i < xs.length; i++) {
      expect((xs[i] ?? 0) - (xs[i - 1] ?? 0)).toBeGreaterThanOrEqual(CAR_LENGTH_M);
    }
  });

  it('узкий проезд не занимают: машина перегородила бы въезд', () => {
    const spots = parkingSpots({
      curbs: [curb],
      asphaltAt: (_x, z) => z > 0 && z < 3.5,
      poles: [],
      plants: [],
    });
    expect(spots).toHaveLength(0);
  });

  it('у опоры и у посадки места нет, без асфальта машин нет вовсе', () => {
    const all = parkingSpots({ curbs: [curb], asphaltAt: (_x, z) => z > 0, poles: [], plants: [] });
    const first = all[0];
    expect(first).toBeDefined();
    const blocked = parkingSpots({
      curbs: [curb],
      asphaltAt: (_x, z) => z > 0,
      poles: [{ x: first?.x ?? 0, z: 0.3 }],
      plants: [],
    });
    expect(blocked.some((s) => Math.abs(s.x - (first?.x ?? 0)) < 0.01)).toBe(false);
    expect(
      parkingSpots({ curbs: [curb], asphaltAt: () => false, poles: [], plants: [] }),
    ).toHaveLength(0);
  });

  it('на изломе борта машины не ставятся поперёк угла', () => {
    const corner: Line = {
      points: [
        { x: 0, z: 0 },
        { x: 3, z: 0 },
        { x: 3, z: 3 },
      ],
    };
    expect(
      parkingSpots({ curbs: [corner], asphaltAt: () => true, poles: [], plants: [] }),
    ).toHaveLength(0);
  });
});

describe('машины вдоль края асфальта', () => {
  it('встают у обоих краёв широкого проезда вдоль него, на узком - нигде', () => {
    const mpp = 0.25;
    const w = 240;
    const h = 120;
    const grid = (rows: [number, number]) => {
      const paved = new Uint8Array(w * h);
      for (let y = rows[0]; y < rows[1]; y++) for (let x = 0; x < w; x++) paved[y * w + x] = 1;
      return { paved, width: w, height: h, minX: 0, minZ: 0, metresPerPx: mpp };
    };
    const input = { curbs: [], asphaltAt: () => false, poles: [], plants: [] };
    // Проезд 10 м: z от 5 до 15.
    const wide = parkingSpots(input, grid([20, 60]));
    expect(wide.length).toBeGreaterThan(3);
    for (const s of wide) {
      expect(Math.min(Math.abs(s.z - 5), Math.abs(s.z - 15))).toBeCloseTo(1.15, 0);
      expect(Math.abs(Math.cos(s.angle))).toBeCloseTo(1, 3);
    }
    // Проезд 4 м машину не вмещает рядом с полосой движения.
    expect(parkingSpots(input, grid([20, 36]))).toHaveLength(0);
  });
});

describe('машины и ограды', () => {
  it('машина не встаёт сквозь забор вдоль борта', () => {
    const fence = {
      points: [
        { x: 0, z: 1.15 },
        { x: 200, z: 1.15 },
      ],
    };
    const spots = parkingSpots({
      curbs: [curb],
      asphaltAt: (_x, z) => z > 0,
      poles: [],
      plants: [],
      fences: [fence],
    });
    expect(spots).toHaveLength(0);
  });
});

describe('машины у края асфальта без борта и дома', () => {
  it('у края без борта машину не ставят ближе EDGE_WALL_M к стене дома (вход в магазин у 1А)', () => {
    // Проезд 10 м (z 5..15), дом стоит за краем: стена в 3,5 м от края проезда.
    const mpp = 0.25;
    const w = 240;
    const h = 120;
    const paved = new Uint8Array(w * h);
    for (let y = 20; y < 60; y++) for (let x = 0; x < w; x++) paved[y * w + x] = 1;
    const house = [
      { x: 10, z: -10 },
      { x: 50, z: -10 },
      { x: 50, z: 1.5 },
      { x: 10, z: 1.5 },
    ];
    const input = { curbs: [], asphaltAt: () => false, poles: [], plants: [], walls: [house] };
    const spots = parkingSpots(input, {
      paved,
      width: w,
      height: h,
      minX: 0,
      minZ: 0,
      metresPerPx: mpp,
    });
    expect(spots.length).toBeGreaterThan(0);
    // У дома (x 10..50) на ближнем к нему краю (z около 6) машин нет.
    expect(spots.filter((s) => s.x > 8 && s.x < 52 && s.z < 10)).toHaveLength(0);
  });
});

describe('машины у борта и дом', () => {
  it('у борта машину не ставят ближе 6 м к стене дома', () => {
    const house = [
      { x: 20, z: 3 },
      { x: 60, z: 3 },
      { x: 60, z: 20 },
      { x: 20, z: 20 },
    ];
    const spots = parkingSpots({
      curbs: [curb],
      asphaltAt: (_x, z) => z > 0 && z < 8,
      poles: [],
      plants: [],
      walls: [house],
    });
    expect(spots.filter((s) => s.x > 15 && s.x < 65)).toHaveLength(0);
  });
});
