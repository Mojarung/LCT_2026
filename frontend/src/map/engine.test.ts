/* Движок карты на записывающем холсте: вписывание, масштаб, сдвиг, выбор мышью и с клавиатуры,
 * довоз до выносок, правка посадок. Кадры (requestAnimationFrame) копятся в очереди и
 * прокручиваются явно: так видно и конечный вид анимации, и то, что она вообще заказана. */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { BasemapJson, SourceConflict } from '../api/artifacts';
import { installCanvas, type InstalledCanvas } from '../test/canvas';
import { PlanEngine } from './engine';
import { DEFAULT_LAYERS, type EngineHooks, type MapItem, type ViewState } from './types';

const WIDTH = 800;
const HEIGHT = 600;

interface Hooks {
  select: ReturnType<typeof vi.fn<EngineHooks['select']>>;
  probe: ReturnType<typeof vi.fn<EngineHooks['probe']>>;
  move: ReturnType<typeof vi.fn<EngineHooks['move']>>;
  remove: ReturnType<typeof vi.fn<EngineHooks['remove']>>;
  viewChanged: ReturnType<typeof vi.fn<EngineHooks['viewChanged']>>;
  placingChanged: ReturnType<typeof vi.fn<EngineHooks['placingChanged']>>;
  ambiguous: ReturnType<typeof vi.fn<EngineHooks['ambiguous']>>;
}

const box = (left: number, top: number, width: number, height: number) =>
  ({
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
    x: left,
    y: top,
    toJSON: () => ({}),
  }) as DOMRect;

let frames: Map<number, FrameRequestCallback>;
let canvasFakes: InstalledCanvas;
/** Движки теста: снимаются после него, иначе наблюдатель темы прошлых тестов заказывает кадры. */
const engines: PlanEngine[] = [];

beforeEach(() => {
  canvasFakes = installCanvas();
  frames = new Map();
  let next = 1;
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    const id = next++;
    frames.set(id, callback);
    return id;
  });
  vi.stubGlobal('cancelAnimationFrame', (id: number) => {
    frames.delete(id);
  });
});

afterEach(() => {
  for (const engine of engines.splice(0)) engine.destroy();
  vi.useRealTimers();
  document.body.replaceChildren();
});

/** Прокрутить заказанные кадры, как будто прошло 10 секунд: анимации доходят до конца. */
function flush(): void {
  const at = performance.now() + 10_000;
  // Кольцо ожидания и пульс выбора заказывают кадр за кадром: хватит нескольких кругов.
  for (let round = 0; round < 5 && frames.size; round++) {
    const list = [...frames.values()];
    frames.clear();
    for (const callback of list) callback(at);
  }
}

function mount() {
  const root = document.createElement('div');
  const holder = document.createElement('div');
  const canvas = document.createElement('canvas');
  holder.append(canvas);
  root.append(holder);
  document.body.append(root);
  vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue(box(0, 0, WIDTH, HEIGHT));
  vi.spyOn(holder, 'getBoundingClientRect').mockReturnValue(box(0, 0, WIDTH, HEIGHT));
  Object.defineProperty(canvas, 'clientWidth', { value: WIDTH });
  Object.defineProperty(canvas, 'clientHeight', { value: HEIGHT });
  const capture = vi.fn();
  Object.defineProperty(canvas, 'setPointerCapture', { value: capture });
  const hooks: Hooks = {
    select: vi.fn(),
    probe: vi.fn(),
    move: vi.fn(),
    remove: vi.fn(),
    viewChanged: vi.fn(),
    placingChanged: vi.fn(),
    ambiguous: vi.fn(),
  };
  const engine = new PlanEngine(canvas, root, hooks);
  engines.push(engine);
  return { engine, canvas, root, holder, hooks, capture };
}

/** Вид движка: снаружи он виден только через холст, а ожидания проще писать в числах. */
const viewOf = (engine: PlanEngine): ViewState => (engine as unknown as { view: ViewState }).view;

function item(id: string, x: number, y: number, over: Partial<MapItem> = {}): MapItem {
  return {
    kind: 'placement',
    id,
    number: 1,
    planting_type: 'tree',
    x,
    y,
    radius: 2,
    verdict: 'allowed',
    species_code: 'tilia_cordata',
    explanation: '',
    value: null,
    checks: [],
    ...over,
  };
}

