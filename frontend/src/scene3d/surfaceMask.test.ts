import { describe, expect, it } from 'vitest';

import {
  ASPHALT,
  absorbSmall,
  ASPHALT_RGB,
  blurBytes,
  classifySurface,
  despeckle,
  distanceInside,
  EMPTY,
  GRASS,
  keepLarge,
  maxFilter,
  PAVERS,
  PAVERS_RGB,
  ROAD,
  ROAD_RGB,
  smoothBinary,
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
    const colors = [ROAD_RGB, PAVERS_RGB, ASPHALT_RGB, SOIL_RGB];
    const rgba = raster(w, h, (x) => [...(colors[Math.floor(x / 10)] ?? SOIL_RGB), 255]);
    const kind = classifySurface(rgba, w, h, 0.25, 128);
    expect([5, 15, 25, 35].map((x) => kind[2 * w + x])).toEqual([ROAD, PAVERS, ASPHALT, GRASS]);
  });

  it('вид покрытия контура - от сервиса: узкий асфальт у проезда по ширине не делится', () => {
    // Плитку за бортом и асфальт решает сервис целиком по части (surface.json, paved_kind).
    const w = 40 + 1 + 12 + 8;
    const h = 30;
    const rgba = raster(w, h, (x) => {
      if (x < 40) return [...ROAD_RGB, 255];
      if (x < 41) return null;
      if (x < 53) return [...ASPHALT_RGB, 255];
      return [...SOIL_RGB, 255];
    });
    const kind = classifySurface(rgba, w, h, 0.25, 128);
    expect(kind[15 * w + 47]).toBe(ASPHALT);
  });

  it('покрытие контура без вида по ширине тоже не делится', () => {
    const w = 60;
    const h = 30;
    // Полоса 3 м посреди газона: раньше по ширине она становилась плиткой.
    const rgba = raster(w, h, (x) =>
      x >= 20 && x < 32 ? [140, 142, 150, 255] : [...SOIL_RGB, 255],
    );
    const kind = classifySurface(rgba, w, h, 0.25, 128);
    expect(kind[15 * w + 26]).toBe(ASPHALT);
    // Растр старых прогонов по-прежнему делится по ширине.
    expect(classifySurface(rgba, w, h, 0.25)[15 * w + 26]).toBe(PAVERS);
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

describe('шум карты покрытий', () => {
  it('мелкий островок газона на проезде и пятнышко асфальта на газоне исчезают', () => {
    const w = 40;
    const h = 20;
    const mask = new Uint8Array(w * h);
    for (let y = 0; y < h; y++) for (let x = 0; x < 20; x++) mask[y * w + x] = 1;
    mask[10 * w + 8] = 0;
    mask[5 * w + 30] = 1;
    despeckle(mask, w, h, 4);
    expect(mask[10 * w + 8]).toBe(1);
    expect(mask[5 * w + 30]).toBe(0);
    // Большие области остаются как были.
    expect(mask[10 * w + 2]).toBe(1);
    expect(mask[10 * w + 35]).toBe(0);
  });
});

describe('сглаживание границ маски', () => {
  it('лесенка растра становится прямой, большая область сохраняет площадь', () => {
    const w = 60;
    const h = 60;
    // Наклонная граница ступеньками по 3 пикселя.
    const v = new Uint8Array(w * h);
    for (let y = 0; y < h; y++) {
      const edge = 10 + Math.floor(y / 3) * 3 * 0.5;
      for (let x = 0; x < w; x++) v[y * w + x] = x < edge ? 255 : 0;
    }
    const s = smoothBinary(v, w, h, 3);
    const area = (m: Uint8Array) => m.reduce((n, x) => n + (x ? 1 : 0), 0);
    expect(Math.abs(area(s) - area(v)) / area(v)).toBeLessThan(0.03);
    // Граница в каждой строке середины отходит от прямой x = 10 + y/2 не больше чем на пиксель.
    for (let y = 10; y < 50; y++) {
      let edge = 0;
      while (edge < w && s[y * w + edge]) edge++;
      expect(Math.abs(edge - (10 + y / 2))).toBeLessThanOrEqual(1.5);
    }
  });

  it('пятно меньше окна исчезает', () => {
    const w = 30;
    const h = 30;
    const v = new Uint8Array(w * h);
    v[15 * w + 15] = 255;
    v[15 * w + 16] = 255;
    expect(smoothBinary(v, w, h, 3).every((x) => x === 0)).toBe(true);
  });
});

describe('проезжая часть', () => {
  it('малые пятна асфальта не опускаются, большие и у края остаются', () => {
    const w = 40;
    const h = 40;
    const m = new Uint8Array(w * h);
    for (let y = 5; y < 8; y++) for (let x = 5; x < 8; x++) m[y * w + x] = 1;
    for (let y = 15; y < 35; y++) for (let x = 15; x < 35; x++) m[y * w + x] = 1;
    m[0] = 1;
    keepLarge(m, w, h, 50);
    expect(m[6 * w + 6]).toBe(0);
    expect(m[20 * w + 20]).toBe(1);
    expect(m[0]).toBe(1);
  });
});

describe('размытие маски', () => {
  it('ступенька становится переходом, середина края - около половины', () => {
    const w = 20;
    const h = 5;
    const v = new Uint8Array(w * h);
    for (let y = 0; y < h; y++) for (let x = 10; x < w; x++) v[y * w + x] = 255;
    const b = blurBytes(v, w, h, 1);
    expect(b[2 * w + 2]).toBe(0);
    expect(b[2 * w + 17]).toBe(255);
    const mid = ((b[2 * w + 9] ?? 0) + (b[2 * w + 10] ?? 0)) / 2;
    expect(mid).toBeGreaterThan(100);
    expect(mid).toBeLessThan(155);
  });
});

describe('обрывки на стыках дорожек', () => {
  it('пятно асфальта между плиткой и газоном отходит плитке, у проезда - остаётся', () => {
    const w = 30;
    const h = 20;
    // 0 - газон, 1 - плитка, 2 - асфальт тротуара, 3 - проезд.
    const l = new Uint8Array(w * h);
    for (let y = 8; y < 12; y++) for (let x = 0; x < w; x++) l[y * w + x] = 1;
    for (let y = 7; y < 10; y++) for (let x = 10; x < 13; x++) l[y * w + x] = 2;
    for (let y = 0; y < 3; y++) for (let x = 0; x < w; x++) l[y * w + x] = 3;
    for (let y = 3; y < 5; y++) for (let x = 20; x < 23; x++) l[y * w + x] = 2;
    const out = absorbSmall(l, w, h, 2, 40, [3]);
    expect(out[8 * w + 11]).toBe(1);
    expect(out[3 * w + 21]).toBe(2);
  });
});
