import { useRef, useState } from 'react';
import { Link } from 'react-router';
import { createPortal } from 'react-dom';

import type { SourceConflict, SourceConflicts } from '../../api/artifacts';

const AREA_NAMES: Record<string, string> = {
  sidewalk: 'тротуар',
  road: 'проезжая часть',
  building: 'контур здания',
};

function conflictObjects(item: SourceConflict): string {
  return [...new Set(item.targets.map((t) => AREA_NAMES[t.object_class] ?? t.object_class))].join(
    ', ',
  );
}

function conflictLink(runId: string, item: SourceConflict): string {
  return `/runs/${encodeURIComponent(runId)}#x=${item.x}&y=${item.y}&m=0.06&conflict=${item.id}`;
}

interface Props {
  report?: SourceConflicts | null;
  runId: string;
  onFocus?: (item: SourceConflict) => void;
  selected?: string | null;
  visible?: boolean;
  onVisibilityChange?: (visible: boolean) => void;
}

export function SourceConflictNotice({
  report,
  runId,
  onFocus,
  selected,
  visible = true,
  onVisibilityChange,
}: Props) {
  const [limit, setLimit] = useState(30);
  const dialog = useRef<HTMLDialogElement>(null);
  if (!report) return null;
  const count = report.items.length;
  const first = report.items[0];
  const scope = (
    <>
      <p>
        Проверены положения {report.checked_trees} деревьев и {report.checked_areas} замкнутых
        контуров. Вырезы в покрытии учитываются; касания границ и неопределённые полосы насаждений
        не считаются конфликтом.
      </p>
      <p>
        Открытые линии, кроны и предполагаемое покрытие по подписям не подтверждают пересечение
        ствола. Проверка зависит от распознавания объектов исходника.
      </p>
      {report.basis === 'saved_basemap' ? (
        <p>
          Этот прогон проверен по сохранённой подоснове, которая могла быть упрощена. Для проверки
          полной исходной геометрии запустите новый прогон.
        </p>
      ) : null}
    </>
  );
  if (!count)
    return (
      <details className="fold source-conflicts-clear">
        <summary>Проверка пересечений подосновы</summary>
        <p>
          {!report.checked_trees || !report.checked_areas
            ? 'Недостаточно распознанных деревьев или замкнутых контуров для проверки пересечений.'
            : 'В проверенных контурах пересечений со стволами не найдено.'}
        </p>
        {scope}
      </details>
    );
  return (
    <>
      <button
        type="button"
        className="source-conflicts-trigger"
        onClick={() => {
          dialog.current?.showModal();
        }}
      >
        Конфликты подосновы · {count}
      </button>
      {createPortal(
        <dialog ref={dialog} className="source-conflicts-dialog" aria-label="Конфликты подосновы">
          <form method="dialog" className="source-conflicts-close">
            <button type="submit" aria-label="Закрыть конфликты подосновы">
              Закрыть ×
            </button>
          </form>
          <section className="source-conflicts">
            <h3 className="notice-title">Деревья пересекаются с покрытием или зданием · {count}</h3>
            <p>
              В исходных данных положения существующих деревьев попали внутрь этих контуров.
              Проверьте слои и решение по сохранению дерева: лунку, изменение покрытия или
              согласованный перенос.
            </p>
            <p>Это предупреждение о подоснове. Оно не означает, что дерево нужно удалить.</p>
            {onVisibilityChange ? (
              <label className="source-conflicts-toggle">
                <input
                  type="checkbox"
                  checked={visible}
                  onChange={(e) => {
                    onVisibilityChange(e.target.checked);
                  }}
                />
                Отметки конфликтов на плане
              </label>
            ) : first ? (
              <Link
                to={conflictLink(runId, first)}
                onClick={() => {
                  dialog.current?.close();
                }}
              >
                Показать конфликты на плане
              </Link>
            ) : null}
            {onFocus ? (
              <details className="fold">
                <summary>Показать места · {count}</summary>
                <ol className="source-conflict-list">
                  {report.items.slice(0, limit).map((item, i) => (
                    <li key={item.id}>
                      <button
                        type="button"
                        className="source-conflict-focus"
                        aria-pressed={selected === item.id}
                        onClick={() => {
                          dialog.current?.close();
                          onFocus(item);
                        }}
                      >
                        Место {i + 1}: {conflictObjects(item)}
                      </button>
                      <details>
                        <summary>Координаты и слои</summary>
                        <p>
                          X {item.x.toFixed(2)}, Y {item.y.toFixed(2)} м
                        </p>
                        <ul>
                          {[...new Set(item.targets.map((t) => t.layer).filter(Boolean))].map(
                            (layer) => (
                              <li key={layer}>{layer}</li>
                            ),
                          )}
                        </ul>
                        <a
                          href={conflictLink(runId, item)}
                          onClick={() => {
                            dialog.current?.close();
                          }}
                        >
                          Ссылка на это место
                        </a>
                      </details>
                    </li>
                  ))}
                </ol>
                {limit < count ? (
                  <button
                    type="button"
                    onClick={() => {
                      setLimit((n) => n + 30);
                    }}
                  >
                    Ещё места
                  </button>
                ) : null}
              </details>
            ) : null}
            <details className="fold">
              <summary>Что проверено</summary>
              {scope}
            </details>
          </section>
        </dialog>,
        document.body,
      )}
    </>
  );
}