/** Улица вдоль оси x: три посадки через 500 м. Вписывание: габарит 1008 x 8 м с полями 4 м,
 *  область без знаков в углу - 800 x 518, поле 16 px; масштаб 768 / 1008 px на метр. */
const FIT_SCALE = 768 / 1008;
const FIT_TX = WIDTH / 2 - 500 * FIT_SCALE;
const FIT_TY = 259;

function street() {
  const mounted = mount();
  const a = item('a', 0, 0);
  const b = item('b', 500, 0, { species_code: 'quercus_robur' });
  const c = item('c', 1000, 0);
  mounted.engine.setPlan([a, b, c], []);
  flush();
  return { ...mounted, a, b, c };
}

function pointer(
  target: HTMLElement,
  type: 'pointerdown' | 'pointermove' | 'pointerup',
  x: number,
  y: number,
  timeStamp = 1000,
): void {
  const event = new PointerEvent(type, { clientX: x, clientY: y, pointerId: 7, bubbles: true });
  Object.defineProperty(event, 'timeStamp', { value: timeStamp });
  target.dispatchEvent(event);
}

function click(target: HTMLElement, x: number, y: number): void {
  pointer(target, 'pointerdown', x, y);
  pointer(target, 'pointerup', x, y);
}

function key(target: HTMLElement, name: string, init: KeyboardEventInit = {}): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key: name, cancelable: true, ...init });
  target.dispatchEvent(event);
  return event;
}

describe('вписывание плана', () => {
  it('план вписан в свободную область над знаками угла, север сверху для улицы вдоль x', () => {
    const { engine, hooks } = street();
    const view = viewOf(engine);
    expect(view.rot).toBe(0);
    expect(view.scale).toBeCloseTo(FIT_SCALE);
    expect(view.tx).toBeCloseTo(FIT_TX);
    expect(view.ty).toBeCloseTo(FIT_TY);
    expect(engine.orientation()).toBe('north');
    // Вписанный вид - четверть шкалы ползунка: от 1/4 до 64 вписанного масштаба.
    expect(engine.zoomShare()).toBeCloseTo(0.25);
    // Кадр отрисован, и о новом масштабе сказано наверх.
    expect(hooks.viewChanged).toHaveBeenCalled();
  });

  it('холст в пикселях устройства, кадр рисует сетку, план и знаки угла', () => {
    const { canvas } = street();
    expect([canvas.width, canvas.height]).toEqual([WIDTH, HEIGHT]);
    const fake = canvasFakes.of(canvas);
    expect(fake?.texts()).toContain('С');
    expect(fake?.texts().some((text) => text.endsWith(' м'))).toBe(true);
    // Кэш подосновы ложится картинкой с запасом 260 px.
    expect(fake?.named('drawImage')[0]?.args.slice(1, 3)).toEqual([-260, -260]);
  });

  it('пустая карта: только сетка, вписывать нечего', () => {
    const { engine, canvas } = mount();
    engine.fit();
    flush();
    expect(viewOf(engine)).toEqual({ scale: 1, tx: 0, ty: 0, rot: 0 });
    expect(canvasFakes.of(canvas)?.named('drawImage')).toEqual([]);
  });

  it('высота колодца на узком экране - под форму плана, но не ниже 260 px', () => {
    const { holder } = street();
    expect(holder.style.height).toBe('260px');
  });

  it('колодец, который сам лежит поверх страницы, высоту не получает', () => {
    const { engine, holder } = mount();
    holder.style.position = 'absolute';
    holder.style.height = '100px';
    engine.setPlan([item('a', 0, 0), item('b', 10, 0)], []);
    expect(holder.style.height).toBe('');
  });

  it('улица по диагонали разворачивается вдоль экрана, разворот переключается на север и обратно', () => {
    const { engine } = mount();
    engine.setPlan([item('a', 0, 0), item('b', 100, 100), item('c', 200, 200)], []);
    expect(viewOf(engine).rot).toBeCloseTo(Math.PI / 4);
    expect(engine.orientation()).toBe('street');
    engine.toggleOrientation();
    expect(viewOf(engine).rot).toBe(0);
    expect(engine.orientation()).toBe('north');
    engine.toggleOrientation();
    expect(viewOf(engine).rot).toBeCloseTo(Math.PI / 4);
  });

  it('подоснова без плана: вписывание по центрам её объектов', () => {
    const { engine } = mount();
    const basemap: BasemapJson = {
      type: 'FeatureCollection',
      bbox: [0, 0, 100, 0],
      features: [
        {
          type: 'Feature',
          properties: { class: 'curb' },
          geometry: {
            type: 'LineString',
            coordinates: [
              [0, 0],
              [100, 0],
            ],
          },
        },
      ],
    };
    engine.setBasemap(basemap);
    expect(viewOf(engine).scale).toBeGreaterThan(0);
    expect(engine.zoomShare()).toBeCloseTo(0.25);
  });
});

