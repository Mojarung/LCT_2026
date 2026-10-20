/* Общие знаки инженерного стиля: файл знаков шаблона не загружен, поэтому каждое дерево - яма и
 * контур кроны, куст - кружок со штриховкой, существующие - кольца «сохраняемое». */

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { type CanvasCall, fakeContext, installCanvas, RecordingPath2D } from '../test/canvas';
import type { ExistingPlant } from './existing';
import type { Box } from './geometry';
import type { Palette } from './palette';
import {
  DIM_ALPHA,
  drawExistingHedges,
  drawExistingSigns,
  drawSignSwatch,
  drawPlanSigns,
  hedgeSignFits,
  RING_INNER_M,
  RING_OUTER_M,
  signInk,
  type SignInk,
} from './signs';
import type { MapItem, ViewState } from './types';

const INK: SignInk = {
  ink: '#111111',
  paper: '#fafafa',
  crown: '#007f00',
  coniferCrown: '#004400',
  coniferRing: '#00aa00',
  halo: '#ffeeaa',
};
const ALL: Box = [-1000, -1000, 1000, 1000];
const view = (scale: number): ViewState => ({ scale, tx: 0, ty: 0, rot: 0 });

function place(
  id: string,
  x: number,
  y: number,
  plantingType = 'tree',
  species: string | undefined = 'tilia_cordata',
  radius = 3,
): MapItem {
  return {
    kind: 'placement',
    id,
    number: 1,
    planting_type: plantingType,
    x,
    y,
    radius,
    verdict: 'allowed',
    species_code: species,
    explanation: '',
    value: null,
    checks: [],
  };
}

/** Команды пути, переданного в fill или stroke. */
const opsOf = (call: CanvasCall | undefined) => {
  const path = call?.args[0];
  if (!(path instanceof RecordingPath2D)) throw new Error('ожидался Path2D');
  return path.ops;
};
const arcs = (call: CanvasCall | undefined) =>
  opsOf(call)
    .filter((op) => op.name === 'arc')
    .map((op) => op.args.slice(0, 3) as number[]);
/** Вызовы, у которых путь непустой: пустые пачки движок тоже обводит, это не знак. */
const drawn = (calls: CanvasCall[]) =>
  calls.filter((c) => c.args[0] instanceof RecordingPath2D && c.args[0].ops.length > 0);

beforeEach(() => {
  installCanvas();
});

