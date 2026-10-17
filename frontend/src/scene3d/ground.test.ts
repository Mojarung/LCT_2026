import { describe, expect, it } from 'vitest';

import {
  areaCurbs,
  areaRings,
  drawSurfaceAreas,
  edgeBetween,
  GROUND_MAP,
  ROAD_DROP_M,
  roadGeometry,
  type MaskInfo,
  type SurfaceAreas,
} from './ground';
import { ASPHALT, GRASS, PAVERS } from './surfaceMask';
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

describe('борт по маске: дорожный у асфальта, садовый у плитки с газоном', () => {
  // Маска 10 x 10 м по метру: z < 4 - асфальт, 4 <= z < 7 - плитка, z >= 7 - газон.
  const kinds = new Uint8Array(100);
  for (let i = 0; i < 100; i++) kinds[i] = i < 40 ? ASPHALT : i < 70 ? PAVERS : GRASS;
  const mask = {
    kinds,
    width: 10,
    height: 10,
    metresPerPx: 1,
    rect: [0, 0, 10, 10],
  } as unknown as MaskInfo;
  const road = edgeBetween(
    mask,
    (k) => k === ASPHALT,
    (k) => k !== ASPHALT,
    0.6,
  );
  const garden = edgeBetween(
    mask,
    (k) => k === PAVERS,
    (k) => k === GRASS,
    0.6,
  );

  it('асфальт и тротуар - дорожный борт', () => {
    expect(road({ x: 1, z: 4 }, { x: 9, z: 4 })).toBe(true);
    expect(garden({ x: 1, z: 4 }, { x: 9, z: 4 })).toBe(false);
  });

  it('тротуар и газон - садовый борт', () => {
    expect(garden({ x: 1, z: 7 }, { x: 9, z: 7 })).toBe(true);
    expect(road({ x: 1, z: 7 }, { x: 9, z: 7 })).toBe(false);
  });

  it('внутри одного покрытия борта нет', () => {
    expect(road({ x: 1, z: 2 }, { x: 9, z: 2 })).toBe(false);
    expect(garden({ x: 1, z: 5.5 }, { x: 9, z: 5.5 })).toBe(false);
  });
});

describe('проезжая часть ниже тротуара', () => {
  it('сетка проезда лежит на высоту борта ниже земли, в координатах сцены', () => {
    const geometry = roadGeometry(AREAS.paved, [10, 20]);
    expect(geometry).not.toBeNull();
    geometry?.computeBoundingBox();
    const box = geometry?.boundingBox;
    expect(box?.min.y).toBeCloseTo(-ROAD_DROP_M);
    expect(box?.max.y).toBeCloseTo(-ROAD_DROP_M);
    // x сцены = X - 10, z сцены = 20 - Y: контур от (0, 0) до (60, 14) чертежа.
    expect(box?.min.x).toBeCloseTo(-10);
    expect(box?.max.x).toBeCloseTo(50);
    expect(box?.min.z).toBeCloseTo(6);
    expect(box?.max.z).toBeCloseTo(20);
  });

  it('части покрытия кладутся цветом своего вида: проезд, плитка, неизвестное', () => {
    const fills: string[] = [];
    const ctx = {
      beginPath: () => undefined,
      moveTo: () => undefined,
      lineTo: () => undefined,
      closePath: () => undefined,
      fill: () => fills.push(ctx.fillStyle as string),
      fillStyle: '',
    } as unknown as CanvasRenderingContext2D;
    const three = [...AREAS.paved, ...AREAS.paved, ...AREAS.paved];
    drawSurfaceAreas(
      ctx,
      { soil: [], paved: three, paved_kind: ['road', 'pavers', 'paved'] },
      [0, 0],
      0,
      0,
      0.25,
    );
    expect(fills).toEqual(['rgb(90, 92, 100)', 'rgb(176, 142, 120)', 'rgb(140, 142, 150)']);
  });
});

describe('борт без обрывков и изломов (пользователь 17.10.2026: «хуйня у борта вблизи»)', () => {
  // Квадрат 20 x 20 м, вершины через метр: короткие отрезки, как у контура карты покрытий.
  const square: number[][] = [];
  for (let i = 0; i < 20; i++) square.push([i, 0]);
  for (let i = 0; i < 20; i++) square.push([20, i]);
  for (let i = 20; i > 0; i--) square.push([i, 20]);
  for (let i = 20; i > 0; i--) square.push([0, i]);
  square.push([0, 0]);
  const areas: SurfaceAreas = { soil: [], paved: [[square]] };

  it('короткий пропуск в ряду (до 1,5 м) заделывается: борт идёт одной линией', () => {
    // Отрезок (5..6, 0) сервис не узнал - щель в метр.
    const lines = areaCurbs(areas, [0, 0], (a) => !(a.z === 0 && a.x === 5));
    expect(lines).toHaveLength(1);
    expect(lines[0]?.points).toHaveLength(square.length);
  });

  it('обрывок борта короче метра не ставится', () => {
    // Борт только на отрезке (7..7.5) - стоял бы отдельным кубиком.
    const tiny: SurfaceAreas = {
      soil: [],
      paved: [
        [
          [
            [0, 0],
            [7, 0],
            [7.5, 0],
            [20, 0],
            [20, 20],
            [0, 20],
            [0, 0],
          ],
        ],
      ],
    };
    const lines = areaCurbs(tiny, [0, 0], (a) => a.x === 7 && a.z === 0);
    expect(lines).toEqual([]);
  });

  it('шпилька контура (разворот назад) из борта убирается: брус не перекручивается', () => {
    const spike: SurfaceAreas = {
      soil: [],
      paved: [
        [
          [
            [0, 0],
            [10, 0],
            [10, 3],
            [10.05, 0],
            [20, 0],
            [20, 20],
            [0, 20],
            [0, 0],
          ],
        ],
      ],
    };
    const [line] = areaCurbs(spike, [0, 0]);
    const zs = (line?.points ?? []).map((p) => p.z);
    expect(zs).not.toContain(-3);
  });
});