describe('масштаб', () => {
  it('кнопки масштаба - вокруг центра холста', () => {
    const { engine } = street();
    engine.zoomBy(2);
    const view = viewOf(engine);
    expect(view.scale).toBeCloseTo(FIT_SCALE * 2);
    expect(view.tx).toBeCloseTo(WIDTH / 2 - (WIDTH / 2 - FIT_TX) * 2);
    expect(view.ty).toBeCloseTo(HEIGHT / 2 - (HEIGHT / 2 - FIT_TY) * 2);
    // log 2 / log 256 = 1/8 шкалы.
    expect(engine.zoomShare()).toBeCloseTo(0.375);
  });

  it('ползунок ставит долю шкалы вокруг центра свободной области', () => {
    const { engine } = street();
    engine.setZoomShare(0.5);
    expect(viewOf(engine).scale).toBeCloseTo(FIT_SCALE * 4);
    expect(engine.zoomShare()).toBeCloseTo(0.5);
  });

  it('колесо - вокруг курсора: точка под ним остаётся на месте', () => {
    const { engine, canvas } = street();
    const event = new WheelEvent('wheel', {
      deltaY: -100,
      clientX: 100,
      clientY: 259,
      cancelable: true,
    });
    canvas.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    const factor = Math.exp(0.15);
    const view = viewOf(engine);
    expect(view.scale).toBeCloseTo(FIT_SCALE * factor);
    expect(view.tx).toBeCloseTo(100 - (100 - FIT_TX) * factor);
  });

  it('плюс, равно и минус с клавиатуры - шаг 1,4', () => {
    const { engine, canvas } = street();
    expect(key(canvas, '+').defaultPrevented).toBe(true);
    expect(viewOf(engine).scale).toBeCloseTo(FIT_SCALE * 1.4);
    key(canvas, '=');
    expect(viewOf(engine).scale).toBeCloseTo(FIT_SCALE * 1.96);
    key(canvas, '-');
    expect(viewOf(engine).scale).toBeCloseTo(FIT_SCALE * 1.4);
    // Незнакомая клавиша карте не принадлежит.
    expect(key(canvas, 'q').defaultPrevented).toBe(false);
  });

  it('вид из ссылки: центр в точке чертежа, метров на пиксель, север сверху', () => {
    const { engine } = street();
    expect(engine.applyHash('#x=100&y=50&m=0.5')).toBe(true);
    expect(viewOf(engine)).toEqual({ scale: 2, tx: 200, ty: 400, rot: 0 });
    expect(engine.applyHash('#m=2')).toBe(false);
  });
});

