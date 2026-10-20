import { describe, expect, it } from 'vitest';
import { countWhite } from './visibility';

describe('building mask', () => {
  it('counts only bright pixels of the RGBA mask', () => {
    const pixels = new Uint8Array([
      255, 255, 255, 255, 0, 0, 0, 255, 200, 200, 200, 255, 90, 0, 0, 255,
    ]);
    expect(countWhite(pixels)).toBe(2);
  });
});
