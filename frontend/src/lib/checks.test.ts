import { describe, expect, it } from 'vitest';

import type { Rule, RuleCheck } from '../api/artifacts';
import { splitChecks, whatFor } from './checks';

const check = (
  rule_id: string,
  outcome: string,
  measured: number | null,
  threshold: number,
): RuleCheck => ({
  rule_id,
  outcome,
  measured_m: measured,
  threshold_m: threshold,
  object_class: null,
});

const A = check('A', 'pass', 2.5, 2); // запас 1,25 - тугая
const B = check('B', 'pass', 10, 2); // запас 5
const C = check('C', 'pass', null, 5); // объекта в чертеже нет
const D = check('D', 'pass', 3, 2); // запас 1,5 - тугая
const E = check('E', 'fail', 1, 2); // нарушена
const F = check('F', 'pass', 6, 2); // запас 3

describe('какие нормы показать', () => {
  it('без нарушений - тугие нормы, остальное под раскрытием с наименьшим запасом скрытых', () => {
    expect(splitChecks([A, B, C, D])).toEqual({ lead: [A, D], hidden: [B, C], restSlack: 5 });
  });

  it('нарушение вытесняет всё остальное под раскрытие', () => {
    expect(splitChecks([A, B, C, D, E])).toEqual({
      lead: [E],
      hidden: [A, B, C, D],
      restSlack: 1.25,
    });
  });

  it('тугая - запас меньше двукратного: 2,5-кратный уже под раскрытием', () => {
    const G = check('G', 'pass', 5, 2); // запас 2,5
    expect(splitChecks([A, G, B])).toEqual({ lead: [A], hidden: [G, B], restSlack: 2.5 });
  });

  it('тугих нет - одна ближайшая норма как доказательство проверки', () => {
    expect(splitChecks([B, F])).toEqual({ lead: [F], hidden: [B], restSlack: 5 });
  });
});

describe('до чего мерили', () => {
  it('класс объекта по-русски в родительном падеже, из проверки или из правила', () => {
    const rules: Record<string, Rule> = { R: { object_class: 'utility.power_cable' } as Rule };
    expect(whatFor({ ...A, object_class: 'curb' }, {})).toBe('бортового камня');
    expect(whatFor({ ...A, rule_id: 'R' }, rules)).toBe('силового кабеля');
    expect(whatFor(A, {})).toBe('объекта');
  });
});
