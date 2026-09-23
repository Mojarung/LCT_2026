import { describe, expect, it } from 'vitest';

import { isWeak, orderItems, pick, shown } from './picking';
import { DEFAULT_LAYERS, type MapItem } from './types';

const item = (over: Partial<MapItem>): MapItem => ({
  kind: 'placement',
  id: 'p',
  number: 1,
  planting_type: 'tree',
  x: 0,
  y: 0,
  radius: 2,
  verdict: 'allowed',
  species_code: 'tilia',
  explanation: '',
  value: null,
  checks: [],
  ...over,
});

describe('выбор отметки', () => {
  it('берётся ближайшая в радиусе кроны', () => {
    const a = item({ id: 'a', x: 0, y: 0 });
    const b = item({ id: 'b', x: 3, y: 0 });
    expect(pick({ x: 2, y: 0 }, [a, b], 10, DEFAULT_LAYERS, new Set())?.id).toBe('b');
    expect(pick({ x: 50, y: 0 }, [a, b], 10, DEFAULT_LAYERS, new Set())).toBeNull();
  });

  it('на общем виде ловится в восьми пикселях, даже если крона мельче', () => {
    const a = item({ radius: 0.5 });
    expect(pick({ x: 7, y: 0 }, [a], 1, DEFAULT_LAYERS, new Set())).toBe(a);
  });

  it('спрятанная фильтром вида не ловится', () => {
    const a = item({});
    expect(pick({ x: 0, y: 0 }, [a], 10, DEFAULT_LAYERS, new Set(['tilia']))).toBeNull();
  });

  it('отказ виден со слоем отказов или как место под барьер', () => {
    const rejection = item({ kind: 'rejection', barrier_m: null });
    const barrier = item({ kind: 'rejection', barrier_m: 0.8 });
    expect(shown(rejection, DEFAULT_LAYERS, new Set())).toBe(false);
    expect(shown(barrier, DEFAULT_LAYERS, new Set())).toBe(true);
    expect(shown(rejection, { ...DEFAULT_LAYERS, rejections: true }, new Set())).toBe(true);
  });

  it('слабое место - по флагу прогона, а у старых прогонов - по минусу вклада', () => {
    const value = { delta: -0.00002, percentile: 0.1, by_term: {}, reasons: [], weak: [] };
    expect(isWeak(item({ value: { ...value, flagged: false } }))).toBe(false);
    expect(isWeak(item({ value }))).toBe(true);
    expect(isWeak(item({ value: { ...value, delta: 0.00001 } }))).toBe(false);
  });

  it('обход с клавиатуры - вдоль улицы', () => {
    const items = [item({ id: 'c', x: 30 }), item({ id: 'a', x: 10 }), item({ id: 'b', x: 20 })];
    expect(orderItems(items, 0).map((i) => i.id)).toEqual(['a', 'b', 'c']);
  });
});
