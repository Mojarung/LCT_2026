import { describe, expect, it } from 'vitest';

import { plantsOf } from './existing';
import { hedgeRows, planSign } from './signs';
import { documentMapStyle, parseMapStyle } from './style';
import type { MapItem } from './types';

const item = (id: string, plantingType: string, x: number, species = 'cotoneaster_lucidus') =>
  ({
    kind: 'placement',
    id,
    number: 1,
    planting_type: plantingType,
    x,
    y: 0,
    radius: 0.6,
    verdict: 'allowed',
    species_code: species,
    explanation: '',
    value: null,
    checks: [],
  }) satisfies MapItem;

describe('знак посадки в инженерном стиле', () => {
  it('кустарник - по типу посадки, хвойное дерево - по форме модели вида', () => {
    expect(planSign('tree', 'tilia_cordata')).toBe('tree');
    expect(planSign('tree', 'pinus_sylvestris')).toBe('conifer');
    expect(planSign('tree', 'picea_pungens')).toBe('conifer');
    // Вид без модели - лиственное: хвойность без данных не придумывается.
    expect(planSign('tree', 'unknown_species')).toBe('tree');
    expect(planSign('tree', undefined)).toBe('tree');
    expect(planSign('shrub', 'juniperus_sabina')).toBe('shrub');
    expect(planSign('hedge', undefined)).toBe('shrub');
  });
});

describe('ряды кустарника - полосой живой изгороди', () => {
  it('кусты ряда собираются по номеру ряда в порядке посадки, одиночки и деревья - нет', () => {
    const placements = [
      item('C001-002', 'shrub', 2),
      item('C001-000', 'shrub', 0),
      item('H003-000', 'shrub', 10),
      item('C001-001', 'shrub', 1),
      item('H003-001', 'shrub', 11),
      // Ряд из одного куста - не полоса.
      item('C002-000', 'shrub', 30),
      // Группа на газоне и подлесок - свои номера, не ряды.
      item('Fp-12ab', 'shrub', 40),
      item('U7-0', 'shrub', 41),
      item('p-71b48fe6bd69', 'tree', 50, 'tilia_cordata'),
    ];

    const { rows, member } = hedgeRows(placements);

    expect(rows.map((row) => row.map((p) => p.id))).toEqual([
      ['C001-000', 'C001-001', 'C001-002'],
      ['H003-000', 'H003-001'],
    ]);
    expect(member.size).toBe(5);
    // Ряды считаются один раз на список посадок.
    expect(hedgeRows(placements)).toBe(hedgeRows(placements));
  });
});

describe('существующее дерево со знаком хвойного', () => {
  const feature = (cls: string, conifer?: boolean) =>
    plantsOf({
      type: 'Feature',
      properties: conifer === undefined ? { class: cls } : { class: cls, conifer },
      geometry: {
        type: 'MultiPoint',
        coordinates: [
          [1, 2],
          [3, 4],
        ],
      },
    });

  it('признак подосновы доезжает до каждой отметки дерева', () => {
    expect(feature('existing_tree', true)?.every((plant) => plant.conifer === true)).toBe(true);
    expect(feature('existing_tree')?.some((plant) => plant.conifer)).toBe(false);
    // Кустарник хвойным кольцом не рисуется, даже если признак пришёл.
    expect(feature('existing_shrub', true)?.some((plant) => plant.conifer)).toBe(false);
  });
});

describe('стиль карты', () => {
  it('по умолчанию инженерный, иллюстрация - только явно', () => {
    expect(parseMapStyle(null)).toBe('engineering');
    expect(parseMapStyle('что-то')).toBe('engineering');
    expect(parseMapStyle('illustrated')).toBe('illustrated');
    expect(documentMapStyle()).toBe('engineering');
    document.documentElement.dataset.mapStyle = 'illustrated';
    expect(documentMapStyle()).toBe('illustrated');
  });
});
