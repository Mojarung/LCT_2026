import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { BasemapFeature } from '../api/artifacts';
import { buildChunks } from './chunks';

// В jsdom нет Path2D: для нарезки важны только ключи кусков и их габариты.
class FakePath {
  moveTo() {}
  lineTo() {}
  closePath() {}
}

beforeEach(() => {
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
