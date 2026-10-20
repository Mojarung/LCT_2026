/* Отрисовка карты на записывающем холсте: кэш подосновы, отметки плана и знаки в углу. */

import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { MaterialLabel, PlantingValue } from '../api/artifacts';
import {
  type CanvasCall,
  fakeContext,
  installCanvas,
  type InstalledCanvas,
  RecordingPath2D,
} from '../test/canvas';
import type { Chunk } from './chunks';
import type { Palette } from './palette';
import {
  type BaseCache,
  CONTEXT_M,
  drawGrid,
  drawNorth,
  drawPending,
  drawPlan,
  drawScaleBar,
  drawSelection,
  type Marks,
  PAD,
  renderBase,
  type Scene,
  uncovered,
} from './render';
import { clearSprites } from './sprites';
import { DEFAULT_LAYERS, type Layers, type MapItem, type ViewState } from './types';

/** Палитра: цвет - имя токена, кроме подмен. */
const palette = (overrides: Record<string, string> = {}) =>
  ({ get: (token: string) => overrides[token] ?? token }) as unknown as Palette;

const view = (scale = 1, tx = 0, ty = 0, rot = 0): ViewState => ({ scale, tx, ty, rot });

let canvas: InstalledCanvas;

beforeEach(() => {
  canvas = installCanvas();
  clearSprites();
});

function item(id: string, x: number, y: number, over: Partial<MapItem> = {}): MapItem {
  return {
    kind: 'placement',
    id,
    number: 1,
    planting_type: 'tree',
    x,
    y,
    radius: 2,
    verdict: 'allowed',
    species_code: 'tilia_cordata',
    explanation: '',
    value: null,
    checks: [],
    ...over,
  };
}

function scene(over: Partial<Scene> = {}): Scene {
  return {
    chunks: [],
    labels: [],
    surface: null,
    existing: [],
    hedges: [],
    placements: [],
    rejections: [],
    focus: null,
    ...over,
  };
}

function marks(over: Partial<Marks> = {}): Marks {
  return {
    layers: DEFAULT_LAYERS,
    speciesOff: new Set(),
    highlight: null,
    selected: null,
    dragging: null,
    dragVerdict: null,
    editing: false,
    ...over,
  };
}

function chunk(over: Partial<Chunk>): Chunk {
  const path = new Path2D();
  return {
    group: 'buildings',
    strokeVar: undefined,
    fillVar: undefined,
    width: 0,
    dash: [],
    texture: undefined,
    shadow: false,
    hedge: false,
    path,
    fillPath: null,
    span: 10,
    minX: 0,
    minY: 0,
    maxX: 10,
    maxY: 10,
    ...over,
  };
}

const layers = (over: Partial<Layers>): Layers => ({ ...DEFAULT_LAYERS, ...over });

/** Команды пути из вызова fill или stroke. */
const opsOf = (call: CanvasCall | undefined) =>
  call?.args[0] instanceof RecordingPath2D ? call.args[0].ops : [];

/** Центры штампов спрайтов: drawImage(канва, sx - half, sy - half, 2 half, 2 half). */
const stamps = (calls: CanvasCall[]) =>
  calls
    .filter((c) => c.name === 'drawImage')
    .map((c) => {
      const [, x, y, w] = c.args as [unknown, number, number, number];
      return [Math.round(x + w / 2), Math.round(y + w / 2)];
    });

describe('кэш подосновы закрывает окно', () => {
  const cache: BaseCache = { ...view(2, 0, 0), dpr: 1, width: 800, height: 600 };

  it('тот же вид или сдвиг в пределах запаса - кэш годен', () => {
    expect(uncovered(cache, view(2, 0, 0), { width: 800, height: 600 })).toBe(false);
    expect(uncovered(cache, view(2, PAD - 1, 0), { width: 800, height: 600 })).toBe(false);
  });

  it('сдвиг дальше запаса или отдаление вдвое - нужна перерисовка', () => {
    expect(uncovered(cache, view(2, PAD + 1, 0), { width: 800, height: 600 })).toBe(true);
    expect(uncovered(cache, view(2, 0, -PAD - 1), { width: 800, height: 600 })).toBe(true);
    expect(uncovered(cache, view(1, 0, 0), { width: 800, height: 600 })).toBe(true);
  });
});

