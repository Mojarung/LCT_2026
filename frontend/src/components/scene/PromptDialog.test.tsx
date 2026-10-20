import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { beforeAll, describe, expect, it, vi } from 'vitest';

import { type PromptDraft, PromptDialog } from './PromptDialog';

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '');
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open');
  };
});

const auto = { text: 'Улица летом, 11:00, липы вдоль борта', negative: 'люди крупным планом' };

/** Окно со своим состоянием черновика, как на странице 3D-вида. */
function Harness({
  onClose,
  onDraft,
}: {
  onClose: () => void;
  onDraft?: (d: PromptDraft | null) => void;
}) {
  const [draft, setDraft] = useState<PromptDraft | null>(null);
  return (
    <PromptDialog
      auto={auto}
      draft={draft}
      onDraft={(d) => {
        setDraft(d);
        onDraft?.(d);
      }}
      onClose={onClose}
    />
  );
}

describe('PromptDialog', () => {
  it('показывает автоматический промпт сервиса, пока текст не тронут', () => {
    render(<PromptDialog auto={auto} draft={null} onDraft={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole('dialog', { name: 'Промпт фото ИИ' })).toHaveAttribute('open');
    expect(screen.getByText('автоматический')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Что нарисовать' })).toHaveValue(auto.text);
    expect(screen.getByRole('textbox', { name: 'Чего не рисовать' })).toHaveValue(auto.negative);
    expect(
      screen.queryByRole('button', { name: 'вернуть автоматический' }),
    ).not.toBeInTheDocument();
  });

  it('без ответа сервиса поля пустые', () => {
    render(<PromptDialog auto={undefined} draft={null} onDraft={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole('textbox', { name: 'Что нарисовать' })).toHaveValue('');
    expect(screen.getByRole('textbox', { name: 'Чего не рисовать' })).toHaveValue('');
  });

  it('правка делает промпт своим, «вернуть автоматический» её отменяет', async () => {
    const onDraft = vi.fn();
    render(<Harness onClose={vi.fn()} onDraft={onDraft} />);
    const text = screen.getByRole('textbox', { name: 'Что нарисовать' });
    await userEvent.type(text, ', вечер');
    expect(text).toHaveValue(`${auto.text}, вечер`);
    expect(screen.getByText('свой')).toBeInTheDocument();
    expect(screen.getByText(/уходит со всеми следующими фото как есть/)).toBeInTheDocument();
    // Вторая строка правится отдельно, первая остаётся своей.
    const negative = screen.getByRole('textbox', { name: 'Чего не рисовать' });
    await userEvent.clear(negative);
    await userEvent.type(negative, 'машины');
    expect(onDraft).toHaveBeenLastCalledWith({ text: `${auto.text}, вечер`, negative: 'машины' });

    await userEvent.click(screen.getByRole('button', { name: 'вернуть автоматический' }));
    expect(onDraft).toHaveBeenLastCalledWith(null);
    expect(screen.getByRole('textbox', { name: 'Что нарисовать' })).toHaveValue(auto.text);
    expect(screen.getByText('автоматический')).toBeInTheDocument();
  });

  it('закрывается кнопкой «готово» и по Esc, окно закрывается при размонтировании', async () => {
    const onClose = vi.fn();
    const { unmount } = render(<Harness onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: 'готово' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    const dialog = screen.getByRole('dialog');
    const cancel = new Event('cancel', { cancelable: true });
    dialog.dispatchEvent(cancel);
    expect(cancel.defaultPrevented).toBe(true);
    expect(onClose).toHaveBeenCalledTimes(2);
    unmount();
    expect(dialog).not.toHaveAttribute('open');
  });
});
