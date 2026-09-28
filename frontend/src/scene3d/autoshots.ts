/* Кадры сцены для галереи и фото: что снимать и откуда.
 *
 * Улица - позами облёта в начале каждого отрезка хребта: камера над осью, взгляд вдоль улицы.
 * Посадка - по кругу: три кадра с тротуара и один сверху, позы считает планировщик shots.ts по
 * кронам в текущем возрасте, зданиям и солнцу. Виды в кадре идут в промпт фото латинскими
 * названиями, деревья и кустарники раздельно: так модель рисует липу липой, а спирею - кустом. */

import type { Pose } from './freecam';
import {
  bounds,
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
}

/** Кадр для фото: 16:9, стороны кратны 32 - так их ждёт модель. */
export const SHOT_WIDTH = 1024;
export const SHOT_HEIGHT = 576;
export const SHOT_FOV = (55 * Math.PI) / 180;
/** Потолок высоты кадров улицы: выше улица превращается в план сверху. */
export const SHOT_CEILING_M = 40;

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

function ranked(plants: readonly Plant[]): string[] {
  const counts = new Map<string, number>();
  for (const p of plants) {
    const name = p.species.name_lat.trim();
    if (name) counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([name]) => name);
}

/** Виды плана в кадре: деревья и кустарники раздельно, частые - первыми. */
export function speciesInView(
  bodies: readonly Body3[],
  pose: Pose,
): { trees: string[]; shrubs: string[] } {
  const seen = bodies
    .filter((b) => !b.plant.existing && inView(pose, b.x, b.z, framing()))
    .map((b) => b.plant);
  return {
    trees: ranked(seen.filter((p) => p.type === 'tree')),
    shrubs: ranked(seen.filter((p) => p.type !== 'tree')),
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
  const request = { subject: [body], obstacles, framing: framing(), sun };
  const ground = planShots({ ...request, viewpoint: 'ground', count: 3 });
  const aerial = planShots({ ...request, viewpoint: 'aerial', count: 1 });
  return [...ground, ...aerial].map((s, i) => ({
    key: `${id}-${i}`,
    pose: s.pose,
    viewpoint: s.viewpoint,
    label:
      s.viewpoint === 'ground' ? `${body.plant.name}, с тротуара` : `${body.plant.name}, сверху`,
    ...speciesInView(bodies, s.pose),
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
  const poses = streetPoses(route, low);
  return poses.map((pose, i) => ({
    key: `street-${i}`,
    pose,
    viewpoint: 'aerial',
    label: poses.length > 1 ? `Участок ${i + 1} из ${poses.length}` : 'Вся улица',
    ...speciesInView(bodies, pose),
  }));
}