describe('сетка листа', () => {
  it('линии через круглые метры, остаток сдвига приводится к положительному', () => {
    const fake = fakeContext();
    // 1 px/м: шаг niceLength(90) = 50 м = 50 px; сдвиг -10 даёт первую линию на 40.
    drawGrid(fake.ctx, 2, { width: 200, height: 100 }, view(1, -10, 0), palette());
    expect(fake.named('setTransform')[0]?.args).toEqual([2, 0, 0, 2, 0, 0]);
    expect(fake.named('moveTo').map((c) => c.args)).toEqual([
      [40.5, 0],
      [90.5, 0],
      [140.5, 0],
      [190.5, 0],
      [0, 0.5],
      [0, 50.5],
    ]);
    expect(fake.named('stroke')[0]?.state).toMatchObject({ strokeStyle: '--grid', lineWidth: 1 });
  });

  it('вырожденный масштаб - сетки нет', () => {
    const fake = fakeContext();
    drawGrid(fake.ctx, 1, { width: 200, height: 100 }, view(0), palette());
    expect(fake.calls).toEqual([]);
  });
});

describe('масштабная линейка и север', () => {
  const area = { left: 0, top: 0, width: 800, height: 600 };

  it('линейка круглой длины слева от диска севера, подпись в метрах над штрихом', () => {
    const fake = fakeContext();
    drawScaleBar(fake.ctx, area, view(1), palette(), 'Inter');
    // 150 / 1 -> 100 м = 100 px; правый край 800 - 31 - 10 - 31 - 10 - 12 = 706, линия на 566,5.
    const texts = fake.named('fillText');
    expect(texts.map((c) => c.args)).toEqual([['100 м', 656, 559.5]]);
    expect(texts[0]?.state).toMatchObject({ font: '500 12px Inter', fillStyle: '--bone-3' });
    const bar = opsOf(fake.named('stroke')[0]);
    expect(bar.slice(0, 2).map((op) => op.args)).toEqual([
      [606, 566.5],
      [706, 566.5],
    ]);
    // Подложка цвета панели под линейкой, полупрозрачная.
    expect(fake.named('roundRect')[0]?.args).toEqual([594, 541.5, 124, 35, 6]);
    expect(fake.named('fill')[0]?.state).toMatchObject({ fillStyle: '--panel', globalAlpha: 0.8 });
  });

  it('линейка шире половины области не рисуется', () => {
    const fake = fakeContext();
    drawScaleBar(fake.ctx, { ...area, width: 150 }, view(1), palette(), 'Inter');
    expect(fake.calls).toEqual([]);
  });

  it('буква «С» над стрелкой, при развороте вида стрелка поворачивается', () => {
    const north = fakeContext();
    drawNorth(north.ctx, area, view(1), palette(), 'Inter');
    expect(north.named('translate')[0]?.args).toEqual([759, 559]);
    expect(north.named('fillText')[0]?.args).toEqual(['С', 0, -25]);
    const turned = fakeContext();
    drawNorth(turned.ctx, area, view(1, 0, 0, Math.PI / 2), palette(), 'Inter');
    const [, x, y] = turned.named('fillText')[0]?.args as [string, number, number];
    expect(x).toBeCloseTo(25);
    expect(y).toBeCloseTo(0);
  });
});

