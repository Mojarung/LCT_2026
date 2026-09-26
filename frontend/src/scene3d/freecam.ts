/* Свободная камера: полёт и шаг пешехода.
 *
 * Мышь - обзор (захват указателя по щелчку, как в играх, или перетаскивание правой кнопкой без
 * захвата), WASD или стрелки - движение, Space и E - вверх, C и Q - вниз, Shift - быстрее,
 * Alt - медленнее, колесо - базовая скорость. Скорость набирается и гасится плавно: резкий
 * старт и остановка дёргают кадр и укачивают. В режиме пешехода глаза на 1,7 м, прыжок
 * пробелом, сквозь стены не пройти.
 *
 * Шаг интегрирования - чистая функция step(): её проверяют тесты без WebGL, а класс Freecam
 * только собирает ввод и отдаёт позу камере. */

import type { Flat } from './types';

export type Mode = 'fly' | 'walk';

export interface Pose {
  x: number;
  y: number;
  z: number;
  /** Поворот вокруг вертикали, радианы: 0 - взгляд на север (-z). */
  yaw: number;
  /** Наклон, радианы: вверх положительный. */
  pitch: number;
}

export interface Motion {
  vx: number;
  vy: number;
  vz: number;
  grounded: boolean;
}

export interface Keys {
  forward: number;
  right: number;
  up: number;
  fast: boolean;
  slow: boolean;
  jump: boolean;
}

export const EYE_M = 1.7;
const WALK_MS = 1.5;
const RUN_MS = 5;
const GRAVITY = 9.81;
const JUMP_MS = 4.2;
/** Время выхода на заданную скорость, секунды: меньше - дёргано, больше - как по льду. */
const RESPONSE_S = 0.18;
export const PITCH_LIMIT = Math.PI / 2 - 0.01;
/** Ниже этой высоты полёт не опускается: камера под газоном показывает изнанку сцены. */
export const FLY_FLOOR_M = 0.3;

export function clampPitch(pitch: number): number {
  return Math.max(-PITCH_LIMIT, Math.min(PITCH_LIMIT, pitch));
}

/** Желаемая скорость по нажатым клавишам в осях сцены. */
export function wishVelocity(
  pose: Pose,
  keys: Keys,
  mode: Mode,
  flySpeed: number,
): [number, number, number] {
  const boost = keys.fast ? 4 : keys.slow ? 0.25 : 1;
  const sin = Math.sin(pose.yaw);
  const cos = Math.cos(pose.yaw);
  if (mode === 'walk') {
    const speed = (keys.fast ? RUN_MS : WALK_MS) * (keys.slow ? 0.5 : 1);
    const len = Math.hypot(keys.forward, keys.right) || 1;
    const f = keys.forward / len;
    const r = keys.right / len;
    return [(-sin * f + cos * r) * speed, 0, (-cos * f - sin * r) * speed];
  }
  // В полёте «вперёд» идёт по взгляду, с наклоном: так долетают до кроны, куда смотрят.
  const cp = Math.cos(pose.pitch);
  const sp = Math.sin(pose.pitch);
  const speed = flySpeed * boost;
  const fx = -sin * cp;
  const fy = sp;
  const fz = -cos * cp;
  return [
    (fx * keys.forward + cos * keys.right) * speed,
    (fy * keys.forward + keys.up) * speed,
    (fz * keys.forward - sin * keys.right) * speed,
  ];
}

export interface StepInput {
  pose: Pose;
  motion: Motion;
  keys: Keys;
  mode: Mode;
  flySpeed: number;
  dt: number;
  /** Сдвиг за стены: получает старую и новую точку на земле, возвращает допустимую. */
  collide?: (from: Flat, to: Flat) => Flat;
}

export function step({ pose, motion, keys, mode, flySpeed, dt, collide }: StepInput): {
  pose: Pose;
  motion: Motion;
} {
  const [wx, wy, wz] = wishVelocity(pose, keys, mode, flySpeed);
  const k = 1 - Math.exp(-dt / RESPONSE_S);
  let vx = motion.vx + (wx - motion.vx) * k;
  let vz = motion.vz + (wz - motion.vz) * k;
  let vy: number;
  let grounded = motion.grounded;
  if (mode === 'walk') {
    vy = motion.vy - GRAVITY * dt;
    if (grounded && keys.jump) {
      vy = JUMP_MS;
      grounded = false;
    }
  } else {
    vy = motion.vy + (wy - motion.vy) * k;
  }
  let x = pose.x + vx * dt;
  let z = pose.z + vz * dt;
  let y = pose.y + vy * dt;
  if (collide) {
    const moved = collide({ x: pose.x, z: pose.z }, { x, z });
    if (moved.x !== x) vx = 0;
    if (moved.z !== z) vz = 0;
    x = moved.x;
    z = moved.z;
  }
  const floor = mode === 'walk' ? EYE_M : FLY_FLOOR_M;
  if (y <= floor) {
    y = floor;
    vy = Math.max(0, vy);
    grounded = mode === 'walk';
  } else if (mode === 'walk' && y > floor + 0.01) {
    grounded = false;
  }
  return { pose: { ...pose, x, y, z }, motion: { vx, vy, vz, grounded } };
}

