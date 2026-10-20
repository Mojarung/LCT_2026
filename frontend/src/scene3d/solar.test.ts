import { describe, expect, it } from 'vitest';

import { clock, SEASON_DAY, showcaseHour, sunDirection, sunPosition } from './solar';

/** Самая высокая точка солнца за день с шагом в минуту. */
function solarNoon(day: number, lat?: number, lon?: number) {
  let best = { hour: 0, elevation: -90, azimuth: 0 };
  for (let m = 0; m < 24 * 60; m++) {
    const hour = m / 60;
    const s = sunPosition(day, hour, lat, lon);
    if (s.elevation > best.elevation) best = { hour, ...s };
  }
  return best;
}

describe('солнце над Москвой', () => {
  it('1 июля в полдень солнце стоит на юге на 57 градусах, полдень по часам - около 12:33', () => {
    const noon = solarNoon(SEASON_DAY.summer);
    // 90 - 55,75 + 23,1 = 57,4 градуса.
    expect(noon.elevation).toBeGreaterThan(56.5);
    expect(noon.elevation).toBeLessThan(58);
    expect(noon.azimuth).toBeGreaterThan(177);
    expect(noon.azimuth).toBeLessThan(183);
    // Московское время на полчаса впереди солнечного (долгота 37,6 против пояса 45).
    expect(noon.hour).toBeGreaterThan(12.4);
    expect(noon.hour).toBeLessThan(12.75);
  });

  it('в равноденствие полдень на высоте 90 - широта, в середине января - около 11 градусов', () => {
    expect(solarNoon(80).elevation).toBeCloseTo(90 - 55.75, 0);
    const winter = solarNoon(SEASON_DAY.winter).elevation;
    expect(winter).toBeGreaterThan(10);
    expect(winter).toBeLessThan(13);
  });

  it('на экваторе в равноденствие солнце в полдень почти в зените', () => {
    expect(solarNoon(80, 0, 45).elevation).toBeGreaterThan(88);
  });

  it('азимут всегда в пределах 0..360, утром восток, вечером запад', () => {
    for (let hour = 0; hour < 24; hour += 0.5) {
      const { azimuth, elevation } = sunPosition(SEASON_DAY.spring, hour);
      expect(azimuth).toBeGreaterThanOrEqual(0);
      expect(azimuth).toBeLessThan(360);
      expect(Math.abs(elevation)).toBeLessThanOrEqual(90);
    }
    expect(sunPosition(SEASON_DAY.spring, 7).azimuth).toBeLessThan(110);
    expect(sunPosition(SEASON_DAY.spring, 19).azimuth).toBeGreaterThan(250);
  });
});

describe('направление на солнце в осях сцены', () => {
  const close = (a: [number, number, number], b: [number, number, number]) => {
    a.forEach((v, i) => {
      expect(v).toBeCloseTo(b[i] ?? NaN, 9);
    });
  };

  it('восток - +x, юг - +z, север - -z, зенит - +y', () => {
    close(sunDirection({ azimuth: 90, elevation: 0 }), [1, 0, 0]);
    close(sunDirection({ azimuth: 180, elevation: 0 }), [0, 0, 1]);
    close(sunDirection({ azimuth: 0, elevation: 0 }), [0, 0, -1]);
    close(sunDirection({ azimuth: 270, elevation: 0 }), [-1, 0, 0]);
    close(sunDirection({ azimuth: 123, elevation: 90 }), [0, 1, 0]);
  });

  it('вектор единичный, его подъём - синус высоты', () => {
    const [x, y, z] = sunDirection({ azimuth: 210, elevation: 30 });
    expect(Math.hypot(x, y, z)).toBeCloseTo(1, 12);
    expect(y).toBeCloseTo(0.5, 12);
  });
});

describe('выставочный час', () => {
  it('после полудня, солнце над горизонтом на 0,58 полуденной высоты, но не выше 22 градусов', () => {
    for (const season of ['spring', 'summer', 'autumn', 'winter'] as const) {
      const hour = showcaseHour(season);
      const day = SEASON_DAY[season];
      const target = Math.min(22, sunPosition(day, 13).elevation * 0.58);
      const elevation = sunPosition(day, hour).elevation;
      expect(hour).toBeGreaterThanOrEqual(13.25);
      expect(hour).toBeLessThanOrEqual(21);
      expect(elevation).toBeGreaterThan(0);
      // Шаг 15 минут: солнце за четверть часа уходит не больше чем на 3 градуса.
      expect(Math.abs(elevation - target)).toBeLessThan(1.6);
    }
  });

  it('летом свет «поздний» позже, чем зимой: зимой темнеет к половине пятого', () => {
    expect(showcaseHour('summer')).toBeGreaterThan(17);
    expect(showcaseHour('winter')).toBeLessThan(15.5);
  });
});

describe('часы сцены', () => {
  it('дробный час пишется как на часах', () => {
    expect(clock(13.25)).toBe('13:15');
    expect(clock(9)).toBe('09:00');
    expect(clock(7.5)).toBe('07:30');
    expect(clock(0.75)).toBe('00:45');
  });
});