describe('выбор, перенос и ожидание ответа', () => {
  it('выбранная - кольцо акцента с засечками, перетаскиваемая - цветом живого вердикта', () => {
    const fake = fakeContext();
    const dragged = item('d', 10, 0);
    const chosen = item('s', 0, 0, { radius: 0 });
    drawSelection(
      fake.ctx,
      view(1),
      marks({ dragging: dragged, dragVerdict: 'rejected', selected: chosen }),
      palette(),
    );
    const colors = fake.named('stroke').map((c) => c.state.strokeStyle);
    expect(colors).toEqual([
      '--accent-halo',
      '--bad',
      '--accent-halo',
      '--bad',
      '--accent-halo',
      '--accent',
      '--accent-halo',
      '--accent',
    ]);
    // Радиус кольца не меньше 9 px и плюс 4.
    expect(fake.named('arc').map((c) => c.args.slice(0, 3))).toEqual([
      [10, 0, 13],
      [0, 0, 13],
    ]);
  });

  it('вердикт без цвета у перетаскиваемой - цвет акцента', () => {
    const fake = fakeContext();
    drawSelection(fake.ctx, view(1), marks({ dragging: item('d', 0, 0) }), palette());
    expect(fake.named('stroke')[1]?.state.strokeStyle).toBe('--accent');
  });

  it('кольцо ожидания - пунктир шагом 11 вокруг каждой посадки', () => {
    const fake = fakeContext();
    drawPending(fake.ctx, view(10), [item('a', 0, 0), item('b', 1, 0)], palette(), 3);
    expect(fake.named('arc').map((c) => c.args.slice(0, 3))).toEqual([
      [0, 0, 32],
      [10, 0, 32],
    ]);
    const strokes = fake.named('stroke');
    expect(strokes[0]?.state).toMatchObject({ lineDash: [6, 5], lineWidth: 4.5 });
    expect(strokes[1]?.state).toMatchObject({ strokeStyle: '--bone-3', lineWidth: 2 });
  });
});

