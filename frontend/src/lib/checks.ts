/* Проверки норм у посадки: какие показать, как назвать объект, до которого мерили. */

import type { Rule, RuleCheck } from '../api/artifacts';

/** Вердикт по-русски: карту смотрят эксперты ДПиООС, а не разработчики. */
export const VERDICT_RU: Record<string, string> = {
  allowed: 'допускается',
  needs_approval: 'требует согласования',
  rejected: 'не допускается',
  forbidden: 'запрещено нормой',
};

export const KIND_RU: Record<string, string> = { tree: 'дерево', shrub: 'кустарник' };

/** Родительный падеж: подставляется в «до ...». Без этого в панели стоит `utility.power_cable`,
 *  и объяснение читает разработчик, а не эксперт. */
export const CLASS_RU: Record<string, string> = {
  building: 'здания',
  structure: 'сооружения',
  road: 'проезжей части',
  curb: 'бортового камня',
  sidewalk: 'тротуара',
  pavement_edge: 'края покрытия',
  tram: 'трамвайных путей',
  railway: 'железнодорожных путей',
  slope: 'откоса',
  pole: 'опоры',
  fence: 'ограды',
  'utility.water': 'водопровода',
  'utility.sewer': 'канализации',
  'utility.storm': 'ливневой канализации',
  'utility.drain': 'дренажа',
  'utility.heat': 'теплосети',
  'utility.gas': 'газопровода',
  'utility.power_cable': 'силового кабеля',
  'utility.telecom': 'сети связи',
  'utility.unknown': 'неопознанной сети',
  'utility.access': 'колодца',
  power_line_overhead: 'воздушной линии',
  existing_tree: 'существующего дерева',
  existing_shrub: 'существующего кустарника',
};

/** Во сколько раз фактический отступ больше нормы. Правила, где запас меньше двукратного,
 *  реально участвуют в решении; остальные проверены и молчат. */
export const TIGHT = 2;

export function whatFor(check: RuleCheck, rules: Record<string, Rule>): string {
  // Пустая строка класса - то же, что его нет: берём класс из правила, как старый plan.js.
  const klass = check.object_class || rules[check.rule_id]?.object_class || '';
  return CLASS_RU[klass] ?? (check.object_class || 'объекта');
}

const ratio = (check: RuleCheck): number =>
  (check.measured_m ?? Number.POSITIVE_INFINITY) / (check.threshold_m ?? 1);

/** Что показать в теле панели, а что убрать под раскрытие.
 *
 *  У посадки два десятка проверенных правил с медианным сорокакратным запасом. Напечатанные
 *  подряд, они прячут единственное, что ограничивало решение. Запас в строке «остальные
 *  выдержаны» считается по самой тугой из скрытых норм, иначе он повторяет показанную. */
export function splitChecks(checks: RuleCheck[]): {
  lead: RuleCheck[];
  hidden: RuleCheck[];
  restSlack: number | null;
} {
  const binding = checks.filter((c) => c.outcome === 'fail' || c.outcome === 'barrier');
  const rest = checks.filter((c) => c.outcome !== 'fail' && c.outcome !== 'barrier');
  const measured = rest
    .filter((c) => c.measured_m != null && c.threshold_m)
    .sort((a, b) => ratio(a) - ratio(b));
  const tight = measured.filter((c) => ratio(c) < TIGHT).slice(0, 3);
  const lead = binding.length ? binding : tight.length ? tight : measured.slice(0, 1);
  const shown = new Set(lead);
  const hidden = checks.filter((c) => !shown.has(c));
  const tail = measured.filter((c) => !shown.has(c));
  const first = tail[0];
  return { lead, hidden, restSlack: first ? ratio(first) : null };
}
