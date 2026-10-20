import { useRef } from 'react';

import { clampSplit } from '../../lib/split';

const KEY_STEP = 0.05;

/** Перемычка между 3D-видом и схемой: тянется мышью или пальцем, двигается стрелками. Доля
 *  схемы считается от высоты рабочей области (host), её задаёт родитель через onChange. */
export function SplitHandle({
  host,
  value,
  onChange,
}: {
  host: React.RefObject<HTMLElement | null>;
  value: number;
  onChange: (value: number) => void;
}) {
  const dragging = useRef(false);

  const fromPointer = (clientY: number) => {
    const rect = host.current?.getBoundingClientRect();
    if (!rect || rect.height <= 0) return;
    onChange(clampSplit((rect.bottom - clientY) / rect.height));
  };

  return (
    <button
      type="button"
      className="scene-split-handle"
      aria-label={`Высота схемы участка: ${String(Math.round(value * 100))} %. Стрелки вверх и вниз меняют, двойной щелчок - поровну`}
      title="Потяните вверх или вниз"
      onPointerDown={(event) => {
        dragging.current = true;
        event.currentTarget.setPointerCapture(event.pointerId);
        // preventDefault снимает и фокус по щелчку: без него стрелки после щелчка не работали.
        event.preventDefault();
        event.currentTarget.focus();
      }}
      onPointerMove={(event) => {
        if (dragging.current) fromPointer(event.clientY);
      }}
      onPointerUp={(event) => {
        dragging.current = false;
        event.currentTarget.releasePointerCapture(event.pointerId);
      }}
      onPointerCancel={() => {
        dragging.current = false;
      }}
      onDoubleClick={() => {
        onChange(0.5);
      }}
      onKeyDown={(event) => {
        if (event.key === 'ArrowUp') onChange(clampSplit(value + KEY_STEP));
        else if (event.key === 'ArrowDown') onChange(clampSplit(value - KEY_STEP));
        else return;
        event.preventDefault();
      }}
    >
      <span aria-hidden="true" />
    </button>
  );
}