describe('отметки плана', () => {
  it('отказ - косой крест в мировых координатах, барьер - двойное кольцо', () => {
    const fake = fakeContext();
    const rejection = item('r', 5, 5, { kind: 'rejection', barrier_m: 1 });
    const off = item('far', 5000, 0, { kind: 'rejection', barrier_m: 1 });
    drawPlan(
      fake.ctx,
      [0, 0, 100, 100],
      view(1),
      scene({ rejections: [rejection, off] }),
      marks({ layers: layers({ rejections: true, barrier: true, placements: false }) }),
      palette(),
      1,
    );
    const [cross, barrier] = fake.named('stroke');
    expect(cross?.state).toMatchObject({ strokeStyle: '--bad', lineWidth: 1 });
    // Крест 3 px на экране: при 1 px/м - 3 м от центра в каждую сторону; дальний отказ отсечён.
    expect(opsOf(cross).map((op) => op.args)).toEqual([
      [2, 2],
      [8, 8],
      [2, 8],
      [8, 2],
    ]);
    expect(barrier?.state).toMatchObject({ strokeStyle: '--warn', lineWidth: 1.4 });
    const rings = opsOf(barrier).filter((op) => op.name === 'arc');
    expect(rings.map((op) => op.args.slice(0, 3))).toEqual([
      [5, 5, 6],
      [5, 5, 6 * 0.55],
    ]);
  });

  it('кроны моделей: приглушённые виды первыми, подсвеченный вид поверх', () => {
    const fake = fakeContext();
    const lime = item('lime', 10, 0, { species_code: 'tilia_cordata' });
    const oak = item('oak', 20, 0, { species_code: 'quercus_robur' });
    drawPlan(
      fake.ctx,
      [-100, -100, 100, 100],
      view(4, 100, 100),
      scene({ placements: [lime, oak] }),
      marks({ highlight: 'tilia_cordata' }),
      palette(),
      1,
      'illustrated',
    );
    // Экран: x = 4 * x + 100, y = 100 - 4 * y.
    expect(stamps(fake.calls)).toEqual([
      [180, 100],
      [140, 100],
    ]);
  });

  it('скрытый вид не рисуется, а на согласовании - янтарное пунктирное кольцо поверх кроны', () => {
    const fake = fakeContext();
    const hidden = item('h', 0, 0, { species_code: 'acer_negundo' });
    const approval = item('a', 10, 0, { verdict: 'needs_approval' });
    drawPlan(
      fake.ctx,
      [-100, -100, 100, 100],
      view(4, 100, 100),
      scene({ placements: [hidden, approval] }),
      marks({ speciesOff: new Set(['acer_negundo']) }),
      palette(),
      1,
      'illustrated',
    );
    expect(stamps(fake.calls)).toEqual([[140, 100]]);
    const [halo, ring] = fake.named('stroke');
    expect(halo?.state).toMatchObject({ strokeStyle: '--accent-halo', lineDash: [4, 3] });
    expect(ring?.state.strokeStyle).toBe('--warn');
    // Радиус кроны 2 м при 4 px/м - 8 px, кольцо на 3 px дальше.
    expect(
      opsOf(ring)
        .find((op) => op.name === 'arc')
        ?.args.slice(0, 3),
    ).toEqual([140, 100, 11]);
  });

  it('в режиме правки выбранная и перетаскиваемая ложатся последними, поверх соседок', () => {
    const fake = fakeContext();
    const chosen = item('s', 0, 0);
    const other = item('o', 10, 0);
    drawPlan(
      fake.ctx,
      [-100, -100, 100, 100],
      view(4, 100, 100),
      scene({ placements: [chosen, other] }),
      marks({ editing: true, selected: chosen }),
      palette(),
      1,
      'illustrated',
    );
    expect(stamps(fake.calls)).toEqual([
      [140, 100],
      [100, 100],
    ]);
  });

  it('в стиле чертежа посадки - знаками, кольцо вердикта то же', () => {
    const fake = fakeContext();
    drawPlan(
      fake.ctx,
      [-100, -100, 100, 100],
      view(4, 100, 100),
      scene({ placements: [item('a', 10, 0, { verdict: 'forbidden' })] }),
      marks(),
      palette(),
      1,
      'engineering',
    );
    const strokes = fake.named('stroke');
    expect(strokes.at(-1)?.state.strokeStyle).toBe('--bad');
    expect(strokes.at(-2)?.state.strokeStyle).toBe('--accent-halo');
  });

  it('слабое место - треугольник над кроной, только у посадки с флагом', () => {
    const fake = fakeContext();
    const weak = item('w', 0, 0, { value: { flagged: true } as PlantingValue });
    const fine = item('f', 10, 0, { value: { flagged: false } as PlantingValue });
    drawPlan(
      fake.ctx,
      [-100, -100, 100, 100],
      view(1),
      scene({ placements: [weak, fine] }),
      marks({ layers: layers({ weak: true }) }),
      palette(),
      1,
      'illustrated',
    );
    const fill = fake.named('fill').at(-1);
    expect(fill?.state.fillStyle).toBe('--bone');
    const triangle = opsOf(fill);
    expect(triangle.map((op) => op.name)).toEqual(['moveTo', 'lineTo', 'lineTo', 'closePath']);
    // Над кроной: радиус max(2, 4 / 1) = 4, плюс 4,5 * 1,6, вершина ещё на 4,5 выше.
    expect(triangle[0]?.args).toEqual([0, 4 + 4.5 * 1.6 - 4.5]);
  });
});

