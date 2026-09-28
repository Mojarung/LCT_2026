/* Проверки норм у посадки: какие показать, как назвать объект, до которого мерили. */

import type { Rule, RuleCheck } from '../api/artifacts';
import type { MapItem } from '../map/types';

/** Вердикт по-русски: карту смотрят эксперты ДПиООС, а не разработчики. */
export const VERDICT_RU: Record<string, string> = {
  allowed: 'допускается',
  needs_approval: 'требует согласования',
  rejected: 'не допускается',
  forbidden: 'запрещено нормой',
};

export const KIND_RU: Record<string, string> = { tree: 'дерево', shrub: 'кустарник' };

/** Что сказать читалке экрана о выбранной отметке. Выбор идёт стрелками по холсту, и без этой
 *  фразы незрячий эксперт не узнаёт, на какой посадке он стоит и что с ней. */
export function describeItem(item: MapItem): string {
  const verdict = VERDICT_RU[item.verdict] ?? item.verdict;
  if (item.kind === 'rejection') {
    return `Выбран отказ № ${String(item.number)}, ${verdict}.${item.note ? ` ${item.note}` : ''}`;
  }
  return `Выбрана посадка № ${String(item.number)}. ${item.species_ru ?? 'вид не назначен'}, ${verdict}`;
}

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
  obstacle: 'препятствия',
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
 *  выдержаны» считается по самой тугой из скрытых норм, иначе он повторяет показанную.
 *
 *  lead - это и список размерных выносок на карте (map/dimensions.ts), в том же порядке:
 *  панель и карта обязаны показывать одни нормы (жюри дизайна, итерация 7). */
export function splitChecks(checks: readonly RuleCheck[]): {
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

/** Строки с одним объектом и одним замером (теплосеть: СП 42 и 623-ПП) склеиваются: две
 *  строки «до теплосети 2,23 м» читались как два объекта (жюри по дизайну, итерация 8). */
export function groupSameMeasure(checks: readonly RuleCheck[]): RuleCheck[][] {
  const groups = new Map<string, RuleCheck[]>();
  for (const check of checks) {
    const key =
      check.measured_m == null
        ? `rule:${check.rule_id}`
        : `${check.object_class ?? ''}:${String(Math.round(check.measured_m * 100))}`;
    const group = groups.get(key);
    if (group) group.push(check);
    else groups.set(key, [check]);
  }
  return [...groups.values()];
}
