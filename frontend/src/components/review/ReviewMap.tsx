import { type KeyboardEvent, useCallback, useEffect, useLayoutEffect, useRef } from 'react';

import { type Box, boundsOf, type ReviewGeometry, type ReviewLabel } from '../../lib/review';

/** Запрос вписать объекты в окно; token меняется на каждый запрос, даже с теми же объектами. */
export interface FitRequest {
  indices: readonly number[];
  token: number;
}

/** Запрос поставить точку в центр окна (подпись, выбранная по номеру). */
export interface CenterRequest {
  x: number;
  y: number;
  token: number;
}

interface View {
  x: number;
  y: number;
  scale: number;
}

const MIN_SCALE = 1e-7;
const MAX_SCALE = 1e7;
const ZOOM_STEP = 1.5;
/** Подпись на карте обрезается: полный текст - в поле слева. */
const LABEL_CHARS = 80;
/** Окно вписывания не уже этого, метров: одиночный знак или короткий штрих без окружения не
 *  опознать по легенде (у тиммейта окно сжималось до метра). */
const MIN_FIT_M = 20;

/** Цвета карты из темы: оранжевый - группа, красный - объект, серый - контекст. */
function colors(element: Element) {
  const style = getComputedStyle(element);
  const read = (token: string, fallback: string) =>
    style.getPropertyValue(token).trim() || fallback;
  return {
    context: read('--review-context', '#8a918b'),
    group: read('--review-group', '#b66100'),
    object: read('--review-object', '#c41c2e'),
    label: read('--review-label', '#3a4a40'),
    labelActive: read('--review-label-active', '#1f45c8'),
    font: read('--sans', 'sans-serif'),
  };
}

function fitted(box: Box, width: number, height: number): View {
  const [x0, y0, x1, y1] = box;
  return {
    x: (x0 + x1) / 2,
    y: (y0 + y1) / 2,
    scale:
      0.88 * Math.min(width / Math.max(x1 - x0, MIN_FIT_M), height / Math.max(y1 - y0, MIN_FIT_M)),
  };
}

/** Геометрия исходника для уточнения: формы не упрощены, неизвестное не скрыто. Выбор объекта -
 *  в полях слева; карта его показывает, двигается мышью и колёсиком, с клавиатуры - стрелками
 *  и клавишами плюс и минус. */
