import { describe, expect, it } from 'vitest';

import { EYE_M } from './freecam';
import {
  aim,
  inCrown,
  compass,
  project,
  bounds,
  fitDistance,
  MIN_SEPARATION,
  planShots,
  type ShotObstacle,
  solid,
  streetPoses,
  inView,
  visibility,
} from './shots';
import { route } from './tour';

const FRAMING = { fov: (55 * Math.PI) / 180, aspect: 16 / 9 };
const TREE = { x: 0, z: 0, height: 12, radius: 3 };

function box(minX: number, minZ: number, maxX: number, maxZ: number, height: number): ShotObstacle {
  const ring = [
    { x: minX, z: minZ },
    { x: maxX, z: minZ },
    { x: maxX, z: maxZ },
    { x: minX, z: maxZ },
  ];
  return { ring, height, ...bounds(ring) };
}

function wrap(a: number): number {
  return Math.atan2(Math.sin(a), Math.cos(a));
}

describe('aim', () => {
  it('looks north with yaw 0 and down with negative pitch', () => {
    expect(aim({ x: 0, y: 10, z: 10 }, { x: 0, y: 0, z: 0 }).yaw).toBeCloseTo(0);
    expect(aim({ x: 0, y: 10, z: 10 }, { x: 0, y: 0, z: 0 }).pitch).toBeCloseTo(-Math.PI / 4);
    // Цель на востоке (+x): курс поворачивает вправо, то есть в минус.
    expect(aim({ x: 0, y: 0, z: 0 }, { x: 5, y: 0, z: 0 }).yaw).toBeCloseTo(-Math.PI / 2);
  });
});

describe('fitDistance', () => {
  it('grows with the subject and never comes closer than the minimum', () => {
    expect(fitDistance(20, FRAMING)).toBeGreaterThan(fitDistance(5, FRAMING));
    expect(fitDistance(0.1, FRAMING)).toBe(6);
  });
});

describe('solid and visibility', () => {
  const house = box(10, -10, 20, 10, 15);

  it('is solid inside a house below its roof only', () => {
    expect(solid([house], 15, 5, 0)).toBe(true);
    expect(solid([house], 15, 20, 0)).toBe(false);
    expect(solid([house], 25, 5, 0)).toBe(false);
  });

  it('hides a tree behind a house and shows it over the roof', () => {
    const tree = [{ x: 0, y: 6, z: 0 }];
    expect(visibility({ x: 40, y: 2, z: 0 }, tree, [house])).toBe(0);
    expect(visibility({ x: 40, y: 60, z: 0 }, tree, [house])).toBe(1);
    expect(visibility({ x: -40, y: 2, z: 0 }, tree, [house])).toBe(1);
  });
});

