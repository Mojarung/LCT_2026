import { useEffect, useId, useRef, useState, type ReactNode } from 'react';

import { IconInfo } from './icons';

/** Задержка перед закрытием по уходу мыши: между значком и окошком есть зазор, и курсор,
 *  который идёт к тексту окошка, не должен его закрыть. */
const CLOSE_DELAY_MS = 150;

/** Определение термина рядом с подписью поля: вместо мелкого текста под каждым полем.
 *  Открывается наведением, фокусом с клавиатуры и касанием; Escape и касание мимо закрывают.
 *  Окошко - потомок значка в DOM, но встаёт от начала строки подписи (ближайший предок
 *  с position: relative), поэтому не вылезает за край узкого экрана. Текст привязан к
 *  значку через aria-describedby и читается читалкой и при закрытом окошке. */
export function InfoTip({ term, children }: { term: string; children: ReactNode }) {
  const id = useId();
  const root = useRef<HTMLSpanElement>(null);
  const closing = useRef<number | undefined>(undefined);
  const pointer = useRef('');
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  const [pinned, setPinned] = useState(false);
  const open = hover || focus || pinned;

  const close = () => {
    window.clearTimeout(closing.current);
    setHover(false);
    setFocus(false);
    setPinned(false);
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };
    const onDown = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) close();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onDown);
    };
  }, [open]);

  useEffect(
    () => () => {
      window.clearTimeout(closing.current);
    },
    [],
  );

  return (
    <span
      ref={root}
      className="tip"
      onMouseEnter={() => {
        window.clearTimeout(closing.current);
        setHover(true);
      }}
      onMouseLeave={() => {
        closing.current = window.setTimeout(() => {
          setHover(false);
        }, CLOSE_DELAY_MS);
      }}
    >
      <button
        type="button"
        className="tip-button"
        aria-label={`Что это: ${term}`}
        aria-describedby={id}
        onFocus={(event) => {
          // Фокус от клика мышью окошко не держит: его держит наведение, а второй клик
          // должен закрывать. Держит только фокус с клавиатуры.
          if (event.target.matches(':focus-visible')) setFocus(true);
        }}
        onBlur={() => {
          setFocus(false);
        }}
        onPointerDown={(event) => {
          pointer.current = event.pointerType;
        }}
        onClick={() => {
          // Касание: первое открывает и закрепляет, второе закрывает. Телефон перед кликом
          // эмулирует наведение, поэтому для касания решает только закрепление. Мышь и
          // клавиатура закрывают уже открытое окошко.
          if (pointer.current === 'touch') {
            if (pinned) close();
            else {
              setHover(false);
              setPinned(true);
            }
          } else if (open) close();
          else setPinned(true);
          pointer.current = '';
        }}
      >
        <IconInfo />
      </button>
      <span role="tooltip" id={id} className="tip-body" hidden={!open}>
        {children}
      </span>
    </span>
  );
}
