import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { BasemapFeature, LawnJson, Position } from '../api/artifacts';
import { buildChunks } from './chunks';
import { LAWN_CLASSES, lawnChunks, lawnFeatures, withLawns } from './lawns';
import { STYLES } from './palette';
import { DEFAULT_LAYERS } from './types';

// В jsdom нет Path2D: для нарезки важны только классы кусков, их стиль и порядок.
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

const square = (x: number, size: number): Position[][] => [
  [
    [x, 0],
    [x + size, 0],
    [x + size, size],
    [x, size],
    [x, 0],
  ],
];

const lawn = (id: string, kind: string, x: number): LawnJson => ({
  id,
  number: 1,
  planting_type: 'lawn',
  kind,
  area_m2: 100,
  rule_ids: ['R-LAWN-KEPT-001', 'R-LAWN-DRAW-001'],
  notes: [],
  explanation: '',
  geometry: { type: 'Polygon', coordinates: square(x, 10) },
});

const feature = (klass: string, geometry: BasemapFeature['geometry']): BasemapFeature => ({
  type: 'Feature',
  properties: { class: klass },
  geometry,
});

describe('газоны плана на карте', () => {
  it('каждый вид газона - свой класс со стилем слоя lawns', () => {
    const features = lawnFeatures([lawn('L1', 'kept', 0), lawn('L2', 'new', 20)]);

    expect(features.map((f) => f.properties.class)).toEqual(['plan_lawn.kept', 'plan_lawn.new']);
    for (const klass of Object.values(LAWN_CLASSES)) {
      expect(STYLES[klass]?.group).toBe('lawns');
      expect(STYLES[klass]?.fill).toBeTruthy();
    }
    // Устраиваемый газон отличается не только тоном, но и пунктиром контура.
    expect(STYLES['plan_lawn.new']?.dash?.length).toBeGreaterThan(0);
    expect(STYLES['plan_lawn.kept']?.dash).toBeUndefined();
  });

  it('вид газона, которого нет в обозначениях, не рисуется', () => {
    expect(lawnFeatures([lawn('L1', 'meadow', 0)])).toEqual([]);
    expect(lawnChunks([])).toEqual([]);
  });

  it('куски газона - в слое lawns, и слой виден по умолчанию', () => {
    const chunks = lawnChunks([lawn('L1', 'kept', 0), lawn('L2', 'new', 20)]);

    expect(chunks).toHaveLength(2);
    expect(chunks.every((chunk) => chunk.group === 'lawns')).toBe(true);
    expect(DEFAULT_LAYERS.lawns).toBe(true);
  });

  it('газон ложится на заливки подосновы, но под её линии', () => {
    const base = buildChunks(
      [
        feature('curb', {
          type: 'LineString',
          coordinates: [
            [0, -1],
            [40, -1],
          ],
        }),
        feature('building', { type: 'Polygon', coordinates: square(50, 10) }),
      ],
      [0, -1, 60, 10],
    );
    const lawns = lawnChunks([lawn('L1', 'kept', 0)]);

    expect(withLawns(base, lawns).map((chunk) => chunk.group)).toEqual([
      'buildings',
      'lawns',
      'surfaces',
    ]);
    expect(withLawns(base, [])).toEqual(base);
  });
});
