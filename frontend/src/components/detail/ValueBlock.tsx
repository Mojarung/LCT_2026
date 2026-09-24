import type { PlantingValue } from '../../api/artifacts';
import { meters, permille } from '../../lib/format';
import type { MapItem } from '../../map/types';

/** Строка слагаемого «пригодность вида» (quality/terms.py, fit): её число первым показывает
 *  «Почему этот вид», второй раз в той же панели оно только отнимает строку. */
const FIT_LINE = 'пригодность вида месту';

/** Чем ценна посадка: какое место её вклад в индекс качества занимает среди посадок плана и
 *  за счёт чего. Сам вклад - десятитысячные доли индекса, в промилле; знака ‰ в шрифте
 *  интерфейса нет, а место среди посадок читается без единиц. Число - в объяснении посадки. */
export function ValueBlock({
  value,
  speciesShown = false,
}: {
  value: PlantingValue | null;
  speciesShown?: boolean;
}) {
  if (!value) return null;
  const weak = speciesShown ? value.weak.filter((line) => !line.startsWith(FIT_LINE)) : value.weak;
  const { value: pm, zero } = permille(value.delta);
  const rank = value.percentile ? Math.round(value.percentile * 100) : null;
  // Слабое место - по порогу размера плана (flagged); у старых прогонов - любой минус.
  const worse = typeof value.flagged === 'boolean' ? value.flagged : pm < 0 && !zero;
  if (worse) {
    // Не «без неё план лучше»: посадка даёт зелень, но тянет вниз средний запас или
    // пригодность. Это слабое место, и чинится оно сдвигом или заменой вида.
    return (
      <>
        <h3 className="detail-heading">Слабое место</h3>
        <p className="value-delta bad">Вклад в индекс качества ниже среднего по плану.</p>
        {weak.length ? (
          <ul className="value-reasons">
            {weak.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : null}
        {value.reasons.length ? (
          <>
            <p className="detail-slack">Что даёт:</p>
            <ul className="value-reasons">
              {value.reasons.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </>
        ) : null}
      </>
    );
  }
  return (
    <>
      <h3 className="detail-heading">Чем ценна посадка</h3>
      <p className="value-delta">
        {zero ? (
          'Вклад в индекс качества около нуля.'
        ) : pm < 0 ? (
          'Вклад в индекс качества чуть ниже среднего по плану.'
        ) : rank ? (
          <>
            Вклад в индекс качества больше, чем у <b>{rank}%</b> посадок плана.
          </>
        ) : (
          'Вклад в индекс качества положительный.'
        )}
      </p>
      {value.reasons.length ? (
        <ul className="value-reasons">
          {value.reasons.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
      {weak.length ? (
        <>
          <p className="detail-slack">Слабее всего:</p>
          <ul className="value-reasons">
            {weak.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </>
      ) : null}
    </>
  );
}

/** Отказ, который снял бы прикорневой барьер: при каком условии и для каких деревьев. */
export function BarrierBlock({ item }: { item: MapItem }) {
  if (item.kind === 'placement' || item.barrier_m == null) return null;
  const distance = item.barrier_m;
  const height = distance < 1 ? 5 : 20;
  return (
    <>
      <h3 className="detail-heading">Возможно с прикорневым барьером</h3>
      <p className="detail-explain">
        До сети или бордюра {meters(distance)} м. С барьером (СП 42.13330.2016, табл. 9.1, прим. 5)
        здесь можно посадить дерево высотой до {height} м. Условие не выполнено: барьер в этом
        прогоне не заложен.
      </p>
    </>
  );
}
