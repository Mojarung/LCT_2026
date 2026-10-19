import { describe, expect, it } from 'vitest';

import { canopyCover, canopyPosts, freeCanopies } from './canopies';
import type { Flat } from './types';

const rect = (x: number, z: number, w: number, d: number): Flat[] => [
  { x, z },
  { x: x + w, z },
  { x: x + w, z: z + d },
  { x, z: z + d },
];

describe('навесы', () => {
  it('отдельный пунктирный контур - навес, у стены или крошечный - нет', () => {
    const house = rect(0, 0, 20, 10);
    const free = rect(30, 0, 6, 4);
    const porchRoof = rect(20.2, 3, 2, 3);
    const sign = rect(40, 0, 1, 1);
    expect(freeCanopies([free, porchRoof, sign], [house])).toEqual([free]);
  });

  it('стойки по углам и через 4 м по длинной стороне, внутри контура', () => {
    const posts = canopyPosts(rect(0, 0, 8, 3));
    expect(posts).toHaveLength(6);
    for (const p of posts) {
      expect(p.x).toBeGreaterThan(0);
      expect(p.x).toBeLessThan(8);
      expect(p.z).toBeGreaterThan(0);
      expect(p.z).toBeLessThan(3);
    }
  });
});

it('площадь под навесом закрыта для оборудования площадки', () => {
  const cover = canopyCover([
    { x: 0, z: 0 },
    { x: 4, z: 0 },
    { x: 4, z: 3 },
    { x: 0, z: 3 },
  ]);
  expect(cover.length).toBeGreaterThan(4);
  expect(cover.every((p) => p.x >= 0 && p.x <= 4 && p.z >= 0 && p.z <= 3)).toBe(true);
});