describe('сдвиг рукой', () => {
  it('протяжка двигает вид на смещение руки и ничего не выбирает', () => {
    const { engine, canvas, hooks, capture } = street();
    pointer(canvas, 'pointerdown', 100, 100);
    expect(capture).toHaveBeenCalledWith(7);
    expect(canvas.classList.contains('dragging')).toBe(true);
    pointer(canvas, 'pointermove', 130, 90);
    pointer(canvas, 'pointerup', 130, 90);
    expect(canvas.classList.contains('dragging')).toBe(false);
    expect(viewOf(engine).tx).toBeCloseTo(FIT_TX + 30);
    expect(viewOf(engine).ty).toBeCloseTo(FIT_TY - 10);
    expect(hooks.select).not.toHaveBeenCalled();
  });

  it('курсор-указатель над посадкой, обычный - мимо', () => {
    const { canvas } = street();
    pointer(canvas, 'pointermove', 400, FIT_TY);
    expect(canvas.style.cursor).toBe('pointer');
    pointer(canvas, 'pointermove', 400, 50);
    expect(canvas.style.cursor).toBe('');
  });

  it('сдвинутый вид удерживается при смене панелей: за центр прежней свободной области', () => {
    const { engine, root } = street();
    engine.zoomBy(2);
    const before = { ...viewOf(engine) };
    const panel = document.createElement('aside');
    panel.dataset.mapObstacle = 'side';
    panel.style.position = 'absolute';
    vi.spyOn(panel, 'getBoundingClientRect').mockReturnValue(box(0, 0, 200, HEIGHT));
    root.append(panel);
    engine.relayout();
    // Свободная область 214..800: её центр сместился на 107 px вправо.
    expect(viewOf(engine).tx).toBeCloseTo(before.tx + 107);
    expect(viewOf(engine).scale).toBe(before.scale);
  });

  it('нетронутый вид при смене панелей вписывается заново в оставшуюся область', () => {
    const { engine, root } = street();
    const panel = document.createElement('aside');
    panel.dataset.mapObstacle = 'side';
    panel.style.position = 'absolute';
    vi.spyOn(panel, 'getBoundingClientRect').mockReturnValue(box(600, 0, 200, HEIGHT));
    root.append(panel);
    engine.relayout();
    // Справа панель: свободно 0..586, поле 16.
    expect(viewOf(engine).scale).toBeCloseTo((586 - 32) / 1008);
  });
});

describe('выбор щелчком', () => {
  it('щелчок по стволу выбирает посадку и довозит её до масштаба выносок 5 px/м в центр', () => {
    const { engine, canvas, hooks, b } = street();
    click(canvas, WIDTH / 2, FIT_TY);
    expect(hooks.select).toHaveBeenLastCalledWith(b);
    // Довоз - анимацией: до кадра вид ещё прежний.
    expect(viewOf(engine).scale).toBeCloseTo(FIT_SCALE);
    flush();
    expect(viewOf(engine)).toMatchObject({ scale: 5, ty: HEIGHT / 2 });
    expect(viewOf(engine).tx).toBeCloseTo(WIDTH / 2 - 500 * 5);
  });

  it('щелчок мимо снимает выбор', () => {
    const { canvas, hooks } = street();
    click(canvas, 50, 50);
    expect(hooks.select).toHaveBeenLastCalledWith(null);
  });

  it('при reduced-motion довоз без анимации', () => {
    const { engine, canvas } = street();
    vi.spyOn(window, 'matchMedia').mockImplementation(
      (query: string) => ({ matches: query.includes('reduce') }) as MediaQueryList,
    );
    click(canvas, WIDTH / 2, FIT_TY);
    expect(viewOf(engine).scale).toBe(5);
  });

  it('уже крупный вид не приближается: человек приблизил сам', () => {
    const { engine, canvas } = street();
    engine.setZoomShare(1);
    const before = { ...viewOf(engine) };
    const { sx, sy } = { sx: 500 * before.scale + before.tx, sy: before.ty };
    click(canvas, sx, sy);
    flush();
    expect(viewOf(engine)).toEqual(before);
  });

  it('под щелчком несколько стволов - список ближайших и точка щелчка, выбора нет', () => {
    const { engine, canvas, hooks } = mount();
    const a = item('a', 0, 0);
    const b = item('b', 500, 0);
    const near = item('near', 503, 0);
    const c = item('c', 1000, 0);
    engine.setPlan([a, b, near, c], []);
    click(canvas, WIDTH / 2, FIT_TY);
    expect(hooks.ambiguous).toHaveBeenCalledWith([b, near], WIDTH / 2, FIT_TY);
    expect(hooks.select).not.toHaveBeenCalled();
  });

  it('выбор из списка тоже довозит до выносок, повторный выбор того же - нет', () => {
    const { engine, b } = street();
    engine.setSelected(b);
    flush();
    expect(viewOf(engine).scale).toBe(5);
    engine.zoomBy(0.5);
    engine.setSelected(b);
    flush();
    expect(viewOf(engine).scale).toBe(2.5);
  });

  it('скрытый слой посадок, выключенный вид и пропавшая посадка снимают выбор', () => {
    const { engine, hooks, a, b, c } = street();
    engine.setSelected(b);
    engine.setLayers({ ...DEFAULT_LAYERS, placements: false });
    expect(hooks.select).toHaveBeenLastCalledWith(null);
    engine.setLayers(DEFAULT_LAYERS);
    engine.setSelected(b);
    hooks.select.mockClear();
    engine.setSpeciesOff(new Set(['quercus_robur']));
    expect(hooks.select).toHaveBeenLastCalledWith(null);
    engine.setSpeciesOff(new Set());
    engine.setSelected(a);
    hooks.select.mockClear();
    engine.setPlan([b, c], []);
    expect(hooks.select).toHaveBeenLastCalledWith(null);
  });
});

