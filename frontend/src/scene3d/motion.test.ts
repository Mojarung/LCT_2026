import { describe, expect, it } from 'vitest';

import { Walls } from './collide';
import {
  EYE_M,
  FLY_FLOOR_M,
  type Keys,
  type Pose,
  clampPitch,
  clampSpeed,
  freshKeys,
  keysOf,
  step,
  wishVelocity,
} from './freecam';
import { hitCrown, pick } from './pick';
import type { Building } from './types';
import { formatView, parseView } from './viewHash';

const idle: Keys = { forward: 0, right: 0, up: 0, fast: false, slow: false, jump: false };
const north: Pose = { x: 0, y: 10, z: 0, yaw: 0, pitch: 0 };
const still = { vx: 0, vy: 0, vz: 0, grounded: false };

describe('свободная камера', () => {
  it('«вперёд» при курсе 0 - на север, то есть в -z; «вправо» - на восток', () => {
    const [x, , z] = wishVelocity(north, { ...idle, forward: 1 }, 'fly', 10);
    expect(x).toBeCloseTo(0);
    expect(z).toBeCloseTo(-10);
    const [rx, , rz] = wishVelocity(north, { ...idle, right: 1 }, 'fly', 10);
    expect(rx).toBeCloseTo(10);
    expect(rz).toBeCloseTo(0);
  });

  it('скорость набирается плавно, а не рывком', () => {
    const { motion } = step({
      pose: north,
      motion: still,
      keys: { ...idle, forward: 1 },
      mode: 'fly',
      flySpeed: 10,
      dt: 1 / 60,
    });
    expect(Math.abs(motion.vz)).toBeGreaterThan(0);
    expect(Math.abs(motion.vz)).toBeLessThan(2);
  });

  it('полёт не опускается под газон, пешеход стоит глазами на 1,7 м и падает на землю', () => {
    const low = step({
      pose: { ...north, y: 0.5 },
      motion: { ...still, vy: -50 },
      keys: idle,
      mode: 'fly',
      flySpeed: 8,
      dt: 0.1,
    });
    expect(low.pose.y).toBe(FLY_FLOOR_M);
    let state = { pose: { ...north, y: 3 }, motion: still };
    for (let i = 0; i < 120; i++) {
      state = step({ ...state, keys: idle, mode: 'walk', flySpeed: 8, dt: 1 / 60 });
    }
    expect(state.pose.y).toBe(EYE_M);
    expect(state.motion.grounded).toBe(true);
  });

  it('прыжок только с земли', () => {
    const jumped = step({
      pose: { ...north, y: EYE_M },
      motion: { ...still, grounded: true },
      keys: { ...idle, jump: true },
      mode: 'walk',
      flySpeed: 8,
      dt: 1 / 60,
    });
    expect(jumped.motion.vy).toBeGreaterThan(0);
    const air = step({
      pose: { ...north, y: 3 },
      motion: still,
      keys: { ...idle, jump: true },
      mode: 'walk',
      flySpeed: 8,
      dt: 1 / 60,
    });
    expect(air.motion.vy).toBeLessThan(0);
  });

  it('наклон не переворачивает камеру через зенит', () => {
    expect(clampPitch(3)).toBeLessThan(Math.PI / 2);
    expect(clampPitch(-3)).toBeGreaterThan(-Math.PI / 2);
  });

  it('клавиши читаются по коду: на русской раскладке KeyW - та же клавиша', () => {
    const keys = keysOf(new Set(['KeyW', 'KeyD', 'ShiftLeft']));
    expect(keys).toMatchObject({ forward: 1, right: 1, fast: true });
    expect(keysOf(new Set(['ControlLeft'])).up).toBe(0);
  });
});

const box: Building = {
  rings: [
    [
      { x: 0, z: 0 },
      { x: 10, z: 0 },
      { x: 10, z: 10 },
      { x: 0, z: 10 },
    ],
  ],
  height: 10,
  floors: 3,
  source: 'label',
  kind: 'building',
  wall: null,
  use: null,
  seed: 1,
};

describe('стены', () => {
  it('шаг в стену останавливается у стены, вдоль стены - скользит', () => {
    const walls = new Walls([box]);
    const into = walls.resolve({ x: -2, z: 5 }, { x: 0.1, z: 5 });
    expect(into.x).toBeLessThan(0);
    const along = walls.resolve({ x: -0.5, z: 5 }, { x: -0.2, z: 6 });
    expect(along.z).toBeCloseTo(6);
    expect(along.x).toBeLessThanOrEqual(-0.34);
  });

  it('крыльцо ниже колена не мешает', () => {
    const porch = new Walls([{ ...box, height: 0.45, kind: 'porch' }]);
    expect(porch.size).toBe(0);
    expect(porch.resolve({ x: -2, z: 5 }, { x: 1, z: 5 })).toEqual({ x: 1, z: 5 });
  });
});

describe('прицел', () => {
  const tree = { x: 0, z: -20, height: 10, radius: 3 };

  it('луч в крону попадает, мимо - нет', () => {
    expect(hitCrown({ ox: 0, oy: 7, oz: 0, dx: 0, dy: 0, dz: -1 }, tree)).toBeCloseTo(17);
    expect(hitCrown({ ox: 0, oy: 7, oz: 0, dx: 1, dy: 0, dz: 0 }, tree)).toBeNull();
  });

  it('из двух на луче выбирается ближняя', () => {
    const near = { ...tree, z: -8 };
    expect(pick({ ox: 0, oy: 7, oz: 0, dx: 0, dy: 0, dz: -1 }, [tree, near])).toBe(1);
    expect(pick({ ox: 0, oy: 7, oz: 0, dx: 0, dy: 0, dz: 1 }, [tree, near])).toBe(-1);
  });
});

describe('ракурс в адресе', () => {
  it('туда и обратно без потери, режим пешехода сохраняется', () => {
    const pose: Pose = { x: 12.3, y: 1.7, z: -40.5, yaw: 0.5, pitch: -0.2 };
    const hash = formatView(pose, 'walk');
    const back = parseView(`#${hash}`);
    expect(back?.mode).toBe('walk');
    expect(back?.pose.x).toBeCloseTo(12.3);
    expect(back?.pose.yaw).toBeCloseTo(0.5, 2);
  });

  it('мусор в адресе не ломает страницу', () => {
    expect(parseView('#view=a,b')).toBeNull();
    expect(parseView('')).toBeNull();
    expect(parseView('#view=1,-5,2,0,0')?.pose.y).toBe(0.3);
  });
});

describe('залипшие клавиши', () => {
  it('клавиша без автоповтора дольше полутора секунд считается отпущенной', () => {
    const pressed = new Map([
      ['KeyW', 1000],
      ['KeyD', 2400],
      ['ShiftLeft', 0],
    ]);
    const fresh = freshKeys(pressed, 2600);
    expect(fresh.has('KeyW')).toBe(false);
    expect(fresh.has('KeyD')).toBe(true);
    // Модификатор не повторяется на всех системах: держится до keyup.
    expect(fresh.has('ShiftLeft')).toBe(true);
  });

  it('скорость полёта не выходит за пределы ползунка', () => {
    expect(clampSpeed(0.2)).toBe(1);
    expect(clampSpeed(500)).toBe(60);
    expect(clampSpeed(12)).toBe(12);
  });
});