export function ReviewMap({
  data,
  paths,
  groupPaths,
  group,
  selected,
  objectChosen,
  labelsVisible,
  label,
  fit,
  center,
}: {
  data: ReviewGeometry;
  paths: readonly Path2D[];
  groupPaths: readonly Path2D[];
  group: number;
  selected: readonly number[];
  /** Выбран конкретный объект, а не вся группа: он обводится красным. */
  objectChosen: boolean;
  labelsVisible: boolean;
  label: ReviewLabel | null;
  fit: FitRequest | null;
  center: CenterRequest | null;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const view = useRef<View>({ x: 0, y: 0, scale: 1 });
  const frame = useRef(0);
  const drag = useRef<{ x: number; y: number } | null>(null);
  // Отрисовка читает свежие пропсы из ref: её зовут и обработчики ввода, и наблюдатели.
  const props = useRef({
    data,
    paths,
    groupPaths,
    group,
    selected,
    objectChosen,
    labelsVisible,
    label,
  });
  useLayoutEffect(() => {
    props.current = {
      data,
      paths,
      groupPaths,
      group,
      selected,
      objectChosen,
      labelsVisible,
      label,
    };
  });

  const draw = useCallback(() => {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      const element = canvas.current;
      const ctx = element?.getContext('2d');
      if (!element || !ctx) return;
      const current = props.current;
      const rect = element.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      element.width = Math.max(1, Math.round(rect.width * dpr));
      element.height = Math.max(1, Math.round(rect.height * dpr));
      const { x, y, scale } = view.current;
      const tone = colors(element);
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, element.width, element.height);
      ctx.setTransform(
        scale * dpr,
        0,
        0,
        -scale * dpr,
        (rect.width / 2 - x * scale) * dpr,
        (rect.height / 2 + y * scale) * dpr,
      );
      ctx.strokeStyle = tone.context;
      ctx.lineWidth = 0.65 / scale;
      for (const path of current.groupPaths) ctx.stroke(path);
      const chosen = current.groupPaths[current.group];
      if (chosen) {
        ctx.strokeStyle = tone.group;
        ctx.lineWidth = 1.8 / scale;
        ctx.stroke(chosen);
      }
      if (current.objectChosen) {
        ctx.strokeStyle = tone.object;
        ctx.lineWidth = 3 / scale;
        for (const index of current.selected) {
          const path = current.paths[index];
          if (path) ctx.stroke(path);
        }
      }
      if (!current.labelsVisible) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.font = `11px ${tone.font}`;
      (current.data.labels ?? []).forEach((item, i) => {
        if (!Number.isFinite(item.x) || !Number.isFinite(item.y)) return;
        const sx = rect.width / 2 + (item.x - x) * scale;
        const sy = rect.height / 2 - (item.y - y) * scale;
        if (sx < 0 || sy < 0 || sx > rect.width || sy > rect.height) return;
        ctx.fillStyle = current.label === item ? tone.labelActive : tone.label;
        ctx.fillText(`${String(i + 1)}: ${item.text.slice(0, LABEL_CHARS)}`, sx + 4, sy - 4);
      });
    });
  }, []);

  const fitTo = useCallback(
    (indices: readonly number[]) => {
      const element = canvas.current;
      if (!element) return;
      const rect = element.getBoundingClientRect();
      view.current = fitted(boundsOf(props.current.data, indices), rect.width, rect.height);
      draw();
    },
    [draw],
  );

  const zoom = useCallback(
    (factor: number) => {
      const next = view.current.scale * factor;
      view.current.scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, next));
      draw();
    },
    [draw],
  );

  // Любое изменение выбора или подписей - перерисовка.
  useEffect(() => {
    draw();
  }, [draw, data, paths, groupPaths, group, selected, objectChosen, labelsVisible, label]);

  useEffect(() => {
    if (fit) fitTo(fit.indices);
  }, [fit, fitTo]);

  useEffect(() => {
    const element = canvas.current;
    if (!center || !element) return;
    view.current.x = center.x;
    view.current.y = center.y;
    view.current.scale = Math.max(view.current.scale, element.getBoundingClientRect().width / 60);
    draw();
  }, [center, draw]);

  // Размер окна и тема: карта читает цвета из CSS-переменных, смена темы - перерисовка.
  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const resize = new ResizeObserver(draw);
    resize.observe(element);
    const theme = new MutationObserver(draw);
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    // Колёсико - не пассивный слушатель: прокрутка страницы под картой не нужна.
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = element.getBoundingClientRect();
      const px = event.clientX - rect.left - rect.width / 2;
      const py = event.clientY - rect.top - rect.height / 2;
      const old = view.current.scale;
      const scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, old * Math.exp(-event.deltaY * 0.001)));
      view.current.x += px / old - px / scale;
      view.current.y -= py / old - py / scale;
      view.current.scale = scale;
      draw();
    };
    element.addEventListener('wheel', wheel, { passive: false });
    return () => {
      resize.disconnect();
      theme.disconnect();
      element.removeEventListener('wheel', wheel);
      cancelAnimationFrame(frame.current);
    };
  }, [draw]);

  const onKeyDown = (event: KeyboardEvent<HTMLCanvasElement>) => {
    const element = canvas.current;
    if (!element) return;
    const step = (0.1 * element.getBoundingClientRect().width) / view.current.scale;
    const moves: Record<string, [number, number]> = {
      ArrowLeft: [-step, 0],
      ArrowRight: [step, 0],
      ArrowUp: [0, step],
      ArrowDown: [0, -step],
    };
    const move = moves[event.key];
    if (move) {
      event.preventDefault();
      view.current.x += move[0];
      view.current.y += move[1];
      draw();
    } else if (event.key === '+' || event.key === '=') {
      event.preventDefault();
      zoom(ZOOM_STEP);
    } else if (event.key === '-') {
      event.preventDefault();
      zoom(1 / ZOOM_STEP);
    }
  };

  return (
    <>
      <div className="review-toolbar">
        <button
          type="button"
          className="ghost small"
          onClick={() => {
            fitTo(data.features.map((_, i) => i));
          }}
        >
          Весь чертёж
        </button>
        <button
          type="button"
          className="ghost small"
          onClick={() => {
            fitTo(selected);
          }}
        >
          Выбранное
        </button>
        <button
          type="button"
          className="ghost small"
          aria-label="Отдалить"
          onClick={() => {
            zoom(1 / ZOOM_STEP);
          }}
        >
          −
        </button>
        <button
          type="button"
          className="ghost small"
          aria-label="Приблизить"
          onClick={() => {
            zoom(ZOOM_STEP);
          }}
        >
          +
        </button>
      </div>
      <canvas
        ref={canvas}
        className="review-canvas"
        tabIndex={0}
        aria-label="Подоснова для уточнения классов. Выбор объекта - в полях слева; стрелки двигают карту, плюс и минус меняют масштаб."
        onKeyDown={onKeyDown}
        onPointerDown={(event) => {
          drag.current = { x: event.clientX, y: event.clientY };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
        onPointerMove={(event) => {
          const from = drag.current;
          if (!from) return;
          view.current.x -= (event.clientX - from.x) / view.current.scale;
          view.current.y += (event.clientY - from.y) / view.current.scale;
          drag.current = { x: event.clientX, y: event.clientY };
          draw();
        }}
      />
    </>
  );
}
