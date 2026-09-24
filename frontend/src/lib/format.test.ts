import { describe, expect, it } from 'vitest';

import {
  aboutText,
  clockText,
  decimal,
  humanSize,
  integer,
  meters,
  permille,
  plural,
  stamp,
} from './format';

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

  it('разряды делятся неразрывным пробелом с пяти знаков, четырёхзначные - слитно', () => {
    const nbsp = '\u00a0';
    expect(meters(2150.23)).toBe('2150,23');
    expect(meters(-13567.5)).toBe(`-13${nbsp}567,50`);
    expect(integer(18780)).toBe(`18${nbsp}780`);
    expect(integer(1964)).toBe('1964');
    expect(integer(302)).toBe('302');
    expect(humanSize(1500 * 1024 * 1024)).toBe('1500,0 МБ');
    expect(humanSize(15000 * 1024 * 1024)).toBe(`15${nbsp}000,0 МБ`);
  });

  it('время прогона - по часам человека, день и месяц без года', () => {
    // Час зависит от пояса машины, минуты и дата - нет.
    expect(stamp('2026-09-23T09:15:00Z')).toMatch(/^23\.09, \d\d:15$/);
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
