import type { QualityJson } from '../../api/artifacts';
import { decimal, plural } from '../../lib/format';

/** Индекс качества плана: оценка, слагаемые с тем, что измерено, и основание каждого.
 *  Веса - выбор команды, и это сказано рядом с каждым слагаемым. */
export function QualityBlock({ quality }: { quality: QualityJson | undefined }) {
  if (!quality?.terms) return null;
  // Первая строка сводки - оценка или причина, по которой её нет: она уже стоит выше.
  const lines = (quality.summary ?? []).slice(1);
  return (
    <section className="quality" aria-labelledby="quality-title">
      <h2 className="detail-heading" id="quality-title">
        Качество плана
      </h2>
      {quality.index == null ? (
        <p className="quality-gate">{quality.gate}</p>
      ) : (
        <p className="quality-index">
          <b>{decimal(quality.index)}</b> из 1
        </p>
      )}
      {/* Итог стоит числом, разбор - под раскрытием: десять слагаемых со шкалами занимали
          панель целиком, и состав плана уходил за нижний край на высоте проектора. */}
      <details className="fold quality-fold">
        <summary>
          Разбор: {quality.terms.length}{' '}
          {plural(quality.terms.length, 'слагаемое', 'слагаемых', 'слагаемых')}
        </summary>
        <ul className="quality-terms">
          {quality.terms.map((term) => (
            <li key={term.key}>
              <details className={`term${term.score == null ? ' term-none' : ''}`}>
                <summary>
                  <span className="term-name">{term.title}</span>
                  <span className="term-score">
                    {term.score == null ? 'нет' : decimal(term.score)}
                  </span>
                  <span className="term-bar" aria-hidden="true">
                    <i style={{ width: `${String(Math.round((term.score ?? 0) * 100))}%` }} />
                  </span>
                </summary>
                <p className="term-note">{term.note}</p>
                <p className="term-basis">
                  {term.basis}
                  {term.score == null
                    ? ''
                    : `. Вес ${String(Math.round(term.weight * 100))}%, выбор команды.`}
                </p>
              </details>
            </li>
          ))}
        </ul>
        {lines.length ? (
          <div className="quality-summary">
            {lines.map((line) => (
              <p key={line}>{line}</p>
            ))}
          </div>
        ) : null}
      </details>
    </section>
  );
}
