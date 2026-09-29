import type { EffectJson, EffectMeasure } from '../../api/artifacts';
import { integer, plain } from '../../lib/format';

/** Строки блока: что заказчик назвал признаками хорошего плана (тень, пылезащита, ярусность)
 *  и итог перечётной ведомости. Остальное - в отчёте интерпретаций. */
const SHOWN = [
  'trees',
  'shrubs',
  'canopy_share',
  'curb_green_share',
  'tiers_trees',
  'noise_curb_m',
  'lawn_m2',
];

function fullTitle(measure: EffectMeasure): string {
  return measure.title.replace(/, доля$/, '');
}

/** В строке - слово до двоеточия («Пылезащита»), расшифровка - в подсказке и для экранного
 *  диктора: подписи в две строки съедали первый экран прогона (жюри по дизайну, итерация 9). */
function title(measure: EffectMeasure): string {
  return fullTitle(measure).split(':')[0] ?? '';
}

const estimate = (measure: EffectMeasure): boolean => measure.note.includes('оценка');

function value(measure: EffectMeasure): string {
  if (measure.before == null && measure.after == null) return 'не определяется';
  const share = measure.unit === '%';
  const text = (v: number | null) => (v == null ? '-' : share ? plain(v) : integer(v));
  const unit = share ? ' %' : measure.unit === 'шт.' ? '' : ` ${measure.unit}`;
  // Оценка - знаком «≈» у значения, а не отдельной строкой пояснения.
  return `${estimate(measure) ? '≈ ' : ''}${text(measure.before)} → ${text(measure.after)}${unit}`;
}

/** Строка говорит о плане: «не определяется» и «0 → 0» ничего не сообщают, а на первом экране
 *  прогона стояли первыми (жюри по дизайну, итерация 8). Почему число не определено - в
 *  отчёте интерпретаций и в quality.json. */
function informative(measure: EffectMeasure): boolean {
  if (measure.before == null && measure.after == null) return false;
  return !(measure.before === 0 && measure.after === 0);
}

/** Баланс «было - стало»: существующие насаждения чертежа и они вместе с посадками плана.
 *  С индексом не смешивается: индекс оценивает план, этот блок описывает улицу. */
export function EffectBlock({ effect }: { effect: EffectJson | null | undefined }) {
  if (!effect?.measures) return null;
  const rows = SHOWN.map((key) => effect.measures.find((m) => m.key === key)).filter(
    (m): m is EffectMeasure => m != null && informative(m),
  );
  return (
    <section className="effect" aria-labelledby="effect-title">
      <h2 className="detail-heading" id="effect-title">
        Было → стало
      </h2>
      <ul className="effect-rows" aria-label="Что план даёт улице">
        {rows.map((m) => (
          <li key={m.key} title={[fullTitle(m), m.note, m.basis].filter(Boolean).join('. ')}>
            <span className="effect-name">
              {title(m)}
              {/* Расшифровка слышна диктору и без наведения: подпись короткая только для глаза. */}
              {title(m) !== fullTitle(m) ? (
                <span className="visually-hidden">{fullTitle(m).slice(title(m).length)}</span>
              ) : null}
            </span>
            <span className="effect-value">{value(m)}</span>
          </li>
        ))}
      </ul>
      <details className="fold effect-method">
        <summary>Что означают показатели</summary>
        <dl>
          {rows.map((m) => (
            <div key={m.key}>
              <dt>{fullTitle(m)}</dt>
              <dd>
                {m.note}
                {m.basis ? ` Основание: ${m.basis}.` : ''}
              </dd>
            </div>
          ))}
        </dl>
      </details>
      {effect.kinds.length ? (
        <details className="fold">
          <summary>Виды посадок: {effect.kinds.length}</summary>
          <ul className="effect-rows">
            {effect.kinds.map((k) => (
              <li key={k.key} title={k.basis}>
                <span className="effect-name">{k.title}</span>
                <span className="effect-value">
                  {k.area_m2 != null
                    ? `${integer(k.area_m2)} м²`
                    : k.length_m != null
                      ? `${integer(k.count)} шт., ${integer(k.length_m)} м`
                      : `${integer(k.count)} шт.`}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