/** Коды клавиш, а не символы: на русской раскладке KeyW остаётся KeyW, а «w» становится «ц». */
const FORWARD = new Set(['KeyW', 'ArrowUp']);
const BACK = new Set(['KeyS', 'ArrowDown']);
const LEFT = new Set(['KeyA', 'ArrowLeft']);
const RIGHT = new Set(['KeyD', 'ArrowRight']);
const UP = new Set(['Space', 'KeyE', 'PageUp']);
// Ctrl не берём: Ctrl+W в браузере закрывает вкладку, и полёт вниз с поворотом её закроет.
const DOWN = new Set(['KeyC', 'KeyQ', 'PageDown']);
export const MOVE_CODES: ReadonlySet<string> = new Set([
  ...FORWARD,
  ...BACK,
  ...LEFT,
  ...RIGHT,
  ...UP,
  ...DOWN,
  'ShiftLeft',
  'ShiftRight',
  'AltLeft',
  'AltRight',
]);

export function keysOf(down: ReadonlySet<string>): Keys {
  const has = (set: Set<string>) => [...set].some((code) => down.has(code));
  return {
    forward: (has(FORWARD) ? 1 : 0) - (has(BACK) ? 1 : 0),
    right: (has(RIGHT) ? 1 : 0) - (has(LEFT) ? 1 : 0),
    up: (has(UP) ? 1 : 0) - (has(DOWN) ? 1 : 0),
    fast: down.has('ShiftLeft') || down.has('ShiftRight'),
    slow: down.has('AltLeft') || down.has('AltRight'),
    jump: down.has('Space'),
  };
}

/** Скорость полёта, м/с: от пешего шага до облёта квартала. Колесо меняет её в WHEEL_STEP раз. */
export const FLY_SPEED_MIN = 1;
export const FLY_SPEED_MAX = 60;
export const FLY_SPEED_DEFAULT = 8;
const WHEEL_STEP = 1.25;
const MOUSE_RAD_PER_PX = 0.0022;

/** Отпускание клавиши теряется, когда в этот момент фокус уходит со страницы: окно загрузки
 *  снимка, переключение окна. Тогда камера летела бесконечно. Поэтому клавиши сбрасываются
 *  при уходе со вкладки, выходе из захвата мыши и снимке, а Shift и Alt сверяются с каждым
 *  событием клавиатуры и мыши - в событии их состояние всегда верное. Сбрасывать клавишу по
 *  отсутствию автоповтора нельзя: повторяется только последняя нажатая, и W с зажатым потом
 *  Shift «замолкала» - полёт вставал через полторы секунды. */
const SHIFTS = ['ShiftLeft', 'ShiftRight'];
const ALTS = ['AltLeft', 'AltRight'];

export function syncModifiers(
  down: ReadonlySet<string>,
  state: { shiftKey: boolean; altKey: boolean },
): Set<string> {
  const next = new Set(down);
  if (!state.shiftKey) for (const code of SHIFTS) next.delete(code);
  if (!state.altKey) for (const code of ALTS) next.delete(code);
  return next;
}

export function clampSpeed(speed: number): number {
  return Math.min(FLY_SPEED_MAX, Math.max(FLY_SPEED_MIN, speed));
}

export interface FreecamOptions {
  element: HTMLElement;
  pose: Pose;
  collide?: (from: Flat, to: Flat) => Flat;
  onChange?: () => void;
  /** Человек взялся за управление: клавиша движения или поворот мышью. Облёт на этом стоп. */
  onInput?: () => void;
}

export class Freecam {
  pose: Pose;
  mode: Mode = 'fly';
  private speed = FLY_SPEED_DEFAULT;
  private motion: Motion = { vx: 0, vy: 0, vz: 0, grounded: false };
  private down = new Set<string>();
  private dragging = false;
  private readonly element: HTMLElement;
  private readonly collide?: (from: Flat, to: Flat) => Flat;
  private readonly onChange?: () => void;
  private readonly onInput?: () => void;
  private readonly off: (() => void)[] = [];

