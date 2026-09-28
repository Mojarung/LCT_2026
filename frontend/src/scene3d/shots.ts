/* Автоматические ракурсы: откуда снять посадку или улицу, чтобы её было видно.
 *
 * Чистая логика без three.js. На вход - что снимать (кроны посадок), здания-препятствия и
 * направление на солнце; на выход - позы камеры с оценкой. Камера обходит объект по кругу:
 * расстояние - чтобы шар объекта целиком вошёл в кадр, высота - с земли (глаза пешехода) или
 * с дрона. Каждая поза проверяется лучами до точек крон: луч, прошедший внутри здания ниже его
 * крыши, закрыт. Штраф - за закрытые точки и за съёмку против солнца. Из лучших берутся
 * разнесённые по азимуту, чтобы кадры не повторяли друг друга.
 *
 * Улица снимается отрезками вдоль её хребта (tour.ts): у длинной улицы один общий кадр
 * показывает деревья спичками. */

import { EYE_M, type Pose } from './freecam';
import { type Route, tourPose } from './tour';
import type { Flat } from './types';

export type Viewpoint = 'aerial' | 'ground';

export interface ShotBody {
  x: number;
  z: number;
  /** Высота до верха кроны. */
  height: number;
  /** Радиус кроны. */
  radius: number;
}

export interface ShotObstacle {
  ring: Flat[];
  height: number;
  minX: number;
  minZ: number;
  maxX: number;
  maxZ: number;
}

export interface Framing {
  /** Вертикальный угол обзора, радианы. */
  fov: number;
  /** Ширина кадра к высоте. */
  aspect: number;
}

export interface PlannedShot {
  pose: Pose;
  viewpoint: Viewpoint;
  /** Азимут камеры от объекта, радианы: 0 - камера к югу от объекта. */
  azimuth: number;
  /** Доля точек объекта, которые видно. */
  visible: number;
  score: number;
}

export interface ShotRequest {
  subject: readonly ShotBody[];
  obstacles: readonly ShotObstacle[];
  framing: Framing;
  viewpoint: Viewpoint;
  count: number;
  /** Куда светит солнце по горизонтали (от сцены к солнцу); нет - ночь или неважно. */
  sun?: Flat | null;
}

/** Сколько азимутов перебирается по кругу. */
export const AZIMUTHS = 16;
/** Кадры одного объекта расходятся по азимуту не меньше чем на столько. */
export const MIN_SEPARATION = Math.PI / 3;
/** Угол, под которым смотрит дрон: 35 градусов вниз. */
export const AERIAL_ELEVATION = (35 * Math.PI) / 180;
/** Запас рамки: объект занимает не весь кадр. */
export const MARGIN = 1.15;
/** Самое близкое расстояние съёмки: ближе кадр - одна кора. */
export const MIN_DISTANCE_M = 6;
/** Точек объекта на проверку видимости: больше не нужно, счёт растёт линейно. */
const PROBES = 16;
const RAY_SAMPLES = 24;

export function bounds(ring: readonly Flat[]): Omit<ShotObstacle, 'ring' | 'height'> {
  let minX = Infinity;
  let minZ = Infinity;
  let maxX = -Infinity;
  let maxZ = -Infinity;
  for (const p of ring) {
    minX = Math.min(minX, p.x);
    minZ = Math.min(minZ, p.z);
    maxX = Math.max(maxX, p.x);
    maxZ = Math.max(maxZ, p.z);
  }
  return { minX, minZ, maxX, maxZ };
}

export function inside(ring: readonly Flat[], x: number, z: number): boolean {
  let hit = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[i];
    const b = ring[j];
    if (!a || !b) continue;
    if (a.z > z !== b.z > z && x < ((b.x - a.x) * (z - a.z)) / (b.z - a.z) + a.x) hit = !hit;
  }
  return hit;
}

/** Точка внутри здания ниже его крыши: камера в стене или луч прошёл сквозь дом. */
export function solid(
  obstacles: readonly ShotObstacle[],
  x: number,
  y: number,
  z: number,
): boolean {
  for (const o of obstacles) {
    if (y >= o.height || x < o.minX || x > o.maxX || z < o.minZ || z > o.maxZ) continue;
    if (inside(o.ring, x, z)) return true;
  }
  return false;
}

/** Взгляд из from в to как курс и наклон камеры (freecam: курс 0 - на север, -z). */
export function aim(
  from: { x: number; y: number; z: number },
  to: { x: number; y: number; z: number },
): { yaw: number; pitch: number } {
  const dx = to.x - from.x;
  const dz = to.z - from.z;
  return {
    yaw: Math.atan2(-dx, -dz),
    pitch: Math.atan2(to.y - from.y, Math.hypot(dx, dz)),
  };
}

