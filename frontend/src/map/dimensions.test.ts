import { describe, expect, it } from 'vitest';

import type { BasemapFeature, RuleCheck } from '../api/artifacts';
import { splitChecks } from '../lib/checks';
import { ClassIndex, dimensionsFor, labelBox, leaderEnd, type Rect, TONES } from './dimensions';

const check = (
  rule_id: string,
  object_class: string,
  measured: number | null,
  threshold: number,
  outcome = 'pass',
): RuleCheck => ({ rule_id, outcome, measured_m: measured, threshold_m: threshold, object_class });

const line = (cls: string, coordinates: [number, number][]): BasemapFeature => ({
  type: 'Feature',
  properties: { class: cls },
  geometry: { type: 'LineString', coordinates },
});

// Посадка в начале координат; борт в 2,5 м к востоку, кабель в 4 м к северу. Опоры на
// подоснове нет: сервис её видел, карта - нет.
const basemap = new ClassIndex([
  line('curb', [
    [2.5, -10],
    [2.5, 10],
  ]),
  line('utility.power_cable', [
    [-10, 4],
    [10, 4],
  ]),
]);
const at = { x: 0, y: 0 };

describe('выноски на карте - те же нормы, что в панели', () => {
  it('список и порядок - «Ближе всего к норме» из панели, дальние нормы молчат', () => {
    const checks = [
      check('R-BUILDING', 'building', 30, 5), // запас 6 - в панели под раскрытием
      check('R-CABLE', 'utility.power_cable', 4, 2), // запас 2 - уже не тугая
      check('R-CURB', 'curb', 2.5, 2), // запас 1,25
      check('R-POLE', 'pole', 5.5, 4), // запас 1,375
    ];
    const lead = splitChecks(checks).lead.map((c) => c.rule_id);
    expect(lead).toEqual(['R-CURB', 'R-POLE']);
    expect(dimensionsFor(at, checks, basemap).map((d) => d.label)).toEqual([
      'борт 2,50 ≥ 2,00',
      'опора 5,50 ≥ 4,00',
    ]);
  });

  it('объект на подоснове - линия к ближайшей точке; нет объекта - окружность радиусом замера', () => {
    const [curb, pole] = dimensionsFor(
      at,
      [check('R-CURB', 'curb', 2.5, 2), check('R-POLE', 'pole', 5.5, 4)],
      basemap,
    );
    expect(curb?.to).toEqual([2.5, 0]);
    expect(pole).toMatchObject({ to: null, measured: 5.5, tone: 'other' });
  });

  it('нарушение одно в списке, малиновое и со знаком «<»', () => {
    const checks = [
      check('R-CURB', 'curb', 2.5, 2),
      check('R-CABLE', 'utility.power_cable', 1.4, 2, 'fail'),
    ];
    expect(dimensionsFor(at, checks, basemap)).toEqual([
      { to: null, measured: 1.4, label: 'силовой кабель 1,40 < 2,00', tone: 'fail' },
    ]);
  });

  it('норма без замера или без расстояния на карту не выносится', () => {
    const checks = [
      check('R-TRAM', 'tram', null, 5, 'fail'),
      check('R-ZONE', 'slope', 0, 0, 'fail'),
    ];
    expect(dimensionsFor(at, checks, basemap)).toEqual([]);
  });
});

describe('плашка подписи стоит за целью, а не на ней', () => {
  const inside = ([x, y, w, h]: Rect, px: number, py: number) =>
    px >= x && px <= x + w && py >= y && py <= y + h;

  it.each([
    [1, 0],
    [-1, 0],
    [0, 1],
    [0, -1],
    [Math.SQRT1_2, -Math.SQRT1_2],
    [-0.6, 0.8],
  ])('направление (%f, %f)', (ux, uy) => {
    const [tx, ty] = [200, 150];
    for (const shift of [0, 23, -46]) {
      const box = labelBox(tx, ty, ux, uy, 120, shift);
      expect(inside(box, tx, ty)).toBe(false);
      // Вся плашка - по ту сторону цели от ствола: её ближняя к стволу точка дальше цели.
      const [x, y, w, h] = box;
      const corners = [
        [x, y],
        [x + w, y],
        [x, y + h],
        [x + w, y + h],
      ] as const;
      const nearest = Math.min(...corners.map(([cx, cy]) => (cx - tx) * ux + (cy - ty) * uy));
      expect(nearest).toBeGreaterThan(0);
    }
  });
});

describe('выноска читается: одна на объект, контраст AA', () => {
  it('два правила на один замер до одного объекта - одна плашка', () => {
    const checks = [
      check('R-HEAT-TREE-001', 'utility.heat', 2.23, 2),
      check('R-HEAT-TREE-002', 'utility.heat', 2.23, 2),
    ];
    expect(dimensionsFor(at, checks, basemap).map((d) => d.label)).toEqual([
      'теплосеть 2,23 ≥ 2,00',
    ]);
  });

  it('белый текст 12 px на каждой заливке - не ниже 4,5:1', () => {
    const channel = (v: number) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    const part = (hex: string, i: number) => channel(Number.parseInt(hex.slice(i, i + 2), 16));
    const luminance = (hex: string) =>
      0.2126 * part(hex, 1) + 0.7152 * part(hex, 3) + 0.0722 * part(hex, 5);
    const ratio = (a: string, b: string) => {
      const [x, y] = [luminance(a), luminance(b)];
      return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
    };
    // Контроль пробы: старый бирюзовый давал 4,13 и должен не пройти.
    expect(ratio('#2f8a82', '#ffffff')).toBeLessThan(4.5);
    for (const tone of Object.values(TONES)) {
      expect(ratio(tone.fill, tone.text)).toBeGreaterThanOrEqual(4.5);
    }
  });
});

describe('сдвинутая плашка связана со своей выноской', () => {
  it('плашка у цели - без линии; сдвинутая на 46 px - линия к ближнему краю плашки', () => {
    const near = labelBox(100, 100, 1, 0, 80);
    expect(leaderEnd(100, 100, near)).toBeNull();
    const shifted = labelBox(100, 100, 1, 0, 80, 46);
    const end = leaderEnd(100, 100, shifted);
    expect(end).not.toBeNull();
    const [x, y, w, h] = shifted;
    expect(end?.[0]).toBeGreaterThanOrEqual(x);
    expect(end?.[0]).toBeLessThanOrEqual(x + w);
    expect(end?.[1]).toBeGreaterThanOrEqual(y);
    expect(end?.[1]).toBeLessThanOrEqual(y + h);
  });
});