  constructor({ element, pose, collide, onChange, onInput }: FreecamOptions) {
    this.element = element;
    this.pose = pose;
    this.collide = collide;
    this.onChange = onChange;
    this.onInput = onInput;
    this.bind();
  }

  get locked(): boolean {
    return document.pointerLockElement === this.element;
  }

  get flySpeed(): number {
    return this.speed;
  }

  setSpeed(speed: number): void {
    this.speed = clampSpeed(speed);
    this.onChange?.();
  }

  /** Забыть все нажатые клавиши: перед снимком и при уходе со вкладки. */
  releaseKeys(): void {
    this.down = new Set();
    this.motion = { ...this.motion, vx: 0, vz: 0, vy: this.mode === 'walk' ? this.motion.vy : 0 };
  }

  setMode(mode: Mode): void {
    this.mode = mode;
    this.motion = { vx: 0, vy: 0, vz: 0, grounded: false };
    if (mode === 'walk') this.pose = { ...this.pose, y: Math.max(this.pose.y, EYE_M) };
    this.onChange?.();
  }

  setPose(pose: Pose): void {
    this.pose = pose;
    this.motion = { vx: 0, vy: 0, vz: 0, grounded: false };
  }

  lock(): void {
    if (!this.locked) void this.element.requestPointerLock();
  }

  update(dt: number): void {
    const next = step({
      pose: this.pose,
      motion: this.motion,
      keys: keysOf(this.down),
      mode: this.mode,
      flySpeed: this.flySpeed,
      dt: Math.min(dt, 0.1),
      collide: this.mode === 'walk' ? this.collide : undefined,
    });
    this.pose = next.pose;
    this.motion = next.motion;
  }

  dispose(): void {
    for (const off of this.off) off();
    if (this.locked) document.exitPointerLock();
  }

  private look(dx: number, dy: number): void {
    if (dx || dy) this.onInput?.();
    this.pose = {
      ...this.pose,
      yaw: this.pose.yaw - dx * MOUSE_RAD_PER_PX,
      pitch: clampPitch(this.pose.pitch - dy * MOUSE_RAD_PER_PX),
    };
  }

  private listen<K extends keyof DocumentEventMap>(
    target: HTMLElement | Document | Window,
    type: K,
    handler: (event: DocumentEventMap[K]) => void,
    options?: AddEventListenerOptions,
  ): void {
    const fn = handler as EventListener;
    target.addEventListener(type, fn, options);
    this.off.push(() => {
      target.removeEventListener(type, fn, options);
    });
  }

  private bind(): void {
    const el = this.element;
    this.listen(el, 'click', () => {
      this.lock();
    });
    this.listen(el, 'contextmenu', (e) => {
      e.preventDefault();
    });
    this.listen(el, 'mousedown', (e) => {
      if (e.button === 2) this.dragging = true;
    });
    this.listen(window, 'mouseup', () => {
      this.dragging = false;
    });
    this.listen(document, 'mousemove', (e) => {
      this.down = syncModifiers(this.down, e);
      if (this.locked || this.dragging) this.look(e.movementX, e.movementY);
    });
    this.listen(
      el,
      'wheel',
      (e) => {
        e.preventDefault();
        this.setSpeed(this.speed * (e.deltaY > 0 ? 1 / WHEEL_STEP : WHEEL_STEP));
      },
      { passive: false },
    );
    this.listen(window, 'keydown', (e) => {
      if (isTyping(e.target)) return;
      if (MOVE_CODES.has(e.code)) {
        this.down = syncModifiers(this.down, e);
        this.down.add(e.code);
        if (![...SHIFTS, ...ALTS].includes(e.code)) this.onInput?.();
        // Пробел и стрелки иначе прокручивают страницу под сценой, Alt - открывает меню окна.
        e.preventDefault();
      }
    });
    this.listen(window, 'keyup', (e) => {
      this.down = syncModifiers(this.down, e);
      this.down.delete(e.code);
    });
    this.listen(window, 'blur', () => {
      this.releaseKeys();
    });
    this.listen(document, 'visibilitychange', () => {
      if (document.hidden) this.releaseKeys();
    });
    this.listen(document, 'pointerlockchange', () => {
      if (!this.locked) this.releaseKeys();
      this.onChange?.();
    });
  }
}

/** Ползунки и флажки пульта клавиши полёта не забирают: иначе после сдвига «времени суток»
 *  камера перестаёт слушаться, пока не щёлкнешь по сцене. */
const CONTROL_INPUTS = new Set(['range', 'checkbox', 'radio', 'button']);

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target instanceof HTMLInputElement) return !CONTROL_INPUTS.has(target.type);
  return target.isContentEditable || ['TEXTAREA', 'SELECT'].includes(target.tagName);
}
