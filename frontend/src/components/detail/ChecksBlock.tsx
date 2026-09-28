import type { Rule, RuleCheck } from '../../api/artifacts';
import { groupSameMeasure, splitChecks, whatFor } from '../../lib/checks';
import { meters, plural } from '../../lib/format';
import { clauseNumber } from '../../lib/quotes';
import { QuoteBlock } from './QuoteBlock';

interface RowProps {
  check: RuleCheck;
  rules: Record<string, Rule>;
  quote?: boolean;
  /** Другие правила с тем же замером до того же объекта: одна строка, все основания. */
  also?: readonly RuleCheck[];
}

/** Правило, норма и пункт акта одной строкой через «·». */
function Clause({ check, rules }: { check: RuleCheck; rules: Record<string, Rule> }) {
  const rule = rules[check.rule_id];
  const threshold = check.threshold_m == null ? null : meters(check.threshold_m);
  const norm = threshold ? `норма ${threshold} м` : '';
  const act = [rule?.act_short || rule?.act_id, rule ? clauseNumber(rule) : '']
    .filter(Boolean)
    .join(', ');
  return (
    // Части через «·»: «норма 2,00 м. параметр проекта» читалось как предложение со строчной
    // буквы после точки (жюри по дизайну, итерация 8).
    <p className="check-clause">
      <span className="check-id">{check.rule_id}</span>
      {check.measured_m != null && norm ? ` · ${norm}` : ''}
      {act ? ` · ${act}` : ''}
    </p>
  );
}

/** Строка проверки: до чего мерили, замер против нормы, правило и пункт акта, цитата. */
export function CheckRow({ check, rules, quote = false, also = [] }: RowProps) {
  const measured = check.measured_m == null ? null : meters(check.measured_m);
  const threshold = check.threshold_m == null ? null : meters(check.threshold_m);
  const failed = [check, ...also].some((c) => c.outcome === 'fail');
  return (
    <li className={`check-item${failed ? ' failed' : ''}`}>
      <div className="check-rule">
        <span className="check-what">до {whatFor(check, rules)}</span>
        <span className="check-dist">
          {measured ? `${measured} м` : threshold ? `норма ${threshold} м` : ''}
        </span>
      </div>
      {[check, ...also].map((c) => (
        <div key={c.rule_id}>
          <Clause check={c} rules={rules} />
          {quote ? <QuoteBlock rule={rules[c.rule_id]} /> : null}
        </div>
      ))}
    </li>
  );
}

/** Нормы у посадки: то, что ограничивало решение, - наверху, остальное - под раскрытием.
 *  У посадки два десятка проверенных правил, и напечатанные подряд они прячут единственное,
 *  что действительно решало. */
export function ChecksBlock({
  checks,
  rules,
}: {
  checks: RuleCheck[];
  rules: Record<string, Rule>;
}) {
  if (!checks.length) return <p className="detail-slack">Проверенных правил не записано.</p>;
  const { lead, hidden, restSlack } = splitChecks(checks);
  const failing = lead.some((c) => c.outcome === 'fail');
  const withFact = hidden.filter((c) => c.measured_m != null);
  const absent = hidden.length - withFact.length;
  const slack = restSlack ? Math.round(restSlack) : 0;
  return (
    <>
      {/* «Ближе всего к норме», а не «ближайшее»: это правило с наименьшим запасом, и оно может
          относиться к объекту за полсотни метров - важно отношение, а не расстояние. */}
      <h3 className="detail-heading">{failing ? 'Нарушено' : 'Ближе всего к норме'}</h3>
      <ul className="checks">
        {groupSameMeasure(lead).map(([check, ...also]) =>
          check ? (
            <CheckRow key={check.rule_id} check={check} also={also} rules={rules} quote />
          ) : null,
        )}
      </ul>
      {!failing && hidden.length ? (
        <p className="detail-slack">
          Проверено ещё {hidden.length} {plural(hidden.length, 'норма', 'нормы', 'норм')}
          {slack > 1 ? (
            <>
              , наименьший запас у них <b>{slack}</b>-кратный
            </>
          ) : null}
          .
        </p>
      ) : null}
      {hidden.length ? (
        <details className="detail-full">
          {/* Число уже названо строкой выше, когда нарушений нет: второй раз оно не нужно. */}
          <summary>
            {!failing
              ? 'Остальные проверки'
              : `Ещё ${String(hidden.length)} ${plural(hidden.length, 'проверка', 'проверки', 'проверок')}`}
          </summary>
          <ul className="checks" style={{ marginTop: 12 }}>
            {withFact.map((check) => (
              <CheckRow key={check.rule_id} check={check} rules={rules} />
            ))}
          </ul>
          {/* Правила без замера («до трамвайных путей норма 5,00 м») не печатаются: объекта нет
              в чертеже. Но из счёта они не исчезают - иначе «проверено 22» и список из 14 строк
              спорят друг с другом. */}
          {absent ? (
            <p className="detail-slack">
              Из них {absent}: объекта нет в чертеже, ограничивать нечему.
            </p>
          ) : null}
        </details>
      ) : null}
    </>
  );
}
