import { describe, expect, it } from 'vitest';

import catalog from '../../../config/species.yaml?raw';
import { plantsOf } from './existing';
import { ALL_MODELS, commonest, MODELS, modelKey, modelOf, planSpecies } from './models';
import type { MapItem } from './types';

/** Коды видов каталога прямо из config/species.yaml: база моделей обязана идти за ним. */
function catalogCodes(): string[] {
  return [...catalog.matchAll(/\{code: ([a-z_]+),/g)].map((match) => match[1] ?? '');
}

describe('база моделей растений', () => {
  it('у каждого вида каталога есть модель', () => {
    const codes = catalogCodes();
    expect(codes.length).toBeGreaterThan(50);
    expect(codes.filter((code) => !MODELS.has(code))).toEqual([]);
  });

  it('в базе нет моделей видов, которых нет в каталоге', () => {
    const codes = new Set(catalogCodes());
    expect(ALL_MODELS.map((m) => m.code).filter((code) => !codes.has(code))).toEqual([]);
  });

  it('образец легенды - самый частый вид плана нужной формы', () => {
    const plan = [
      'syringa_vulgaris',
      'cotoneaster_lucidus',
      'tilia_cordata',
      'cotoneaster_lucidus',
      'juniperus_sabina',
      'juniperus_sabina',
      'juniperus_sabina',
      undefined,
    ];
    // Хвойный кустарник и дерево в образец «кустарник» не годятся, даже если их больше.
    expect(commonest(plan, 'shrub')).toBe('cotoneaster_lucidus');
    expect(commonest(plan, 'broadleaf')).toBe('tilia_cordata');
    expect(commonest([], 'shrub')).toBeNull();
  });

  it('вид вне базы рисуется моделью своего типа посадки', () => {
    expect(modelOf('unknown_species', 'shrub').form).toBe('shrub');
    expect(modelOf(undefined, 'tree').form).toBe('broadleaf');
    expect(modelKey('unknown_species', 'tree')).toBe('~tree');
    expect(modelKey('tilia_cordata', 'tree')).toBe('tilia_cordata');
  });

  it('цвета моделей - #rrggbb: спрайт осветляет и затемняет их арифметикой', () => {
    for (const model of ALL_MODELS) {
      expect(model.tone).toMatch(/^#[0-9a-f]{6}$/);
      if (model.bloom) expect(model.bloom).toMatch(/^#[0-9a-f]{6}$/);
    }
  });
});

describe('существующие насаждения с подосновы', () => {
  const feature = (cls: string, geometry: Parameters<typeof plantsOf>[0]['geometry']) =>
    plantsOf({ type: 'Feature', properties: { class: cls }, geometry });

  it('точка знака - крона по умолчанию', () => {
    expect(feature('existing_tree', { type: 'Point', coordinates: [10, 20] })).toEqual([
      { x: 10, y: 20, r: 2.5, shrub: false },
    ]);
  });

  it('кружок кроны - крона своего размера', () => {
    const ring = [
      [0, 0],
      [4, 0],
      [4, 4],
      [0, 4],
      [0, 0],
    ] as [number, number][];
    expect(feature('existing_tree', { type: 'Polygon', coordinates: [ring] })).toEqual([
      { x: 2, y: 2, r: 2, shrub: false },
    ]);
  });

  it('массив насаждений остаётся линией подосновы, а не одной огромной кроной', () => {
    const ring = [
      [0, 0],
      [40, 0],
      [40, 30],
      [0, 0],
    ] as [number, number][];
    expect(feature('existing_tree', { type: 'Polygon', coordinates: [ring] })).toBeNull();
  });

  it('не насаждения не трогаются', () => {
    expect(feature('building', { type: 'Point', coordinates: [0, 0] })).toBeNull();
  });
});

describe('полосы деревьев не становятся отдельными кронами', () => {
  const geometry = {
    type: 'MultiPoint' as const,
    coordinates: [
      [0, 0],
      [0.8, 0],
      [1.6, 0],
    ] as [number, number][],
  };
  it.each([undefined, 'strip'] as const)('новые и старые артефакты: %s', (vegetation_kind) => {
    expect(
      plantsOf({
        type: 'Feature',
        properties: { class: 'existing_tree', vegetation_kind },
        geometry,
      }),
    ).toBeNull();
  });
  it('явная группа отдельных деревьев сохраняется', () => {
    expect(
      plantsOf({
        type: 'Feature',
        properties: { class: 'existing_tree', vegetation_kind: 'individual' },
        geometry,
      }),
    ).toHaveLength(3);
  });
});

describe('виды плана для легенды', () => {
  it('по убыванию числа посадок, без вида - своей строкой', () => {
    const item = (code: string | undefined, name: string, type = 'tree') =>
      ({
        kind: 'placement',
        id: `${code ?? '-'}-${name}`,
        number: 1,
        planting_type: type,
        x: 0,
        y: 0,
        radius: 1,
        verdict: 'allowed',
        species_code: code,
        species_ru: name,
        explanation: '',
        value: null,
        checks: [],
      }) satisfies MapItem;
    const rows = planSpecies([
      item('tilia_cordata', 'Липа мелколистная'),
      item('spiraea_japonica', 'Спирея японская', 'shrub'),
      item('spiraea_japonica', 'Спирея японская', 'shrub'),
      item(undefined, ''),
    ]);
    expect(rows.map((row) => row.name)).toEqual([
      'Спирея японская',
      'Липа мелколистная',
      'вид не назначен',
    ]);
    expect(rows[0]?.plantingType).toBe('shrub');
  });
});