describe('посадки общими знаками, пока знаков шаблона нет', () => {
  it('дерево крупным планом - яма r 0,42 м и контур кроны цветом кроны', () => {
    const fake = fakeContext();
    const onItem = vi.fn();
    const tree = place('p1', 5, 2);

    drawPlanSigns(fake.ctx, [tree], ALL, view(10), INK, 1, 'plan', () => true, onItem);

    // Экран: x вправо, y чертежа вверх - вниз на экране.
    expect(onItem).toHaveBeenCalledWith(tree, 50, -20, 30);
    const strokes = drawn(fake.named('stroke'));
    expect(strokes).toHaveLength(1);
    expect(strokes[0]?.state.strokeStyle).toBe(INK.crown);
    expect(strokes[0]?.state.lineWidth).toBe(1);
    expect(arcs(strokes[0])).toEqual([[50, -20, 30]]);
    const pits = drawn(fake.named('fill'));
    expect(pits).toHaveLength(1);
    expect(pits[0]?.state.fillStyle).toBe(INK.ink);
    expect(arcs(pits[0])[0]?.[2]).toBeCloseTo(4.2);
    // Яма - поверх кроны: заливка идёт последней.
    expect(fake.calls.at(-2)?.name).toBe('fill');
    expect(fake.calls.at(-1)?.name).toBe('restore');
  });

  it('хвойное - тёмным контуром с двенадцатью засечками наружу', () => {
    const fake = fakeContext();
    drawPlanSigns(
      fake.ctx,
      [place('p1', 0, 0, 'tree', 'pinus_sylvestris')],
      ALL,
      view(10),
      INK,
      1,
      'plan',
      () => true,
      vi.fn(),
    );

    const strokes = drawn(fake.named('stroke'));
    expect(strokes).toHaveLength(1);
    expect(strokes[0]?.state.strokeStyle).toBe(INK.coniferCrown);
    const ops = opsOf(strokes[0]);
    expect(ops.filter((op) => op.name === 'lineTo')).toHaveLength(12);
    // Засечка от кроны наружу: длина 0,13 радиуса, не больше 5 пикселей.
    const [first] = ops.filter((op) => op.name === 'lineTo');
    expect(first?.args).toEqual([expect.closeTo(33.9), 0]);
  });

  it('на общем виде контура кроны нет, яма не мельче PIT_MIN_PX', () => {
    const fake = fakeContext();
    const onItem = vi.fn();
    const tree = place('p1', 10, 0);

    drawPlanSigns(fake.ctx, [tree], ALL, view(1), INK, 1, 'plan', () => true, onItem);

    expect(drawn(fake.named('stroke'))).toHaveLength(0);
    expect(arcs(drawn(fake.named('fill'))[0])).toEqual([[10, 0, 1.7]]);
    expect(onItem).toHaveBeenCalledWith(tree, 10, 0, 3);
  });

  it('подсвеченный вид: ямы крупнее, с ореолом, контур толще', () => {
    const fake = fakeContext();
    drawPlanSigns(
      fake.ctx,
      [place('p1', 0, 0)],
      ALL,
      view(10),
      INK,
      1,
      'lift',
      () => true,
      vi.fn(),
    );

    const strokes = drawn(fake.named('stroke'));
    expect(strokes.map((c) => [c.state.strokeStyle, c.state.lineWidth])).toEqual([
      [INK.crown, 1.7],
      [INK.halo, 3],
    ]);
    // Ореол ямы - до её заливки.
    const halo = fake.calls.indexOf(strokes[1] as CanvasCall);
    const pit = fake.calls.indexOf(drawn(fake.named('fill'))[0] as CanvasCall);
    expect(halo).toBeLessThan(pit);
  });

  it('на общем виде lift яма не мельче 3,4 пикселя', () => {
    const fake = fakeContext();
    drawPlanSigns(fake.ctx, [place('p1', 0, 0)], ALL, view(1), INK, 1, 'lift', () => true, vi.fn());
    expect(arcs(drawn(fake.named('fill'))[0])[0]?.[2]).toBe(3.4);
  });

  it('вид в тени подсветки другого - с непрозрачностью DIM_ALPHA', () => {
    const fake = fakeContext();
    drawPlanSigns(fake.ctx, [place('p1', 0, 0)], ALL, view(10), INK, 1, 'dim', () => true, vi.fn());

    for (const call of drawn([...fake.named('fill'), ...fake.named('stroke')]))
      expect(call.state.globalAlpha).toBe(DIM_ALPHA);
    // После прохода прозрачность возвращается: проход в save/restore.
    expect(fake.ctx.globalAlpha).toBe(1);
  });

  it('посадка вне видимой области и исключённая проходом не рисуются', () => {
    const fake = fakeContext();
    const onItem = vi.fn();
    const far = place('far', 50, 0);
    const skipped = place('skip', 0, 0);
    const kept = place('kept', 1, 0);

    drawPlanSigns(
      fake.ctx,
      [far, skipped, kept],
      [-10, -10, 10, 10],
      view(10),
      INK,
      1,
      'plan',
      (p) => p !== skipped,
      onItem,
    );

    expect(onItem.mock.calls.map(([p]) => (p as MapItem).id)).toEqual(['kept']);
    expect(arcs(drawn(fake.named('fill'))[0])).toHaveLength(1);
  });
});

