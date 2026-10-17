import { describe, expect, it } from 'vitest';

import {
  ASPHALT,
  ASPHALT_RGB,
  classifySurface,
  distanceInside,
  EMPTY,
  GRASS,
  maxFilter,
  PAVERS,
  PAVERS_RGB,
  ROAD,
  ROAD_RGB,
  SOIL_RGB,
} from './surfaceMask';

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

  it('узкая полоса покрытия - плитка тротуара, широкая - асфальт, грунт - газон, пусто - пусто', () => {
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
    expect(at(18, 18)).toBe(EMPTY);
  });

  it('щель по линии борта закрывается покрытием, тротуар остаётся плиткой', () => {
    // 0,25 м на пиксель: газон 1 м, тротуар 2 м, щель борта 0,5 м, проезд 10 м, щель 0,5 м,
    // газон 3 м.
    const w = 84;
    const h = 10;
    const rgba = raster(w, h, (x) => {
      if (x < 4) return SOIL;
      if (x < 12) return PAVED;
      if (x < 14) return null;
      if (x < 54) return PAVED;
      if (x < 56) return null;
      if (x < 68) return SOIL;
      return null;
    });
    const kind = classifySurface(rgba, w, h, 0.25);
    const at = (x: number) => kind[5 * w + x];
    expect(at(8)).toBe(PAVERS);
    expect(at(13)).not.toBe(GRASS); // щель между тротуаром и проездом
    expect(at(34)).toBe(ASPHALT);
    expect(at(55)).toBe(GRASS); // щель между проездом и газоном - газон
    expect(at(62)).toBe(GRASS);
    expect(at(2)).toBe(GRASS);
  });

  it('узкий газон между тротуаром и проездом остаётся газоном: закрывается только пустая щель', () => {
    // 0,25 м на пиксель: газон, тротуар 2 м, газон 0,75 м (лунки деревьев), проезд 10 м.
    const w = 70;
    const h = 10;
    const rgba = raster(w, h, (x) => {
      if (x < 4) return SOIL;
      if (x < 12) return PAVED;
      if (x < 15) return SOIL;
      if (x < 55) return PAVED;
      return SOIL;
    });
    const kind = classifySurface(rgba, w, h, 0.25);
    expect(kind[5 * w + 13]).toBe(GRASS);
  });

  it('край контура считается покрытием от половины покрытия пикселя: асфальт не вылезает за край', () => {
    // Контур кладётся непрозрачной заливкой, край - пиксели с долей покрытия (альфа).
    const opaque: [number, number, number, number] = [140, 142, 150, 255];
    const edge: [number, number, number, number] = [140, 142, 150, 60];
    const w = 40;
    const h = 4;
    const rgba = raster(w, h, (x) => (x < 20 ? opaque : x === 20 ? edge : null));
    const kind = classifySurface(rgba, w, h, 0.25, 128);
    expect(kind[2 * w + 19]).not.toBe(GRASS);
    expect(kind[2 * w + 20]).toBe(EMPTY);
    // Растр старых прогонов полупрозрачный: там покрытие - любой непустой пиксель.
    expect(classifySurface(rgba, w, h, 0.25)[2 * w + 20]).not.toBe(GRASS);
  });

  it('вид покрытия контура читается по цвету: проезд, асфальт тротуара, плитка, газон', () => {
    const w = 40;
    const h = 4;
    const colors = [ROAD_RGB, ASPHALT_RGB, PAVERS_RGB, SOIL_RGB];
    const rgba = raster(w, h, (x) => [...(colors[Math.floor(x / 10)] ?? SOIL_RGB), 255]);
    const kind = classifySurface(rgba, w, h, 0.25, 128);
    expect([5, 15, 25, 35].map((x) => kind[2 * w + x])).toEqual([ROAD, ASPHALT, PAVERS, GRASS]);
  });

  it('щель между тротуаром и газоном - газон: садовый борт встаёт по краю тротуара', () => {
    // 0,25 м на пиксель: плитка 2 м, щель 0,5 м (линия борта), газон 3 м, дальше пусто.
    const w = 60;
    const h = 4;
    const rgba = raster(w, h, (x) => {
      if (x < 8) return [...PAVERS_RGB, 255];
      if (x < 10) return null;
      if (x < 22) return [...SOIL_RGB, 255];
      return null;
    });
    const kind = classifySurface(rgba, w, h, 0.25, 128);
    expect(kind[2 * w + 9]).toBe(GRASS);
    expect(kind[2 * w + 40]).toBe(EMPTY);
  });
});
