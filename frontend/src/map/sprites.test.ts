import { beforeEach, describe, expect, it, vi } from 'vitest';

import { fakeContext, installCanvas, RecordingPath2D, type InstalledCanvas } from '../test/canvas';
import type { PlantModel } from './models';
import { clearSprites, quantize, shade, sprite, stamp, XRAY_TRUNK_PX } from './sprites';

const INK = '#2d2a22';
const EXISTING_INK = '#8a866d';
const TRUNK = '#4a3527';
const SHADOW = 'rgba(62, 66, 40, 0.28)';
const HALO = '#fbf7ec';

const LINDEN: PlantModel = { form: 'broadleaf', tone: '#808080', lobes: 9 };

let canvas: InstalledCanvas;

beforeEach(() => {
  canvas = installCanvas();
  clearSprites();
});

function drawn(s: { canvas: HTMLCanvasElement }) {
  const fake = canvas.of(s.canvas);
  if (!fake) throw new Error('у спрайта не просили контекст');
  return fake;
}

describe('ступени радиуса спрайта', () => {
  it('радиус округляется до четверти октавы, мелкий - до одного пикселя', () => {
    expect(quantize(16)).toBe(16);
    expect(quantize(10)).toBeCloseTo(2 ** 3.25);
    // 10 и 10,3 - одна ступень: спрайт не перерисовывается на каждом кадре зума.
    expect(quantize(10.3)).toBe(quantize(10));
    expect(quantize(12)).not.toBe(quantize(10));
    expect(quantize(0.3)).toBe(1);
  });
});

describe('кэш спрайтов', () => {
  it('тот же вид, ступень, состояние и плотность - тот же спрайт; другое состояние - новый', () => {
    const a = sprite('tilia', LINDEN, 16, 'plan', 1);
    expect(sprite('tilia', LINDEN, 16.2, 'plan', 1)).toBe(a);
    expect(sprite('tilia', LINDEN, 16, 'dim', 1)).not.toBe(a);
    expect(sprite('tilia', LINDEN, 16, 'plan', 2)).not.toBe(a);
    clearSprites();
    expect(sprite('tilia', LINDEN, 16, 'plan', 1)).not.toBe(a);
  });

  it('переполненный кэш начинается заново', () => {
    const first = sprite('k0', LINDEN, 2, 'dim', 1);
    for (let i = 1; i < 900; i++) sprite(`k${String(i)}`, LINDEN, 2, 'dim', 1);
    expect(sprite('k0', LINDEN, 2, 'dim', 1)).toBe(first);
    sprite('k900', LINDEN, 2, 'dim', 1);
    expect(sprite('k0', LINDEN, 2, 'dim', 1)).not.toBe(first);
  });
});

describe('размер спрайта', () => {
  it('сторона - крона с запасом на тень и кайму, в пикселях устройства', () => {
    // r = 16: тень max(1.5, 16 * 0.12) = 1.92, половина ceil(17.6 + 1.92 + 3) = 23.
    const plan = sprite('tilia', LINDEN, 16, 'plan', 2);
    expect(plan.radius).toBe(16);
    expect(plan.half).toBe(23);
    expect(plan.canvas.width).toBe(92);
    expect(plan.canvas.height).toBe(92);
    // Подсвеченный - шире на кайму, приглушённый - без тени.
    expect(sprite('tilia', LINDEN, 16, 'lift', 1).half).toBe(26);
    expect(sprite('tilia', LINDEN, 16, 'dim', 1).half).toBe(21);
    const fake = drawn(plan);
    expect(fake.named('scale')[0]?.args).toEqual([2, 2]);
    expect(fake.named('translate')[0]?.args).toEqual([23, 23]);
  });

  it('без контекста холста спрайт остаётся пустым, но с размером', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    const s = sprite('tilia', LINDEN, 16, 'plan', 1);
    expect(s.half).toBe(23);
    expect(canvas.of(s.canvas)).toBeUndefined();
  });
});