interface Sphere {
  x: number;
  y: number;
  z: number;
  r: number;
  top: number;
}

/** Шар, в который входят все кроны: центр по середине охвата, радиус до дальней кроны. */
export function sphereOf(subject: readonly ShotBody[]): Sphere {
  let minX = Infinity;
  let minZ = Infinity;
  let maxX = -Infinity;
  let maxZ = -Infinity;
  let top = 0;
  for (const b of subject) {
    minX = Math.min(minX, b.x - b.radius);
    maxX = Math.max(maxX, b.x + b.radius);
    minZ = Math.min(minZ, b.z - b.radius);
    maxZ = Math.max(maxZ, b.z + b.radius);
    top = Math.max(top, b.height);
  }
  const x = (minX + maxX) / 2;
  const z = (minZ + maxZ) / 2;
  const y = top / 2;
  let r = 0;
  for (const b of subject) {
    const flat = Math.hypot(b.x - x, b.z - z) + b.radius;
    r = Math.max(r, Math.hypot(flat, Math.max(y, b.height - y)));
  }
  return { x, y, z, r: Math.max(r, 1), top };
}

/** Расстояние, с которого шар радиуса r целиком входит в кадр с запасом. */
export function fitDistance(r: number, framing: Framing): number {
  const vertical = framing.fov / 2;
  const horizontal = Math.atan(Math.tan(vertical) * framing.aspect);
  return Math.max(MIN_DISTANCE_M, (r * MARGIN) / Math.sin(Math.min(vertical, horizontal)));
}

function probes(subject: readonly ShotBody[]): { x: number; y: number; z: number }[] {
  const step = Math.max(1, Math.ceil(subject.length / PROBES));
  const out: { x: number; y: number; z: number }[] = [];
  for (let i = 0; i < subject.length; i += step) {
    const b = subject[i];
    if (b) out.push({ x: b.x, y: Math.max(0.5, b.height - b.radius), z: b.z });
  }
  return out;
}

/** Доля точек, до которых луч из камеры не проходит сквозь здания. */
export function visibility(
  eye: { x: number; y: number; z: number },
  points: readonly { x: number; y: number; z: number }[],
  obstacles: readonly ShotObstacle[],
): number {
  if (!points.length) return 0;
  let seen = 0;
  for (const p of points) {
    let blocked = false;
    // Концы не проверяются: точка кроны может стоять вплотную к стене.
    for (let i = 1; i < RAY_SAMPLES && !blocked; i++) {
      const t = i / RAY_SAMPLES;
      blocked = solid(
        obstacles,
        eye.x + (p.x - eye.x) * t,
        eye.y + (p.y - eye.y) * t,
        eye.z + (p.z - eye.z) * t,
      );
    }
    if (!blocked) seen += 1;
  }
  return seen / points.length;
}

function candidate(
  sphere: Sphere,
  azimuth: number,
  request: ShotRequest,
  points: readonly { x: number; y: number; z: number }[],
): PlannedShot | null {
  const distance = fitDistance(sphere.r, request.framing);
  const dirX = Math.sin(azimuth);
  const dirZ = Math.cos(azimuth);
  let eye: { x: number; y: number; z: number };
  let target: { x: number; y: number; z: number };
  if (request.viewpoint === 'ground') {
    eye = { x: sphere.x + dirX * distance, y: EYE_M, z: sphere.z + dirZ * distance };
    target = { x: sphere.x, y: Math.max(EYE_M, sphere.top * 0.45), z: sphere.z };
  } else {
    const flat = distance * Math.cos(AERIAL_ELEVATION);
    eye = {
      x: sphere.x + dirX * flat,
      y: sphere.y + distance * Math.sin(AERIAL_ELEVATION),
      z: sphere.z + dirZ * flat,
    };
    target = { x: sphere.x, y: sphere.y, z: sphere.z };
  }
  if (solid(request.obstacles, eye.x, eye.y, eye.z)) return null;
  const visible = visibility(eye, points, request.obstacles);
  // Солнце за спиной - кроны освещены; в лицо - силуэты на засвеченном небе.
  const sun = request.sun;
  const light = sun ? -(dirX * sun.x + dirZ * sun.z) / (Math.hypot(sun.x, sun.z) || 1) : 0;
  const { yaw, pitch } = aim(eye, target);
  return {
    pose: { ...eye, yaw, pitch },
    viewpoint: request.viewpoint,
    azimuth,
    visible,
    score: visible - 0.2 * light,
  };
}

function separated(a: number, b: number): boolean {
  const d = Math.abs(Math.atan2(Math.sin(a - b), Math.cos(a - b)));
  return d >= MIN_SEPARATION - 1e-9;
}

