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

function title(measure: EffectMeasure): string {
  return measure.title.replace(/, доля$/, '');
}

function value(measure: EffectMeasure): string {
  if (measure.before == null && measure.after == null) return 'не определяется';
  const share = measure.unit === '%';
  const text = (v: number | null) => (v == null ? '-' : share ? plain(v) : integer(v));
  const unit = share ? ' %' : measure.unit === 'шт.' ? '' : ` ${measure.unit}`;
  return `${text(measure.before)} → ${text(measure.after)}${unit}`;
}

function shownNote(measure: EffectMeasure): string {
  const unknown = measure.before == null && measure.after == null;
  return unknown || measure.note.includes('оценка') ? measure.note : '';
}

/** Баланс «было - стало»: существующие насаждения чертежа и они вместе с посадками плана.
 *  С индексом не смешивается: индекс оценивает план, этот блок описывает улицу. */
export function EffectBlock({ effect }: { effect: EffectJson | null | undefined }) {
  if (!effect?.measures) return null;
  const rows = SHOWN.map((key) => effect.measures.find((m) => m.key === key)).filter(
    (m): m is EffectMeasure => m != null,
  );
  return (
    <section className="effect" aria-labelledby="effect-title">
      <h2 className="detail-heading" id="effect-title">
        Было → стало
      </h2>
      <p className="term-note">
        Существующие насаждения и они вместе с посадками плана. Вырубку сервис не назначает.
      </p>
      <ul className="effect-rows" aria-label="Что план даёт улице">
        {rows.map((m) => (
          <li key={m.key} title={m.basis}>
            <span className="effect-name">{title(m)}</span>
            <span className="effect-value">{value(m)}</span>
            {/* Почему «не определяется» и где число - оценка: видно без наведения, с касания и
                с клавиатуры, а не только во всплывающей подсказке. */}
            {shownNote(m) ? <span className="effect-note">{shownNote(m)}</span> : null}
          </li>
        ))}
      </ul>
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
