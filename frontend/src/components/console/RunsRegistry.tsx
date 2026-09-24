import { Link } from 'react-router';

import { useRuns } from '../../api/queries';
import type { RunOut } from '../../api/types';
import { integer, stamp } from '../../lib/format';

export const RECENT_LIMIT = 12;

const STATE_RU: Record<string, string> = {
  queued: 'в очереди',
  running: 'считается',
  succeeded: 'готов',
  failed: 'не удался',
};

function placements(run: RunOut): string {
  const value = run.summary?.placements;
  return typeof value === 'number' ? integer(value) : '-';
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
        </tr>
      </thead>
      <tbody>
        {runs.data.map((run) => (
          <tr key={run.id}>
            <td className={`state state-${run.state}`} title={STATE_RU[run.state]}>
              <span className="visually-hidden">{STATE_RU[run.state]}</span>
            </td>
            <td className="name">
              <Link to={`/runs/${run.id}`} title={run.source_name}>
                {run.source_name}
              </Link>
            </td>
            <td className="mono">{run.profile}</td>
            <td className="mono num">{placements(run)}</td>
            <td className="mono num nowrap">
              <time dateTime={run.created_at}>{stamp(run.created_at)}</time>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
