import { describe, expect, it } from 'vitest';

import { groundCutRings, roadEdges } from './edges';
import {
  areaCurbs,
  areaRings,
  drawSurfaceAreas,
  edgeBetween,
  GROUND_MAP,
  groundGeometry,
  pavedOnLeft,
  ROAD_DROP_M,
  roadGeometry,
  smoothSurfaceAreas,
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
    expect(lawn).toMatch(/^0\.4\d, 0\.5\d, share\.r$/);
    expect(paver).toMatch(/^0\.4\d, 0\.5\d, share\.g$/);
  });

  it('переход газона к проезду - газон до борта, без светлой полосы асфальта', () => {
    // Доли газона, плитки и асфальта считаются без канала проезда (B).
    expect(GROUND_MAP).toMatch(
      /share = vec3\(m\.r, m\.g, max\(1\.0 - m\.r - m\.g - m\.b, 0\.0\)\)/,
    );
    expect(GROUND_MAP).toMatch(/share \/= max\(share\.r \+ share\.g \+ share\.b/);
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

describe('сглаживание контуров покрытий', () => {
  it('излом в несколько градусов и прямой угол скругляются, прямая остаётся прямой', () => {
    // Проезд 20 x 8 с изломом 6° посреди северного края и прямыми углами.
    const ring = [
      [0, 0],
      [20, 0],
      [20, 8],
      [10, 8.6],
      [0, 8],
      [0, 0],
    ];
    const smooth = smoothSurfaceAreas({ soil: [], paved: [[ring]], paved_kind: ['road'] });
    const pts = smooth.paved[0]?.[0] ?? [];
    expect(pts[0]).toEqual(pts.at(-1));
    // Излом снят: вершины (10, 8.6) больше нет, а край рядом - плавная дуга из многих точек.
    expect(pts.some(([x, y]) => x === 10 && y === 8.6)).toBe(false);
    expect(pts.filter(([, y = 0]) => y > 8.05).length).toBeGreaterThan(4);
    // Прямой угол скруглён радиусным камнем: самого угла нет, скругление не дальше 1,6 м от
    // него, а не расползается по прямой.
    expect(pts.some(([x, y]) => x === 20 && y === 0)).toBe(false);
    const corner = pts.filter(([x = 0, y = 0]) => x > 18 && y < 2);
    expect(corner.length).toBeGreaterThan(2);
    for (const [x = 0, y = 0] of corner) expect(Math.hypot(20 - x, y)).toBeLessThanOrEqual(1.6);
    // Южный край - прямая от скругления до скругления.
    const south = pts.filter(([, y = 0]) => y === 0);
    expect(Math.min(...south.map(([x = 0]) => x))).toBeLessThanOrEqual(1.6);
    expect(Math.max(...south.map(([x = 0]) => x))).toBeGreaterThanOrEqual(18.4);
    // Вид части сохранён.
    expect(smooth.paved_kind).toEqual(['road']);
  });
});

describe('лесенка растра на контуре', () => {
  it('ступени клеток заменяются прямой, а выемка в два метра остаётся', () => {
    // Северный край проезда: лесенка из четырёх ступеней по метру между x 10 и 14, потом
    // выемка 2 x 2 м на x 30..32.
    const ring = [
      [0, 0],
      [60, 0],
      [60, 8],
      [32, 8],
      [32, 6],
      [30, 6],
      [30, 8],
      [14, 8],
      [14, 9],
      [13, 9],
      [13, 10],
      [12, 10],
      [12, 11],
      [11, 11],
      [11, 12],
      [10, 12],
      [0, 12],
      [0, 0],
    ];
    const pts = smoothSurfaceAreas({ soil: [], paved: [[ring]] }).paved[0]?.[0] ?? [];
    // Ни одной вершины лесенки не осталось: край между (14, 8) и (10, 12) - прямая.
    for (const [x = 0, y = 0] of pts) {
      if (x > 10.5 && x < 13.5 && y > 8.5 && y < 11.5) {
        const offLine = Math.abs(x + y - 22) / Math.SQRT2;
        expect(offLine, `(${x}, ${y})`).toBeLessThan(0.3);
      }
    }
    // Выемка на месте: внутри неё покрытия нет, дно выемки сохранено.
    expect(pts.some(([x = 0, y = 0]) => x > 30 && x < 32 && Math.abs(y - 6) < 0.8)).toBe(true);
  });
});

describe('земля с вырезом проезда по контуру', () => {
  /** Покрыта ли точка (x, z) сцены треугольниками сетки земли. */
  const covers = (g: ReturnType<typeof groundGeometry>, x: number, z: number): boolean => {
    const pos = g.getAttribute('position');
    const index = g.getIndex();
    const n = index ? index.count : pos.count;
    const at = (i: number) => (index ? index.getX(i) : i);
    for (let t = 0; t < n; t += 3) {
      const [a, b, c] = [at(t), at(t + 1), at(t + 2)].map((k) => [pos.getX(k), pos.getZ(k)]);
      if (!a || !b || !c) continue;
      const s = (p: number[], q: number[]) =>
        ((q[0] ?? 0) - (p[0] ?? 0)) * (z - (p[1] ?? 0)) -
        ((q[1] ?? 0) - (p[1] ?? 0)) * (x - (p[0] ?? 0));
      const d1 = s(a, b);
      const d2 = s(b, c);
      const d3 = s(c, a);
      if ((d1 >= 0 && d2 >= 0 && d3 >= 0) || (d1 <= 0 && d2 <= 0 && d3 <= 0)) return true;
    }
    return false;
  };

  it('край земли - контур проезда, а не размытый порог маски: у борта нет нахлёста и щели', () => {
    // Проезд с прямоугольной выемкой 3 x 2 м (Камчатская, 17.10.2026): по маске угол
    // выемки скруглялся, газон наползал на проезд мимо борта.
    const road = [
      [
        [0, 0],
        [20, 0],
        [20, 6],
        [12, 6],
        [12, 4],
        [9, 4],
        [9, 6],
        [0, 6],
        [0, 0],
      ],
    ];
    const edges = roadEdges({ soil: [], paved: [road], paved_kind: ['road'] }, [0, 0], () => false);
    const g = groundGeometry([-50, -50, 50, 50], groundCutRings(edges, 1.2, 1));
    // z сцены = -Y.
    expect(covers(g, 5, -3)).toBe(false); // проезд
    expect(covers(g, 9.1, -4.1)).toBe(true); // угол выемки - земля
    expect(covers(g, 8.9, -3.9)).toBe(false); // рядом с углом - уже проезд
    expect(covers(g, 5, -6.1)).toBe(true); // за краем проезда
    expect(covers(g, 40, 40)).toBe(true); // поле вокруг
    g.computeBoundingBox();
    expect(g.boundingBox?.max.y).toBeCloseTo(0);
  });
});

describe('ориентация линий борта: покрытие слева', () => {
  // Маска 10 x 10 м по метру: z < 7 - плитка, z >= 7 - газон.
  const kinds = new Uint8Array(100);
  for (let i = 0; i < 100; i++) kinds[i] = i < 70 ? PAVERS : GRASS;
  const mask = {
    kinds,
    width: 10,
    height: 10,
    metresPerPx: 1,
    rect: [0, 0, 10, 10],
  } as unknown as MaskInfo;

  it('линия с покрытием справа разворачивается, с покрытием слева остаётся', () => {
    // Ход +x вдоль z = 7: слева (+z) газон, справа плитка - разворот.
    const wrong = {
      points: [
        { x: 0, z: 7 },
        { x: 9, z: 7 },
      ],
    };
    const right = {
      points: [
        { x: 9, z: 7 },
        { x: 0, z: 7 },
      ],
    };
    const [a, b] = pavedOnLeft([wrong, right], mask);
    expect(a?.points).toEqual([
      { x: 9, z: 7 },
      { x: 0, z: 7 },
    ]);
    expect(b?.points).toEqual([
      { x: 9, z: 7 },
      { x: 0, z: 7 },
    ]);
  });

  it('отметки верха разворачиваются вместе с точками', () => {
    const wrong = {
      points: [
        { x: 0, z: 7 },
        { x: 9, z: 7 },
      ],
      tops: [0.1, 0.2],
    };
    expect(pavedOnLeft([wrong], mask)[0]?.tops).toEqual([0.2, 0.1]);
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
