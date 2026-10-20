import { describe, expect, it, vi } from 'vitest';
import { SceneEngine } from './engine';
import { planToScene, sceneToPlan } from './planNavigation';

describe('схема участка', () => {
  it('переводит точку чертежа в сцену и обратно с учётом начала и направления севера', () => {
    const origin: [number, number] = [12000, 23000];
    expect(planToScene(12025, 23075, origin)).toEqual({ x: 25, z: -75 });
    expect(sceneToPlan({ x: 25, z: -75 }, origin)).toEqual({ x: 12025, y: 23075 });
  });

  function engine(roof = 0) {
    const e = Object.create(SceneEngine.prototype) as SceneEngine;
    const stopTour = vi.fn();
    const setView = vi.fn();
    const releaseKeys = vi.fn();
    Object.assign(e, {
      world: { bounds: [0, 0, 100, 100] },
      walls: { roofAt: () => roof },
      freecam: { pose: { yaw: 1.2 }, releaseKeys },
      stopTour,
      setView,
    });
    return { e, stopTour, setView, releaseKeys };
  }

  it('останавливает облёт и переносит на высоту глаз, сохраняя направление', () => {
    const { e, stopTour, setView, releaseKeys } = engine();
    expect(e.teleportTo(25, 75)).toBe(true);
    expect(stopTour).toHaveBeenCalled();
    expect(releaseKeys).toHaveBeenCalled();
    expect(setView).toHaveBeenCalledWith({ x: 25, z: 75, y: 1.7, yaw: 1.2, pitch: 0 }, 'walk');
  });

  it('не переносит внутрь препятствий и за границы участка', () => {
    const { e, setView } = engine(10);
    expect(e.teleportTo(25, 75)).toBe(false);
    expect(setView).not.toHaveBeenCalled();
    const clear = engine();
    const invalid: [number, number][] = [
      [-1, 10],
      [101, 10],
      [10, -1],
      [10, 101],
      [NaN, 10],
      [10, Infinity],
    ];
    for (const [x, z] of invalid) {
      expect(clear.e.teleportTo(x, z)).toBe(false);
    }
    expect(clear.stopTour).not.toHaveBeenCalled();
  });
});
