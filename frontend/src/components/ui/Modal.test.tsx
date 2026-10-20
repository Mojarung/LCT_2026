import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Modal, SheetButton } from './Modal';

afterEach(() => {
  vi.useRealTimers();
});

/** Окно с кнопкой, которая его открывает: так им пользуется панель прогона. */
function Harness({ onClose }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <SheetButton
        icon="layers"
        label="Слои"
        count={3}
        onClick={() => {
          setOpen(true);
        }}
      />
      <Modal
        open={open}
        title="Слои карты"
        onClose={() => {
          onClose?.();
          setOpen(false);
        }}
      >
        <p>Содержимое окна</p>
      </Modal>
    </>
  );
}

const dialog = () => document.querySelector('dialog') as HTMLDialogElement;

describe('модальное окно', () => {
  it('открывается кнопкой панели: заголовок, содержимое и счётчик на кнопке', async () => {
    render(<Harness />);
    const opener = screen.getByRole('button', { name: /Слои/ });
    expect(opener).toHaveAttribute('aria-haspopup', 'dialog');
    expect(opener).toHaveTextContent('3');
    expect(screen.queryByText('Содержимое окна')).not.toBeInTheDocument();
    await userEvent.click(opener);
    expect(dialog()).toHaveAttribute('open');
    expect(screen.getByRole('heading', { name: 'Слои карты' })).toBeInTheDocument();
    expect(screen.getByText('Содержимое окна')).toBeInTheDocument();
    // Окно в портале у body, а не внутри панели, из которой его открыли.
    expect(dialog().parentElement).toBe(document.body);
  });

  it('кнопка закрытия уводит окно после короткой анимации', async () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: /Слои/ }));
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть: Слои карты' }));
    expect(dialog()).toHaveAttribute('data-closing', '1');
    // Второе нажатие во время ухода не закрывает окно дважды.
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть: Слои карты' }));
    expect(onClose).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(dialog()).not.toHaveAttribute('open');
    expect(screen.queryByText('Содержимое окна')).not.toBeInTheDocument();
  });

  it('Esc (событие cancel) и щелчок по фону закрывают окно', async () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: /Слои/ }));
    vi.useFakeTimers();
    const cancel = new Event('cancel', { cancelable: true });
    act(() => {
      dialog().dispatchEvent(cancel);
    });
    expect(cancel.defaultPrevented).toBe(true);
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(onClose).toHaveBeenCalledTimes(1);

    vi.useRealTimers();
    await userEvent.click(screen.getByRole('button', { name: /Слои/ }));
    vi.useFakeTimers();
    // Щелчок по содержимому окна его не закрывает, по самому <dialog> (фону) - закрывает.
    fireEvent.click(screen.getByText('Содержимое окна'));
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(dialog());
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('при «уменьшить движение» закрывается сразу, без анимации', async () => {
    vi.spyOn(window, 'matchMedia').mockImplementation(
      (query: string) =>
        ({
          matches: query.includes('reduce'),
          media: query,
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
        }) as unknown as MediaQueryList,
    );
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: /Слои/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Закрыть: Слои карты' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(dialog()).not.toHaveAttribute('data-closing');
  });

  it('с родным showModal и close окно открывается и закрывается ими', () => {
    const showModal = vi.fn(function (this: HTMLDialogElement) {
      this.setAttribute('open', '');
    });
    const close = vi.fn(function (this: HTMLDialogElement) {
      this.removeAttribute('open');
    });
    const proto = HTMLDialogElement.prototype as Partial<HTMLDialogElement>;
    const had = { showModal: proto.showModal, close: proto.close };
    proto.showModal = showModal;
    proto.close = close;
    try {
      const { rerender } = render(
        <Modal open title="Окно" wide onClose={() => undefined}>
          текст
        </Modal>,
      );
      expect(showModal).toHaveBeenCalledTimes(1);
      expect(dialog()).toHaveClass('modal-wide');
      rerender(
        <Modal open={false} title="Окно" wide onClose={() => undefined}>
          текст
        </Modal>,
      );
      expect(close).toHaveBeenCalledTimes(1);
    } finally {
      proto.showModal = had.showModal;
      proto.close = had.close;
    }
  });

  it('кнопка панели без счётчика не рисует ноль', () => {
    render(<SheetButton icon="layers" label="Слои" onClick={() => undefined} />);
    expect(screen.getByRole('button', { name: 'Слои' })).toHaveTextContent(/^Слои$/);
  });
});
