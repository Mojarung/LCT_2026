import { fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PlanEngine } from './engine';
import { toWorld } from './view';

function navigationMap(rot: number) {
  const canvas = document.createElement('canvas');
  canvas.setPointerCapture = vi.fn();
  vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
    left: 100,
    top: 200,
    width: 800,
    height: 400,
  } as DOMRect);
  Object.defineProperties(canvas, { clientWidth: { value: 800 }, clientHeight: { value: 400 } });
  const navigate = vi.fn<(x: number, y: number) => void>();
  const select = vi.fn();
  const view = { scale: 4, tx: 300, ty: 120, rot };
  // Ввод тестируется без растрового рендера и загрузки подосновы.
  const engine = Object.create(PlanEngine.prototype) as PlanEngine;
  Object.assign(engine, {
    canvas,
    view,
    hooks: { navigate, select },
    cleanup: [],
    marks: { selected: null },
    editing: false,
    placing: false,
    schedule: vi.fn(),
  });
  (engine as unknown as { bindInput(): void }).bindInput();
  return { engine, canvas, navigate, select, view };
}

describe('основной план как навигация 3D', () => {
  it.each([0, Math.PI / 3])(
    'передаёт координаты точки при повороте %s, не выбирая посадку',
    (rot) => {
      const { engine, canvas, navigate, select, view } = navigationMap(rot);
      fireEvent.pointerDown(canvas, { button: 0, pointerId: 1, clientX: 450, clientY: 350 });
      fireEvent.pointerUp(canvas, { button: 0, pointerId: 1, clientX: 450, clientY: 350 });
      const point = toWorld(view, 350, 150);
      expect(navigate).toHaveBeenCalledWith(point.x, point.y);
      expect(select).not.toHaveBeenCalled();
      engine.destroy();
    },
  );

  it('перетаскивание перемещает план, отменённый жест не переносит камеру', () => {
    const { engine, canvas, navigate, view } = navigationMap(0);
    fireEvent.pointerDown(canvas, { button: 0, pointerId: 1, clientX: 450, clientY: 350 });
    fireEvent.pointerMove(canvas, { pointerId: 1, clientX: 490, clientY: 370 });
    fireEvent.pointerUp(canvas, { button: 0, pointerId: 1, clientX: 490, clientY: 370 });
    expect(view.tx).toBe(340);
    expect(view.ty).toBe(140);
    expect(navigate).not.toHaveBeenCalled();
    fireEvent.pointerDown(canvas, { button: 0, pointerId: 2, clientX: 450, clientY: 350 });
    fireEvent.pointerCancel(canvas, { pointerId: 2 });
    fireEvent.pointerUp(canvas, { button: 0, pointerId: 2, clientX: 450, clientY: 350 });
    expect(navigate).not.toHaveBeenCalled();
    engine.destroy();
  });

  it('стрелки двигают карту, Enter переносит в центр и не передаёт клавиши камере', () => {
    const { engine, canvas, navigate, view } = navigationMap(Math.PI / 3);
    document.body.appendChild(canvas);
    const globalKey = vi.fn();
    window.addEventListener('keydown', globalKey);
    fireEvent.keyDown(canvas, { key: 'ArrowRight', code: 'ArrowRight' });
    expect(view.tx).toBe(260);
    fireEvent.keyDown(canvas, { key: 'Enter', code: 'Enter' });
    const point = toWorld(view, 400, 200);
    expect(navigate).toHaveBeenCalledWith(point.x, point.y);
    expect(globalKey).not.toHaveBeenCalled();
    window.removeEventListener('keydown', globalKey);
    canvas.remove();
    engine.destroy();
  });
});
