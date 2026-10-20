import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
    expect(screen.getByRole('listbox', { name: 'Посадки рядом: выберите одну' })).toBeVisible();
  });
});

describe('PickChooser: клавиши, мышь и место на карте', () => {
  const many = Array.from({ length: 8 }, (_, i) => item(`m${String(i)}`, i + 1, 'Сирень'));

  it('Home, End и стрелки по кругу; пробел выбирает', async () => {
    const user = userEvent.setup();
    const chosen = vi.fn();
    render(
      <div>
        <PickChooser choice={{ ...choice, items: many }} onChoose={chosen} onClose={vi.fn()} />
      </div>,
    );
    const options = screen.getAllByRole('option');
    await user.keyboard('{ArrowUp}');
    expect(options[7]).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(options[0]).toHaveFocus();
    await user.keyboard('{End}');
    expect(options[7]).toHaveFocus();
    await user.keyboard('{Home}');
    expect(options[0]).toHaveFocus();
    // Прочие клавиши список не трогает.
    await user.keyboard('x');
    expect(options[0]).toHaveFocus();
    await user.keyboard(' ');
    expect(chosen).toHaveBeenCalledWith(many[0]);
    // Список обрезан до ближайших - подсказка приблизить карту.
    expect(screen.getByText(/Показаны ближайшие/)).toBeVisible();
  });

  it('щелчок выбирает, наведение подсвечивает, Tab и колесо закрывают', async () => {
    const user = userEvent.setup();
    const chosen = vi.fn();
    const closed = vi.fn();
    render(
      <div>
        <PickChooser choice={choice} onChoose={chosen} onClose={closed} />
      </div>,
    );
    const options = screen.getAllByRole('option');
    await user.hover(options[1] as HTMLElement);
    expect(options[1]).toHaveAttribute('aria-selected', 'true');
    await user.click(options[1] as HTMLElement);
    expect(chosen).toHaveBeenCalledWith(choice.items[1]);
    expect(closed).not.toHaveBeenCalled();
    fireEvent.keyDown(options[0] as HTMLElement, { key: 'Tab' });
    expect(closed).toHaveBeenCalledTimes(1);
    fireEvent.wheel(document.body);
    expect(closed).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/Показаны ближайшие/)).not.toBeInTheDocument();
  });

  it('отказ - крестиком и номером, посадка без вида - так и подписана', () => {
    const rejection: MapItem = { ...item('r', 5, ''), kind: 'rejection', verdict: 'rejected' };
    const bare: MapItem = { ...item('n', 6, ''), species_ru: undefined };
    render(
      <div>
        <PickChooser
          choice={{ ...choice, items: [rejection, bare] }}
          onChoose={vi.fn()}
          onClose={vi.fn()}
        />
      </div>,
    );
    const [first, second] = screen.getAllByRole('option');
    expect(first).toHaveTextContent('Отказ № 5');
    expect(first?.querySelector('.pick-cross')).not.toBeNull();
    expect(second).toHaveTextContent('№ 6, вид не назначен');
  });

  it('встаёт у точки щелчка и обходит панели поверх карты', () => {
    // jsdom не раскладывает страницу: у панели - настоящий прямоугольник, иначе её не обойти.
    const rect = vi
      .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockReturnValue(DOMRect.fromRect({ x: 0, y: 0, width: 120, height: 400 }));
    const { container } = render(
      <div className="workspace">
        <aside data-map-obstacle="" />
        <aside data-map-obstacle="" />
        <div className="holder">
          <PickChooser choice={choice} onChoose={vi.fn()} onClose={vi.fn()} />
        </div>
      </div>,
    );
    const box = container.querySelector<HTMLElement>('.pick-chooser');
    expect(box?.style.left).toMatch(/px$/);
    expect(box?.style.top).toMatch(/px$/);
    expect(rect).toHaveBeenCalled();
    rect.mockRestore();
  });
});
