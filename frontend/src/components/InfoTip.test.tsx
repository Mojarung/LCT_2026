import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { InfoTip } from './InfoTip';

const TEXT = 'Расстояние между соседними посадками в ряду.';

function setup() {
  render(
    <div>
      <InfoTip term="Шаг посадки">{TEXT}</InfoTip>
      <button type="button">снаружи</button>
    </div>,
  );
  return screen.getByRole('button', { name: 'Что это: Шаг посадки' });
}

describe('определение термина', () => {
  it('закрыто по умолчанию, но читалка получает текст описанием значка', () => {
    const button = setup();
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    expect(button).toHaveAccessibleDescription(TEXT);
  });

  it('наведение открывает, уход мыши закрывает', async () => {
    const user = userEvent.setup();
    const button = setup();

    await user.hover(button);
    expect(screen.getByRole('tooltip')).toHaveTextContent(TEXT);
    await user.unhover(button);
    await waitFor(() => {
      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    });
  });

  it('фокус с клавиатуры открывает, Escape закрывает, не уводя фокус', async () => {
    const user = userEvent.setup();
    const button = setup();

    await user.tab();
    expect(button).toHaveFocus();
    expect(screen.getByRole('tooltip')).toBeVisible();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });

  it('касание: первое открывает, второе закрывает, касание мимо тоже закрывает', () => {
    const button = setup();
    const tap = () => {
      // Телефон эмулирует наведение перед кликом: так и здесь.
      fireEvent.pointerDown(button, { pointerType: 'touch' });
      fireEvent.mouseEnter(button);
      fireEvent.click(button);
    };

    tap();
    expect(screen.getByRole('tooltip')).toBeVisible();
    tap();
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();

    tap();
    expect(screen.getByRole('tooltip')).toBeVisible();
    fireEvent.pointerDown(screen.getByRole('button', { name: 'снаружи' }));
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });
});
