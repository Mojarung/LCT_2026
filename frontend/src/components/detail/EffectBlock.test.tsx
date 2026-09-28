import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { EffectJson } from '../../api/artifacts';
import { EffectBlock } from './EffectBlock';

const measure = (
  key: string,
  title: string,
  unit: string,
  before: number | null,
  after: number | null,
  note = '',
) => ({
  key,
  title,
  unit,
  before,
  after,
  delta: null,
  basis: 'основание',
  kind: 'requirement',
  note,
});

const effect: EffectJson = {
  stock_source: 'marks',
  area_m2: 1000,
  curb_m: 500,
  length_m: 400,
  measures: [
    measure('trees', 'Деревья', 'шт.', null, null, 'по чертежу число деревьев не определяется'),
    measure('canopy_share', 'Тень: площадь взрослых крон, доля', '%', 25.2, 26.2),
    measure(
      'curb_green_share',
      'Пылезащита: борта под кронами и нижним ярусом, доля',
      '%',
      32.4,
      37.7,
    ),
    measure('tiers_trees', 'Ярусность: деревья с кустарником под кроной', 'шт.', 0, 200),
    measure('noise_curb_m', 'Шумозащита: борта с полосой насаждений от 10 м', 'м', 1200, 1937),
  ],
  kinds: [
    {
      key: 'curb_hedge',
      title: 'Живая изгородь вдоль борта',
      planting_type: 'shrub',
      count: 743,
      length_m: 743,
      area_m2: null,
      basis: '743-ПП, п. 2.1.13(1)',
      places: {},
    },
  ],
  noise: [],
  notes: [],
};

describe('EffectBlock', () => {
  it('shows before and after for the street and the planting kinds', () => {
    render(<EffectBlock effect={effect} />);

    expect(screen.getByRole('heading', { name: 'Было → стало' })).toBeVisible();
    const rows = within(screen.getByRole('list', { name: 'Что план даёт улице' }));
    // В строке - слово до двоеточия, расшифровка - для диктора и в подсказке.
    expect(rows.getByText('Пылезащита')).toBeVisible();
    expect(rows.getByText(': борта под кронами и нижним ярусом')).toBeInTheDocument();
    expect(rows.getByText('32,4 → 37,7 %')).toBeVisible();
    expect(rows.getByText('0 → 200')).toBeVisible();
    // «Деревья: не определяется» ничего не говорит о плане: строки нет, причина - в отчёте.
    expect(rows.queryByText('Деревья')).toBeNull();
    expect(rows.queryByText('не определяется')).toBeNull();
    expect(screen.getByText('Живая изгородь вдоль борта')).toBeInTheDocument();
  });

  it('hides a zero-to-zero row: the street has no lawn to speak of', () => {
    const noLawn: EffectJson = {
      ...effect,
      measures: [...effect.measures, measure('lawn_m2', 'Газон', 'м²', 0, 0)],
    };
    render(<EffectBlock effect={noLawn} />);
    const rows = within(screen.getByRole('list', { name: 'Что план даёт улице' }));
    expect(rows.queryByText('Газон')).toBeNull();
  });

  it('renders nothing for runs made before the balance existed', () => {
    const { container } = render(<EffectBlock effect={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});
