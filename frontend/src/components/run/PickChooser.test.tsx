import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { MapItem } from '../../map/types';
import { PickChooser } from './PickChooser';

const item = (id: string, number: number, species: string): MapItem => ({
  kind: 'placement',
  id,
  number,
  planting_type: 'shrub',
  x: 0,
  y: 0,
  radius: 0.5,
  verdict: 'allowed',
  species_code: 'syringa_vulgaris',
  species_ru: species,
  explanation: '',
  value: null,
  checks: [],
});

const choice = {
  items: [item('a', 12, 'Сирень обыкновенная'), item('b', 13, 'Спирея японская')],
  x: 100,
  y: 100,
};

describe('PickChooser', () => {
  it('ставит фокус на ближайшую посадку и выбирает стрелками и Enter', () => {
    const chosen = vi.fn();
    render(
      <div>
        <PickChooser choice={choice} onChoose={chosen} onClose={() => undefined} />
      </div>,
    );
    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveFocus();
    expect(options[0]).toHaveTextContent('№ 12, Сирень обыкновенная');
    expect(options[0]).toHaveTextContent('допускается');

    fireEvent.keyDown(options[0] as HTMLElement, { key: 'ArrowDown' });
    expect(options[1]).toHaveFocus();
    expect(options[1]).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(options[1] as HTMLElement, { key: 'Enter' });
    expect(chosen).toHaveBeenCalledWith(choice.items[1]);
  });

  it('закрывается по Esc и по щелчку мимо', () => {
    const closed = vi.fn();
    render(
      <div>
        <PickChooser choice={choice} onChoose={() => undefined} onClose={closed} />
      </div>,
    );
    fireEvent.keyDown(screen.getAllByRole('option')[0] as HTMLElement, { key: 'Escape' });
    expect(closed).toHaveBeenCalledTimes(1);
    fireEvent.pointerDown(document.body);
    expect(closed).toHaveBeenCalledTimes(2);
  });

  it('список назван для читалки экрана', () => {
    render(
      <div>
        <PickChooser choice={choice} onChoose={() => undefined} onClose={() => undefined} />
      </div>,
    );
    expect(screen.getByRole('listbox', { name: 'Стволы рядом: выберите посадку' })).toBeVisible();
  });
});
