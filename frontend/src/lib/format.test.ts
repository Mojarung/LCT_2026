import { describe, expect, it } from 'vitest';

import { aboutText, clockText, decimal, humanSize, meters, permille, plural } from './format';

describe('plural', () => {
  it.each([
    [1, 'посадка'],
    [2, 'посадки'],
    [4, 'посадки'],
    [5, 'посадок'],
    [11, 'посадок'],
    [12, 'посадок'],
    [14, 'посадок'],
    [21, 'посадка'],
    [22, 'посадки'],
    [111, 'посадок'],
    [112, 'посадок'],
    [0, 'посадок'],
  ])('%i -> %s', (count, word) => {
    expect(plural(count, 'посадка', 'посадки', 'посадок')).toBe(word);
  });
});

describe('числа для эксперта', () => {
  it('метры с запятой и двумя знаками', () => {
    expect(meters(2.5)).toBe('2,50');
    expect(meters(0.93)).toBe('0,93');
    expect(decimal(0.871)).toBe('0,87');
  });

  it('часы хода прогона', () => {
    expect(clockText(65)).toBe('1:05');
    expect(clockText(3)).toBe('0:03');
    expect(clockText(-3)).toBe('0:00');
  });

  it('остаток словами', () => {
    expect(aboutText(5)).toBe('несколько секунд');
    expect(aboutText(11)).toBe('около 20 с');
    expect(aboutText(60)).toBe('около минуты');
    expect(aboutText(150)).toBe('около 3 мин');
  });

  it('размер файла словами человека', () => {
    expect(humanSize(512)).toBe('512 Б');
    expect(humanSize(2048)).toBe('2 КБ');
    expect(humanSize(3.4 * 1024 * 1024)).toBe('3,4 МБ');
  });

  it('вклад посадки в промилле, ноль ниже половины сотой', () => {
    expect(permille(0.00019)).toEqual({ value: 0.19, text: '+0,19 ‰', zero: false });
    expect(permille(-0.00042)).toEqual({ value: -0.42, text: '−0,42 ‰', zero: false });
    expect(permille(0.000001).zero).toBe(true);
  });
});
