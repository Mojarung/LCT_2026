import type { Assortment } from '../api/artifacts';

type Alternative = Assortment['alternatives'][number];

/** Альтернативы подряд с одной причиной - одной группой: «Клён 74%, Вяз 72%: квота вида 10%
 *  выбрана». «Оценка ниже» не печатается, это видно по процентам. */
export function runnersText(runners: readonly Alternative[]): string {
  const groups: { why: string; names: string[] }[] = [];
  for (const alt of runners) {
    const why = alt.why_not === 'оценка ниже' ? '' : alt.why_not;
    const name = `${alt.name_ru} ${String(alt.percent)}%`;
    const last = groups.at(-1);
    if (last && last.why === why) last.names.push(name);
    else groups.push({ why, names: [name] });
  }
  return groups
    .map(({ why, names }) => (why ? `${names.join(', ')}: ${why}` : names.join(', ')))
    .join('; ');
}
