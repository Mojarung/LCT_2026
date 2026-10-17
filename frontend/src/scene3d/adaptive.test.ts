import { describe, expect, it } from 'vitest';

import { AdaptiveQuality } from './adaptive';

function run(q: AdaptiveQuality, fps: number, seconds: number, from: number): number {
  let t = from;
  const dt = 1 / fps;
  while (t < from + seconds) {
    q.sample(dt, t);
    t += dt;
  }
  return t;
}

describe('адаптивное качество', () => {
  it('медленный кадр снижает сначала разрешение, потом дальность крон', () => {
    const q = new AdaptiveQuality();
    let t = run(q, 30, 6, 0);
    expect(q.scale).toBeLessThan(1);
    expect(q.lod).toBe(1);
    t = run(q, 30, 20, t);
    expect(q.scale).toBeCloseTo(0.55, 2);
    expect(q.lod).toBeLessThan(1);
    // Запас появился - сначала возвращается детализация, потом разрешение.
    t = run(q, 120, 6, t);
    expect(q.lod).toBeGreaterThan(0.45);
    run(q, 120, 30, t);
    expect(q.lod).toBe(1);
    expect(q.scale).toBe(1);
  });

  it('быстрый компьютер ничего не теряет, скрытая вкладка не считается', () => {
    const q = new AdaptiveQuality();
    run(q, 144, 10, 0);
    expect(q.scale).toBe(1);
    expect(q.sample(5, 11)).toBe(false);
    expect(q.scale).toBe(1);
  });

  it('первые секунды - сборка шейдеров, их не считаем', () => {
    const q = new AdaptiveQuality();
    run(q, 10, 1.5, 0);
    expect(q.scale).toBe(1);
  });
});
