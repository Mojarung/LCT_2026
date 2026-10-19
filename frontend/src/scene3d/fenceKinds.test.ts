import { describe, expect, it } from 'vitest';

import { distanceToArea, picketSpots, splitPlaygroundFences } from './fenceKinds';

const square = [
  { x: 0, z: 0 },
  { x: 10, z: 0 },
  { x: 10, z: 10 },
  { x: 0, z: 10 },
  { x: 0, z: 0 },
];

describe('splitPlaygroundFences', () => {
  it('a fence along the playground edge is the playground fence, a far one is not', () => {
    const along = {
      points: [
        { x: -0.5, z: -0.5 },
        { x: 10.5, z: -0.5 },
      ],
    };
    const far = {
      points: [
        { x: 0, z: 20 },
        { x: 10, z: 20 },
      ],
    };
    const kinds = splitPlaygroundFences([along, far], [[square]]);
    expect(kinds.playground).toEqual([along]);
    expect(kinds.other).toEqual([far]);
  });

  it('a long street fence that only touches the playground stays metal', () => {
    const street = {
      points: [
        { x: -40, z: -1 },
        { x: 40, z: -1 },
      ],
    };
    const kinds = splitPlaygroundFences([street], [[square]]);
    expect(kinds.other).toEqual([street]);
  });
});

describe('distanceToArea', () => {
  it('is zero inside and the edge distance outside', () => {
    expect(distanceToArea([square], { x: 5, z: 5 })).toBe(0);
    expect(distanceToArea([square], { x: 5, z: -2 })).toBeCloseTo(2);
  });
});

describe('picketSpots', () => {
  it('spaces pickets along the line and turns them with it', () => {
    const spots = picketSpots(
      [
        {
          points: [
            { x: 0, z: 0 },
            { x: 0, z: 1 },
          ],
        },
      ],
      0.25,
    );
    expect(spots).toHaveLength(4);
    expect(spots[0]?.z).toBeCloseTo(0.125);
    expect(Math.abs(spots[0]?.yaw ?? 0)).toBeCloseTo(Math.PI / 2);
  });
});
