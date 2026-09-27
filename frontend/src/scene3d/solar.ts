/* Положение солнца над Москвой по дню года и местному времени: тени в 3D-виде должны лечь
 * так, как лягут на улице, иначе снимок нельзя показывать рядом с планом. Формулы - NOAA
 * (склонение и уравнение времени по Спенсеру), точности в полградуса для картинки хватает. */

/** Широта и долгота центра Москвы, градусы. Улицы пилота разнесены на десятки километров,
 *  по высоте солнца это доли градуса. */
export const MOSCOW_LAT = 55.75;
export const MOSCOW_LON = 37.62;
/** Московское время - UTC+3 круглый год. */
const MSK_OFFSET_H = 3;

export interface Sun {
  /** Высота над горизонтом, градусы. */
  elevation: number;
  /** Азимут от севера по часовой, градусы. */
  azimuth: number;
}

const RAD = Math.PI / 180;

export function sunPosition(
  dayOfYear: number,
  hours: number,
  lat = MOSCOW_LAT,
  lon = MOSCOW_LON,
): Sun {
  const g = ((2 * Math.PI) / 365) * (dayOfYear - 1 + (hours - 12) / 24);
  const decl =
    0.006918 -
    0.399912 * Math.cos(g) +
    0.070257 * Math.sin(g) -
    0.006758 * Math.cos(2 * g) +
    0.000907 * Math.sin(2 * g) -
    0.002697 * Math.cos(3 * g) +
    0.00148 * Math.sin(3 * g);
  const eqTime =
    229.18 *
    (0.000075 +
      0.001868 * Math.cos(g) -
      0.032077 * Math.sin(g) -
      0.014615 * Math.cos(2 * g) -
      0.040849 * Math.sin(2 * g));
  const solarMinutes = hours * 60 + eqTime + 4 * lon - 60 * MSK_OFFSET_H;
  const hourAngle = (solarMinutes / 4 - 180) * RAD;
  const phi = lat * RAD;
  const cosZenith =
    Math.sin(phi) * Math.sin(decl) + Math.cos(phi) * Math.cos(decl) * Math.cos(hourAngle);
  const zenith = Math.acos(Math.min(1, Math.max(-1, cosZenith)));
  const elevation = 90 - zenith / RAD;
  const az =
    Math.atan2(
      Math.sin(hourAngle),
      Math.cos(hourAngle) * Math.sin(phi) - Math.tan(decl) * Math.cos(phi),
    ) / RAD;
  return { elevation, azimuth: (az + 180 + 360) % 360 };
}

/** Направление на солнце в координатах сцены: x - восток, y - вверх, z - юг. */
export function sunDirection(sun: Sun): [number, number, number] {
  const el = sun.elevation * RAD;
  const az = sun.azimuth * RAD;
  const horizontal = Math.cos(el);
  return [horizontal * Math.sin(az), Math.sin(el), -horizontal * Math.cos(az)];
}

export type Season = 'spring' | 'summer' | 'autumn' | 'winter';

/** День года каждого сезона сцены: цветение в начале мая, середина лета, золотая осень и
 *  середина января - низкое солнце, длинные тени, темнеет к половине пятого. */
export const SEASON_DAY: Record<Season, number> = {
  spring: 128,
  summer: 182,
  autumn: 275,
  winter: 15,
};

/** Час сцены как на часах: 13.25 -> «13:15». */
export function clock(hour: number): string {
  const h = Math.floor(hour);
  const m = Math.round((hour - h) * 60);
  return `${String(h).padStart(2, '0')}:${String(m === 60 ? 0 : m).padStart(2, '0')}`;
}
