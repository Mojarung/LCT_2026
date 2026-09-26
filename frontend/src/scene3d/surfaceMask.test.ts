import { describe, expect, it } from 'vitest';

import { ASPHALT, classifySurface, distanceInside, GRASS, maxFilter, PAVERS } from './surfaceMask';

const PAVED: [number, number, number, number] = [140, 142, 150, 96];
const SOIL: [number, number, number, number] = [104, 158, 104, 88];

/** Карта w x h, где функция решает цвет пикселя. */
function raster(
  w: number,
  h: number,
  at: (x: number, y: number) => number[] | null,
): Uint8ClampedArray {
  const out = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const c = at(x, y);
      if (c) out.set(c, (y * w + x) * 4);
    }
  }
  return out;
}

describe('покрытие земли в 3D', () => {
  it('расстояние до края покрытия растёт к середине полосы', () => {
    const paved = new Uint8Array(9).fill(1);
    paved[0] = 0;
    const d = distanceInside(paved, 9, 1);
    expect(Array.from(d.slice(0, 5))).toEqual([0, 1, 2, 3, 4]);
  });

  it('максимум в окне равен максимуму соседей, у края окно обрезается', () => {
    const src = new Float32Array([1, 5, 2, 0, 0, 7, 0]);
    expect(Array.from(maxFilter(src, 7, 1, 1))).toEqual([5, 5, 5, 2, 7, 7, 7]);
  });

  it('узкая полоса покрытия - плитка тротуара, широкая - асфальт, грунт и пустое - газон', () => {
    // Метр на пиксель: газон, полоса 3 м, газон, проезд 12 м, газон; внизу пусто.
    const w = 30;
    const h = 20;
    const rgba = raster(w, h, (x, y) => {
      if (y >= 16) return null;
      if (x < 2) return SOIL;
      if (x < 5) return PAVED;
      if (x < 12) return SOIL;
      if (x < 24) return PAVED;
      return SOIL;
    });
    const kind = classifySurface(rgba, w, h, 1);
    const at = (x: number, y: number) => kind[y * w + x];
    expect(at(3, 8)).toBe(PAVERS);
    expect(at(6, 8)).toBe(GRASS);
    expect(at(18, 8)).toBe(ASPHALT);
    expect(at(13, 8)).toBe(ASPHALT);
    expect(at(18, 18)).toBe(GRASS);
  });
});