describe('одиночный кустарник общим знаком', () => {
  it('крупным планом - кружок листа со штриховкой 45° и обводкой чернилами', () => {
    const fake = fakeContext();
    const onItem = vi.fn();
    const shrub = place('s1', 1, 1, 'shrub', 'cotinus_coggygria', 0.6);

    drawPlanSigns(fake.ctx, [shrub], ALL, view(10), INK, 1, 'plan', () => true, onItem);

    expect(onItem).toHaveBeenCalledWith(shrub, 10, -10, 6);
    const fills = drawn(fake.named('fill'));
    // Лист, штриховка поверх, затем ямы (пустые) не в счёт.
    expect(fills[0]?.state.fillStyle).toBe(INK.paper);
    expect(arcs(fills[0])).toEqual([[10, -10, 4]]);
    const pattern = fills[1]?.state.fillStyle as { repetition: string; setTransform: unknown };
    expect(pattern.repetition).toBe('repeat');
    // Узор приколот к экрану: обратная матрица текущего преобразования.
    expect(pattern.setTransform).toHaveBeenCalled();
    const outline = drawn(fake.named('stroke'));
    expect(outline.map((c) => [c.state.strokeStyle, c.state.lineWidth])).toEqual([[INK.ink, 1]]);
  });

  it('плитка штриховки - диагонали через холст 5x5 при dpr 1', () => {
    const installed = installCanvas();
    const fake = fakeContext();
    // Другой цвет чернил - новая плитка, а не кэш прошлого теста.
    const ink = { ...INK, ink: '#222222' };
    drawPlanSigns(
      fake.ctx,
      [place('s1', 0, 0, 'shrub', undefined, 0.6)],
      ALL,
      view(10),
      ink,
      1,
      'plan',
      () => true,
      vi.fn(),
    );

    const tile = installed.contexts.at(-1);
    expect(tile?.ctx.canvas.width).toBe(5);
    expect(tile?.named('lineTo').map((c) => c.args)).toEqual([
      [0, 0],
      [5, 0],
      [10, 0],
    ]);
    expect(tile?.named('stroke')[0]?.state.strokeStyle).toBe('#222222');
  });

  it('на общем виде - бледная точка чернил, без штриховки', () => {
    const fake = fakeContext();
    drawPlanSigns(
      fake.ctx,
      [place('s1', 0, 0, 'shrub', undefined, 0.6)],
      ALL,
      view(1),
      INK,
      1,
      'dim',
      () => true,
      vi.fn(),
    );

    const [dot] = drawn(fake.named('fill'));
    expect(dot?.state.fillStyle).toBe(INK.ink);
    expect(dot?.state.globalAlpha).toBeCloseTo(DIM_ALPHA * 0.55);
    expect(arcs(dot)[0]?.[2]).toBe(1.2);
    expect(drawn(fake.named('stroke'))).toHaveLength(0);
  });

  it('подсвеченный куст - с ореолом толщиной 4 под кружком', () => {
    const fake = fakeContext();
    drawPlanSigns(
      fake.ctx,
      [place('s1', 0, 0, 'shrub', undefined, 0.1)],
      ALL,
      view(1),
      INK,
      1,
      'lift',
      () => true,
      vi.fn(),
    );

    const strokes = drawn(fake.named('stroke'));
    expect(strokes[0]?.state.strokeStyle).toBe(INK.halo);
    expect(strokes[0]?.state.lineWidth).toBe(4);
    // Мелкий подсвеченный куст не мельче 3,4 пикселя и без штриховки (мельче 3,5).
    expect(arcs(strokes[0])[0]?.[2]).toBe(3.4);
    expect(drawn(fake.named('fill'))).toHaveLength(1);
  });
});

