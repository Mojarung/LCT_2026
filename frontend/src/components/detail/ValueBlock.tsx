import type { PlantingValue } from '../../api/artifacts';
import { permille } from '../../lib/format';
import type { MapItem } from '../../map/types';
import { meters } from '../../lib/format';

/** Чем ценна посадка: насколько упадёт индекс качества без неё и за счёт чего. */
export function ValueBlock({ value }: { value: PlantingValue | null }) {
  if (!value) return null;
  const { value: pm, text, zero } = permille(value.delta);
  const rank =
    pm > 0 && !zero && value.percentile
      ? ` Больше, чем у ${String(Math.round(value.percentile * 100))}% посадок плана.`
      : '';
  // Слабое место - по порогу размера плана (flagged); у старых прогонов - любой минус.
  const worse = typeof value.flagged === 'boolean' ? value.flagged : pm < 0 && !zero;
  if (worse) {
    // Не «без неё план лучше»: посадка даёт зелень, но тянет вниз средний запас или
    // пригодность. Это слабое место, и чинится оно сдвигом или заменой вида.
    return (
      <>
        <h3 className="detail-heading">Слабое место</h3>
        <p className="value-delta bad">
          Вклад в индекс качества <b>{text}</b>: посадка слабее среднего по плану.
        </p>
        {value.weak.length ? (
          <ul className="value-reasons">
            {value.weak.map((line) => (
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
          <>
            Вклад в индекс качества <b>{text}</b>: чуть ниже среднего по плану.
          </>
        ) : (
          <>
            Вклад в индекс качества <b>{text}</b>.{rank}
          </>
        )}
      </p>
      {value.reasons.length ? (
        <ul className="value-reasons">
          {value.reasons.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
      {value.weak.length ? (
        <>
          <p className="detail-slack">Слабее всего:</p>
          <ul className="value-reasons">
            {value.weak.map((line) => (
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
