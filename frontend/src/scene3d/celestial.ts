/* Луна над Москвой: положение на небе и фаза для дня и часа сцены.
 *
 * Формулы - из SunCalc (github.com/mourner/suncalc, Владимир Агафонкин, BSD-2-Clause), по
 * «Astronomy Answers» Питера Хлессенса: средние элементы орбиты с главными поправками, до
 * градуса по положению. Для картинки этого хватает с запасом; фаза считается по углу
 * между Солнцем и Землёй, если смотреть с Луны, и на знакомых полнолуниях сходится до
 * процента освещённости. */

import { MOSCOW_LAT, MOSCOW_LON } from './solar';

const RAD = Math.PI / 180;
const DAY_MS = 86_400_000;
const J1970 = 2_440_588;
const J2000 = 2_451_545;
const OBLIQUITY = RAD * 23.4397;
const SUN_DISTANCE_KM = 149_598_000;
/** Год сцены: сезоны 3D-вида - дни этого года. */
export const SCENE_YEAR = 2026;
const MSK_OFFSET_H = 3;

function toDays(ms: number): number {
  return ms / DAY_MS - 0.5 + J1970 - J2000;
}

function rightAscension(l: number, b: number): number {
  return Math.atan2(
    Math.sin(l) * Math.cos(OBLIQUITY) - Math.tan(b) * Math.sin(OBLIQUITY),
    Math.cos(l),
  );
}

function declination(l: number, b: number): number {
  return Math.asin(
    Math.sin(b) * Math.cos(OBLIQUITY) + Math.cos(b) * Math.sin(OBLIQUITY) * Math.sin(l),
  );
}

function sunCoords(d: number): { ra: number; dec: number } {
  const m = RAD * (357.5291 + 0.98560028 * d);
  const c = RAD * (1.9148 * Math.sin(m) + 0.02 * Math.sin(2 * m) + 0.0003 * Math.sin(3 * m));
  const l = m + c + RAD * 102.9372 + Math.PI;
  return { ra: rightAscension(l, 0), dec: declination(l, 0) };
}

function moonCoords(d: number): { ra: number; dec: number; dist: number } {
  const l0 = RAD * (218.316 + 13.176396 * d);
  const m = RAD * (134.963 + 13.064993 * d);
  const f = RAD * (93.272 + 13.22935 * d);
  const l = l0 + RAD * 6.289 * Math.sin(m);
  const b = RAD * 5.128 * Math.sin(f);
  return { ra: rightAscension(l, b), dec: declination(l, b), dist: 385_001 - 20_905 * Math.cos(m) };
}

/** Момент сцены в миллисекундах UTC: день года сезона и час по Москве. */
export function sceneTime(dayOfYear: number, hours: number): number {
  return Date.UTC(SCENE_YEAR, 0, 1) + (dayOfYear - 1) * DAY_MS + (hours - MSK_OFFSET_H) * 3_600_000;
}

export interface MoonState {
  /** Высота над горизонтом, градусы. */
  elevation: number;
  /** Азимут от севера по часовой, градусы. */
  azimuth: number;
  /** Освещённая доля диска: 0 - новолуние, 1 - полнолуние. */
  fraction: number;
  /** Растущая луна - освещён правый край (для северного полушария). */
  waxing: boolean;
}

export function moonState(ms: number, lat = MOSCOW_LAT, lon = MOSCOW_LON): MoonState {
  const d = toDays(ms);
  const phi = RAD * lat;
  const moon = moonCoords(d);
  const hourAngle = RAD * (280.16 + 360.9856235 * d) + RAD * lon - moon.ra;
  const altitude = Math.asin(
    Math.sin(phi) * Math.sin(moon.dec) + Math.cos(phi) * Math.cos(moon.dec) * Math.cos(hourAngle),
  );
  // Азимут SunCalc - от юга к западу; сцене нужен от севера по часовой.
  const south = Math.atan2(
    Math.sin(hourAngle),
    Math.cos(hourAngle) * Math.sin(phi) - Math.tan(moon.dec) * Math.cos(phi),
  );
  const sun = sunCoords(d);
  const elongation = Math.acos(
    Math.sin(sun.dec) * Math.sin(moon.dec) +
      Math.cos(sun.dec) * Math.cos(moon.dec) * Math.cos(sun.ra - moon.ra),
  );
  const incidence = Math.atan2(
    SUN_DISTANCE_KM * Math.sin(elongation),
    moon.dist - SUN_DISTANCE_KM * Math.cos(elongation),
  );
  const limb = Math.atan2(
    Math.cos(sun.dec) * Math.sin(sun.ra - moon.ra),
    Math.sin(sun.dec) * Math.cos(moon.dec) -
      Math.cos(sun.dec) * Math.sin(moon.dec) * Math.cos(sun.ra - moon.ra),
  );
  return {
    elevation: altitude / RAD,
    azimuth: (south / RAD + 180 + 360) % 360,
    fraction: (1 + Math.cos(incidence)) / 2,
    waxing: limb < 0,
  };
}
