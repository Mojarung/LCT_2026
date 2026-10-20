import { describe, expect, it } from 'vitest';

import type { SourceConflict } from '../api/artifacts';
import { fakeContext } from '../test/canvas';
import { drawSourceConflicts } from './sourceConflicts';
import type { ViewState } from './types';

const conflict = (id: string, x: number, y: number): SourceConflict => ({
  id,
  x,
  y,
  tree_refs: [],
  targets: [],
});

// Север сверху, 10 пикселей на метр, начало чертежа в (100, 200) экрана.
const view: ViewState = { scale: 10, tx: 100, ty: 200, rot: 0 };

describe('отметки конфликтов исходника', () => {
  it('кольцо в точке конфликта и номер по порядку в кружке справа сверху', () => {
    const fake = fakeContext();
    drawSourceConflicts(
      fake.ctx,
      view,
      [conflict('a', 0, 0), conflict('b', 5, -3)],
      null,
      800,
      600,
    );
    const arcs = fake.named('arc').map((c) => c.args.slice(0, 3));
    // Радиус кольца - масштаб в пределах 14..42: при 10 пикселях на метр - нижняя граница 14.
    expect(arcs).toEqual([
      [100, 200, 14],
      [114, 186, 11],
      [150, 230, 14],
      [164, 216, 11],
    ]);
    expect(fake.texts()).toEqual(['1', '2']);
    const texts = fake.named('fillText');
    expect(texts[1]?.args.slice(1)).toEqual([164, 216]);
    expect(texts[0]?.state).toMatchObject({
      fillStyle: '#ffffff',
      font: 'bold 12px sans-serif',
      textAlign: 'center',
      textBaseline: 'middle',
    });
    // Кисть возвращается: отметки рисуются между save и restore.
    expect(fake.calls[0]?.name).toBe('save');
    expect(fake.calls.at(-1)?.name).toBe('restore');
  });

  it('выбранный конфликт обведён толще, кольцо растёт с масштабом до 42', () => {
    const fake = fakeContext();
    drawSourceConflicts(
      fake.ctx,
      { ...view, scale: 100 },
      [conflict('a', 0, 0), conflict('b', 1, 0)],
      'b',
      800,
      600,
    );
    const widths = fake.named('stroke').map((c) => [c.state.strokeStyle, c.state.lineWidth]);
    expect(widths).toEqual([
      ['#fff9e9', 5],
      ['#ac3e08', 2],
      ['#fff9e9', 7],
      ['#ac3e08', 4],
    ]);
    expect(fake.named('arc')[0]?.args[2]).toBe(42);
  });

  it('конфликт дальше 60 пикселей за краем холста не рисуется, а номер у следующего свой', () => {
    const fake = fakeContext();
    drawSourceConflicts(
      fake.ctx,
      view,
      [conflict('far', -100, 0), conflict('near', 0, 0)],
      null,
      800,
      600,
    );
    expect(fake.named('arc')).toHaveLength(2);
    expect(fake.texts()).toEqual(['2']);
  });
});
