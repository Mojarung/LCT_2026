/* Разбор цитат норм из rules.json для панели посадки. Перенос из static/plan.js: поведение
 * закреплено золотым файлом __fixtures__/quotes.golden.json по всем правилам свода. */

import type { Rule } from '../api/artifacts';

export interface TableQuote {
  what: string;
  tree: string;
  shrub: string;
  note: string;
}

export interface ListRow {
  what: string;
  value: string;
}

/** Номер пункта без текста: `clause` в своде содержит и то и другое, поэтому цитата под ним
 *  дословно повторяла строку над собой. */
export function clauseNumber(rule: Pick<Rule, 'clause'>): string {
  const clause = rule.clause || '';
  const cut = clause.indexOf(': ');
  return cut > 0 ? clause.slice(0, cut) : clause;
}

export function quoteOf(rule: Pick<Rule, 'clause' | 'quote'>): string {
  if (rule.quote) return rule.quote;
  const clause = rule.clause || '';
  const cut = clause.indexOf(': ');
  return cut > 0 ? clause.slice(cut + 2) : '';
}

/** Строка табл. 9.1: «объект | до ствола дерева | до кустарника», иногда с примечанием в
 *  хвосте. Напечатанная палками, она читается как дамп: эксперт видит два числа и гадает,
 *  какое из них про ствол. Точка с запятой - перечень строк другой таблицы: его разбирать
 *  так нельзя, иначе «не нормируется» встаёт там, где в акте стоит 5-6 м. */
export function tableQuote(text: string): TableQuote | null {
  if (text.includes(';')) return null;
  const cells = text.split('|').map((cell) => cell.trim());
  if (cells.length !== 3) return null;
  const [what = '', tree = '', rest = ''] = cells;
  if (!/^([\d,.]+|[-—])$/.test(tree)) return null;
  const tail = /^([\d,.]+|[-—])\s*\.?\s*([^]*)$/.exec(rest);
  if (!tail) return null;
  const value = (raw: string) => (/^[\d,.]+$/.test(raw) ? `${raw} м` : 'не нормируется');
  return {
    what: what.replace(/^[-–—]\s*/, ''),
    tree: value(tree),
    shrub: value(tail[1] ?? ''),
    note: (tail[2] ?? '').trim(),
  };
}

/** Цитата-перечень «вариант | значение; вариант | значение» - так устроена табл. 3.6.2
 *  743-ПП: расстояния между деревьями по типу посадки. Единица - только числу или диапазону. */
export function listQuote(text: string): ListRow[] | null {
  const rows = text
    .split(';')
    .map((row) => row.trim())
    .filter(Boolean);
  if (rows.length < 2) return null;
  const pairs: ListRow[] = [];
  for (const row of rows) {
    const cells = row.split('|').map((cell) => cell.trim());
    const [what, value] = cells;
    if (cells.length !== 2 || !what || !value) return null;
    const numeric = /^[\d,.]+(\s*[-–]\s*[\d,.]+)?$/.test(value);
    pairs.push({ what, value: numeric ? `${value} м` : value });
  }
  return pairs;
}
