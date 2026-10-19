import { describe, expect, it } from 'vitest';
import { fitScale, measureCrown, quantile } from './fit';

/** Облако «листвы»: эллипс полуосей a x b на высоте от y0 до y1, плюс одинокий дальний лист. */
function cloud(a: number, b: number, y0: number, y1: number, stray = 0): number[] {
  const out: number[] = [];
  for (let i = 0; i < 2000; i++) {
    const t = (i / 2000) * Math.PI * 2;
    const r = ((i * 7919) % 1000) / 1000;
    const s = Math.sqrt(r);
    out.push(
      Math.cos(t) * a * s,
      y0 + (((i * 104729) % 1000) / 1000) * (y1 - y0),
      Math.sin(t) * b * s,
    );
  }
  if (stray) out.push(stray, y1, 0);
  return out;
}

describe('crown fit', () => {
  it('measures width per axis and ignores a stray leaf', () => {
    const leaves = cloud(3, 2, 4, 10, 20);
    const m = measureCrown(leaves, leaves);
    expect(m.widthX).toBeGreaterThan(5.7);
    expect(m.widthX).toBeLessThan(6.1);
    expect(m.widthZ).toBeGreaterThan(3.75);
    expect(m.widthZ).toBeLessThan(4.1);
    expect(m.height).toBeGreaterThan(9.9);
  });

  it('scales both crown axes to the plan diameter and the top to the plan height', () => {
    const leaves = cloud(3, 2, 4, 10);
    const m = measureCrown(leaves, leaves);
    const s = fitScale(m, 8, 15);
    expect(m.widthX * s.x).toBeCloseTo(8, 6);
    expect(m.widthZ * s.z).toBeCloseTo(8, 6);
    expect(m.height * s.y).toBeCloseTo(15, 6);
  });

  it('interpolates quantiles of a sorted array', () => {
    expect(quantile([0, 10], 0.5)).toBe(5);
    expect(quantile([], 0.5)).toBe(0);
    expect(quantile([1, 2, 3, 4, 5], 1)).toBe(5);
  });
});
