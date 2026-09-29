import { describe, expect, it } from 'vitest';

import { mergePlants } from './existing';

describe('mergePlants', () => {
  it('одно дерево из знака и кружка кроны - один ствол с большей кроной', () => {
    const merged = mergePlants([
      { x: 0, y: 0, r: 2.5, shrub: false },
      { x: 0.4, y: 0, r: 3, shrub: false, conifer: true },
      { x: 0.8, y: 0, r: 1, shrub: false },
    ]);
    expect(merged).toHaveLength(1);
    expect(merged[0]).toMatchObject({ y: 0, r: 3, conifer: true });
    expect(merged[0]?.x).toBeCloseTo(0.4);
  });

  it('деревья дальше метра и куст рядом с деревом остаются отдельными', () => {
    const merged = mergePlants([
      { x: 0, y: 0, r: 2.5, shrub: false },
      { x: 1.5, y: 0, r: 2.5, shrub: false },
      { x: 0.2, y: 0, r: 0.8, shrub: true },
    ]);
    expect(merged).toHaveLength(3);
  });
});