describe('ряд кустарника - полосой живой изгороди', () => {
  const row = (xs: number[], species = 'cotoneaster_lucidus') =>
    xs.map((x, i) => place(`C001-00${String(i)}`, x, 0, 'shrub', species, 0.6));

  it('крупным планом - полоса 0,83 м: чернила, лист, штриховка по одной оси', () => {
    const fake = fakeContext();
    const onItem = vi.fn();
    const shrubs = row([0, 1, 2]);

    drawPlanSigns(fake.ctx, shrubs, ALL, view(10), INK, 1, 'plan', () => true, onItem);

    const strokes = drawn(fake.named('stroke'));
    expect(strokes.map((c) => c.state.lineWidth)).toEqual([
      expect.closeTo(10.3),
      expect.closeTo(8.3),
      expect.closeTo(8.3),
    ]);
    expect(strokes[0]?.state.strokeStyle).toBe(INK.ink);
    expect(strokes[1]?.state.strokeStyle).toBe(INK.paper);
    expect(typeof strokes[2]?.state.strokeStyle).toBe('object');
    expect(opsOf(strokes[0]).map((op) => [op.name, ...op.args])).toEqual([
      ['moveTo', 0, 0],
      ['lineTo', 10, 0],
      ['lineTo', 20, 0],
    ]);
    // Кусты ряда отдельными кружками не рисуются, но кольца вердикта им нужны.
    expect(drawn(fake.named('fill'))).toHaveLength(0);
    expect(onItem).toHaveBeenCalledTimes(3);
    expect(onItem.mock.calls[0]?.[3]).toBe(6);
  });

  it('подсвеченный ряд - с ореолом шире полосы на 6 пикселей', () => {
    const fake = fakeContext();
    drawPlanSigns(fake.ctx, row([0, 1]), ALL, view(10), INK, 1, 'lift', () => true, vi.fn());
    const [halo] = drawn(fake.named('stroke'));
    expect(halo?.state.strokeStyle).toBe(INK.halo);
    expect(halo?.state.lineWidth).toBeCloseTo(14.3);
  });

  it('на общем виде - тонкая линия ряда без листа и штриховки', () => {
    const fake = fakeContext();
    drawPlanSigns(fake.ctx, row([0, 1]), ALL, view(2), INK, 1, 'plan', () => true, vi.fn());
    const strokes = drawn(fake.named('stroke'));
    expect(strokes).toHaveLength(1);
    expect(strokes[0]?.state.strokeStyle).toBe(INK.ink);
    expect(strokes[0]?.state.lineWidth).toBeCloseTo(1.66);
  });

  it('тонкая подсвеченная линия - не тоньше 2,4 пикселя и с ореолом', () => {
    const fake = fakeContext();
    drawPlanSigns(fake.ctx, row([0, 1]), ALL, view(2), INK, 1, 'lift', () => true, vi.fn());
    expect(
      drawn(fake.named('stroke')).map((c) => [c.state.strokeStyle, c.state.lineWidth]),
    ).toEqual([
      [INK.halo, expect.closeTo(5.4)],
      [INK.ink, expect.closeTo(2.4)],
    ]);
  });

  it('разрыв больше 2,6 м и смена вида делят ряд, одиночный остаток - кружком', () => {
    const fake = fakeContext();
    const shrubs = [...row([0, 1, 5]), place('C001-003', 6, 0, 'shrub', 'spiraea_japonica', 0.6)];

    drawPlanSigns(fake.ctx, shrubs, ALL, view(10), INK, 1, 'plan', () => true, vi.fn());

    const [strip] = drawn(fake.named('stroke'));
    // Полоса - только первые два куста; куст в 4 м от соседа и куст другого вида - одиночки.
    expect(opsOf(strip).map((op) => op.name)).toEqual(['moveTo', 'lineTo']);
    const [sheet] = drawn(fake.named('fill'));
    expect(arcs(sheet).map(([x]) => x)).toEqual([50, 60]);
  });

  it('куст ряда вне прохода рвёт полосу', () => {
    const fake = fakeContext();
    const shrubs = row([0, 1, 2]);
    drawPlanSigns(
      fake.ctx,
      shrubs,
      ALL,
      view(10),
      INK,
      1,
      'plan',
      (p) => p.id !== 'C001-001',
      vi.fn(),
    );
    // Полосы нет: остались два одиночных куста.
    expect(arcs(drawn(fake.named('fill'))[0]).map(([x]) => x)).toEqual([0, 20]);
  });
});

