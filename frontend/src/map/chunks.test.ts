import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { BasemapFeature } from '../api/artifacts';
import { buildChunks } from './chunks';

// В jsdom нет Path2D: для нарезки важны только ключи кусков и их габариты. Кружки всех
// кусков пишутся в один журнал: тест, который их считает, сам проверяет, что кусок один.
const arc = vi.fn();
class FakePath {
  arc = arc;
  moveTo() {}
  lineTo() {}
  closePath() {}
}

beforeEach(() => {
  arc.mockClear();
  vi.stubGlobal('Path2D', FakePath);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const line = (klass: string, from: [number, number], to: [number, number]): BasemapFeature => ({
  type: 'Feature',
  properties: { class: klass },
  geometry: { type: 'LineString', coordinates: [from, to] },
});

describe('нарезка подосновы', () => {
  it('один кусок на класс, полку размера и ячейку сетки', () => {
    const chunks = buildChunks(
      [
        line('curb', [0, 0], [0.3, 0]), // полка до 0,5 м
        line('curb', [1, 1], [1.2, 1]), // та же полка и ячейка
        line('curb', [0, 0], [30, 0]), // крупная полка
        line('utility.water', [0, 0], [0.3, 0]),
      ],
      [0, 0, 240, 240],
    );
    expect(chunks).toHaveLength(3);
  });

  it('неизвестный класс не рисуется', () => {
    expect(buildChunks([line('nothing', [0, 0], [1, 1])], [0, 0, 10, 10])).toEqual([]);
  });

  it('заливки идут раньше линий', () => {
    const chunks = buildChunks(
      [
        line('curb', [0, 0], [1, 0]),
        {
          type: 'Feature',
          properties: { class: 'lawn' },
          geometry: {
            type: 'Polygon',
            coordinates: [
              [
                [0, 0],
                [5, 0],
                [5, 5],
                [0, 0],
              ],
            ],
          },
        },
      ],
      [0, 0, 10, 10],
    );
    expect(chunks[0]?.fillVar).toBe('--c-lawn');
  });

  it('условный знак-точка не отбрасывается по размеру', () => {
    const [chunk] = buildChunks(
      [
        {
          type: 'Feature',
          properties: { class: 'pole' },
          geometry: { type: 'Point', coordinates: [3, 3] },
        },
      ],
      [0, 0, 10, 10],
    );
    expect(chunk?.span).toBe(Infinity);
  });
});

it('полоса остаётся условными кружками, не попадает в модели крон', () => {
  const existing: import('./existing').ExistingPlant[] = [];
  const chunks = buildChunks(
    [
      {
        type: 'Feature',
        properties: { class: 'existing_tree', vegetation_kind: 'strip' },
        geometry: {
          type: 'MultiPoint',
          coordinates: [
            [0, 0],
            [0.8, 0],
            [1.6, 0],
          ],
        },
      },
    ],
    [0, 0, 10, 10],
    existing,
  );
  expect(existing).toHaveLength(0);
  expect(chunks).toHaveLength(1);
  expect(chunks[0]?.path).toBeInstanceOf(FakePath);
  const arc = (chunks[0]?.path as unknown as FakePath | undefined)?.arc;
  expect(arc).toHaveBeenCalledTimes(3);
  expect(arc).toHaveBeenCalledWith(0, 0, 0.25, 0, Math.PI * 2);
});

it('recognised shrub strip is a filled band, never a list of crowns', () => {
  const feature: BasemapFeature = {
    type: 'Feature',
    properties: { class: 'existing_shrub', vegetation_kind: 'shrub_strip' },
    geometry: {
      type: 'LineString',
      coordinates: [
        [0, 0],
        [4, 0],
        [4, 4],
      ],
    },
  };
  const existing: import('./existing').ExistingPlant[] = [];
  const hedges: import('../api/artifacts').Position[][] = [];
  const chunks = buildChunks([feature], [0, 0, 10, 10], existing, hedges);
  expect(existing).toEqual([]);
  expect(chunks).toHaveLength(1);
  expect(chunks[0]?.fillVar).toBe('--c-existing');
  // Ось полосы - для знака живой изгороди шаблона в стиле чертежа, кусок помечен.
  expect(hedges).toEqual([
    [
      [0, 0],
      [4, 0],
      [4, 4],
    ],
  ]);
  expect(chunks[0]?.hedge).toBe(true);
  expect(chunks[0]?.minX).toBeLessThan(0);
  expect(chunks[0]?.maxY).toBeGreaterThan(4);
});
