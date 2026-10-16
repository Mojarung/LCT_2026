import { describe, expect, it } from 'vitest';

import type { Geometry, Position } from '../api/artifacts';
import { poleSites } from './poles';

/** Ромб основания знака: центр и полуразмах, контур замкнут. */
function diamond(cx: number, cy: number, r: number): Position[] {
  return [
    [cx, cy - r],
    [cx + r, cy],
    [cx, cy + r],
    [cx - r, cy],
    [cx, cy - r],
  ];
}

const polygon = (ring: Position[]): Geometry => ({ type: 'Polygon', coordinates: [ring] });
const line = (...points: Position[]): Geometry => ({ type: 'LineString', coordinates: points });

/** Фонарь Мосгеотреста, разобранный на примитивы: ромб, его заливка, стойка, консоль, плафон. */
function lampParts(cx: number, cy: number, r = 0.2): Geometry[] {
  const top = cy + r + 1.4;
  return [
    polygon(diamond(cx, cy, r)),
    polygon(diamond(cx, cy, r)),
    line([cx, cy + r], [cx, top]),
    line([cx, top], [cx + 0.6, top]),
    line([cx + 0.4, top], [cx + 0.4, top - 0.4], [cx + 0.5, top - 0.5], [cx + 0.6, top - 0.4]),
  ];
}

describe('опоры из частей условных знаков', () => {
  it('части одного знака дают одну опору на ромбе основания', () => {
    const sites = poleSites(lampParts(100, 200));
    expect(sites).toHaveLength(1);
    expect(sites[0]?.[0]).toBeCloseTo(100);
    expect(sites[0]?.[1]).toBeCloseTo(200);
  });

  it('два знака рядом остаются двумя, даже если их штрихи касаются', () => {
    // Табличка на стойке в 0,7 м от фонаря: у каждого знака свой ромб.
    const sign = [
      line([100.7, 200.2], [100.7, 201.0]),
      line([100.5, 201.0], [100.9, 201.0], [100.9, 201.8], [100.5, 201.8], [100.5, 201.0]),
      line(...diamond(100.7, 200, 0.2)),
    ];
    const sites = poleSites([...lampParts(100, 200), ...sign]);
    expect(sites).toHaveLength(2);
  });

  it('знак в крупном масштабе узнаётся по форме, а не по размеру', () => {
    // Ромб 1,4 м, стойка 3 м и вытянутый шестигранник 4 м на её конце.
    const parts = [
      polygon(diamond(500, 500, 0.7)),
      line([500, 500.7], [500, 503.7]),
      polygon([
        [499.4, 503.7],
        [500.6, 503.7],
        [500.9, 505.7],
        [500.6, 507.7],
        [499.4, 507.7],
        [499.1, 505.7],
        [499.4, 503.7],
      ]),
    ];
    const sites = poleSites(parts);
    expect(sites).toHaveLength(1);
    expect(sites[0]?.[1]).toBeCloseTo(500);
  });

  it('знак без основания даёт одну опору в середине', () => {
    const sites = poleSites([
      line([10, 10], [10, 11.4]),
      line([9.8, 10], [10.2, 10]),
      line([9.85, 10.1], [10.15, 10.1]),
    ]);
    expect(sites).toHaveLength(1);
  });

  it('одиночная длинная линия опорой не становится', () => {
    expect(poleSites([line([0, 0], [0, 12])])).toHaveLength(0);
  });

  it('точки вставки знаков в 0,35 м - две разные опоры, копия в сантиметре - одна', () => {
    const point = (x: number, y: number): Geometry => ({ type: 'Point', coordinates: [x, y] });
    expect(poleSites([point(0, 0), point(0.35, 0)])).toHaveLength(2);
    expect(poleSites([point(0, 0), point(0.01, 0)])).toHaveLength(1);
  });
});
