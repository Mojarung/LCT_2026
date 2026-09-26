import { describe, expect, it } from 'vitest';

import { moonState, sceneTime } from './celestial';
import { clearance, clusters, pointAt, route, spine, tourPose, tourRoute } from './tour';
import type { Flat } from './types';

describe('луна', () => {
  it('в полнолуние 25.01.2024 диск освещён почти весь, в новолуние 11.01.2024 - почти нет', () => {
    expect(moonState(Date.UTC(2024, 0, 25, 17, 54)).fraction).toBeGreaterThan(0.98);
    expect(moonState(Date.UTC(2024, 0, 11, 11, 57)).fraction).toBeLessThan(0.02);
  });

  it('за неделю после новолуния луна растёт, за неделю до - убывает', () => {
    expect(moonState(Date.UTC(2024, 0, 18)).waxing).toBe(true);
    expect(moonState(Date.UTC(2024, 0, 4)).waxing).toBe(false);
  });

  it('высота и азимут в своих пределах, момент сцены - московское время', () => {
    const m = moonState(sceneTime(182, 23));
    expect(Math.abs(m.elevation)).toBeLessThanOrEqual(90);
    expect(m.azimuth).toBeGreaterThanOrEqual(0);
    expect(m.azimuth).toBeLessThan(360);
    expect(sceneTime(1, 3)).toBe(Date.UTC(2026, 0, 1, 0));
  });
});

/** Улица буквой Г: 200 м на восток и 150 м на север, плюс двор в стороне от угла. */
function lStreet(): Flat[] {
  const points: Flat[] = [];
  for (let x = 0; x <= 200; x += 4) points.push({ x, z: 0 }, { x, z: 6 });
  for (let z = 0; z >= -150; z -= 4) points.push({ x: 200, z }, { x: 206, z });
  for (let x = 80; x <= 100; x += 4) points.push({ x, z: 40 });
  return points;
}

describe('облёт', () => {
  it('хребет идёт от конца до конца улицы и не заходит во двор сбоку', () => {
    const line = spine(clusters(lStreet()));
    const ends = [line[0], line[line.length - 1]].map((p) => ({
      x: Math.round(p?.x ?? 0),
      z: Math.round(p?.z ?? 0),
    }));
    const west = ends.find((p) => p.x < 30);
    const north = ends.find((p) => p.z < -120);
    expect(west).toBeDefined();
    expect(north).toBeDefined();
    expect(line.every((p) => p.z < 30)).toBe(true);
  });

  it('маршрут размечен по длине, точка на середине лежит на середине', () => {
    const r = route([
      { x: 0, z: 0 },
      { x: 100, z: 0 },
    ]);
    expect(r.length).toBeCloseTo(100);
    expect(pointAt(r, 50).x).toBeCloseTo(50);
    expect(pointAt(r, 500).x).toBeCloseTo(100);
  });

  it('камера смотрит вперёд по ходу, а на обратном пути - назад по маршруту', () => {
    const r = route([
      { x: 0, z: 0 },
      { x: 300, z: 0 },
    ]);
    // Вперёд - на восток: курс -90 градусов (0 - север, против часовой - налево).
    expect(tourPose(r, 50).yaw).toBeCloseTo(-Math.PI / 2);
    const back = tourPose(r, 300 + 100);
    expect(back.x).toBeCloseTo(200);
    expect(back.yaw).toBeCloseTo(Math.PI / 2);
    expect(back.pitch).toBeLessThan(0);
  });

  it('облетать нечего - маршрута нет', () => {
    expect(tourRoute([])).toBeNull();
    expect(tourRoute([{ x: 0, z: 0 }])).toBeNull();
    expect(tourRoute(lStreet())?.length).toBeGreaterThan(250);
  });
});

describe('высота облёта', () => {
  it('над домом в 17 этажей камера идёт выше крыши, вдали от него - на базовой высоте', () => {
    const r = route([
      { x: 0, z: 0 },
      { x: 600, z: 0 },
    ]);
    const tower = { minX: 290, minZ: 5, maxX: 310, maxZ: 25, height: 52.2 };
    const heights = clearance(r, [tower]);
    const at = (x: number) => heights[Math.round(x / 5)] ?? 0;
    expect(at(300)).toBeGreaterThanOrEqual(52.2 + 10 - 0.01);
    expect(at(10)).toBeCloseTo(30);
    expect(at(590)).toBeCloseTo(30);
    // Подъём начинается до дома, а не у стены.
    expect(at(260)).toBeGreaterThan(40);
    expect(tourPose(r, 300, heights).y).toBeGreaterThan(62);
  });
});