describe('существующие насаждения кольцами «сохраняемое»', () => {
  const plant = (x: number, extra: Partial<ExistingPlant> = {}): ExistingPlant => ({
    x,
    y: 0,
    r: 4,
    shrub: false,
    ...extra,
  });

  it('крупным планом - белый круг, двойное кольцо чернилами, у хвойного зелёное кольцо', () => {
    const fake = fakeContext();
    drawExistingSigns(fake.ctx, [plant(0), plant(10, { conifer: true })], ALL, view(20), INK);

    const outer = RING_OUTER_M * 20;
    const [discs] = drawn(fake.named('fill'));
    expect(discs?.state.fillStyle).toBe(INK.paper);
    expect(discs?.state.globalAlpha).toBe(1);
    expect(arcs(discs).map(([, , r]) => r)).toEqual([outer, outer]);
    const [rings, conifers] = drawn(fake.named('stroke'));
    expect(rings?.state.strokeStyle).toBe(INK.ink);
    expect(arcs(rings).map(([, , r]) => r)).toEqual([
      outer,
      expect.closeTo(RING_INNER_M * 20),
      outer,
      expect.closeTo(RING_INNER_M * 20),
    ]);
    expect(conifers?.state.strokeStyle).toBe(INK.coniferRing);
    expect(conifers?.state.lineWidth).toBe(3);
    expect(arcs(conifers)).toEqual([[200, 0, expect.closeTo(outer + 1.5 + 0.4)]]);
  });

  it('кустарник - зубчатый кружок из девяти лопастей', () => {
    const fake = fakeContext();
    drawExistingSigns(fake.ctx, [plant(0, { shrub: true })], ALL, view(20), INK);

    const fills = drawn(fake.named('fill'));
    expect(fills).toHaveLength(1);
    const ops = opsOf(fills[0]);
    expect(ops.filter((op) => op.name === 'arc')).toHaveLength(9);
    expect(ops.at(-1)?.name).toBe('closePath');
    // Лопасть - кружок 0,36 радиуса знака (0,55 м -> 11 px).
    expect(ops[1]?.args[2]).toBeCloseTo(11 * 0.36);
  });

  it('на среднем виде кольцо одно: двойное различимо только с полутора пикселей', () => {
    const fake = fakeContext();
    drawExistingSigns(fake.ctx, [plant(0)], ALL, view(10), INK);
    expect(arcs(drawn(fake.named('stroke'))[0])).toHaveLength(1);
  });

  it('на общем виде кольцо 2,3 пикселя и бледнее', () => {
    const fake = fakeContext();
    drawExistingSigns(
      fake.ctx,
      [plant(0), plant(4, { shrub: true }), plant(9999)],
      ALL,
      view(0.5),
      INK,
    );
    const [discs, scallops] = fake.named('fill');
    expect(discs?.state.globalAlpha).toBe(0.32);
    expect(arcs(discs)).toEqual([[0, 0, 2.3]]);
    // Дерево за пределами видимого не рисуется, куст - зубчатым кружком 2,3 пикселя.
    expect(opsOf(scallops).filter((op) => op.name === 'arc')).toHaveLength(9);
  });
});

describe('живая изгородь съёмки без знака шаблона', () => {
  it('знаком не рисуется: полоса остаётся подоснове', () => {
    expect(hedgeSignFits(view(100))).toBe(false);
    const fake = fakeContext();
    drawExistingHedges(
      fake.ctx,
      [
        [
          [0, 0],
          [10, 0],
        ],
      ],
      ALL,
      view(10),
      INK,
    );
    expect(fake.calls).toEqual([]);
  });
});

