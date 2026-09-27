import { describe, expect, it } from 'vitest';

import { parseViewHash } from './viewHash';

describe('ссылка на место на плане', () => {
  it('центр и метров на пиксель', () => {
    expect(parseViewHash('#x=9125.5&y=-8905.2&m=0.05')).toEqual({ x: 9125.5, y: -8905.2, m: 0.05 });
  });

  it('масштаб по умолчанию - 0,1 м на пиксель', () => {
    expect(parseViewHash('#x=1&y=2')).toEqual({ x: 1, y: 2, m: 0.1 });
  });

  it('битая ссылка не ломает вид', () => {
    expect(parseViewHash('#x=a&y=2')).toBeNull();
    expect(parseViewHash('#x=1&y=2&m=0')).toBeNull();
    expect(parseViewHash('#y=2')).toBeNull();
    expect(parseViewHash('')).toBeNull();
  });
});
