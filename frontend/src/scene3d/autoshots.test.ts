import { describe, expect, it } from 'vitest';

import { wallAhead } from './autoshots';
import { bounds, type ShotObstacle } from './shots';

/** Дом 10 x 10 м высотой 20 м с южной стеной на z = -10. */
const ring = [
  { x: -5, z: -20 },
  { x: 5, z: -20 },
  { x: 5, z: -10 },
  { x: -5, z: -10 },
];
const house: ShotObstacle[] = [{ ring, height: 20, ...bounds(ring) }];

describe('кадр улицы перед стеной', () => {
  it('взгляд на север в стену в 10 м - кадр упирается в дом', () => {
    expect(wallAhead({ x: 0, y: 8, z: 0, yaw: 0, pitch: 0 }, house)).toBe(true);
  });

  it('тот же дом за спиной, выше крыши или дальше 15 м - кадр свободен', () => {
    expect(wallAhead({ x: 0, y: 8, z: 0, yaw: Math.PI, pitch: 0 }, house)).toBe(false);
    expect(wallAhead({ x: 0, y: 25, z: 0, yaw: 0, pitch: 0 }, house)).toBe(false);
    expect(wallAhead({ x: 0, y: 8, z: 12, yaw: 0, pitch: 0 }, house)).toBe(false);
  });
});
