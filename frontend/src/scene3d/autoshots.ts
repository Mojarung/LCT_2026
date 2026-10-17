/* Кадры сцены для галереи и фото: что снимать и откуда.
 *
 * Улица - позами облёта в начале каждого отрезка хребта: камера над осью, взгляд вдоль улицы.
 * Посадка - по кругу: три кадра с тротуара и один сверху, позы считает планировщик shots.ts по
 * кронам в текущем возрасте, зданиям и солнцу. Виды в кадре идут в промпт фото латинскими
 * названиями, деревья и кустарники раздельно: так модель рисует липу липой, а спирею - кустом. */

import { EYE_M, type Pose } from './freecam';
import {
  bounds,
  compass,
  project,
  solid,
  type Framing,
  inView,
  planShots,
  type ShotObstacle,
  streetPoses,
  type Viewpoint,
} from './shots';
import { clearance, tourRoute } from './tour';
import type { Body3 } from './trees';
import type { Flat, Plant, World } from './types';

export type ShotTarget = { kind: 'street' } | { kind: 'plant'; id: string };

export interface AutoShot {
  key: string;
  pose: Pose;
  viewpoint: Viewpoint;
  label: string;
  /** Латинские названия деревьев плана в кадре, частые - первыми. */
  trees: string[];
  /** То же для кустарников и изгородей. */
  shrubs: string[];
  /** Русские названия тех же видов для подписи кадра: латынь - промпту. */
  names: string[];
  /** Где на кадре снятая посадка: доли ширины и высоты. Кольцо рисует галерея, а не кадр -
   *  иначе модель фото перенесла бы его на снимок. */
  mark?: { u: number; v: number } | null;
  /** Есть ли в кадре здания: без них промпт фото не говорит о фасадах. */
  buildings?: boolean;
}

/** Кадр для фото: 16:9, стороны кратны 32 - так их ждёт модель. */
/** 1536 x 864: деталей заметно больше, чем в 1024 x 576, видеопамять та же (сравнение
 *  17.10.2026); после апскейла и уменьшения фото - 3840 x 2160. */
export const SHOT_WIDTH = 1536;
export const SHOT_HEIGHT = 864;
export const SHOT_FOV = (55 * Math.PI) / 180;
/** Дальше этого соседние кроны кадр посадки не заслоняют: камера так далеко не уходит. */
const OCCLUDER_REACH_M = 60;
/** Потолок высоты кадров улицы: выше улица превращается в план сверху. */
export const SHOT_CEILING_M = 40;

/** Ближе этого стена перед кадром улицы закрывает его целиком: автокадр «Участок 2 из 6»
 *  показывал фасад вплотную (жюри дизайна, итерация 12). */
export const WALL_CLEAR_M = 15;

/** Упирается ли взгляд кадра в здание ближе reach метров: точки луча через метр. */
export function wallAhead(
  pose: Pose,
  obstacles: readonly ShotObstacle[],
  reach = WALL_CLEAR_M,
): boolean {
  const level = Math.cos(pose.pitch);
  for (let d = 2; d <= reach; d += 1) {
    const x = pose.x - Math.sin(pose.yaw) * level * d;
    const z = pose.z - Math.cos(pose.yaw) * level * d;
    const y = pose.y + Math.sin(pose.pitch) * d;
    if (solid(obstacles, x, y, z)) return true;
  }
  return false;
}

export function framing(): Framing {
  return { fov: SHOT_FOV, aspect: SHOT_WIDTH / SHOT_HEIGHT };
}

export function obstaclesOf(world: World): ShotObstacle[] {
  return world.buildings
    .filter((b) => b.kind === 'building' || b.kind === 'structure')
    .flatMap((b) => {
      const ring = b.rings[0];
      return ring && ring.length > 2 ? [{ ring, height: b.height, ...bounds(ring) }] : [];
    });
}

function ranked(plants: readonly Plant[], nameOf: (p: Plant) => string): string[] {
  const counts = new Map<string, number>();
  for (const p of plants) {
    const name = nameOf(p).trim();
    if (name) counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([name]) => name);
}

const latin = (p: Plant) => p.species.name_lat;

/** Есть ли в кадре хоть одно здание: углы и середины стен у земли и на уровне крыши. Без
 *  зданий в кадре абзац промпта про новые фасады модель читала как просьбу их нарисовать
 *  и ставила дома на пустой газон у края сцены. */