describe('выбор с клавиатуры', () => {
  it('стрелки идут вдоль улицы по кругу, Home и End - к концам, Escape снимает выбор', () => {
    const { engine, canvas, hooks, a, b, c } = street();
    expect(key(canvas, 'ArrowRight').defaultPrevented).toBe(true);
    expect(hooks.select).toHaveBeenLastCalledWith(a);
    // Первый выбор довозит посадку до масштаба выносок.
    flush();
    expect(viewOf(engine)).toMatchObject({ scale: 5, tx: WIDTH / 2, ty: HEIGHT / 2 });
    key(canvas, 'ArrowDown');
    expect(hooks.select).toHaveBeenLastCalledWith(b);
    key(canvas, 'ArrowLeft');
    key(canvas, 'ArrowUp');
    expect(hooks.select).toHaveBeenLastCalledWith(c);
    key(canvas, 'Home');
    expect(hooks.select).toHaveBeenLastCalledWith(a);
    key(canvas, 'End');
    expect(hooks.select).toHaveBeenLastCalledWith(c);
    key(canvas, 'Escape');
    expect(hooks.select).toHaveBeenLastCalledWith(null);
  });

  it('на крупном виде переход к соседке сдвигает вид, а не масштаб', () => {
    const { engine, canvas, a } = street();
    engine.setSelected(a);
    flush();
    key(canvas, 'ArrowRight');
    flush();
    // Соседка в 500 м за краем: вид подвинут так, что она в 60 px от правой кромки.
    expect(viewOf(engine).scale).toBe(5);
    expect(500 * 5 + viewOf(engine).tx).toBeCloseTo(WIDTH - 60);
  });

  it('Enter и пробел ставят выбранную в центр свободной области', () => {
    const { engine, canvas, a } = street();
    engine.setSelected(a);
    flush();
    engine.zoomBy(2);
    expect(key(canvas, 'Enter').defaultPrevented).toBe(true);
    flush();
    expect(viewOf(engine).tx).toBeCloseTo(WIDTH / 2);
    expect(viewOf(engine).ty).toBeCloseTo(HEIGHT / 2);
    engine.zoomBy(0.8);
    key(canvas, ' ');
    flush();
    expect(viewOf(engine).tx).toBeCloseTo(WIDTH / 2);
  });

  it('в пустом плане стрелки ничего не выбирают', () => {
    const { canvas, hooks } = mount();
    key(canvas, 'ArrowRight');
    expect(hooks.select).not.toHaveBeenCalled();
  });
});