describe('рисунок кроны по состоянию', () => {
  it('план: тень вниз-вправо, заливка тоном, блик, обводка чернилами и ствол', () => {
    const fake = drawn(sprite('tilia', LINDEN, 16, 'plan', 1));
    const fills = fake.named('fill');
    // Первая заливка - тень контура, сдвинутая на 1.92 вниз-вправо.
    expect(fills[0]?.state.fillStyle).toBe(SHADOW);
    expect(fake.named('translate')[1]?.args[0]).toBeCloseTo(1.92);
    expect(fills[0]?.args[0]).toBeInstanceOf(RecordingPath2D);
    // Крона: тот же контур тоном модели без прозрачности.
    expect(fills[1]?.state.fillStyle).toBe('#808080');
    expect(fills[1]?.state.globalAlpha).toBe(1);
    expect(fills[1]?.args[0]).toBe(fills[0]?.args[0]);
    // Блик сверху слева светлее тона.
    const ellipse = fake.named('ellipse')[0];
    expect(ellipse?.args.slice(0, 4).map((v) => Number(v))).toEqual([
      -16 * 0.28,
      -16 * 0.3,
      16 * 0.5,
      16 * 0.4,
    ]);
    expect(fills[2]?.state.fillStyle).toBe(shade('#808080', 0.2));
    expect(fills[2]?.state.globalAlpha).toBe(0.55);
    // Обводка чернилами толщиной r / 14.
    const strokes = fake.named('stroke');
    expect(strokes[0]?.state.strokeStyle).toBe(INK);
    expect(strokes[0]?.state.lineWidth).toBeCloseTo(16 / 14);
    // Ствол в центре.
    const trunk = fills.at(-1);
    expect(trunk?.state.fillStyle).toBe(TRUNK);
    expect(fake.named('arc').at(-1)?.args.slice(0, 3)).toEqual([0, 0, 1.28]);
  });

  it('облако лиственного: одна опора и одна дуга на лопасть', () => {
    const fake = drawn(sprite('tilia', LINDEN, 16, 'plan', 1));
    const outline = fake.named('fill')[1]?.args[0] as RecordingPath2D;
    const names = outline.ops.map((op) => op.name);
    expect(names[0]).toBe('moveTo');
    expect(names.filter((n) => n === 'quadraticCurveTo')).toHaveLength(9);
    expect(names.at(-1)).toBe('closePath');
  });

  it('рисунок кроны зависит от вида и повторяется от кадра к кадру', () => {
    const ops = (key: string) => {
      clearSprites();
      const fake = drawn(sprite(key, LINDEN, 16, 'dim', 1));
      return (fake.named('fill')[0]?.args[0] as RecordingPath2D).ops;
    };
    expect(ops('tilia')).toEqual(ops('tilia'));
    expect(ops('tilia')).not.toEqual(ops('acer'));
  });

  it('подсвеченный вид обведён светлой каймой до заливки и толще обычного', () => {
    const fake = drawn(sprite('tilia', LINDEN, 16, 'lift', 1));
    const [halo, ink] = fake.named('stroke');
    expect(halo?.state.strokeStyle).toBe(HALO);
    expect(halo?.state.lineWidth).toBeCloseTo(16 / 14 + 5);
    expect(ink?.state.lineWidth).toBeCloseTo(16 / 14 + 0.8);
    const order = fake.calls.map((c) => c.name);
    expect(order.indexOf('stroke')).toBeLessThan(order.lastIndexOf('fill'));
  });

  it('приглушённый: без тени и блика, заливка и обводка полупрозрачные', () => {
    const fake = drawn(sprite('tilia', LINDEN, 16, 'dim', 1));
    expect(fake.named('clip')).toHaveLength(0);
    const [crown, trunk] = fake.named('fill');
    expect(crown?.state.fillStyle).toBe('#808080');
    expect(crown?.state.globalAlpha).toBe(0.34);
    expect(fake.named('stroke')[0]?.state.globalAlpha).toBe(0.4);
    expect(trunk?.state.globalAlpha).toBe(0.4);
  });

  it('существующее дерево: бледные чернила тоньше и крестик съёмки вместо ствола', () => {
    const fake = drawn(sprite('old', LINDEN, 16, 'existing', 1));
    const strokes = fake.named('stroke');
    expect(strokes[0]?.state.strokeStyle).toBe(EXISTING_INK);
    expect(strokes[0]?.state.lineWidth).toBe(1);
    expect(fake.named('fill')[0]?.state.globalAlpha).toBe(0.9);
    // Крестик: две черты с плечом max(1.6, 16 * 0.22).
    const arm = 16 * 0.22;
    expect(fake.named('moveTo').map((c) => c.args)).toEqual([
      [-arm, 0],
      [0, -arm],
    ]);
    expect(fake.named('lineTo').map((c) => c.args)).toEqual([
      [arm, 0],
      [0, arm],
    ]);
    expect(fake.named('arc')).toHaveLength(0);
  });

  it('режим правки: крона почти прозрачная, ствол крупной точкой с каймой', () => {
    const fake = drawn(sprite('tilia', LINDEN, 16, 'xray', 1));
    const [crown, trunk] = fake.named('fill');
    expect(crown?.state.globalAlpha).toBe(0.25);
    expect(trunk?.state.fillStyle).toBe(INK);
    expect(trunk?.state.globalAlpha).toBe(1);
    expect(fake.named('arc')[0]?.args.slice(0, 3)).toEqual([0, 0, XRAY_TRUNK_PX]);
    const strokes = fake.named('stroke');
    expect(strokes[0]?.state.globalAlpha).toBe(0.65);
    expect(strokes.at(-1)?.state.strokeStyle).toBe(HALO);
  });
});

