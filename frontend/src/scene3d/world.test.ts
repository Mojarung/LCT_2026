import { describe, expect, it } from 'vitest';

import type { BasemapJson, PlanJson } from '../api/artifacts';
import type { SceneJson } from './types';
import {
  buildWorld,
  distinctFeatures,
  floorsByArea,
  frameAt,
  hashOf,
  heightOf,
  median,
  signedArea,
} from './world';

const species = {
  name_ru: 'Липа мелколистная',
  name_lat: 'Tilia cordata',
  life_form: 'tree_large',
  height_m: 25,
  crown_diameter_m: 6,
  crown_mature_m: 12,
  evergreen: false,
  conifer: false,
  growth: 'medium',
  genus: 'tilia',
  family: 'Malvaceae',
};

function scene(overrides: Partial<SceneJson> = {}): SceneJson {
  return {
    version: 1,
    extent: [900, 1900, 1300, 2300],
    counts: {},
    buildings: [
      {
        rings: [
          [
            [1000, 2000],
            [1020, 2000],
            [1020, 2010],
            [1000, 2010],
            [1000, 2000],
          ],
        ],
        height_m: 16.2,
        floors: 5,
        floors_source: 'label',
        kind: 'building',
        wall: 'brick',
        use: 'residential',
        labels: ['К-', '5'],
      },
    ],
    plants: [
      { id: 'a', x: 1100, y: 2100, type: 'tree', code: 'tilia_cordata', structure: 'row' },
      { id: 'b', x: 1110, y: 2100, type: 'tree', code: 'tilia_cordata', structure: 'row' },
      { id: 'c', x: 1120, y: 2102, type: 'shrub', code: 'unknown', structure: null },
    ],
    species: { tilia_cordata: species },
    ...overrides,
  };
}

const basemap: BasemapJson = {
  type: 'FeatureCollection',
  bbox: [900, 1900, 1300, 2300],
  features: [
    {
      type: 'Feature',
      properties: { class: 'curb' },
      geometry: {
        type: 'LineString',
        coordinates: [
          [1090, 2090],
          [1130, 2090],
        ],
      },
    },
    {
      type: 'Feature',
      properties: { class: 'pole' },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [1099, 2095],
            [1101, 2095],
            [1101, 2097],
            [1099, 2097],
            [1099, 2095],
          ],
        ],
      },
    },
    {
      type: 'Feature',
      properties: { class: 'existing_tree' },
      geometry: { type: 'Point', coordinates: [1105, 2110] },
    },
    {
      type: 'Feature',
      properties: { class: 'curb' },
      geometry: {
        type: 'LineString',
        coordinates: [
          [5000, 5000],
          [5010, 5000],
        ],
      },
    },
  ],
};

describe('сцена из артефактов', () => {
  it('начало сцены - в медиане посадок, север чертежа уходит в -z', () => {
    const world = buildWorld({ scene: scene(), plan: null, basemap: null });
    expect(world.origin).toEqual([1110, 2100]);
    const [a] = world.plants;
    expect(a?.x).toBe(-10);
    expect(a?.z).toBe(-0);
    const frame = frameAt([0, 0]);
    expect(frame.toFlat(3, 5)).toEqual({ x: 3, z: -5 });
  });

  it('здание берёт высоту и этажность из scene.json, замыкающая точка контура снята', () => {
    const world = buildWorld({ scene: scene(), plan: null, basemap: null });
    const [b] = world.buildings;
    expect(b?.height).toBe(16.2);
    expect(b?.floors).toBe(5);
    expect(b?.rings[0]).toHaveLength(4);
    expect(world.floorsBy.label).toBe(1);
    expect(world.fallback).toBe(false);
  });

  it('вид без карточки в scene.json получает размеры по типу посадки, а не падает', () => {
    const world = buildWorld({ scene: scene(), plan: null, basemap: null });
    const shrub = world.plants.find((p) => p.id === 'c');
    expect(shrub?.species.life_form).toBe('shrub_medium');
    expect(shrub?.species.height_m).toBeGreaterThan(0);
  });

  it('подоснова даёт борта, опоры и существующие деревья, дальнее за границей сцены отброшено', () => {
    const world = buildWorld({ scene: scene(), plan: null, basemap });
    expect(world.curbs).toHaveLength(1);
    expect(world.poles).toHaveLength(1);
    expect(world.poles[0]?.x).toBeCloseTo(-10);
    const existing = world.plants.filter((p) => p.existing);
    expect(existing).toHaveLength(1);
    expect(existing[0]?.existingRadius).toBe(2.5);
  });

  it('старый прогон без scene.json открывается по плану и подоснове', () => {
    const plan = {
      placements: [
        {
          id: 'p1',
          planting_type: 'tree',
          species: {
            code: 'tilia_cordata',
            name_ru: 'Липа',
            name_lat: '',
            crown_diameter_m: 6,
            life_form: 'tree_large',
          },
          x: 1100,
          y: 2100,
        },
      ],
    } as unknown as PlanJson;
    const withBuilding: BasemapJson = {
      ...basemap,
      features: [
        ...basemap.features,
        {
          type: 'Feature',
          properties: { class: 'building' },
          geometry: {
            type: 'Polygon',
            coordinates: [
              [
                [1000, 2000],
                [1030, 2000],
                [1030, 2025],
                [1000, 2025],
                [1000, 2000],
              ],
            ],
          },
        },
      ],
    };
    const world = buildWorld({ scene: null, plan, basemap: withBuilding });
    expect(world.fallback).toBe(true);
    expect(world.plants.find((p) => p.id === 'p1')?.species.crown_diameter_m).toBe(6);
    expect(world.buildings).toHaveLength(1);
    expect(world.buildings[0]?.floors).toBe(5);
    expect(world.floorsBy.assumed).toBe(1);
  });
});