describe('образцы знаков для легенды', () => {
  const swatch = (sign: Parameters<typeof drawSignSwatch>[1], alpha?: number) => {
    const fake = fakeContext();
    drawSignSwatch(fake.ctx, sign, 20, INK, 1, alpha);
    return fake;
  };

  it('дерево - контур кроны 0,42 стороны и яма в центре', () => {
    const fake = swatch('tree', 0.5);
    const [crown] = fake.named('stroke');
    expect(crown?.state.strokeStyle).toBe(INK.crown);
    expect(crown?.state.globalAlpha).toBe(0.5);
    expect(arcs(crown)).toEqual([[10, 10, expect.closeTo(8.4)]]);
    expect(fake.named('arc')[0]?.args.slice(0, 3)).toEqual([10, 10, expect.closeTo(2.6)]);
    expect(fake.named('fill')[0]?.state.fillStyle).toBe(INK.ink);
  });

  it('хвойное - контур 0,34 стороны с засечками', () => {
    const [crown] = swatch('conifer').named('stroke');
    expect(crown?.state.strokeStyle).toBe(INK.coniferCrown);
    expect(arcs(crown)[0]?.[2]).toBeCloseTo(6.8);
    expect(opsOf(crown).filter((op) => op.name === 'lineTo')).toHaveLength(12);
  });

  it('кустарник - лист, штриховка и обводка', () => {
    const fake = swatch('shrub');
    const fills = fake.named('fill');
    expect(fills[0]?.state.fillStyle).toBe(INK.paper);
    expect(typeof fills[1]?.state.fillStyle).toBe('object');
    expect(arcs(fills[0])).toEqual([[10, 10, expect.closeTo(6)]]);
    expect(fake.named('stroke')[0]?.state.strokeStyle).toBe(INK.ink);
  });

  it('изгородь - диагональ: чернила шире листа на 2, штриховка поверх', () => {
    const strokes = swatch('hedge').named('stroke');
    expect(strokes.map((c) => c.state.lineWidth)).toEqual([8, 6, 6]);
    expect(strokes[0]?.state.strokeStyle).toBe(INK.ink);
    expect(strokes[1]?.state.strokeStyle).toBe(INK.paper);
    expect(opsOf(strokes[0]).map((op) => op.args)).toEqual([
      [expect.closeTo(4), expect.closeTo(12.4)],
      [expect.closeTo(16), expect.closeTo(7.6)],
    ]);
  });

  it('существующее дерево - белый круг и два кольца, хвойное - плюс зелёное', () => {
    const tree = swatch('existing-tree');
    expect(tree.named('fill')[0]?.state.fillStyle).toBe(INK.paper);
    expect(arcs(tree.named('stroke')[0])).toEqual([
      [10, 10, 6],
      [10, 10, expect.closeTo(6 * (RING_INNER_M / RING_OUTER_M) - 0.6)],
    ]);
    expect(tree.named('stroke')).toHaveLength(1);

    const conifer = swatch('existing-conifer');
    const ring = conifer.named('stroke')[1];
    expect(ring?.state.strokeStyle).toBe(INK.coniferRing);
    expect(ring?.state.lineWidth).toBe(2.2);
    expect(conifer.named('arc').at(-1)?.args.slice(0, 3)).toEqual([10, 10, 7.6]);
  });

  it.each(['existing-shrub', 'existing-hedge'] as const)(
    '%s - зубчатый кружок листа с обводкой',
    (sign) => {
      const fake = swatch(sign);
      expect(opsOf(fake.named('fill')[0]).filter((op) => op.name === 'arc')).toHaveLength(9);
      expect(fake.named('fill')[0]?.state.fillStyle).toBe(INK.paper);
      expect(fake.named('stroke')[0]?.state.strokeStyle).toBe(INK.ink);
    },
  );
});

describe('чернила знаков из токенов темы', () => {
  it('каждое поле - свой токен --sign-*', () => {
    const palette = { get: (token: string) => `value${token}` } as unknown as Palette;
    expect(signInk(palette)).toEqual({
      ink: 'value--sign-ink',
      paper: 'value--sign-paper',
      crown: 'value--sign-crown',
      coniferCrown: 'value--sign-crown-conifer',
      coniferRing: 'value--sign-conifer',
      halo: 'value--accent-halo',
    });
  });
});
