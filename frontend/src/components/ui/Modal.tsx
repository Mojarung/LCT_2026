import { type ReactNode, useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { IconClose, UiIcon, type UiGlyph } from '../icons';

/** Сколько длится уход окна: короче появления, чтобы закрытие отвечало сразу. */
const CLOSE_MS = 150;

/** Модальное окно по центру экрана на родном <dialog>: фокус остаётся внутри, Esc и клик по
 *  затемнённому фону закрывают. Окно - в портале у body: панель, из которой его открыли, может
 *  уехать за край или погаснуть, а окно не должно унаследовать её прозрачность. */
export function Modal({
  open,
  title,
  onClose,
  children,
  wide = false,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** Широкое окно - для каталога и таблиц. */
  wide?: boolean;
}) {
  const box = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [closing, setClosing] = useState(false);

  useEffect(() => {
    const dialog = box.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      // В jsdom showModal нет: тогда достаточно атрибута open.
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
    }
    if (!open && dialog.open) {
      if (typeof dialog.close === 'function') dialog.close();
      else dialog.removeAttribute('open');
    }
  }, [open]);

  // Клик по самому <dialog> - это клик по затемнённому фону вокруг окна. Слушатель, а не
  // onClick в разметке: с клавиатуры окно закрывает Esc (событие cancel), а щелчок по фону -
  // удобство для мыши.
  const closeRef = useRef<() => void>(() => undefined);
  useEffect(() => {
    const dialog = box.current;
    if (!dialog) return;
    const onBackdrop = (event: MouseEvent) => {
      if (event.target === dialog) closeRef.current();
    };
    dialog.addEventListener('click', onBackdrop);
    return () => {
      dialog.removeEventListener('click', onBackdrop);
    };
  }, []);

  const requestClose = () => {
    if (closing) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) {
      onClose();
      return;
    }
    setClosing(true);
    window.setTimeout(() => {
      setClosing(false);
      onClose();
    }, CLOSE_MS);
  };

  useEffect(() => {
    closeRef.current = requestClose;
  });

  return createPortal(
    <dialog
      ref={box}
      className={wide ? 'modal modal-wide' : 'modal'}
      aria-labelledby={titleId}
      data-closing={closing ? '1' : undefined}
      onCancel={(event) => {
        event.preventDefault();
        requestClose();
      }}
    >
      {open ? (
        <div className="modal-card">
          <header className="modal-head">
            <h2 id={titleId}>{title}</h2>
            <button
              type="button"
              className="modal-close"
              aria-label={`Закрыть: ${title}`}
              onClick={requestClose}
            >
              <IconClose />
            </button>
          </header>
          <div className="modal-content">{children}</div>
        </div>
      ) : null}
    </dialog>,
    document.body,
  );
}

/** Строка панели, которая открывает окно: значок, название, счётчик и шеврон «откроется». */
export function SheetButton({
  icon,
  label,
  count,
  onClick,
}: {
  icon: UiGlyph;
  label: string;
  count?: number;
  onClick: () => void;
}) {
  return (
    <button type="button" className="sheet-button" aria-haspopup="dialog" onClick={onClick}>
      <UiIcon name={icon} size={17} />
      <span className="sheet-label">{label}</span>
      {count ? <span className="sheet-count">{count}</span> : null}
      <span className="sheet-go" aria-hidden="true" />
    </button>
  );
}