describe('вспомогательные числа', () => {
  it('этажность по площади и высота по этажам - те же, что у сервиса', () => {
    expect(floorsByArea(40)).toBe(1);
    expect(floorsByArea(300)).toBe(2);
    expect(floorsByArea(900)).toBe(5);
    expect(heightOf(1)).toBe(4);
    expect(heightOf(5)).toBeCloseTo(16.2);
  });

  it('площадь со знаком, медиана и устойчивый хэш', () => {
    expect(
      signedArea([
        [0, 0],
        [2, 0],
        [2, 2],
        [0, 2],
      ]),
    ).toBe(4);
    expect(median([3, 1, 2])).toBe(2);
    expect(median([4, 1, 2, 3])).toBe(2.5);
    expect(median([])).toBe(0);
    expect(hashOf('a')).toBe(hashOf('a'));
    expect(hashOf('a')).not.toBe(hashOf('b'));
  });
});

it.each([undefined, 'strip'] as const)(
  'полоса %s - ряд крон по знакам с шагом кроны, но не стволы и не посадки плана',
  (vegetation_kind) => {
    const world = buildWorld({
      scene: scene(),
      plan: null,
      basemap: {
        ...basemap,
        features: [
          {
            type: 'Feature',
            properties: { class: 'existing_tree', vegetation_kind },
            geometry: {
              type: 'MultiPoint',
              coordinates: [
                [1100, 2100],
                [1100.8, 2100],
                [1101.6, 2100],
              ],
            },
          },
          {
            type: 'Feature',
            properties: { class: 'existing_tree' },
            geometry: { type: 'Point', coordinates: [1200, 2100] },
          },
        ],
      },
    });
    expect(world.plants.filter((p) => p.existing && !p.strip)).toHaveLength(1);
    expect(world.plants.filter((p) => !p.existing)).toHaveLength(3);
    expect(world.treeStrips).toHaveLength(1);
    expect(world.treeStrips?.[0]).toHaveLength(3);
    // Три знака в 1,6 м - одна крона ряда: шаг ряда - взрослая крона, а не шаг знаков.
    expect(world.plants.filter((p) => p.strip)).toHaveLength(1);
  },
);

it('точная копия объекта подосновы в 3D не задваивается, сдвинутый на миллиметр остаётся', () => {
  const fence = (dy: number) => ({
    type: 'Feature' as const,
    properties: { class: 'fence' },
    geometry: {
      type: 'LineString' as const,
      coordinates: [
        [1090, 2080 + dy],
        [1130, 2080 + dy],
      ] as [number, number][],
    },
  });
  expect(distinctFeatures([fence(0), fence(0), fence(0.001)])).toHaveLength(2);
  const world = buildWorld({
    scene: scene(),
    plan: null,
    basemap: {
      ...basemap,
      features: [...basemap.features, ...basemap.features, fence(0), fence(0)],
    },
  });
  expect(world.fences).toHaveLength(1);
  expect(world.poles).toHaveLength(1);
  expect(world.curbs).toHaveLength(1);
  expect(world.plants.filter((p) => p.existing)).toHaveLength(1);
});

it('shrub strips become continuous axes planted with a row of bushes', () => {
  const world = buildWorld({
    scene: null,
    plan: null,
    basemap: {
      type: 'FeatureCollection',
      bbox: [0, 0, 20, 20],
      features: [
        {
          type: 'Feature',
          properties: { class: 'existing_shrub', vegetation_kind: 'shrub_strip' },
          geometry: {
            type: 'LineString',
            coordinates: [
              [1, 2],
              [5, 2],
              [8, 3],
            ],
          },
        },
      ],
    },
  });
  // Кустарниковая полоса - ряд кустов по оси с шагом STRIP_SHRUB_STEP_M (пользователь,
  // 19.10.2026: брус с фактурой листвы читался плоским), а не плоский брус.
  expect(world.plants.length).toBeGreaterThanOrEqual(10);
  expect(world.plants.every((p) => p.type === 'existing_shrub' && p.strip)).toBe(true);
  const onAxis = (p: { x: number; z: number }) =>
    (Math.abs(p.z - 8) < 1e-6 && p.x >= -9 && p.x <= -5) ||
    (p.x >= -5 && p.x <= -2 && Math.abs(p.z - (8 - (p.x + 5) / 3)) < 1e-6);
  expect(world.plants.every(onAxis)).toBe(true);
  expect(world.treeStrips).toHaveLength(0);
  expect(world.shrubStrips).toEqual([
    {
      points: [
        { x: -9, z: 8 },
        { x: -5, z: 8 },
        { x: -2, z: 7 },
      ],
    },
  ]);
});

