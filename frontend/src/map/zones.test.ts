import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Position, ZonesJson } from '../api/artifacts';
import { STYLES } from './palette';
import { DEFAULT_LAYERS } from './types';
import { ZONE_CLASSES, zoneChunks, zoneFeatures } from './zones';

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

const zones = (...verdicts: string[]): ZonesJson => ({
  type: 'FeatureCollection',
  features: verdicts.map((verdict, i) => ({
    type: 'Feature',
    properties: { verdict, area_m2: 100 },
    geometry: { type: 'MultiPolygon', coordinates: [square(i * 20, 10)] },
  })),
});

describe('зоны допустимости на карте', () => {
  it('каждый вердикт зоны - свой класс со стилем слоя zones', () => {
    const features = zoneFeatures(zones('allowed', 'needs_approval'));

    expect(features.map((f) => f.properties.class)).toEqual([
      'zone.allowed',
      'zone.needs_approval',
    ]);
    for (const klass of Object.values(ZONE_CLASSES)) {
      expect(STYLES[klass]?.group).toBe('zones');
      expect(STYLES[klass]?.fill).toBeTruthy();
    }
  });

  it('вердикт без обозначения и прогон без зон ничего не рисуют', () => {
    expect(zoneFeatures(zones('forbidden'))).toEqual([]);
    expect(zoneChunks(undefined)).toEqual([]);
  });

  it('куски зон - в слое zones, выключенном по умолчанию', () => {
    const chunks = zoneChunks(zones('allowed', 'needs_approval'));

    expect(chunks).toHaveLength(2);
    expect(chunks.every((chunk) => chunk.group === 'zones')).toBe(true);
    expect(DEFAULT_LAYERS.zones).toBe(false);
  });
});
