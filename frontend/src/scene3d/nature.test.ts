import { describe, expect, it } from 'vitest';

import { archetypeOf, foliageColor, foliageOf, hexRgb, isGreen } from './archetypes';
import { existingSize, PLAN_YEAR, plantingStock, sizeAt } from './growth';
import { SEASON_DAY, sunDirection, sunPosition } from './solar';
import type { Plant, SceneSpeciesJson } from './types';

const linden: SceneSpeciesJson = {
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

function plant(code: string, species: Partial<SceneSpeciesJson> = {}, type = 'tree'): Plant {
  return {
    id: code,
    x: 0,
    z: 0,
    type,
    code,
    name: code,
    species: { ...linden, ...species },
    existing: false,
    seed: 12345,
  };
}

describe('рост посадок', () => {
  it('в год посадки - крупномер, в 10 лет крона равна условному знаку плана', () => {
    expect(sizeAt(linden, 0)).toEqual(plantingStock(linden));
    expect(sizeAt(linden, PLAN_YEAR).crown).toBeCloseTo(6);
  });

  it('растёт монотонно и не перерастает взрослый размер каталога', () => {
    let last = sizeAt(linden, 0);
    for (const year of [5, 10, 20, 40, 80, 200]) {
      const now = sizeAt(linden, year);
      expect(now.height).toBeGreaterThanOrEqual(last.height);
      expect(now.crown).toBeGreaterThanOrEqual(last.crown);
      last = now;
    }
    expect(last.height).toBeLessThanOrEqual(25);
    expect(last.crown).toBeLessThanOrEqual(12);
  });

  it('быстрорастущий вид в 10 лет выше медленного', () => {
    const fast = sizeAt({ ...linden, growth: 'fast' }, 10).height;
    const slow = sizeAt({ ...linden, growth: 'slow' }, 10).height;
    expect(fast).toBeGreaterThan(slow);
  });

  it('куст сажается ниже метра, существующее дерево выше куста', () => {
    const shrub = {
      ...linden,
      life_form: 'shrub_medium',
      height_m: 2,
      crown_diameter_m: 1.2,
      crown_mature_m: 1.8,
    };
    expect(plantingStock(shrub).height).toBeLessThan(1);
    expect(existingSize(2.5, false, 1).height).toBeGreaterThan(existingSize(0.8, true, 1).height);
  });
});

describe('солнце над Москвой', () => {
  it('в полдень лета выше 50 градусов на юге, в полночь под горизонтом', () => {
    const noon = sunPosition(SEASON_DAY.summer, 13);
    expect(noon.elevation).toBeGreaterThan(50);
    expect(noon.elevation).toBeLessThan(60);
    expect(noon.azimuth).toBeGreaterThan(160);
    expect(noon.azimuth).toBeLessThan(200);
    expect(sunPosition(SEASON_DAY.summer, 0).elevation).toBeLessThan(0);
  });

  it('утром солнце на востоке, вечером на западе, осенью ниже, чем летом', () => {
    expect(sunPosition(SEASON_DAY.summer, 8).azimuth).toBeLessThan(120);
    expect(sunPosition(SEASON_DAY.summer, 18).azimuth).toBeGreaterThan(240);
    expect(sunPosition(SEASON_DAY.autumn, 13).elevation).toBeLessThan(
      sunPosition(SEASON_DAY.summer, 13).elevation,
    );
  });

  it('направление: юг - это +z сцены, восток - +x', () => {
    const [, , z] = sunDirection({ elevation: 0, azimuth: 180 });
    expect(z).toBeCloseTo(1);
    const [x] = sunDirection({ elevation: 0, azimuth: 90 });
    expect(x).toBeCloseTo(1);
  });
});

describe('архетипы и листва', () => {
  it('род уточняет форму кроны', () => {
    expect(archetypeOf(plant('betula_pendula', { genus: 'betula' }))).toBe('birch');
    expect(archetypeOf(plant('picea_abies', { genus: 'picea', conifer: true }))).toBe('spruce');
    expect(archetypeOf(plant('tilia_cordata'))).toBe('broadleaf');
    expect(
      archetypeOf(
        plant('juniperus_sabina', { genus: 'juniperus', life_form: 'shrub_medium' }, 'shrub'),
      ),
    ).toBe('creeper');
  });

  it('тон цветущего кустарника без поля bloom - это цветок, листва у него зелёная', () => {
    const lilac = foliageOf('#a892d2', undefined);
    expect(isGreen(lilac.leaf)).toBe(true);
    expect(lilac.flower).toEqual(hexRgb('#a892d2'));
    const purple = foliageOf('#a06f73', '#f1e7dd');
    expect(purple.leaf).toEqual(hexRgb('#a06f73'));
  });

  it('летом сирень зелёная, весной цветёт, осенью липа желтеет, хвоя не меняется', () => {
    const lilac = plant('syringa_josikaea', { genus: 'syringa', life_form: 'shrub_tall' }, 'shrub');
    const summer = foliageColor(lilac, 'summer');
    expect(summer.g).toBeGreaterThan(summer.b);
    const spring = foliageColor(lilac, 'spring');
    expect(spring.b).toBeGreaterThan(summer.b);
    const fall = foliageColor(plant('tilia_cordata'), 'autumn');
    expect(fall.r).toBeGreaterThan(fall.b * 1.5);
    const spruce = plant('picea_abies', { genus: 'picea', conifer: true, evergreen: true });
    expect(foliageColor(spruce, 'autumn')).toEqual(foliageColor(spruce, 'summer'));
  });
});