export function buildingsInView(buildings: World['buildings'], pose: Pose): boolean {
  const frame = framing();
  return buildings.some((b) =>
    (b.rings[0] ?? []).some((p, i, ring) => {
      const next = ring[(i + 1) % ring.length] ?? p;
      const points = [p, { x: (p.x + next.x) / 2, z: (p.z + next.z) / 2 }];
      return points.some(
        (q) =>
          project(pose, { x: q.x, y: 0, z: q.z }, frame) !== null ||
          project(pose, { x: q.x, y: b.height, z: q.z }, frame) !== null,
      );
    }),
  );
}

/** Виды плана в кадре: деревья и кустарники раздельно, частые - первыми. */
export function speciesInView(
  bodies: readonly Body3[],
  pose: Pose,
): { trees: string[]; shrubs: string[]; names: string[] } {
  const seen = bodies
    .filter((b) => !b.plant.existing && inView(pose, b.x, b.z, framing()))
    .map((b) => b.plant);
  const trees = seen.filter((p) => p.type === 'tree');
  const shrubs = seen.filter((p) => p.type !== 'tree');
  return {
    trees: ranked(trees, latin),
    shrubs: ranked(shrubs, latin),
    names: [...ranked(trees, (p) => p.name), ...ranked(shrubs, (p) => p.name)],
  };
}

export function plantShots(
  bodies: readonly Body3[],
  id: string,
  obstacles: readonly ShotObstacle[],
  sun: Flat | null,
): AutoShot[] {
  const body = bodies.find((b) => b.plant.id === id);
  if (!body) return [];
  // Соседи, что могут заслонить кадр: выше глаз и не дальше, чем уходит камера.
  const occluders = bodies.filter(
    (b) =>
      b !== body &&
      b.height > EYE_M + 0.3 &&
      Math.hypot(b.x - body.x, b.z - body.z) < OCCLUDER_REACH_M,
  );
  const request = { subject: [body], obstacles, framing: framing(), sun, occluders };
  const ground = planShots({ ...request, viewpoint: 'ground', count: 3 });
  const aerial = planShots({ ...request, viewpoint: 'aerial', count: 1 });
  // Кадр сверху - первым: крону в густой посадке с тротуара часто заслоняют кусты и соседи.
  return [...aerial, ...ground].map((s, i) => ({
    key: `${id}-${i}`,
    pose: s.pose,
    viewpoint: s.viewpoint,
    label: `${capital(compass(s.azimuth))}, ${s.viewpoint === 'ground' ? 'с тротуара' : 'сверху'}`,
    ...speciesInView(bodies, s.pose),
    mark: project(
      s.pose,
      { x: body.x, y: Math.max(0.5, body.height - body.radius), z: body.z },
      framing(),
    ),
  }));
}

export function streetShots(
  bodies: readonly Body3[],
  obstacles: readonly ShotObstacle[],
  sun: Flat | null,
): AutoShot[] {
  const planted = bodies.filter((b) => !b.plant.existing);
  if (!planted.length) return [];
  const route = tourRoute(planted);
  if (!route) {
    const [shot] = planShots({
      subject: planted,
      obstacles,
      framing: framing(),
      sun,
      viewpoint: 'aerial',
      count: 1,
    });
    return shot
      ? [
          {
            key: 'street-0',
            pose: shot.pose,
            viewpoint: 'aerial',
            label: 'Весь участок',
            ...speciesInView(bodies, shot.pose),
          },
        ]
      : [];
  }
  // Облёту нужна высота над крышами, кадру - нет: камера у башни не должна уходить на 80 м
  // и снимать улицу сверху. Потолок снимает это, а где камера упёрлась бы в дом, высота облёта.
  const safe = clearance(route, obstacles);
  const low = safe.map((h, i) => {
    const p = route.points[i];
    const capped = Math.min(h, SHOT_CEILING_M);
    return p && solid(obstacles, p.x, capped, p.z) ? h : capped;
  });
  // Кадры, упёртые в стену, отбрасываются; если такие все - лучше они, чем пустая галерея.
  const all = streetPoses(route, low);
  const open = all.filter((pose) => !wallAhead(pose, obstacles));
  const poses = open.length ? open : all;
  return poses.map((pose, i) => ({
    key: `street-${i}`,
    pose,
    viewpoint: 'aerial',
    label: poses.length > 1 ? `Участок ${i + 1} из ${poses.length}` : 'Вся улица',
    ...speciesInView(bodies, pose),
  }));
}

function capital(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
