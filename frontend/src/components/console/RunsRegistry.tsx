import { type FocusEvent, type KeyboardEvent, useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router';

import { useDeleteRun, useRuns } from '../../api/queries';
import type { RunOut } from '../../api/types';
import { drawingName, integer, stamp } from '../../lib/format';
import { IconDelete } from '../icons';

export const RECENT_LIMIT = 12;

const STATE_RU: Record<string, string> = {
  queued: 'в очереди',
  running: 'считается',
  succeeded: 'готов',
  failed: 'не удался',
};

/** Удалить можно только законченный прогон: идущий сервер не отдаст (409). */
const FINISHED = new Set<string>(['succeeded', 'failed']);

function placements(run: RunOut): string {
  const value = run.summary?.placements;
  return typeof value === 'number' ? integer(value) : '-';
}

/** Строка реестра. Удаление - в два клика: значок корзины раскрывает под строкой панель
 *  подтверждения, фокус переходит на «Точно удалить?», второй клик удаляет. Браузерный
 *  confirm не берём: он блокирует страницу и автоматическую проверку. Панель - отдельной
 *  строкой на всю ширину, а не в ячейке: кнопки в ячейке раздвигали таблицу за край панели
 *  и резали имя чертежа до трёх букв. Escape, «Отмена» и уход фокуса снимают подтверждение. */
function RunRow({ run }: { run: RunOut }) {
  const [armed, setArmed] = useState(false);
  const remove = useDeleteRun();
  const trash = useRef<HTMLButtonElement>(null);
  const confirm = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const name = drawingName(run.source_name);
  const finished = FINISHED.has(run.state);

  useEffect(() => {
    if (armed) confirm.current?.focus();
  }, [armed]);

  const disarm = () => {
    setArmed(false);
    trash.current?.focus();
  };
  const erase = () => {
    if (remove.isPending) return;
    remove.mutate(run.id, { onError: disarm });
  };
  // Фокус ушёл и с корзины, и с панели (к другой строке, в форму) - подтверждение снимается.
  const leave = (event: FocusEvent<HTMLButtonElement>) => {
    const next = event.relatedTarget;
    if (remove.isPending || next === trash.current || panel.current?.contains(next)) return;
    setArmed(false);
  };
  const escape = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'Escape') disarm();
  };

  return (
    <>
      <tr className={armed ? 'armed' : undefined}>
        <td className={`state state-${run.state}`} title={STATE_RU[run.state]}>
          <span className="visually-hidden">{STATE_RU[run.state]}</span>
        </td>
        <td className="name">
          <Link to={`/runs/${run.id}`} title={run.source_name}>
            {name}
          </Link>
        </td>
        <td className="mono">{run.profile}</td>
        <td className="mono num">{placements(run)}</td>
        <td className="mono num nowrap">
          <time dateTime={run.created_at}>{stamp(run.created_at)}</time>
        </td>
        <td className="act">
          {finished && (
            <button
              ref={trash}
              type="button"
              className="row-action"
              aria-label={`Удалить прогон ${name}`}
              aria-expanded={armed}
              aria-controls={armed ? panelId : undefined}
              title="Удалить прогон"
              onClick={() => {
                setArmed(!armed);
              }}
              onBlur={leave}
              onKeyDown={escape}
            >
              <IconDelete />
            </button>
          )}
        </td>
      </tr>
      {armed && (
        <tr className="row-confirm">
          <td colSpan={6}>
            <div className="confirm-panel" id={panelId} ref={panel}>
              <span className="confirm-text">Файлы прогона удалятся без возврата.</span>
              <span className="confirm-buttons">
                <button
                  ref={confirm}
                  type="button"
                  className="row-action danger"
                  aria-label={remove.isPending ? undefined : `Точно удалить прогон ${name}?`}
                  aria-busy={remove.isPending}
                  onClick={erase}
                  onBlur={leave}
                  onKeyDown={escape}
                >
                  {remove.isPending ? 'Удаляем…' : 'Точно удалить?'}
                </button>
                <button
                  type="button"
                  className="row-action"
                  onClick={disarm}
                  onBlur={leave}
                  onKeyDown={escape}
                >
                  Отмена
                </button>
              </span>
            </div>
          </td>
        </tr>
      )}
      {remove.isError && (
        <tr className="row-note">
          <td colSpan={6}>
            <span role="alert">Прогон не удалён: {remove.error.message}</span>
          </td>
        </tr>
      )}
    </>
  );
}

export function RunsRegistry() {
  const runs = useRuns(RECENT_LIMIT);

  if (runs.isPending) {
    return <p className="empty">Загружаем прогоны…</p>;
  }
  if (runs.isError) {
    return <p className="empty">Список прогонов не загрузился: {runs.error.message}</p>;
  }
  if (!runs.data.length) {
    return (
      <div className="empty">
        <p>Прогонов ещё не было.</p>
        <p className="hint">Первый появится здесь через несколько секунд после запуска.</p>
      </div>
    );
  }
  return (
    <table className="registry">
      <thead>
        <tr>
          <th scope="col">
            <span className="visually-hidden">состояние</span>
          </th>
          <th scope="col">чертёж</th>
          <th scope="col">профиль</th>
          <th scope="col" className="num">
            посадок
          </th>
          <th scope="col" className="num">
            когда
          </th>
          <th scope="col">
            <span className="visually-hidden">действия</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {runs.data.map((run) => (
          <RunRow key={run.id} run={run} />
        ))}
      </tbody>
    </table>
  );
}