describe('правка плана', () => {
  it('режим правки помечает холст; перенос мышью - живая проба и правка с прежним местом', () => {
    const { engine, canvas, hooks, b } = street();
    engine.setEditing(true);
    expect(canvas.classList.contains('editable')).toBe(true);
    pointer(canvas, 'pointerdown', WIDTH / 2, FIT_TY);
    pointer(canvas, 'pointermove', WIDTH / 2 + 30, FIT_TY);
    const moved = 500 + 30 / FIT_SCALE;
    expect(hooks.probe).toHaveBeenCalledOnce();
    expect(hooks.probe.mock.calls[0]?.[1]).toBeCloseTo(moved);
    // Проба не чаще раза в 120 мс.
    pointer(canvas, 'pointermove', WIDTH / 2 + 31, FIT_TY, 1050);
    expect(hooks.probe).toHaveBeenCalledOnce();
    pointer(canvas, 'pointerup', WIDTH / 2 + 30, FIT_TY, 1100);
    expect(hooks.move).toHaveBeenCalledOnce();
    const [movedItem, x, y, from] = hooks.move.mock.calls[0] ?? [];
    expect(movedItem).toBe(b);
    expect(x).toBeCloseTo(moved);
    expect(y).toBeCloseTo(0);
    expect(from).toEqual({ x: 500, y: 0 });
    expect(b.x).toBeCloseTo(moved);
    // Вид при переносе не уехал.
    expect(viewOf(engine).tx).toBeCloseTo(FIT_TX);
  });

  it('щелчок в режиме правки выбирает, но не приближает', () => {
    const { engine, canvas, hooks, b } = street();
    engine.setEditing(true);
    click(canvas, WIDTH / 2, FIT_TY);
    flush();
    expect(hooks.select).toHaveBeenLastCalledWith(b);
    expect(viewOf(engine).scale).toBeCloseTo(FIT_SCALE);
    expect(hooks.move).not.toHaveBeenCalled();
  });

  it('Delete удаляет выбранную посадку только в режиме правки', () => {
    const { engine, canvas, hooks, b } = street();
    engine.setSelected(b);
    key(canvas, 'Delete');
    expect(hooks.remove).not.toHaveBeenCalled();
    engine.setEditing(true);
    expect(key(canvas, 'Delete').defaultPrevented).toBe(true);
    expect(hooks.remove).toHaveBeenCalledWith(b);
  });

  it('перенос без перетаскивания: следующий щелчок - новое место выбранной', () => {
    const { engine, canvas, hooks, b } = street();
    engine.setSelected(b);
    flush();
    expect(engine.armPlacing()).toBe(false);
    engine.setEditing(true);
    expect(engine.armPlacing()).toBe(true);
    expect(hooks.placingChanged).toHaveBeenLastCalledWith(true);
    expect(canvas.classList.contains('placing')).toBe(true);
    // На масштабе 5 px/м щелчок на 50 px правее центра - 10 м правее посадки.
    click(canvas, WIDTH / 2 + 50, HEIGHT / 2);
    expect(hooks.placingChanged).toHaveBeenLastCalledWith(false);
    expect(hooks.move).toHaveBeenCalledOnce();
    const [, x, , from] = hooks.move.mock.calls[0] ?? [];
    expect(x).toBeCloseTo(510);
    expect(from).toEqual({ x: 500, y: 0 });
    expect(hooks.select).not.toHaveBeenCalledWith(null);
  });

  it('Escape снимает режим переноса, но не выбор; выход из правки - тоже снимает', () => {
    const { engine, canvas, hooks, b } = street();
    engine.setEditing(true);
    engine.setSelected(b);
    engine.armPlacing();
    key(canvas, 'Escape');
    expect(hooks.placingChanged).toHaveBeenLastCalledWith(false);
    expect(hooks.select).not.toHaveBeenCalled();
    engine.armPlacing();
    engine.setEditing(false);
    expect(hooks.placingChanged).toHaveBeenLastCalledWith(false);
    expect(canvas.classList.contains('editable')).toBe(false);
    engine.setEditing(true);
    engine.armPlacing();
    engine.cancelPlacing();
    expect(canvas.classList.contains('placing')).toBe(false);
  });

  it('Alt со стрелкой сдвигает на полметра, с Shift - на два; правка уходит одна после паузы', () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    const { engine, canvas, hooks, b } = street();
    engine.setEditing(true);
    engine.setSelected(b);
    flush();
    expect(key(canvas, 'ArrowRight', { altKey: true }).defaultPrevented).toBe(true);
    expect(b.x).toBeCloseTo(500.5);
    key(canvas, 'ArrowUp', { altKey: true, shiftKey: true });
    expect(b.y).toBeCloseTo(2);
    expect(hooks.probe).toHaveBeenCalledTimes(2);
    expect(hooks.move).not.toHaveBeenCalled();
    vi.advanceTimersByTime(450);
    expect(hooks.move).toHaveBeenCalledOnce();
    const [, x, y, from] = hooks.move.mock.calls[0] ?? [];
    expect(x).toBeCloseTo(500.5);
    expect(y).toBeCloseTo(2);
    expect(from).toEqual({ x: 500, y: 0 });
    // Без режима правки Alt со стрелкой - обычный переход к соседке.
    engine.setEditing(false);
    key(canvas, 'ArrowRight', { altKey: true });
    expect(hooks.select).toHaveBeenCalled();
  });

  it('кольцо ожидания у посадки, чей перенос ушёл на сервер, и снятие по ответу', () => {
    const { engine, canvas, b } = street();
    const fake = canvasFakes.of(canvas);
    engine.setPending(b, true);
    fake?.reset();
    flush();
    const dashed = fake?.named('stroke').filter((c) => c.state.lineDash.join() === '6,5') ?? [];
    expect(dashed.length).toBeGreaterThan(0);
    engine.setPending(b, false);
    flush();
    fake?.reset();
    engine.zoomBy(1.01);
    flush();
    expect(fake?.named('stroke').filter((c) => c.state.lineDash.join() === '6,5')).toEqual([]);
  });

  it('ответ живой пробы красит перетаскиваемую цветом вердикта и даёт выноски по её трассе', () => {
    const style = document.documentElement.style;
    style.setProperty('--bad', '#cc0000');
    style.setProperty('--accent', '#00aa00');
    const { engine, canvas, b } = street();
    engine.setBasemap({
      type: 'FeatureCollection',
      bbox: [0, -10, 1000, 10],
      features: [
        {
          type: 'Feature',
          properties: { class: 'utility.power_cable' },
          geometry: {
            type: 'LineString',
            coordinates: [
              [0, 1],
              [1000, 1],
            ],
          },
        },
      ],
    });
    // Крупно, 10 px/м, посадка в центре холста: выноска в метр - 10 px.
    engine.applyHash('#x=500&y=0&m=0.1');
    engine.setEditing(true);
    pointer(canvas, 'pointerdown', WIDTH / 2, HEIGHT / 2);
    pointer(canvas, 'pointermove', WIDTH / 2 + 10, HEIGHT / 2);
    engine.setDragProbe({
      verdict: 'rejected',
      checks: [
        {
          rule_id: 'R-CABLE',
          outcome: 'fail',
          measured_m: 1,
          threshold_m: 2,
          object_class: 'utility.power_cable',
        },
      ],
    });
    const fake = canvasFakes.of(canvas);
    fake?.reset();
    flush();
    expect(b.x).toBeCloseTo(501);
    const colors = fake?.named('stroke').map((c) => c.state.strokeStyle) ?? [];
    expect(colors).toContain('#cc0000');
    expect(fake?.texts()).toContain('силовой кабель 1,00 < 2,00');
    // Отпустили - вердикт пробы снят, правка ушла.
    pointer(canvas, 'pointerup', WIDTH / 2 + 10, HEIGHT / 2);
    fake?.reset();
    flush();
    expect(fake?.texts()).not.toContain('силовой кабель 1,00 < 2,00');
    style.removeProperty('--bad');
    style.removeProperty('--accent');
  });
});

