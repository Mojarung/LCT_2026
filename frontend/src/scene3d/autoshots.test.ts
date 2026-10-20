import { describe, expect, it } from 'vitest';

import {
  buildingsInView,
  framing,
  obstaclesOf,
  plantShots,
  SHOT_CEILING_M,
  SHOT_HEIGHT,
  SHOT_WIDTH,
  speciesInView,
  streetShots,
  wallAhead,
} from './autoshots';
import type { Pose } from './freecam';
import type { Body3 } from './trees';
import type { Building, Plant, SceneSpeciesJson, World } from './types';
import { bounds, type ShotObstacle } from './shots';

/** Дом 10 x 10 м высотой 20 м с южной стеной на z = -10. */
const ring = [
  { x: -5, z: -20 },
  { x: 5, z: -20 },
  { x: 5, z: -10 },
  { x: -5, z: -10 },
];
const house: ShotObstacle[] = [{ ring, height: 20, ...bounds(ring) }];

describe('кадр улицы перед стеной', () => {
  it('взгляд на север в стену в 10 м - кадр упирается в дом', () => {
    expect(wallAhead({ x: 0, y: 8, z: 0, yaw: 0, pitch: 0 }, house)).toBe(true);
  });

  it('тот же дом за спиной, выше крыши или дальше 15 м - кадр свободен', () => {
    expect(wallAhead({ x: 0, y: 8, z: 0, yaw: Math.PI, pitch: 0 }, house)).toBe(false);
    expect(wallAhead({ x: 0, y: 25, z: 0, yaw: 0, pitch: 0 }, house)).toBe(false);
    expect(wallAhead({ x: 0, y: 8, z: 12, yaw: 0, pitch: 0 }, house)).toBe(false);
  });
});

const SPECIES: SceneSpeciesJson = {
  name_ru: 'Липа мелколистная',
  name_lat: 'Tilia cordata',
  life_form: 'tree_large',
  height_m: 20,
  crown_diameter_m: 6,
  crown_mature_m: 10,
  evergreen: false,
  conifer: false,
  growth: 'medium',
  genus: 'tilia',
  family: 'Malvaceae',
};

function body(id: string, x: number, z: number, over: Partial<Plant> = {}): Body3 {
  const plant: Plant = {
    id,
    x,
    z,
    type: 'tree',
    code: 'tilia_cordata',
    name: SPECIES.name_ru,
    species: SPECIES,
    existing: false,
    seed: 1,
    ...over,
  };
  return { plant, x, z, height: 8, radius: 3 };
}

const north = (z: number): Pose => ({ x: 0, y: 1.7, z, yaw: 0, pitch: 0 });

describe('здания и виды в кадре', () => {
  it('препятствия кадра - дома и сооружения с контуром, не крыльца', () => {
    const building = (kind: Building['kind'], points = ring): Building => ({
      rings: [points],
      height: 12,
      floors: 4,
      source: 'label',
      kind,
      wall: null,
      use: null,
      seed: 0,
    });
    const world = {
      buildings: [
        building('building'),
        building('structure'),
        building('porch'),
        building('building', ring.slice(0, 2)),
      ],
    } as World;
    const obstacles = obstaclesOf(world);
    expect(obstacles).toHaveLength(2);
    expect(obstacles[0]?.height).toBe(12);
    expect(obstacles[0]?.minX).toBe(-5);
    expect(obstacles[0]?.minZ).toBe(-20);
  });

  it('дом впереди - в кадре, за спиной - нет', () => {
    const building = { rings: [ring], height: 20 } as Building;
    expect(buildingsInView([building], north(0))).toBe(true);
    expect(buildingsInView([building], { ...north(0), yaw: Math.PI })).toBe(false);
    expect(framing().aspect).toBeCloseTo(SHOT_WIDTH / SHOT_HEIGHT, 6);
  });

  it('виды в кадре: частые первыми, деревья отдельно от кустов, существующие не считаются', () => {
    const bodies = [
      body('a', 0, -20),
      body('b', 2, -22),
      body('c', -2, -25, {
        type: 'shrub',
        name: 'Сирень',
        species: { ...SPECIES, name_lat: 'Syringa vulgaris' },
      }),
      body('d', 0, -30, { species: { ...SPECIES, name_lat: 'Acer platanoides' }, name: 'Клён' }),
      body('d', 0, -30, { species: { ...SPECIES, name_lat: 'Acer platanoides' }, name: 'Клён' }),
      body('d', 0, -30, { species: { ...SPECIES, name_lat: 'Acer platanoides' }, name: 'Клён' }),
      body('e', 1, -20, { existing: true, species: { ...SPECIES, name_lat: 'Betula' } }),
      body('f', 0, 30, { species: { ...SPECIES, name_lat: 'Behind me' } }),
    ];
    const seen = speciesInView(bodies, north(0));
    expect(seen.trees).toEqual(['Acer platanoides', 'Tilia cordata']);
    expect(seen.shrubs).toEqual(['Syringa vulgaris']);
    expect(seen.names).toEqual(['Клён', SPECIES.name_ru, 'Сирень']);
  });
});

describe('кадры посадки и улицы', () => {
  it('кадры посадки: сверху первым, потом три с тротуара, посадка отмечена на кадре', () => {
    const bodies = [body('t1', 0, 0), body('t2', 6, 0)];
    expect(plantShots(bodies, 'нет', [], null)).toEqual([]);
    const shots = plantShots(bodies, 't1', [], { x: 1, z: 0 });
    expect(shots).toHaveLength(4);
    expect(shots[0]?.viewpoint).toBe('aerial');
    expect(shots[0]?.label).toMatch(/, сверху$/);
    expect(shots.slice(1).every((s) => s.viewpoint === 'ground')).toBe(true);
    expect(shots[1]?.label).toMatch(/^[А-Я].*, с тротуара$/);
    expect(shots.map((s) => s.key)).toEqual(['t1-0', 't1-1', 't1-2', 't1-3']);
    for (const s of shots) {
      expect(s.trees).toContain('Tilia cordata');
      expect(s.mark).not.toBeNull();
    }
  });

  it('без посадок кадров улицы нет; группа деревьев - один кадр всего участка', () => {
    expect(streetShots([body('e', 0, 0, { existing: true })], [], null)).toEqual([]);
    const group = [body('a', 0, 0), body('b', 4, 0), body('c', 0, 4)];
    const shots = streetShots(group, [], null);
    expect(shots).toHaveLength(1);
    expect(shots[0]?.key).toBe('street-0');
    expect(shots[0]?.label).toBe('Весь участок');
    expect(shots[0]?.viewpoint).toBe('aerial');
  });

  it('длинная улица - кадры вдоль неё сверху, не выше потолка над открытым местом', () => {
    const avenue = Array.from({ length: 50 }, (_, i) => body(`t${i}`, i * 8, (i % 2) * 10));
    const shots = streetShots(avenue, [], null);
    expect(shots.length).toBeGreaterThan(1);
    expect(shots[0]?.label).toBe(`Участок 1 из ${shots.length}`);
    for (const s of shots) {
      expect(s.viewpoint).toBe('aerial');
      expect(s.pose.y).toBeLessThanOrEqual(SHOT_CEILING_M + 1);
      expect(s.trees).toEqual(['Tilia cordata']);
    }
  });
});
