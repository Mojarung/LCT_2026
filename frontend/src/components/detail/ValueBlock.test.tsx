import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { PlantingValue } from '../../api/artifacts';
import type { MapItem } from '../../map/types';
import { BarrierBlock, ValueBlock } from './ValueBlock';

function value(patch: Partial<PlantingValue> = {}): PlantingValue {
  return {
    delta: 0.0004,
    percentile: 0.8,
    by_term: {},
    reasons: ['тень на тротуаре'],
    weak: [],
    ...patch,
  };
}

const item: MapItem = {
  kind: 'rejection',
  id: 'r1',
  number: 3,
  planting_type: 'tree',
  x: 0,
  y: 0,
  radius: 2,
  verdict: 'forbidden',
  explanation: '',
  value: null,
  checks: [],
  barrier_m: 0.8,
};

describe('чем ценна посадка', () => {
  it('без оценки ничего не показывает', () => {
    const { container } = render(<ValueBlock value={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('сильная посадка: место среди посадок плана и что она даёт', () => {
    render(<ValueBlock value={value({ weak: ['мало места кроне'] })} />);
    expect(screen.getByRole('heading', { name: 'Чем ценна посадка' })).toBeInTheDocument();
    expect(screen.getByText(/больше, чем у/)).toHaveTextContent('80%');
    expect(screen.getByText('тень на тротуаре')).toBeInTheDocument();
    expect(screen.getByText('Слабее всего:')).toBeInTheDocument();
    expect(screen.getByText('мало места кроне')).toBeInTheDocument();
  });

  it('посадка ниже середины плана: доля тех, кто лучше', () => {
    render(<ValueBlock value={value({ percentile: 0.3, reasons: [] })} />);
    expect(screen.getByText(/ниже, чем у/)).toHaveTextContent('70%');
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });

  it('без места среди посадок - просто положительный вклад', () => {
    render(<ValueBlock value={value({ percentile: null })} />);
    expect(screen.getByText('Вклад в индекс качества положительный.')).toBeInTheDocument();
  });

  it('нулевой вклад так и называется', () => {
    render(<ValueBlock value={value({ delta: 0 })} />);
    expect(screen.getByText('Вклад в индекс качества около нуля.')).toBeInTheDocument();
  });

  it('небольшой минус без флага - «чуть ниже среднего», а не слабое место', () => {
    render(<ValueBlock value={value({ delta: -0.0002, flagged: false })} />);
    expect(screen.getByRole('heading', { name: 'Чем ценна посадка' })).toBeInTheDocument();
    expect(
      screen.getByText('Вклад в индекс качества чуть ниже среднего по плану.'),
    ).toBeInTheDocument();
  });

  it('помеченная посадка - слабое место: сначала минусы, потом что даёт', () => {
    render(
      <ValueBlock
        value={value({ flagged: true, weak: ['вид плохо подходит месту'], reasons: ['тень'] })}
      />,
    );
    expect(screen.getByRole('heading', { name: 'Слабое место' })).toBeInTheDocument();
    expect(screen.getByText(/ниже среднего по плану/)).toBeInTheDocument();
    expect(screen.getByText('вид плохо подходит месту')).toBeInTheDocument();
    expect(screen.getByText('Что даёт:')).toBeInTheDocument();
    expect(screen.getByText('тень')).toBeInTheDocument();
  });

  it('старый прогон без флага: любой заметный минус - слабое место', () => {
    render(<ValueBlock value={value({ delta: -0.002, reasons: [], weak: [] })} />);
    expect(screen.getByRole('heading', { name: 'Слабое место' })).toBeInTheDocument();
    expect(screen.queryByText('Что даёт:')).not.toBeInTheDocument();
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });

  it('при показанном блоке вида не повторяет пригодность вида и категорию', () => {
    render(
      <ValueBlock
        speciesShown
        value={value({
          reasons: ['пригодность вида месту 0,9', 'тень на тротуаре'],
          weak: ['улица районного значения (МГСН 1.02-02, табл. В.6)'],
        })}
      />,
    );
    expect(screen.queryByText(/пригодность вида месту/)).not.toBeInTheDocument();
    expect(screen.queryByText(/табл\. В\.6/)).not.toBeInTheDocument();
    expect(screen.queryByText('Слабее всего:')).not.toBeInTheDocument();
    expect(screen.getByText('тень на тротуаре')).toBeInTheDocument();
  });
});

describe('отказ, который снял бы барьер', () => {
  it('близко к сети - дерево до 5 м', () => {
    render(<BarrierBlock item={item} />);
    expect(
      screen.getByRole('heading', { name: 'Возможно с прикорневым барьером' }),
    ).toBeInTheDocument();
    expect(screen.getByText(/высотой до 5 м/)).toBeInTheDocument();
  });

  it('от метра - дерево до 20 м', () => {
    render(<BarrierBlock item={{ ...item, barrier_m: 1.5 }} />);
    expect(screen.getByText(/высотой до 20 м/)).toBeInTheDocument();
  });

  it('у посадки и у отказа без барьера блока нет', () => {
    const { container, rerender } = render(<BarrierBlock item={{ ...item, kind: 'placement' }} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<BarrierBlock item={{ ...item, barrier_m: null }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