describe('выноски и служебные отметки', () => {
  const basemap: BasemapJson = {
    type: 'FeatureCollection',
    bbox: [0, -10, 1000, 10],
    features: [
      {
        type: 'Feature',
        properties: { class: 'curb' },
        geometry: {
          type: 'LineString',
          coordinates: [
            [0, 2.5],
            [1000, 2.5],
          ],
        },
      },
    ],
  };

  it('у выбранной посадки - выноска до борта с замером и нормой', () => {
    const { engine, canvas, b } = street();
    engine.setBasemap(basemap);
    b.checks = [
      {
        rule_id: 'R-CURB',
        outcome: 'pass',
        measured_m: 2.5,
        threshold_m: 2,
        object_class: 'curb',
      },
    ];
    engine.setSelected(b);
    flush();
    expect(canvasFakes.of(canvas)?.texts()).toContain('борт 2,50 ≥ 2,00');
  });

  it('конфликты исходника - кольца с номерами; фокус на конфликте - крупно и в центр', () => {
    const { engine, canvas, hooks } = street();
    const conflict: SourceConflict = { id: 'k', x: 1000, y: 0, tree_refs: [], targets: [] };
    engine.setSourceConflicts([conflict], 'k');
    flush();
    // Конфликт на краю вписанного плана - кольцо и номер «1».
    expect(canvasFakes.of(canvas)?.texts()).toContain('1');
    engine.setSourceConflicts([], null);
    flush();
    canvasFakes.of(canvas)?.reset();
    hooks.viewChanged.mockClear();
    engine.focusSourceConflict(conflict);
    expect(hooks.viewChanged).toHaveBeenCalledOnce();
    expect(viewOf(engine)).toMatchObject({ scale: 18, ty: HEIGHT / 2 });
    expect(viewOf(engine).tx).toBeCloseTo(WIDTH / 2 - 1000 * 18);
    engine.setSourceConflicts([conflict], 'k');
    flush();
    expect(canvasFakes.of(canvas)?.texts()).toContain('1');
  });

  it('разбор объекта: фон приглушён, объект обведён; фокус и возврат к прежнему виду', () => {
    const { engine, canvas } = street();
    engine.setSemanticReview({
      selected: [{ type: 'Point', coordinates: [500, 0] }],
      changed: [{ type: 'MultiPoint', coordinates: [[510, 0]] }],
    });
    const fake = canvasFakes.of(canvas);
    fake?.reset();
    flush();
    const veil = fake?.named('fillRect').find((c) => c.state.globalAlpha === 0.52);
    expect(veil?.args).toEqual([0, 0, WIDTH, HEIGHT]);
    expect(engine.focusSemanticReview([490, -10, 510, 10])).toBe(true);
    flush();
    // Габарит 20 м с полями 3 и 4 м - 34 м на высоту 600 - 32 px.
    expect(viewOf(engine).scale).toBeCloseTo(568 / 34);
    engine.restoreSemanticReviewView();
    flush();
    expect(viewOf(engine).scale).toBeCloseTo(FIT_SCALE);
    expect(viewOf(engine).tx).toBeCloseTo(FIT_TX);
    // Второй возврат - не к чему: вид остаётся.
    engine.zoomBy(2);
    const zoomed = { ...viewOf(engine) };
    engine.restoreSemanticReviewView();
    flush();
    expect(viewOf(engine)).toEqual(zoomed);
    engine.setSemanticReview(null);
    fake?.reset();
    flush();
    expect(fake?.named('fillRect').some((c) => c.state.globalAlpha === 0.52)).toBe(false);
  });

  it('вид из состава: посадки вида вписываются, если их не видно', () => {
    const { engine, a } = street();
    engine.showSpecies('quercus_robur');
    flush();
    // Все видны - вид не двигается.
    expect(viewOf(engine).scale).toBeCloseTo(FIT_SCALE);
    engine.setSelected(a);
    flush();
    engine.showSpecies('quercus_robur');
    flush();
    // Одна посадка - не крупнее 6 px/м, в центре свободной области.
    expect(viewOf(engine).scale).toBe(6);
    expect(viewOf(engine).tx).toBeCloseTo(WIDTH / 2 - 500 * 6);
  });

  it('газоны, зоны, слои, подсветка и карта покрытий заказывают перерисовку', () => {
    const { engine } = street();
    const calls: (() => void)[] = [
      () => {
        engine.setLawns([]);
      },
      () => {
        engine.setZones(undefined);
      },
      () => {
        engine.setHighlight('quercus_robur');
      },
      () => {
        engine.setSurface(null);
      },
      () => {
        engine.touchItems();
      },
      () => {
        engine.repaint();
      },
    ];
    for (const call of calls) {
      call();
      expect(frames.size).toBe(1);
      flush();
    }
  });

  it('смена темы документа перерисовывает карту', async () => {
    street();
    document.documentElement.dataset.theme = 'dark';
    await Promise.resolve();
    expect(frames.size).toBe(1);
  });

  it('после destroy карта не слушает ни клавиши, ни мышь', () => {
    const { engine, canvas, hooks } = street();
    engine.destroy();
    key(canvas, 'ArrowRight');
    click(canvas, WIDTH / 2, FIT_TY);
    expect(hooks.select).not.toHaveBeenCalled();
  });
});
