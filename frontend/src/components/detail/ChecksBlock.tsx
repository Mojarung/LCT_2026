import type { Rule, RuleCheck } from '../../api/artifacts';
import { splitChecks, whatFor } from '../../lib/checks';
import { meters, plural } from '../../lib/format';
import { clauseNumber } from '../../lib/quotes';
import { QuoteBlock } from './QuoteBlock';

interface RowProps {
  check: RuleCheck;
  rules: Record<string, Rule>;
  quote?: boolean;
}

/** Строка проверки: до чего мерили, замер против нормы, правило и пункт акта, цитата. */
export function CheckRow({ check, rules, quote = false }: RowProps) {
  const rule = rules[check.rule_id];
  const measured = check.measured_m == null ? null : meters(check.measured_m);
  const threshold = check.threshold_m == null ? null : meters(check.threshold_m);
  const failed = check.outcome === 'fail';
  const act = [rule?.act_short || rule?.act_id, rule ? clauseNumber(rule) : '']
    .filter(Boolean)
    .join(', ');
  const norm = threshold ? `норма ${threshold} м` : '';
  return (
    <li className={`check-item${failed ? ' failed' : ''}`}>
      <div className="check-rule">
        <span className="check-what">до {whatFor(check, rules)}</span>
        <span className="check-dist">{measured ? `${measured} м` : norm}</span>
      </div>
      <p className="check-clause">
        <span className="check-id">{check.rule_id}</span>
        {measured && norm ? `, ${norm}` : ''}
        {act ? `. ${act}` : ''}
      </p>
      {quote ? <QuoteBlock rule={rule} /> : null}
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
        {lead.map((check) => (
          <CheckRow key={check.rule_id} check={check} rules={rules} quote />
        ))}
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
          <summary>
            Ещё {hidden.length} {plural(hidden.length, 'проверка', 'проверки', 'проверок')}
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
              Из них {absent}: такого объекта в чертеже нет, норма проверена, ограничивать нечему.
            </p>
          ) : null}
        </details>
      ) : null}
    </>
  );
}
