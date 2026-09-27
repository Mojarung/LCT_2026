import { describe, expect, it } from 'vitest';

import golden from './__fixtures__/quotes.golden.json';
import { clauseNumber, listQuote, quoteOf, tableQuote } from './quotes';

describe('цитаты норм', () => {
  it('строка табл. 9.1 разбирается на дерево и кустарник', () => {
    expect(tableQuote('Край проезжей части | 2,0 | 1,0')).toEqual({
      what: 'Край проезжей части',
      tree: '2,0 м',
      shrub: '1,0 м',
      note: '',
    });
  });

  it('прочерк в колонке - «не нормируется», хвост после числа - примечание', () => {
    expect(tableQuote('Газопровод | 1,5 | - Прим. 5: условие')).toEqual({
      what: 'Газопровод',
      tree: '1,5 м',
      shrub: 'не нормируется',
      note: 'Прим. 5: условие',
    });
  });

  it('перечень строк другой таблицы таблицей 9.1 не считается', () => {
    expect(tableQuote('перечень; строк | 1 | 2')).toBeNull();
  });

  it('перечень «вариант | значение; ...» - списком, число с единицей', () => {
    expect(listQuote('Однорядная | 5-6; Групповая | 5-7')).toEqual([
      { what: 'Однорядная', value: '5-6 м' },
      { what: 'Групповая', value: '5-7 м' },
    ]);
    expect(listQuote('одна строка | 5')).toBeNull();
  });

  it('номер пункта без текста и цитата из пункта, если своей нет', () => {
    const rule = { clause: 'п. 9.6, табл. 9.1: край проезжей части', quote: '' };
    expect(clauseNumber(rule)).toBe('п. 9.6, табл. 9.1');
    expect(quoteOf(rule)).toBe('край проезжей части');
    expect(quoteOf({ ...rule, quote: 'дословно' })).toBe('дословно');
  });

  it('совпадает со старым plan.js на всех 76 правилах настоящего прогона', () => {
    expect(golden).toHaveLength(76);
    for (const item of golden) {
      const rule = { clause: item.clause, quote: item.quote };
      const text = quoteOf(rule);
      expect({ id: item.rule_id, clause: clauseNumber(rule), text }).toEqual({
        id: item.rule_id,
        clause: item.clauseNumber,
        text: item.quoteOf,
      });
      expect(text ? tableQuote(text) : null).toEqual(item.table);
      expect(text ? listQuote(text) : null).toEqual(item.list);
    }
  });
});