/** Лучшие разнесённые ракурсы объекта. Совсем закрытые (ни одной точки) не берутся. */
export function planShots(request: ShotRequest): PlannedShot[] {
  if (!request.subject.length || request.count <= 0) return [];
  const sphere = sphereOf(request.subject);
  const points = probes(request.subject);
  const all: PlannedShot[] = [];
  for (let i = 0; i < AZIMUTHS; i++) {
    const shot = candidate(sphere, (i / AZIMUTHS) * Math.PI * 2, request, points);
    if (shot && shot.visible > 0) all.push(shot);
  }
  all.sort((a, b) => b.score - a.score || a.azimuth - b.azimuth);
  const chosen: PlannedShot[] = [];
  for (const shot of all) {
    if (chosen.length >= request.count) break;
    if (chosen.every((c) => separated(c.azimuth, shot.azimuth))) chosen.push(shot);
  }
  return chosen;
}

/** Длина отрезка улицы на один кадр. */
export const SEGMENT_M = 120;
/** Больше кадров улица не получает: дальше - облёт. */
export const MAX_STREET_SHOTS = 6;
/** Кадр снимается от начала отрезка: камера на этой доле отрезка, взгляд вперёд. */
const SEGMENT_OFFSET = 0.15;

/** Кадры улицы - позы облёта в начале каждого отрезка хребта: камера над осью выше крыш,
 *  взгляд вперёд и вниз вдоль улицы. С такого ракурса улица занимает кадр, а не полоску среди
 *  поля, и модели фото нечего дорисовывать. */
export function streetPoses(route: Route, heights: readonly number[]): Pose[] {
  const parts = Math.max(1, Math.min(MAX_STREET_SHOTS, Math.round(route.length / SEGMENT_M)));
  const size = route.length / parts;
  return Array.from({ length: parts }, (_, i) => {
    const p = tourPose(route, i * size + size * SEGMENT_OFFSET, heights);
    return { x: p.x, y: p.y, z: p.z, yaw: p.yaw, pitch: p.pitch };
  });
}

/** Дальше этого виды в подпись кадра не идут: на кадре они - пятна. */
export const VIEW_RANGE_M = 160;

/** Точка в конусе обзора камеры по горизонтали: для подписи видов в кадре. */
export function inView(pose: Pose, x: number, z: number, framing: Framing): boolean {
  const dx = x - pose.x;
  const dz = z - pose.z;
  const d = Math.hypot(dx, dz);
  if (d > VIEW_RANGE_M || d < 0.5) return d < 0.5;
  // Курс 0 смотрит на -z, рост курса поворачивает к -x.
  const fx = -Math.sin(pose.yaw);
  const fz = -Math.cos(pose.yaw);
  const half = Math.atan(Math.tan(framing.fov / 2) * framing.aspect);
  return (dx * fx + dz * fz) / d >= Math.cos(half);
}

/** Где точка окажется на кадре: доли ширины и высоты от левого верхнего угла, null - за
 *  кадром или за спиной. Та же камера, что у three.js: курс вокруг вертикали, потом наклон. */
export function project(
  pose: Pose,
  point: { x: number; y: number; z: number },
  framing: Framing,
): { u: number; v: number } | null {
  const dx = point.x - pose.x;
  const dy = point.y - pose.y;
  const dz = point.z - pose.z;
  // Поворот мира в систему камеры: сначала обратный курс, затем обратный наклон.
  const cy = Math.cos(-pose.yaw);
  const sy = Math.sin(-pose.yaw);
  const x1 = dx * cy + dz * sy;
  const z1 = -dx * sy + dz * cy;
  const cp = Math.cos(-pose.pitch);
  const sp = Math.sin(-pose.pitch);
  const y2 = dy * cp - z1 * sp;
  const z2 = dy * sp + z1 * cp;
  if (z2 >= -0.1) return null;
  const f = 1 / Math.tan(framing.fov / 2);
  const u = 0.5 + ((x1 / -z2) * f) / framing.aspect / 2;
  const v = 0.5 - ((y2 / -z2) * f) / 2;
  return u < 0 || u > 1 || v < 0 || v > 1 ? null : { u, v };
}

const COMPASS = [
  'с юга',
  'с юго-востока',
  'с востока',
  'с северо-востока',
  'с севера',
  'с северо-запада',
  'с запада',
  'с юго-запада',
];

/** Откуда смотрит камера, словами: азимут 0 - камера к югу от объекта, рост - на восток. */
export function compass(azimuth: number): string {
  const turn = ((azimuth % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
  return COMPASS[Math.round(turn / (Math.PI / 4)) % COMPASS.length] ?? 'с юга';
}
