/* Размерные выноски на записывающем холсте: линия со стрелкой и засечками к объекту, окружность
 * радиусом замера, когда объекта на подоснове нет, плашки без наложений. */

import { describe, expect, it } from 'vitest';

import type { BasemapFeature, Geometry } from '../api/artifacts';
import { fakeContext } from '../test/canvas';
import { ClassIndex, type Dimension, drawDimensions, TONES } from './dimensions';
import type { MapItem, ViewState } from './types';

const item: MapItem = {
  kind: 'placement',
  id: 'p',
  number: 1,
  planting_type: 'tree',
  x: 0,
  y: 0,
  radius: 1,
  verdict: 'allowed',
  explanation: '',
  value: null,
  checks: [],
};

// 10 px/м, ствол в (300, 300) экрана.
const view: ViewState = { scale: 10, tx: 300, ty: 300, rot: 0 };

const dimension = (over: Partial<Dimension>): Dimension => ({
  to: [5, 0],
  measured: 5,
  label: 'борт 5,00 ≥ 2,00',
  tone: 'surface',
  ...over,
});

describe('выноски выбранной посадки', () => {
  it('без выносок ничего не рисуется', () => {
    const fake = fakeContext();
    drawDimensions(fake.ctx, view, item, [], 'Inter');
    expect(fake.calls).toEqual([]);
  });

  it('линия от ствола к объекту, засечки на концах, стрелка и плашка цветом тона', () => {
    const fake = fakeContext();
    drawDimensions(fake.ctx, view, item, [dimension({})], 'Inter');
    const moves = fake.named('moveTo').map((c) => c.args);
    // Линия (300, 300) -> (350, 300), засечки поперёк по 5 px, затем стрелка от цели.
    expect(moves.slice(0, 4)).toEqual([
      [300, 300],
      [300, 305],
      [350, 305],
      [350, 300],
    ]);
    expect(fake.named('lineTo')[0]?.args).toEqual([350, 300]);
    const stroke = fake.named('stroke')[0];
    expect(stroke?.state).toMatchObject({ strokeStyle: TONES.surface.fill, lineWidth: 1.6 });
    const [label] = fake.named('fillText');
    expect(label?.args[0]).toBe('борт 5,00 ≥ 2,00');
    expect(label?.state).toMatchObject({ fillStyle: TONES.surface.text, font: '600 12px Inter' });
    // Плашка за целью по направлению выноски: левый край правее цели.
    const plate = fake.named('roundRect')[0]?.args as number[];
    expect(plate[0]).toBeGreaterThan(350);
    expect(plate[3]).toBe(20);
  });

  it('объекта на подоснове нет - пунктирная окружность радиусом замера и радиус-выноска', () => {
    const fake = fakeContext();
    drawDimensions(
      fake.ctx,
      view,
      item,
      [dimension({ to: null, measured: 4, tone: 'fail', label: 'опора 4,00 < 5,00' })],
      'Inter',
    );
    const circle = fake.named('arc')[0];
    expect(circle?.args.slice(0, 3)).toEqual([300, 300, 40]);
    const [ring, line] = fake.named('stroke');
    expect(ring?.state).toMatchObject({ lineDash: [5, 4], strokeStyle: TONES.fail.fill });
    // Радиус-выноска к окружности - уже сплошной линией.
    expect(line?.state.lineDash).toEqual([]);
    // Первая окружность - радиус вверх-вправо, под -45 градусов.
    const end = fake.named('lineTo')[0]?.args as [number, number];
    expect(end[0]).toBeCloseTo(300 + 40 * Math.SQRT1_2);
    expect(end[1]).toBeCloseTo(300 - 40 * Math.SQRT1_2);
  });

  it('окружность мельче 6 px и объект у самого ствола не рисуются', () => {
    const fake = fakeContext();
    drawDimensions(
      fake.ctx,
      view,
      item,
      [dimension({ to: null, measured: 0.5 }), dimension({ to: [0.2, 0] })],
      'Inter',
    );
    expect(fake.named('stroke')).toEqual([]);
    expect(fake.texts()).toEqual([]);
  });

  it('две выноски в одну сторону - плашки не налезают, сдвинутая ведёт к цели тонкой линией', () => {
    const fake = fakeContext();
    drawDimensions(
      fake.ctx,
      view,
      item,
      [
        dimension({ to: [5, 0], label: 'борт 5,00 ≥ 2,00' }),
        dimension({ to: [5, 0.1], label: 'тротуар 5,00 ≥ 1,00' }),
      ],
      'Inter',
    );
    const [first, second] = fake
      .named('roundRect')
      .map((c) => c.args as [number, number, number, number]);
    if (!first || !second) throw new Error('плашек нет');
    const overlap =
      first[0] < second[0] + second[2] &&
      first[0] + first[2] > second[0] &&
      first[1] < second[1] + second[3] &&
      first[1] + first[3] > second[1];
    expect(overlap).toBe(false);
    // Тонкая линия-указатель толщиной 1 px у сдвинутой плашки.
    expect(fake.named('stroke').some((c) => c.state.lineWidth === 1)).toBe(true);
  });
});

describe('геометрия подосновы для выносок', () => {
  const feature = (cls: string, geometry: Geometry): BasemapFeature => ({
    type: 'Feature',
    properties: { class: cls },
    geometry,
  });

  it('точки, контуры и наборы геометрий - всё идёт в поиск ближайшего объекта класса', () => {
    const index = new ClassIndex([
      feature('pole', { type: 'Point', coordinates: [3, 4] }),
      feature('pole', { type: 'MultiPoint', coordinates: [[10, 0]] }),
      feature('building', {
        type: 'Polygon',
        coordinates: [
          [
            [20, -5],
            [30, -5],
            [30, 5],
            [20, 5],
            [20, -5],
          ],
        ],
      }),
      feature('fence', {
        type: 'MultiPolygon',
        coordinates: [
          [
            [
              [0, 50],
              [10, 50],
            ],
          ],
        ],
      }),
      feature('curb', {
        type: 'GeometryCollection',
        geometries: [
          {
            type: 'MultiLineString',
            coordinates: [
              [
                [-7, -10],
                [-7, 10],
              ],
            ],
          },
        ],
      }),
      // Класс без короткого имени на карту не выносится.
      feature('unknown_class', { type: 'Point', coordinates: [0, 0] }),
    ]);
    expect(index.nearest('pole', 0, 0, 10)).toEqual([3, 4]);
    expect(index.nearest('pole', 9, 0, 10)).toEqual([10, 0]);
    expect(index.nearest('building', 0, 0, 25)).toEqual([20, 0]);
    expect(index.nearest('fence', 5, 45, 10)).toEqual([5, 50]);
    expect(index.nearest('curb', 0, 3, 10)).toEqual([-7, 3]);
    // Дальше предела поиска и класс без объектов - ничего.
    expect(index.nearest('building', 0, 0, 10)).toBeNull();
    expect(index.nearest('unknown_class', 0, 0, 10)).toBeNull();
  });
});