it('does not drop a shrub axis crossing the scene with both ends outside', () => {
  const world = buildWorld({
    scene: scene({ extent: [0, 0, 10, 10], plants: [], buildings: [] }),
    plan: null,
    basemap: {
      type: 'FeatureCollection',
      bbox: [-20, -20, 20, 20],
      features: [
        {
          type: 'Feature',
          properties: { class: 'existing_shrub', vegetation_kind: 'shrub_strip' },
          geometry: {
            type: 'LineString',
            coordinates: [
              [-20, 5],
              [20, 5],
            ],
          },
        },
      ],
    },
  });
  expect(world.shrubStrips).toHaveLength(1);
  const shrubs = world.plants.filter((p) => p.strip);
  expect(shrubs.length).toBeGreaterThan(5);
  // Кусты - только в пределах сцены, хотя ось уходит на 20 м за край.
  const [minX, , maxX] = world.bounds;
  expect(shrubs.every((p) => p.x >= minX && p.x <= maxX)).toBe(true);
});

it('takes plan flowerbeds into the scene in scene coordinates', () => {
  const plan = {
    run_id: 'r',
    source: { name: 'x', sha256: '', dxf_version: '' },
    summary: {},
    placements: [],
    rejections: [],
    warnings: [],
    lawns: [
      {
        id: 'L1',
        number: 1,
        planting_type: 'lawn',
        kind: 'flowerbed',
        area_m2: 4,
        rule_ids: [],
        notes: [],
        explanation: '',
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [1100, 2100],
              [1102, 2100],
              [1102, 2102],
              [1100, 2102],
              [1100, 2100],
            ],
          ],
        },
      },
      {
        id: 'L2',
        number: 2,
        planting_type: 'lawn',
        kind: 'kept',
        area_m2: 100,
        rule_ids: [],
        notes: [],
        explanation: '',
        geometry: { type: 'Polygon', coordinates: [] },
      },
    ],
  } as unknown as PlanJson;
  const world = buildWorld({ scene: scene(), plan, basemap: null });
  expect(world.flowerbeds).toHaveLength(1);
  const [ox, oy] = world.origin;
  expect(world.flowerbeds?.[0]?.[0]?.[0]).toEqual({ x: 1100 - ox, z: -(2100 - oy) });
});

it('takes fence axes from the basemap instead of the raw double lines', () => {
  const basemap = {
    type: 'FeatureCollection',
    bbox: [900, 1900, 1300, 2300],
    features: [
      {
        type: 'Feature',
        properties: { class: 'fence' },
        geometry: {
          type: 'LineString',
          coordinates: [
            [1100, 2100.15],
            [1120, 2100.15],
          ],
        },
      },
      {
        type: 'Feature',
        properties: { class: 'fence' },
        geometry: {
          type: 'LineString',
          coordinates: [
            [1100, 2099.85],
            [1120, 2099.85],
          ],
        },
      },
    ],
    fence_axes: [
      [
        [1100, 2100],
        [1120, 2100],
      ],
    ],
  } as unknown as BasemapJson;
  const world = buildWorld({ scene: scene(), plan: null, basemap });
  expect(world.fences).toHaveLength(1);
  expect(world.fenceAxes).toBe(true);
  const [ox, oy] = world.origin;
  expect(world.fences[0]?.points[0]).toEqual({ x: 1100 - ox, z: -(2100 - oy) });
});

it('takes benches drawn in the survey (1.9 x 0.6 m rectangles) as bench spots along their axis', () => {
  const bench = (x: number, y: number) => ({
    type: 'Feature',
    properties: { class: 'obstacle' },
    geometry: {
      type: 'Polygon',
      coordinates: [
        [
          [x, y],
          [x + 1.9, y],
          [x + 1.9, y + 0.6],
          [x, y + 0.6],
          [x, y],
        ],
      ],
    },
  });
  const pit = {
    type: 'Feature',
    properties: { class: 'obstacle' },
    geometry: {
      type: 'Polygon',
      coordinates: [
        [
          [1150, 2150],
          [1156, 2150],
          [1156, 2152],
          [1150, 2152],
          [1150, 2150],
        ],
      ],
    },
  };
  const basemap = {
    type: 'FeatureCollection',
    bbox: [900, 1900, 1300, 2300],
    features: [bench(1100, 2100), pit],
  } as unknown as BasemapJson;
  const world = buildWorld({ scene: scene(), plan: null, basemap });
  expect(world.benches).toHaveLength(1);
  const b = world.benches?.[0];
  const [ox, oy] = world.origin;
  expect(b?.x).toBeCloseTo(1100.95 - ox);
  expect(b?.z).toBeCloseTo(-(2100.3 - oy));
  // Ось x модели - вдоль длинной стороны (x чертежа): угол 0 или пи.
  expect(Math.abs(Math.sin(b?.angle ?? 1))).toBeLessThan(1e-6);
});