describe('кэш подосновы', () => {
  const rect = { width: 100, height: 50 };

  function base() {
    const target = document.createElement('canvas');
    const mask = document.createElement('canvas');
    return { target, mask, fake: () => canvas.of(target), maskFake: () => canvas.of(mask) };
  }

  it('холст с запасом PAD по краям, заливка, обводка и пунктир кусков подосновы', () => {
    const { target, mask, fake } = base();
    const building = chunk({
      fillVar: '--c-building-fill',
      strokeVar: '--c-building',
      width: 1.3,
      texture: 'hatch',
      shadow: true,
      fillPath: new Path2D(),
    });
    const water = chunk({ group: 'utilities', strokeVar: '--c-water', width: 2, dash: [4, 2] });
    const hiddenZone = chunk({ group: 'zones', fillVar: '--c-zone', fillPath: new Path2D() });
    const tiny = chunk({ strokeVar: '--c-building', width: 1, span: 0.5 });
    const far = chunk({ strokeVar: '--c-building', width: 1, minX: 5000, maxX: 5010 });
    const cache = renderBase(
      target,
      mask,
      rect,
      1,
      view(2),
      scene({ chunks: [building, water, hiddenZone, tiny, far] }),
      DEFAULT_LAYERS,
      palette({ '--utility-opacity': '0.5' }),
    );
    expect(cache).toMatchObject({ scale: 2, dpr: 1, width: 100, height: 50 });
    expect([target.width, target.height]).toEqual([100 + PAD * 2, 50 + PAD * 2]);
    const calls = fake()?.calls ?? [];
    const fills = calls.filter((c) => c.name === 'fill');
    // Тень здания отдельным проходом, затем заливка цветом и фактурой штриховки.
    expect(
      fills.map((c) => (typeof c.state.fillStyle === 'string' ? c.state.fillStyle : 'узор')),
    ).toEqual(['--c-shadow', '--c-building-fill', 'узор']);
    const shadowMatrix = calls.filter((c) => c.name === 'setTransform')[2]?.args;
    expect(shadowMatrix?.slice(4)).toEqual([PAD + 4, PAD + 4]);
    const strokes = calls.filter((c) => c.name === 'stroke');
    expect(
      strokes.map((c) => [c.state.strokeStyle, c.state.lineWidth, c.state.globalAlpha]),
    ).toEqual([
      ['--c-building', 0.65, 1],
      ['--c-water', 1, 0.5],
    ]);
    // Пунктир в экранных пикселях: делится на масштаб и снимается после обводки.
    expect(strokes[1]?.state.lineDash).toEqual([2, 1]);
    expect(calls.filter((c) => c.name === 'setLineDash').at(-1)?.args).toEqual([[]]);
  });

  it('в стиле чертежа нет теней и фактур', () => {
    const { target, mask, fake } = base();
    const building = chunk({
      fillVar: '--c-building-fill',
      texture: 'hatch',
      shadow: true,
      fillPath: new Path2D(),
    });
    renderBase(
      target,
      mask,
      rect,
      1,
      view(2),
      scene({ chunks: [building] }),
      DEFAULT_LAYERS,
      palette(),
      'engineering',
    );
    expect(
      fake()
        ?.named('fill')
        .map((c) => c.state.fillStyle),
    ).toEqual(['--c-building-fill']);
  });

  it('карта покрытий без масок ложится растром на свои метры', () => {
    const { target, mask, fake } = base();
    const img = document.createElement('canvas');
    const surface = { img, x: 1, y: 2, w: 3, h: 4, soil: null, paved: null };
    renderBase(target, mask, rect, 1, view(2), scene({ surface }), DEFAULT_LAYERS, palette());
    expect(fake()?.named('drawImage')[0]?.args).toEqual([img, 1, 2, 3, 4]);
    // Слой карты покрытий выключен - растра нет.
    const off = base();
    renderBase(
      off.target,
      off.mask,
      rect,
      1,
      view(2),
      scene({ surface }),
      layers({ surfacemap: false }),
      palette(),
    );
    expect(off.fake()?.named('drawImage')).toEqual([]);
  });

  it('с масками в стиле чертежа грунт и асфальт - плоскими цветами темы', () => {
    const { target, mask, fake } = base();
    const surface = {
      img: document.createElement('canvas'),
      x: 0,
      y: 0,
      w: 10,
      h: 10,
      soil: document.createElement('canvas'),
      paved: document.createElement('canvas'),
    };
    renderBase(
      target,
      mask,
      rect,
      1,
      view(2),
      scene({ surface }),
      DEFAULT_LAYERS,
      palette(),
      'engineering',
    );
    const scratch = canvas.contexts.find(
      (c) =>
        c !== fake() &&
        c.named('fillRect').some((f) => f.state.globalCompositeOperation === 'source-in'),
    );
    const colors = scratch
      ?.named('fillRect')
      .filter((f) => f.state.globalCompositeOperation === 'source-in');
    expect(colors?.map((c) => c.state.fillStyle)).toEqual(['--c-asphalt', '--c-lawn-fill']);
    // Слой каждого покрытия ложится на подоснову целиком.
    expect(fake()?.named('drawImage')).toHaveLength(2);
  });

  it('подписи материала - с 5 px/м, вторая подпись в занятой клетке не рисуется', () => {
    const labels: MaterialLabel[] = [
      [0, 0, 'А', 'asphalt'],
      [0.2, 0, 'Б', 'asphalt'],
      [20, 0, 'ГАЗОН', 'lawn'],
    ];
    const near = base();
    renderBase(
      near.target,
      near.mask,
      rect,
      1,
      view(5),
      scene({ labels }),
      DEFAULT_LAYERS,
      palette(),
    );
    expect(near.fake()?.texts()).toEqual(['А', 'ГАЗОН']);
    expect(near.fake()?.named('fillText')[1]?.args).toEqual(['ГАЗОН', 100, 0]);
    const far = base();
    renderBase(
      far.target,
      far.mask,
      rect,
      1,
      view(4),
      scene({ labels }),
      DEFAULT_LAYERS,
      palette(),
    );
    expect(far.fake()?.texts()).toEqual([]);
  });

  it('существующие деревья - бледными кронами моделей, не мельче 4 px', () => {
    const { target, mask, fake } = base();
    const existing = [
      { x: 0, y: 0, r: 0.1, shrub: false },
      { x: 10, y: 0, r: 0.1, shrub: true },
      { x: 9000, y: 0, r: 1, shrub: false },
    ];
    renderBase(target, mask, rect, 1, view(1), scene({ existing }), DEFAULT_LAYERS, palette());
    const drawn = fake()?.named('drawImage') ?? [];
    expect(drawn).toHaveLength(2);
    const [, x, , w] = drawn[0]?.args as [unknown, number, number, number];
    expect(x + w / 2).toBeCloseTo(0);
  });

  it('за границей работ подоснова бледнеет: маска вычитается из кэша', () => {
    const { target, mask, fake, maskFake } = base();
    renderBase(
      target,
      mask,
      rect,
      1,
      view(1),
      scene({ focus: new Path2D() }),
      DEFAULT_LAYERS,
      palette(),
    );
    // Маска в половинном разрешении.
    expect([mask.width, mask.height]).toEqual([310, 285]);
    const m = maskFake();
    expect(m?.named('fillRect')[0]?.state.fillStyle).toBe('rgba(0, 0, 0, 0.7)');
    expect(m?.named('stroke')[0]?.state).toMatchObject({
      lineWidth: CONTEXT_M * 2,
      globalCompositeOperation: 'destination-out',
    });
    const cut = fake()?.named('drawImage').at(-1);
    expect(cut?.args).toEqual([mask, 0, 0, 620, 570]);
    expect(cut?.state.globalCompositeOperation).toBe('destination-out');
  });

  it('без контекста холста кэш пустой, но с размером вида', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    const { target, mask } = base();
    expect(renderBase(target, mask, rect, 2, view(3), scene(), DEFAULT_LAYERS, palette())).toEqual({
      ...view(3),
      dpr: 2,
      width: 100,
      height: 50,
    });
  });
});
