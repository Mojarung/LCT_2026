import { describe, expect, it } from 'vitest';

import {
  extentOf,
  fitView,
  focusOf,
  GROUP_MAX_SCALE,
  groupView,
  niceLength,
  scaleFromShare,
  toScreen,
  toWorld,
  zoomAt,
  zoomShare,
} from './view';

describe('вид карты', () => {
  it('экран -> чертёж -> экран возвращает ту же точку при любом развороте и масштабе', () => {
    for (const rot of [0, 0.4, -1.1, Math.PI / 2]) {
      const view = { scale: 3.7, tx: 120, ty: -40, rot };
      const world = toWorld(view, 333, 222);
      const { sx, sy } = toScreen(view, world.x, world.y);
      expect(sx).toBeCloseTo(333, 9);
      expect(sy).toBeCloseTo(222, 9);
    }
  });

  it('север (+Y чертежа) без разворота смотрит вверх экрана', () => {
    const view = { scale: 1, tx: 0, ty: 0, rot: 0 };
    expect(toScreen(view, 0, 10).sy).toBeLessThan(toScreen(view, 0, 0).sy);
  });

  it('круглая длина: 1, 2 или 5 на порядок', () => {
    expect(niceLength(137)).toBe(100);
    expect(niceLength(260)).toBe(200);
    expect(niceLength(0.7)).toBe(0.5);
    expect(niceLength(9.9)).toBe(5);
  });

  it('весь план вписывается целиком, крупный вид - лента на 55% высоты', () => {
    // Лента 600 x 100 в области 1000 x 500: целиком масштаб 1,667, лента на трети высоты.
    const ext = extentOf(
      { rot: 0 },
      [
        { x: 0, y: 0 },
        { x: 600, y: 100 },
      ],
      0,
    );
    const area = { left: 0, top: 0, width: 1000, height: 500 };
    expect(fitView(ext, area, 'whole').scale).toBeCloseTo(1000 / 600, 9);
    expect(fitView(ext, area, 'close').scale).toBeCloseTo((0.55 * 500) / 100, 9);
  });

  it('крупный вид не приближает сильнее трёх видов «весь план»', () => {
    const ext = extentOf(
      { rot: 0 },
      [
        { x: 0, y: 0 },
        { x: 6000, y: 10 },
      ],
      0,
    );
    const area = { left: 0, top: 0, width: 1000, height: 500 };
    const whole = fitView(ext, area, 'whole').scale;
    expect(fitView(ext, area, 'close').scale).toBeCloseTo(whole * 3, 9);
  });

  it('вписанный план стоит по центру свободной области', () => {
    const ext = extentOf(
      { rot: 0 },
      [
        { x: 10, y: 10 },
        { x: 110, y: 60 },
      ],
      0,
    );
    const area = { left: 300, top: 50, width: 400, height: 300 };
    const fitted = fitView(ext, area, 'whole');
    const view = { ...fitted, rot: 0 };
    const middle = toScreen(view, 60, 35);
    expect(middle.sx).toBeCloseTo(500, 9);
    expect(middle.sy).toBeCloseTo(200, 9);
  });

  it('крупный вид встаёт туда, где посадки, и не выходит за конец ленты', () => {
    // Лента 1000 м, почти все посадки у восточного конца: центр габаритов пришёлся бы на пустое
    // место посередине.
    const points = [
      { x: 0, y: 0 },
      ...Array.from({ length: 40 }, (_, i) => ({ x: 800 + i * 5, y: 50 })),
      { x: 1000, y: 100 },
    ];
    const ext = extentOf({ rot: 0 }, points, 0);
    const area = { left: 0, top: 0, width: 1000, height: 500 };
    const view = { ...fitView(ext, area, 'close', focusOf({ rot: 0 }, points)), rot: 0 };
    expect(view.scale).toBeCloseTo(2.75, 9);
    // Окно 1000 / 2,75 = 364 м прижато к восточному концу ленты: пустого поля за концом нет.
    expect(toWorld(view, 1000, 250).x).toBeCloseTo(1000, 6);
    expect(toWorld(view, 0, 250).x).toBeCloseTo(1000 - 1000 / 2.75, 6);
    // Поперёк лента помещается целиком и стоит по центру.
    expect(toWorld(view, 500, 250).y).toBeCloseTo(50, 6);
  });

  it('если лента помещается в кадр целиком, крупный вид стоит по её центру', () => {
    const points = [
      { x: 0, y: 0 },
      { x: 90, y: 0 },
      { x: 95, y: 0 },
      { x: 100, y: 80 },
    ];
    const ext = extentOf({ rot: 0 }, points, 0);
    const area = { left: 0, top: 0, width: 1000, height: 500 };
    const view = { ...fitView(ext, area, 'close', focusOf({ rot: 0 }, points)), rot: 0 };
    const middle = toWorld(view, 500, 250);
    expect(middle.x).toBeCloseTo(50, 6);
    expect(middle.y).toBeCloseTo(40, 6);
  });

  it('вид из состава: посадки вне кадра вписываются, все в кадре - вид не двигается', () => {
    const area = { left: 0, top: 0, width: 1000, height: 500 };
    const view = { scale: 2, tx: 0, ty: 400, rot: 0 };
    const inside = [
      { x: 50, y: 50 },
      { x: 150, y: 100 },
    ];
    expect(groupView(view, inside, area)).toBeNull();

    const far = [
      { x: 2000, y: 0 },
      { x: 2100, y: 40 },
    ];
    const target = groupView(view, far, area);
    expect(target).not.toBeNull();
    const shown = { ...view, ...target };
    for (const { x, y } of far) {
      const { sx, sy } = toScreen(shown, x, y);
      expect(sx).toBeGreaterThan(0);
      expect(sx).toBeLessThan(1000);
      expect(sy).toBeGreaterThan(0);
      expect(sy).toBeLessThan(500);
    }
  });

  it('одна посадка вида не раздувается на весь экран', () => {
    const area = { left: 0, top: 0, width: 1000, height: 500 };
    const view = { scale: 0.5, tx: 0, ty: 0, rot: 0 };
    const target = groupView(view, [{ x: 5000, y: 5000 }], area);
    expect(target?.scale).toBe(GROUP_MAX_SCALE);
  });

  it('медиана точек по осям вида', () => {
    const points = [
      { x: 0, y: 0 },
      { x: 10, y: 4 },
      { x: 30, y: 8 },
    ];
    expect(focusOf({ rot: 0 }, points)).toEqual({ u: 10, v: -4 });
    expect(focusOf({ rot: 0 }, [])).toBeNull();
  });

  it('масштаб вокруг точки: точка под курсором остаётся на месте', () => {
    const view = { scale: 2, tx: 50, ty: 70, rot: 0.3 };
    const before = toWorld(view, 400, 300);
    const after = toWorld(zoomAt(view, 400, 300, 1.4), 400, 300);
    expect(after.x).toBeCloseTo(before.x, 9);
    expect(after.y).toBeCloseTo(before.y, 9);
  });

  it('ползунок масштаба логарифмический и обратимый', () => {
    const fit = 2;
    expect(zoomShare(fit * 0.25, fit)).toBeCloseTo(0, 9);
    expect(zoomShare(fit * 64, fit)).toBeCloseTo(1, 9);
    expect(scaleFromShare(zoomShare(7.3, fit), fit)).toBeCloseTo(7.3, 9);
  });
});
