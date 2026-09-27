import { describe, expect, it } from 'vitest';

import {
  candidatesAt,
  isWeak,
  MAX_CANDIDATES,
  orderItems,
  pick,
  preferSelected,
  shown,
} from './picking';
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

  it('в перекрытых кронах выигрывает ствол, в который целились, а не крона сверху', () => {
    // Масштаб 20 px/м: радиус попадания в ствол - полметра. Точка внутри обеих крон,
    // ствол b в 0,3 м, ствол a в 1 м.
    const a = item({ id: 'a', x: 0, y: 0, radius: 3 });
    const b = item({ id: 'b', x: 1.3, y: 0, radius: 3 });
    expect(pick({ x: 1, y: 0 }, [b, a], 20, DEFAULT_LAYERS, new Set())?.id).toBe('b');
    expect(pick({ x: 0.2, y: 0 }, [b, a], 20, DEFAULT_LAYERS, new Set())?.id).toBe('a');
  });

  it('вдали от стволов щелчок по кроне берёт крону с ближайшим стволом', () => {
    const a = item({ id: 'a', x: 0, y: 0, radius: 3 });
    const b = item({ id: 'b', x: 4, y: 0, radius: 3 });
    expect(pick({ x: 2.4, y: 0 }, [a, b], 20, DEFAULT_LAYERS, new Set())?.id).toBe('b');
    expect(pick({ x: 0, y: 2.5 }, [a, b], 20, DEFAULT_LAYERS, new Set())?.id).toBe('a');
  });

  it('кандидаты для списка: все стволы в радиусе попадания, ближайшие первыми', () => {
    const a = item({ id: 'a', x: 0, y: 0 });
    const b = item({ id: 'b', x: 0.4, y: 0 });
    const c = item({ id: 'c', x: 0.1, y: 0.05 });
    const far = item({ id: 'far', x: 2, y: 0 });
    const hidden = item({ id: 'hidden', x: 0.05, y: 0, species_code: 'acer' });
    const found = candidatesAt(
      { x: 0.1, y: 0 },
      [a, b, c, far, hidden],
      20,
      DEFAULT_LAYERS,
      new Set(['acer']),
    );
    expect(found.map((i) => i.id)).toEqual(['c', 'a', 'b']);
  });

  it('один ствол под курсором - не спор, список не нужен', () => {
    const a = item({ id: 'a', x: 0, y: 0 });
    const b = item({ id: 'b', x: 3, y: 0 });
    expect(candidatesAt({ x: 0, y: 0 }, [a, b], 20, DEFAULT_LAYERS, new Set())).toHaveLength(1);
  });

  it('список не длиннее MAX_CANDIDATES', () => {
    const many = Array.from({ length: 20 }, (_, i) => item({ id: String(i), x: i * 0.01, y: 0 }));
    expect(candidatesAt({ x: 0, y: 0 }, many, 20, DEFAULT_LAYERS, new Set())).toHaveLength(
      MAX_CANDIDATES,
    );
  });

  it('тянется выбранная, если её ствол под курсором, иначе ближайшая', () => {
    const a = item({ id: 'a' });
    const b = item({ id: 'b' });
    expect(preferSelected([a, b], b)).toBe(b);
    expect(preferSelected([a, b], item({ id: 'c' }))).toBe(a);
    expect(preferSelected([], a)).toBeNull();
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
