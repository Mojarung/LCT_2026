import { describe, expect, it } from 'vitest';
import { semanticReviewTarget } from './reviewView';
import { toScreen } from './view';

const area = { left: 0, top: 0, width: 500, height: 500 };
const view = { scale: 10, tx: 100, ty: 300, rot: 0 };
describe('камера уточнения объектов', () => {
  it('сохраняет вид, когда группа уже хорошо видна', () => {
    expect(semanticReviewTarget(view, [0, 0, 10, 10], area, true)).toBeNull();
  });
  it('приближает слишком маленький объект даже внутри экрана', () => {
    const target = semanticReviewTarget({ ...view, scale: 0.1 }, [0, 0, 10, 10], area, true);
    expect(target?.scale).toBeGreaterThan(0.1);
  });
  it('показывает далёкую группу между панелями с учётом поворота', () => {
    const rot = Math.PI / 4;
    const free = { left: 12, top: 80, width: 420, height: 500 };
    const target = semanticReviewTarget({ ...view, rot }, [500, 700, 520, 730], free, true);
    expect(target).not.toBeNull();
    if (!target) return;
    for (const [x, y] of [
      [500, 700],
      [520, 700],
      [520, 730],
      [500, 730],
    ]) {
      const p = toScreen({ ...target, rot }, x ?? 0, y ?? 0);
      expect(p.sx).toBeGreaterThan(free.left);
      expect(p.sx).toBeLessThan(free.left + free.width);
      expect(p.sy).toBeGreaterThan(free.top);
      expect(p.sy).toBeLessThan(free.top + free.height);
    }
  });
  it('явное приближение доступно для одиночной точки', () => {
    const target = semanticReviewTarget(view, [5, 5, 5, 5], area, false);
    expect(target).not.toBeNull();
    expect(Number.isFinite(target?.scale)).toBe(true);
  });
});
