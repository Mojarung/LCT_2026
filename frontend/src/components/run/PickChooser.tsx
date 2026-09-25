import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';

import { VERDICT_RU } from '../../lib/checks';
import { placeNear } from '../../lib/popover';
import { modelKey, modelOf } from '../../map/models';
import { MAX_CANDIDATES } from '../../map/picking';
import type { MapItem } from '../../map/types';
import { ModelSwatch } from './ModelSwatch';

export interface Choice {
  /** Отметки, чьи стволы попали под щелчок, ближайшие первыми. */
  items: MapItem[];
  /** Точка щелчка в пикселях холста. */
  x: number;
  y: number;
}

function label(item: MapItem): string {
  if (item.kind === 'rejection') return `Отказ № ${String(item.number)}`;
  return `№ ${String(item.number)}, ${item.species_ru ?? 'вид не назначен'}`;
}

/** Список посадок под спорным щелчком: стволы рядом, кроны друг на друге. Выбор кликом или
 *  стрелками и Enter; Esc и щелчок мимо закрывают. Рядом с точкой щелчка, но внутри карты и
 *  не на панелях: у края и у панели список открывается в другую сторону. Родитель монтирует
 *  его заново на каждый спорный щелчок (key), поэтому состояние начинается с первого пункта. */
export function PickChooser({
  choice,
  onChoose,
  onClose,
}: {
  choice: Choice;
  onChoose: (item: MapItem) => void;
  onClose: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const options = useRef<(HTMLLIElement | null)[]>([]);
  const [active, setActive] = useState(0);
  const title = useId();

  // Место - у точки щелчка, внутри карты и не на панелях поверх неё (data-map-obstacle).
  useLayoutEffect(() => {
    const element = box.current;
    const holder = element?.parentElement;
    if (!element || !holder) return;
    const frame = holder.getBoundingClientRect();
    const panels = [
      ...(holder.closest('.workspace')?.querySelectorAll<HTMLElement>('[data-map-obstacle]') ?? []),
    ]
      .map((panel) => panel.getBoundingClientRect())
      .filter((rect) => rect.width > 0 && rect.height > 0)
      .map((rect) => ({
        left: rect.left - frame.left,
        top: rect.top - frame.top,
        width: rect.width,
        height: rect.height,
      }));
    const { left, top } = placeNear(
      choice.x,
      choice.y,
      { width: element.offsetWidth, height: element.offsetHeight },
      { width: holder.clientWidth, height: holder.clientHeight },
      panels,
    );
    element.style.left = `${String(left)}px`;
    element.style.top = `${String(top)}px`;
  }, [choice]);

  useEffect(() => {
    options.current[0]?.focus({ preventScroll: true });
    const outside = (event: Event) => {
      if (!box.current?.contains(event.target as Node)) onClose();
    };
    document.addEventListener('pointerdown', outside, true);
    document.addEventListener('wheel', outside, true);
    return () => {
      document.removeEventListener('pointerdown', outside, true);
      document.removeEventListener('wheel', outside, true);
    };
  }, [onClose]);

  const move = (to: number) => {
    const count = choice.items.length;
    const next = (to + count) % count;
    setActive(next);
    options.current[next]?.focus({ preventScroll: true });
  };

  const keys = (event: KeyboardEvent, index: number) => {
    const item = choice.items[index];
    const actions: Record<string, () => void> = {
      ArrowDown: () => {
        move(index + 1);
      },
      ArrowUp: () => {
        move(index - 1);
      },
      Home: () => {
        move(0);
      },
      End: () => {
        move(choice.items.length - 1);
      },
      Enter: () => {
        if (item) onChoose(item);
      },
      ' ': () => {
        if (item) onChoose(item);
      },
      Escape: onClose,
      Tab: onClose,
    };
    const action = actions[event.key];
    if (!action) return;
    if (event.key !== 'Tab') event.preventDefault();
    action();
  };

  return (
    <div className="pick-chooser" ref={box}>
      <p className="pick-chooser-title" id={title}>
        Стволы рядом: выберите посадку
      </p>
      <ul role="listbox" aria-labelledby={title}>
        {choice.items.map((item, index) => (
          <li
            key={item.id}
            role="option"
            aria-selected={index === active}
            tabIndex={index === active ? 0 : -1}
            ref={(element) => {
              options.current[index] = element;
            }}
            onClick={() => {
              onChoose(item);
            }}
            onKeyDown={(event) => {
              keys(event, index);
            }}
            onMouseEnter={() => {
              setActive(index);
            }}
          >
            {item.kind === 'placement' ? (
              <ModelSwatch
                model={modelOf(item.species_code, item.planting_type)}
                modelKey={modelKey(item.species_code, item.planting_type)}
                size={24}
              />
            ) : (
              <i className="pick-cross" aria-hidden="true" />
            )}
            <span className="pick-text">
              <span className="pick-name">{label(item)}</span>
              <span className="pick-verdict">{VERDICT_RU[item.verdict] ?? item.verdict}</span>
            </span>
          </li>
        ))}
      </ul>
      {/* Список обрезан: под щелчком стволов больше, чем в нём строк. Приближение разводит
          стволы, и спорных щелчков становится меньше. */}
      {choice.items.length >= MAX_CANDIDATES ? (
        <p className="pick-chooser-hint">
          Показаны ближайшие. Приблизьте карту, чтобы стволы разошлись.
        </p>
      ) : null}
    </div>
  );
}
