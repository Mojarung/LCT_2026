import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  EYE_M,
  FLY_SPEED_DEFAULT,
  FLY_SPEED_MAX,
  Freecam,
  type FreecamOptions,
  type Pose,
} from './freecam';

/* Камера полёта и пешехода на событиях DOM: клавиши, колесо, мышь, захват указателя. */

const POSE: Pose = { x: 0, y: 10, z: 0, yaw: 0, pitch: 0 };

let lockedTo: Element | null = null;
Object.defineProperty(document, 'pointerLockElement', {
  configurable: true,
  get: () => lockedTo,
});
Object.assign(document, {
  exitPointerLock: () => {
    lockedTo = null;
  },
});

const cams: Freecam[] = [];
afterEach(() => {
  for (const cam of cams.splice(0)) cam.dispose();
  lockedTo = null;
});

function make(over: Partial<FreecamOptions> = {}) {
  const element = document.createElement('div');
  document.body.append(element);
  const requestPointerLock = vi.fn(() => {
    lockedTo = element;
    return Promise.resolve();
  });
  Object.assign(element, { requestPointerLock });
  const onChange = vi.fn();
  const onInput = vi.fn();
  const cam = new Freecam({ element, pose: { ...POSE }, onChange, onInput, ...over });
  cams.push(cam);
  return { cam, element, onChange, onInput, requestPointerLock };
}

const key = (type: 'keydown' | 'keyup', code: string, init: KeyboardEventInit = {}) => {
  const event = new KeyboardEvent(type, { code, cancelable: true, ...init });
  window.dispatchEvent(event);
  return event;
};

function mouseMove(dx: number, dy: number): void {
  const event = new MouseEvent('mousemove');
  Object.defineProperty(event, 'movementX', { value: dx });
  Object.defineProperty(event, 'movementY', { value: dy });
  document.dispatchEvent(event);
}

describe('свободная камера: клавиши', () => {
  it('W ведёт камеру вперёд, на север (-z), и сообщает, что человек взялся за управление', () => {
    const { cam, onInput } = make();
    const down = key('keydown', 'KeyW');
    expect(down.defaultPrevented).toBe(true);
    expect(onInput).toHaveBeenCalledTimes(1);
    for (let i = 0; i < 20; i++) cam.update(0.05);
    expect(cam.pose.z).toBeLessThan(-5);
    expect(cam.pose.x).toBeCloseTo(0, 6);
    key('keyup', 'KeyW');
    const z = cam.pose.z;
    for (let i = 0; i < 40; i++) cam.update(0.05);
    // Камера тормозит, а не летит бесконечно.
    expect(cam.pose.z - z).toBeGreaterThan(-5);
  });

  it('Shift сам по себе за управление не считается; посторонние клавиши не перехватываются', () => {
    const { onInput } = make();
    key('keydown', 'ShiftLeft', { shiftKey: true });
    expect(onInput).not.toHaveBeenCalled();
    expect(key('keydown', 'KeyZ').defaultPrevented).toBe(false);
  });

  it('в поле ввода клавиши полёта не забираются, на ползунке - забираются', () => {
    const { onInput } = make();
    const text = document.createElement('input');
    document.body.append(text);
    const typing = new KeyboardEvent('keydown', { code: 'KeyW', bubbles: true, cancelable: true });
    text.dispatchEvent(typing);
    expect(typing.defaultPrevented).toBe(false);
    const range = document.createElement('input');
    range.type = 'range';
    document.body.append(range);
    const slide = new KeyboardEvent('keydown', { code: 'KeyW', bubbles: true, cancelable: true });
    range.dispatchEvent(slide);
    expect(slide.defaultPrevented).toBe(true);
    const area = document.createElement('textarea');
    document.body.append(area);
    const note = new KeyboardEvent('keydown', { code: 'KeyW', bubbles: true, cancelable: true });
    area.dispatchEvent(note);
    expect(note.defaultPrevented).toBe(false);
    expect(onInput).toHaveBeenCalledTimes(1);
  });

  it('уход со вкладки и потеря окна сбрасывают нажатые клавиши', () => {
    const { cam } = make();
    key('keydown', 'KeyD');
    window.dispatchEvent(new Event('blur'));
    for (let i = 0; i < 10; i++) cam.update(0.05);
    expect(cam.pose.x).toBeCloseTo(0, 6);
    key('keydown', 'KeyD');
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));
    Reflect.deleteProperty(document, 'hidden');
    for (let i = 0; i < 10; i++) cam.update(0.05);
    expect(cam.pose.x).toBeCloseTo(0, 6);
  });
});

