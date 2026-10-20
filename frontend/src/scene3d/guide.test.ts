import { describe, expect, it } from 'vitest';
import { crownMiddle, sizeGuide } from './guide';

describe('size guide', () => {
  it('draws the crown ring at the crown middle with the plan diameter and a mast to the top', () => {
    const guide = sizeGuide();
    guide.show(10, -4, 12, 6);
    const [ring, ground, pole] = guide.group.children;
    expect(guide.group.visible).toBe(true);
    expect(guide.group.position.toArray()).toEqual([10, 0, -4]);
    expect(ring?.scale.x).toBe(3);
    expect(ring?.position.y).toBe(crownMiddle(12, 6));
    expect(ground?.scale.z).toBe(3);
    expect(pole?.scale.y).toBe(12);
    guide.hide();
    expect(guide.group.visible).toBe(false);
  });

  it('keeps the ring inside the crown for a low wide shrub', () => {
    expect(crownMiddle(1.5, 3)).toBeCloseTo(0.9);
    expect(crownMiddle(20, 8)).toBe(16);
  });
});
