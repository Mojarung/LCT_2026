import type { Assortment, AssortmentReason } from '../../api/artifacts';
import { runnersText } from '../../lib/alternatives';
import { plural } from '../../lib/format';

/** Сколько оснований видно сразу: остальные под раскрытием, как проверки норм. */
const LEAD = 3;
/** Нормы решают выбор, справочник и практика пилота его подкрепляют. */
const ORDER: Record<string, number> = { norm: 0, reference: 1, pilot: 2 };

const rank = (reason: AssortmentReason) => ORDER[reason.kind] ?? 3;

function Reason({ reason }: { reason: AssortmentReason }) {
  return (
    <li>
      {reason.text}
      {reason.rule_id ? <span className="check-id"> {reason.rule_id}</span> : null}
    </li>
  );
}

/** Почему посажен этот вид, а не другой: пригодность, основания по нормам и справочнику,
 *  ближайшие альтернативы. Норма объясняет место, этот блок - выбор растения; эксперт ДПиООС
 *  спрашивает оба. «Оценка ниже» у альтернативы не печатается: это следует из процентов. */
export function SpeciesBlock({ assortment }: { assortment: Assortment | null | undefined }) {
  if (!assortment) return null;
  const reasons = [...assortment.reasons].sort((a, b) => rank(a) - rank(b));
  const lead = reasons.slice(0, LEAD);
  const rest = reasons.slice(LEAD);
  const runners = assortment.alternatives.slice(0, 3);
  return (
    <>
      <h3 className="detail-heading">Почему этот вид</h3>
      <p className="detail-slack">
        Пригодность месту <b>{assortment.percent}%</b>
      </p>
      {lead.length ? (
        <ul className="value-reasons" aria-label="Основания выбора вида">
          {lead.map((reason) => (
            <Reason key={`${reason.kind}:${reason.text}`} reason={reason} />
          ))}
        </ul>
      ) : null}
      {rest.length ? (
        <details className="detail-full">
          <summary>
            Ещё {rest.length} {plural(rest.length, 'основание', 'основания', 'оснований')}
          </summary>
          <ul className="value-reasons">
            {rest.map((reason) => (
              <Reason key={`${reason.kind}:${reason.text}`} reason={reason} />
            ))}
          </ul>
        </details>
      ) : null}
      {runners.length ? (
        <p className="detail-slack">Рядом по оценке: {runnersText(runners)}.</p>
      ) : null}
    </>
  );
}