describe('свободная камера: мышь и колесо', () => {
  it('щелчок захватывает указатель, мышь в захвате поворачивает взгляд', () => {
    const { cam, element, requestPointerLock, onChange, onInput } = make();
    element.click();
    expect(requestPointerLock).toHaveBeenCalledTimes(1);
    expect(cam.locked).toBe(true);
    document.dispatchEvent(new Event('pointerlockchange'));
    expect(onChange).toHaveBeenCalled();
    mouseMove(100, -50);
    expect(cam.pose.yaw).toBeCloseTo(-0.22, 6);
    expect(cam.pose.pitch).toBeCloseTo(0.11, 6);
    expect(onInput).toHaveBeenCalled();
    // Уже захвачен - второй раз не просится.
    cam.lock();
    expect(requestPointerLock).toHaveBeenCalledTimes(1);
  });

  it('без захвата поворот - только при зажатой правой кнопке, контекстное меню не открывается', () => {
    const { cam, element } = make();
    mouseMove(100, 0);
    expect(cam.pose.yaw).toBe(0);
    element.dispatchEvent(new MouseEvent('mousedown', { button: 2 }));
    mouseMove(100, 0);
    expect(cam.pose.yaw).toBeCloseTo(-0.22, 6);
    window.dispatchEvent(new MouseEvent('mouseup'));
    mouseMove(100, 0);
    expect(cam.pose.yaw).toBeCloseTo(-0.22, 6);
    const menu = new MouseEvent('contextmenu', { cancelable: true });
    element.dispatchEvent(menu);
    expect(menu.defaultPrevented).toBe(true);
  });

  it('потеря захвата сбрасывает клавиши', () => {
    const { cam } = make();
    key('keydown', 'KeyW');
    lockedTo = null;
    document.dispatchEvent(new Event('pointerlockchange'));
    cam.update(0.1);
    expect(cam.pose.z).toBeCloseTo(0, 6);
  });

  it('колесо меняет скорость полёта в 1,25 раза, в пределах', () => {
    const { cam, element, onChange } = make();
    expect(cam.flySpeed).toBe(FLY_SPEED_DEFAULT);
    const wheel = new WheelEvent('wheel', { deltaY: -1, cancelable: true });
    element.dispatchEvent(wheel);
    expect(wheel.defaultPrevented).toBe(true);
    expect(cam.flySpeed).toBeCloseTo(FLY_SPEED_DEFAULT * 1.25, 6);
    element.dispatchEvent(new WheelEvent('wheel', { deltaY: 1 }));
    expect(cam.flySpeed).toBeCloseTo(FLY_SPEED_DEFAULT, 6);
    cam.setSpeed(1000);
    expect(cam.flySpeed).toBe(FLY_SPEED_MAX);
    expect(onChange).toHaveBeenCalled();
  });
});

describe('свободная камера: режимы', () => {
  it('пешеход стоит на высоте глаз, полёт спускается не ниже пола', () => {
    const { cam } = make();
    cam.setPose({ ...POSE, y: 0.5 });
    cam.setMode('walk');
    expect(cam.mode).toBe('walk');
    expect(cam.pose.y).toBe(EYE_M);
    cam.update(0.05);
    expect(cam.pose.y).toBeCloseTo(EYE_M, 6);
    cam.setMode('fly');
    key('keydown', 'KeyC');
    for (let i = 0; i < 40; i++) cam.update(0.05);
    expect(cam.pose.y).toBeCloseTo(0.3, 6);
  });

  it('стены и крыши: шаг упирается в стену, над домом полёт - выше крыши', () => {
    const collide = vi.fn((from: { x: number; z: number }) => from);
    const roof = vi.fn(() => 12);
    const { cam } = make({ collide, roof });
    key('keydown', 'KeyW');
    for (let i = 0; i < 10; i++) cam.update(0.05);
    expect(cam.pose.z).toBe(0);
    expect(collide).toHaveBeenCalled();
    expect(cam.pose.y).toBeCloseTo(12.3, 6);
  });

  it('снятие слушателей и выход из захвата', () => {
    const { cam, element, requestPointerLock } = make();
    const exit = vi.spyOn(document, 'exitPointerLock');
    element.click();
    cam.dispose();
    expect(exit).toHaveBeenCalledTimes(1);
    element.click();
    expect(requestPointerLock).toHaveBeenCalledTimes(1);
    key('keydown', 'KeyW');
    cam.releaseKeys();
    cam.update(0.1);
    expect(cam.pose.z).toBe(0);
  });
});
