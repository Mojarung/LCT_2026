import { integer, plural } from '../../lib/format';
import {
  ASSIGNABLE,
  className,
  evidenceName,
  groupNeedsReview,
  type ClassificationJson,
  type ReviewGeometry,
} from '../../lib/review';

const GEOMETRY_NAMES: Record<string, string> = {
  Point: 'Точка',
  MultiPoint: 'Точки',
  LineString: 'Линия',
  MultiLineString: 'Линии',
  Polygon: 'Площадь',
  MultiPolygon: 'Площади',
};

/** Каждая строка — однородная группа, а назначения сохраняются по точным ссылкам объектов. */
export function ReviewGroupTable({
  data,
  report,
  order,
  members,
  assignments,
  selected,
  onSelect,
  onAssign,
}: {
  data: ReviewGeometry;
  report: ClassificationJson;
  order: number[];
  members: number[][];
  assignments: Readonly<Record<string, string>>;
  selected: number;
  onSelect: (group: number) => void;
  onAssign: (group: number, value: string) => void;
}) {
  return (
    <div
      className="review-table-scroll"
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Scroll region must accept keyboard focus.
      tabIndex={0}
      role="region"
      aria-label="Таблица типов объектов"
    >
      <table className="review-table">
        <caption>
          Объекты по слоям{' '}
          <span>
            · {integer(order.length)} {plural(order.length, 'группа', 'группы', 'групп')}
          </span>
        </caption>
        <thead>
          <tr>
            <th scope="col">Слой / блок</th>
            <th scope="col">Сейчас в расчёте</th>
            <th scope="col">Новый тип</th>
          </tr>
        </thead>
        <tbody>
          {order.map((index) => {
            const item = report.groups[index];
            if (!item) return null;
            const refs = (members[index] ?? []).flatMap((i) => data.features[i]?.id ?? []);
            const drafts = refs.flatMap((id) => (assignments[id] ? [assignments[id]] : []));
            const values = new Set(drafts);
            const uniform = drafts.length === refs.length && values.size === 1;
            const value = uniform ? drafts[0] : drafts.length ? 'mixed' : '';
            const pending = groupNeedsReview(item);
            const rowName = `${item.layer}, группа ${index + 1}`;
            const hint =
              item.llm_hint && ASSIGNABLE.includes(item.llm_hint.suggestion) ? item.llm_hint : null;
            return (
              <tr
                key={index}
                className={selected === index ? 'is-selected' : undefined}
                onClick={(event) => {
                  if (
                    event.target instanceof Element &&
                    event.target.closest('button, select, input, a')
                  )
                    return;
                  onSelect(index);
                }}
              >
                <th scope="row">
                  <button
                    type="button"
                    className="review-layer"
                    aria-pressed={selected === index}
                    aria-label={`Показать слой ${rowName}`}
                    onClick={() => {
                      onSelect(index);
                    }}
                  >
                    {item.layer}
                  </button>
                  <span className="review-cell-note">
                    {item.block ? `Блок: ${item.block} · ` : ''}
                    {GEOMETRY_NAMES[item.geometry] ?? item.geometry} · {integer(item.features)} шт.
                  </span>
                </th>
                <td>
                  <span>{className(item.object_class)}</span>
                  <span
                    className={`review-cell-note${pending && drafts.length !== refs.length ? ' needs-review' : ''}`}
                  >
                    {drafts.length
                      ? `К применению: ${drafts.length} из ${refs.length}`
                      : pending
                        ? 'Требует уточнения'
                        : item.evidence.method.startsWith('explicit_')
                          ? 'Уточнено ранее'
                          : 'Распознано'}
                  </span>
                  <span className="review-cell-note">
                    {item.review_reason ?? evidenceName(item.evidence.method)}
                  </span>
                </td>
                <td>
                  <select
                    aria-label={`Новый тип: ${rowName}`}
                    value={value}
                    disabled={!refs.length}
                    onChange={(event) => {
                      onAssign(index, event.target.value);
                    }}
                  >
                    <option value="">Без изменений</option>
                    {value === 'mixed' ? (
                      <option value="mixed" disabled>
                        Разные назначения
                      </option>
                    ) : null}
                    {ASSIGNABLE.map((kind) => (
                      <option key={kind} value={kind}>
                        {className(kind)}
                      </option>
                    ))}
                  </select>
                  {drafts.length ? (
                    <button
                      type="button"
                      className="ghost small review-row-reset"
                      aria-label={`Отменить изменения: ${rowName}`}
                      onClick={() => {
                        onAssign(index, '');
                      }}
                    >
                      Отменить
                    </button>
                  ) : pending && ASSIGNABLE.includes(item.object_class) ? (
                    <button
                      type="button"
                      className="ghost small review-row-reset"
                      aria-label={`Подтвердить тип: ${rowName}`}
                      onClick={() => {
                        onAssign(index, item.object_class);
                      }}
                    >
                      Подтвердить текущий
                    </button>
                  ) : null}
                  {hint && value !== hint.suggestion ? (
                    <>
                      <span className="review-cell-note">
                        Модель {hint.model} предлагает: {className(hint.suggestion)} (
                        {hint.confidence.toLocaleString('ru-RU', { maximumFractionDigits: 2 })})
                      </span>
                      <button
                        type="button"
                        className="ghost small review-row-reset"
                        aria-label={`Принять подсказку: ${rowName}`}
                        onClick={() => {
                          onAssign(index, hint.suggestion);
                        }}
                      >
                        Принять подсказку
                      </button>
                    </>
                  ) : null}
                </td>
              </tr>
            );
          })}
          {!order.length ? (
            <tr>
              <td colSpan={3}>Подходящих групп нет. Измените поиск или фильтр.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
