import { describe, expect, it } from 'vitest';

import { placePeople } from './people';
import { ASPHALT, GRASS, PAVERS } from './surfaceMask';
import { atmosphereOf, CALM, particleCount } from './weather';

describe('погода', () => {
  it('в тихую погоду небо и земля не меняются', () => {
    const calm = atmosphereOf({ ...CALM, wind: 0 }, 0.3);
    expect(calm.clouds).toBe(0.3);
    expect(calm.fog).toBe(0);
    expect(calm.wet).toBe(0);
    expect(calm.snowCover).toBe(0);
    expect(Math.hypot(calm.windX, calm.windZ)).toBe(0);
  });

  it('дождь затягивает небо и мочит землю, снег ложится и сгущает дымку сильнее дождя', () => {
    const rain = atmosphereOf({ ...CALM, rain: 0.8 }, 0.2);
    const snow = atmosphereOf({ ...CALM, snow: 0.8 }, 0.2);
    expect(rain.clouds).toBeGreaterThan(0.7);
    expect(rain.wet).toBe(1);
    expect(snow.snowCover).toBe(1);
    expect(snow.fog).toBeGreaterThan(rain.fog);
  });

  it('ветер дует с запада-юго-запада: воздух движется на восток-северо-восток', () => {
    const w = atmosphereOf({ ...CALM, wind: 1 }, 0);
    expect(w.windX).toBeGreaterThan(0);
    expect(w.windZ).toBeLessThan(0);
    expect(Math.hypot(w.windX, w.windZ)).toBeCloseTo(12);
    expect(w.sway).toBeGreaterThan(atmosphereOf(CALM, 0).sway);
  });

  it('частиц тем больше, чем сильнее осадки, и не больше запаса', () => {
    expect(particleCount(1000, 0)).toBe(0);
    expect(particleCount(1000, 0.5)).toBeLessThan(particleCount(1000, 0.9));
    expect(particleCount(1000, 3)).toBe(1000);
  });
});

describe('люди', () => {
  /** Метр на пиксель: газон, по середине - тротуар шириной 3 м вдоль x, сбоку проезд. */
  function grid() {
    const width = 60;
    const height = 20;
    const kinds = new Uint8Array(width * height).fill(GRASS);
    for (let y = 8; y < 11; y++) for (let x = 0; x < width; x++) kinds[y * width + x] = PAVERS;
    for (let y = 14; y < 20; y++) for (let x = 0; x < width; x++) kinds[y * width + x] = ASPHALT;
    return {
      kinds,
      width,
      height,
      metresPerPx: 1,
      rect: [0, 0, 60, 20] as [number, number, number, number],
    };
  }

  it('люди стоят на тротуаре, а не на газоне и не на проезде', () => {
    const people = placePeople(grid(), 50);
    expect(people).toHaveLength(50);
    expect(people.every((p) => p.z > 8 && p.z < 11)).toBe(true);
  });

  it('гуляющие идут вдоль тротуара, расстановка повторяется', () => {
    const people = placePeople(grid(), 80);
    const walking = people.filter((p) => p.span > 0);
    expect(walking.length).toBeGreaterThan(10);
    // Вдоль x: курс плюс-минус 90 градусов, синус по модулю - единица.
    expect(walking.every((p) => Math.abs(Math.abs(Math.sin(p.heading)) - 1) < 1e-6)).toBe(true);
    expect(placePeople(grid(), 80)).toEqual(people);
  });

  it('без тротуаров и площадок людей нет', () => {
    const empty = { ...grid(), kinds: new Uint8Array(60 * 20).fill(GRASS) };
    expect(placePeople(empty, 30)).toEqual([]);
  });
});
