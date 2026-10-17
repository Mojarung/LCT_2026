import { describe, expect, it } from 'vitest';

import {
  areaCurbs,
  areaRings,
  drawSurfaceAreas,
  grassEdge,
  GROUND_MAP,
  type MaskInfo,
  type SurfaceAreas,
} from './ground';
import type { Flat } from './types';

/* Контуры карты покрытий поверх растра: край проезда - прямая, а не лесенка клеток
 * (пользователь, 17.10.2026: «как будто кто-то отгрыз»). */

const AREAS: SurfaceAreas = {
  soil: [
    [
      [
        [0, 14],
        [60, 9],
        [60, 40],
        [0, 40],
        [0, 14],
      ],
    ],
  ],
  paved: [
    [
      [
        [0, 0],
        [60, 0],
        [60, 9],
        [0, 14],
        [0, 0],
      ],
    ],
  ],
};

describe('контуры покрытий на 3D-виде', () => {
  it('переводят координаты чертежа в пиксели маски: z сцены - минус y чертежа', () => {
    // Начало сцены (10, 20), левый верхний угол маски (-5, -30) в метрах сцены, 0,25 м в пикселе.
    const rings = areaRings(AREAS.paved, [10, 20], -5, -30, 0.25);
    expect(rings[0]?.[0]?.[0]).toEqual([(0 - 10 + 5) / 0.25, (-(0 - 20) + 30) / 0.25]);
    expect(rings[0]?.[0]?.[3]).toEqual([(0 - 10 + 5) / 0.25, (-(14 - 20) + 30) / 0.25]);
  });

  it('кладут грунт и поверх него покрытие', () => {
    const fills: string[] = [];
    const ctx = {
      beginPath: () => undefined,
      moveTo: () => undefined,
      lineTo: () => undefined,
      closePath: () => undefined,
      fill: () => fills.push(ctx.fillStyle as string),
      fillStyle: '',
    } as unknown as CanvasRenderingContext2D;
    drawSurfaceAreas(ctx, AREAS, [0, 0], 0, 0, 0.25);
    expect(fills).toEqual(['rgb(104, 158, 104)', 'rgb(140, 142, 150)']);
  });

  it('без контуров ничего не рисуют', () => {
    let touched = false;
    const ctx = new Proxy({}, { get: () => () => (touched = true) }) as CanvasRenderingContext2D;
    drawSurfaceAreas(ctx, { soil: [], paved: [] }, [0, 0], 0, 0, 0.25);
    expect(touched).toBe(false);
  });
});

describe('край покрытия на 3D-виде', () => {
  it('граница газона и плитки - порог маски без шума: край прямой, а не «обгрызенный»', () => {
    const lawn = /float lawn = smoothstep\(([^;]+)\);/.exec(GROUND_MAP)?.[1] ?? '';
    const paver = /float paver = smoothstep\(([^)]+)\)/.exec(GROUND_MAP)?.[1] ?? '';
    expect(lawn).toMatch(/^0\.4\d, 0\.5\d, m\.r$/);
    expect(paver).toMatch(/^0\.4\d, 0\.5\d, m\.g$/);
  });
});

describe('бортовой камень по краю покрытия', () => {
  it('идёт по каждому кольцу покрытия в координатах сцены, газон бортом не обводится', () => {
    const lines = areaCurbs(AREAS, [10, 20]);
    expect(lines).toHaveLength(1);
    expect(lines[0]?.points[0]).toEqual({ x: -10, z: 20 });
    expect(lines[0]?.points[3]).toEqual({ x: -10, z: 6 });
    // Кольцо замкнуто: последняя точка - первая.
    expect(lines[0]?.points.at(-1)).toEqual(lines[0]?.points[0]);
  });

  it('идёт только там, где по одну сторону газон: шов между двумя покрытиями без борта', () => {
    // Край проезда от (0, 0) до (60, 0) сцены - шов с тротуаром, остальные стороны - газон.
    const lines = areaCurbs(AREAS, [0, 0], (a: Flat, b: Flat) => !(a.z === 0 && b.z === 0));
    expect(lines).toHaveLength(1);
    const points = lines[0]?.points ?? [];
    expect(points[0]).toEqual({ x: 60, z: 0 });
    expect(points.at(-1)).toEqual({ x: 0, z: 0 });
  });

  it('без контуров бортов нет', () => {
    expect(areaCurbs({ soil: [], paved: [] }, [0, 0])).toEqual([]);
  });
});

describe('край газона по маске', () => {
  // Маска 10 x 10 м по метру: z < 5 - асфальт, z >= 5 - газон.
  const kinds = new Uint8Array(100);
  for (let i = 50; i < 100; i++) kinds[i] = 0;
  for (let i = 0; i < 50; i++) kinds[i] = 2;
  const mask = {
    kinds,
    width: 10,
    height: 10,
    metresPerPx: 1,
    rect: [0, 0, 10, 10],
  } as unknown as MaskInfo;
  const edge = grassEdge(mask, 0.6);

  it('отрезок между газоном и покрытием - край', () => {
    expect(edge({ x: 1, z: 5 }, { x: 9, z: 5 })).toBe(true);
  });

  it('отрезок внутри покрытия или внутри газона - не край', () => {
    expect(edge({ x: 1, z: 2 }, { x: 9, z: 2 })).toBe(false);
    expect(edge({ x: 1, z: 8 }, { x: 9, z: 8 })).toBe(false);
  });
});