describe('planShots', () => {
  it('orbits a lone tree with distinct azimuths at eye level', () => {
    const shots = planShots({
      subject: [TREE],
      obstacles: [],
      framing: FRAMING,
      viewpoint: 'ground',
      count: 4,
    });

    expect(shots).toHaveLength(4);
    for (const s of shots) expect(s.pose.y).toBe(EYE_M);
    for (let i = 0; i < shots.length; i++) {
      for (let j = i + 1; j < shots.length; j++) {
        const d = Math.abs(wrap((shots[i]?.azimuth ?? 0) - (shots[j]?.azimuth ?? 0)));
        expect(d).toBeGreaterThanOrEqual(MIN_SEPARATION - 1e-9);
      }
    }
  });

  it('points the camera at the subject', () => {
    const [shot] = planShots({
      subject: [{ ...TREE, x: 100, z: -50 }],
      obstacles: [],
      framing: FRAMING,
      viewpoint: 'aerial',
      count: 1,
    });
    expect(shot).toBeDefined();
    if (!shot) return;
    const { pose } = shot;
    const expected = aim(pose, { x: 100, y: 6, z: -50 });
    expect(pose.yaw).toBeCloseTo(expected.yaw, 5);
    expect(pose.pitch).toBeLessThan(0);
    expect(pose.y).toBeGreaterThan(TREE.height);
  });

  it('avoids the side where a tall house blocks the view', () => {
    // Башня к востоку от дерева, вплотную: с востока с земли его не видно.
    const tower = box(4, -30, 40, 30, 60);
    const shots = planShots({
      subject: [TREE],
      obstacles: [tower],
      framing: FRAMING,
      viewpoint: 'ground',
      count: 2,
    });

    expect(shots.length).toBeGreaterThan(0);
    for (const s of shots) {
      expect(s.visible).toBe(1);
      expect(s.pose.x).toBeLessThan(4);
    }
  });

  it('keeps the camera out of a neighbour crown and looks past it', () => {
    // Сосед - крупная крона в 8 м к югу: кадр с юга закрыт, из кроны снимать нельзя.
    const neighbour = { x: 0, z: 8, height: 14, radius: 5 };
    const shots = planShots({
      subject: [TREE],
      obstacles: [],
      occluders: [neighbour],
      framing: FRAMING,
      viewpoint: 'ground',
      count: 3,
    });

    expect(shots.length).toBeGreaterThan(0);
    for (const s of shots) {
      expect(inCrown([neighbour], s.pose.x, s.pose.y, s.pose.z)).toBe(false);
      expect(Math.abs(wrap(s.azimuth))).toBeGreaterThan(0.3);
    }
  });

  it('prefers the sun behind the camera', () => {
    const [best] = planShots({
      subject: [TREE],
      obstacles: [],
      framing: FRAMING,
      viewpoint: 'aerial',
      count: 1,
      // Солнце на юге (+z): камера должна встать к югу, азимут около нуля.
      sun: { x: 0, z: 1 },
    });
    expect(Math.abs(wrap(best?.azimuth ?? Math.PI))).toBeLessThan(0.01);
  });

  it('returns nothing for an empty subject', () => {
    expect(
      planShots({ subject: [], obstacles: [], framing: FRAMING, viewpoint: 'aerial', count: 3 }),
    ).toEqual([]);
  });
});

describe('streetPoses', () => {
  const line = route([
    { x: 0, z: 0 },
    { x: 480, z: 0 },
  ]);

  it('puts one pose per 120 m segment above the spine, looking along it', () => {
    const poses = streetPoses(line, []);

    expect(poses).toHaveLength(4);
    for (const p of poses) {
      expect(p.z).toBeCloseTo(0, 5);
      expect(p.y).toBe(30);
      expect(p.pitch).toBeLessThan(0);
      // Вдоль улицы на восток: курс -90 градусов.
      expect(p.yaw).toBeCloseTo(-Math.PI / 2, 5);
    }
    expect(poses[1]?.x ?? 0).toBeGreaterThan(poses[0]?.x ?? 0);
  });

  it('caps a long street at six shots', () => {
    const long = route([
      { x: 0, z: 0 },
      { x: 3000, z: 0 },
    ]);
    expect(streetPoses(long, [])).toHaveLength(6);
  });
});

describe('inView', () => {
  const pose = { x: 0, y: 30, z: 0, yaw: -Math.PI / 2, pitch: -0.4 };

  it('sees what is ahead and not what is behind or too far', () => {
    expect(inView(pose, 50, 5, FRAMING)).toBe(true);
    expect(inView(pose, -50, 0, FRAMING)).toBe(false);
    expect(inView(pose, 0, 50, FRAMING)).toBe(false);
    expect(inView(pose, 500, 0, FRAMING)).toBe(false);
  });
});

describe('project and compass', () => {
  it('puts the aimed point in the frame centre', () => {
    const eye = { x: 0, y: 10, z: 20 };
    const target = { x: 3, y: 2, z: -4 };
    const pose = { ...eye, ...aim(eye, target) };
    const at = project(pose, target, FRAMING);
    expect(at?.u).toBeCloseTo(0.5, 5);
    expect(at?.v).toBeCloseTo(0.5, 5);
  });

  it('places a point to the right of the view on the right half, behind - nowhere', () => {
    const pose = { x: 0, y: 1.7, z: 0, yaw: 0, pitch: 0 };
    expect(project(pose, { x: 3, y: 1.7, z: -20 }, FRAMING)?.u).toBeGreaterThan(0.5);
    expect(project(pose, { x: 0, y: 1.7, z: 20 }, FRAMING)).toBeNull();
  });

  it('names the side the camera looks from', () => {
    expect(compass(0)).toBe('с юга');
    expect(compass(Math.PI / 2)).toBe('с востока');
    expect(compass(Math.PI)).toBe('с севера');
    expect(compass(-Math.PI / 4)).toBe('с юго-запада');
  });
});
