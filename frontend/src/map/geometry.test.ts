import { describe, expect, it } from 'vitest';

import type { BasemapFeature } from '../api/artifacts';
import {
  boundaryRings,
  boundsOfPoints,
  contentPoints,
  coversPlan,
  insideRing,
  principalAxis,
  trimmed,
} from './geometry';

describe('геометрия подосновы', () => {
  it('главная ось точек вдоль прямой под 30 градусов - 30 градусов', () => {
    const angle = Math.PI / 6;
    const points = Array.from({ length: 50 }, (_, i) => ({
      x: i * Math.cos(angle) + ((i % 3) - 1) * 0.01,
      y: i * Math.sin(angle),
    }));
    expect(principalAxis(points)).toBeCloseTo(angle, 3);
  });

  it('меньше трёх точек - без разворота', () => {
    expect(
      principalAxis([
        { x: 0, y: 0 },
        { x: 5, y: 5 },
      ]),
    ).toBe(0);
  });

  it('далёкий выброс отрезается 2-98-м процентилем', () => {
    const points = Array.from({ length: 100 }, (_, i) => ({ x: i, y: i % 10 }));
    points.push({ x: 50_000, y: 3 });
    const kept = trimmed(points);
    expect(kept.some((p) => p.x === 50_000)).toBe(false);
    expect(kept.length).toBeGreaterThan(90);
  });

  it('граница работ в опору вписывания не входит', () => {
    const features: BasemapFeature[] = [
      {
        type: 'Feature',
        properties: { class: 'work_boundary' },
        geometry: {
          type: 'LineString',
          coordinates: [
            [-5000, 0],
            [5000, 0],
          ],
        },
      },
      {
        type: 'Feature',
        properties: { class: 'curb' },
        geometry: {
          type: 'LineString',
          coordinates: [
            [0, 0],
            [10, 0],
          ],
        },
      },
    ];
    expect(contentPoints(features)).toEqual([{ x: 5, y: 0 }]);
  });

  it('участок - замкнутые контуры границы работ одного обхода; обрывки контуром не считаются', () => {
    const boundary = (geometry: BasemapFeature['geometry']): BasemapFeature => ({
      type: 'Feature',
      properties: { class: 'work_boundary' },
      geometry,
    });
    // По часовой стрелке: разворачивается, чтобы контуры складывались, а не вычитались.
    const clockwise: [number, number][] = [
      [0, 0],
      [0, 10],
      [10, 10],
      [10, 0],
      [0, 0],
    ];
    const rings = boundaryRings([
      boundary({ type: 'LineString', coordinates: clockwise }),
      boundary({
        type: 'LineString',
        coordinates: [
          [50, 0],
          [90, 0],
        ],
      }),
      boundary({
        type: 'Polygon',
        coordinates: [
          [
            [20, 0],
            [30, 0],
            [30, 10],
            [20, 10],
            [20, 0],
          ],
          // Дыра полигона участком остаётся: берётся только внешний контур.
          [
            [22, 2],
            [22, 8],
            [28, 8],
            [22, 2],
          ],
        ],
      }),
    ]);
    expect(rings).toHaveLength(2);
    expect(rings[0]).toEqual([...clockwise].reverse());
    expect(insideRing(5, 5, rings[0] ?? [])).toBe(true);
    expect(insideRing(25, 5, rings[1] ?? [])).toBe(true);
    expect(insideRing(15, 5, rings[0] ?? [])).toBe(false);
  });

  it('граница бледнит подоснову, только если очерчивает план', () => {
    const square: [number, number][] = [
      [0, 0],
      [10, 0],
      [10, 10],
      [0, 10],
      [0, 0],
    ];
    const plan = Array.from({ length: 20 }, (_, i) => ({ x: 1 + (i % 8), y: 1 + (i % 5) }));
    expect(coversPlan([square], plan)).toBe(true);
    // Рамка листа в углу чертежа: внутри неё посадок нет - это не участок.
    expect(coversPlan([square], [...plan, ...plan.map((p) => ({ x: p.x + 100, y: p.y }))])).toBe(
      false,
    );
    expect(coversPlan([], plan)).toBe(false);
    expect(coversPlan([square], [])).toBe(false);
  });

  it('габарит точек с запасом', () => {
    expect(
      boundsOfPoints(
        [
          { x: 1, y: 2 },
          { x: 3, y: -4 },
        ],
        10,
      ),
    ).toEqual([-9, -14, 13, 12]);
    expect(boundsOfPoints([], 10)).toBeNull();
  });
});