describe('формы моделей', () => {
  it.each([
    ['conifer', 12],
    ['dwarf_conifer', 10],
    ['creeper', 8],
  ] as const)('%s - звезда из %i лучей с внутренней звездой темнее', (form, lobes) => {
    const fake = drawn(sprite(form, { form, tone: '#808080', lobes }, 16, 'plan', 1));
    const outline = fake.named('fill')[1]?.args[0] as RecordingPath2D;
    expect(outline.ops.filter((op) => op.name === 'moveTo')).toHaveLength(1);
    expect(outline.ops.filter((op) => op.name === 'lineTo')).toHaveLength(lobes * 2 - 1);
    // Внутренняя звезда - светлее тона, без блика-эллипса.
    expect(fake.named('fill')[2]?.state.fillStyle).toBe(shade('#808080', 0.22));
    expect(fake.named('ellipse')).toHaveLength(0);
  });

  it('стелющийся и кустарник - точка чернил в центре, а не ствол', () => {
    for (const form of ['creeper', 'shrub'] as const) {
      clearSprites();
      const fake = drawn(sprite(form, { form, tone: '#808080', lobes: 7 }, 16, 'plan', 1));
      const dot = fake.named('fill').at(-1);
      expect(dot?.state.fillStyle).toBe(INK);
      expect(fake.named('arc').at(-1)?.args[2]).toBeCloseTo(16 * 0.09);
    }
  });

  it.each(['columnar', 'rounded', 'broadleaf'] as const)('%s - облако', (form) => {
    const fake = drawn(sprite(form, { form, tone: '#808080', lobes: 6 }, 4, 'dim', 1));
    const outline = fake.named('fill')[0]?.args[0] as RecordingPath2D;
    expect(outline.ops.filter((op) => op.name === 'quadraticCurveTo')).toHaveLength(6);
  });

  it('плакучее с кроной от 8 px - двенадцать свисающих ветвей темнее тона', () => {
    const model: PlantModel = { form: 'weeping', tone: '#808080', lobes: 9 };
    const fake = drawn(sprite('salix', model, 16, 'plan', 1));
    const branches = fake
      .named('stroke')
      .find((c) => c.state.strokeStyle === shade('#808080', -0.35));
    expect(branches?.state.lineWidth).toBe(0.9);
    // 12 ветвей и ни одной штриховки: крона 16 px меньше 22.
    expect(fake.named('moveTo')).toHaveLength(12);
  });

  it('крупная лиственная крона штрихуется, кустарник и мелкая - нет', () => {
    const hatched = (model: PlantModel, radius: number) => {
      clearSprites();
      const fake = drawn(sprite('k', model, radius, 'plan', 1));
      return fake.named('stroke').some((c) => c.state.strokeStyle === 'rgba(45, 42, 34, 0.2)');
    };
    expect(hatched(LINDEN, 32)).toBe(true);
    expect(hatched(LINDEN, 16)).toBe(false);
    expect(hatched({ form: 'shrub', tone: '#808080', lobes: 7 }, 32)).toBe(false);
  });

  it('цветение - точки цвета цветков: семь на дереве, четыре на кусте', () => {
    const dots = (model: PlantModel) => {
      clearSprites();
      const fake = drawn(sprite('k', model, 16, 'plan', 1));
      return fake.named('fill').filter((c) => c.state.fillStyle === '#ff0000');
    };
    expect(dots({ ...LINDEN, bloom: '#ff0000' })).toHaveLength(7);
    expect(dots({ form: 'shrub', tone: '#808080', lobes: 7, bloom: '#ff0000' })).toHaveLength(4);
  });

  it('крона мельче 5 px - без деталей: ни обрезки, ни блика', () => {
    const fake = drawn(sprite('k', { ...LINDEN, bloom: '#ff0000' }, 4, 'plan', 1));
    expect(fake.named('clip')).toHaveLength(0);
    expect(fake.named('ellipse')).toHaveLength(0);
  });
});

describe('вывод спрайта на карту', () => {
  it('спрайт растягивается под радиус кроны с центром в точке', () => {
    const s = sprite('tilia', LINDEN, 16, 'plan', 1);
    const fake = fakeContext();
    stamp(fake.ctx, s, 100, 50, 32);
    // k = 2: половина стороны 23 -> 46.
    expect(fake.named('drawImage')[0]?.args).toEqual([s.canvas, 54, 4, 92, 92]);
  });
});

describe('оттенок цвета', () => {
  it('светлее - к белому, темнее - к чёрному, с отсечкой', () => {
    expect(shade('#808080', 0.5)).toBe('rgb(192, 192, 192)');
    expect(shade('#808080', -0.5)).toBe('rgb(64, 64, 64)');
    expect(shade('#ff0000', 0)).toBe('rgb(255, 0, 0)');
    expect(shade('#123456', 1)).toBe('rgb(255, 255, 255)');
    expect(shade('#123456', -1)).toBe('rgb(0, 0, 0)');
  });
});
