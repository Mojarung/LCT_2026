import { Link } from 'react-router';

import { useRuns } from '../../api/queries';
import { drawingName, integer, plural, stamp } from '../../lib/format';
import { RECENT_LIMIT } from './RunsRegistry';

const SHOWN = 3;

/** Последние готовые прогоны под формой запуска: открыть готовый план - одно нажатие с
 *  первого экрана, без поиска по реестру ниже. Пока готовых нет, блока нет. */
export function RecentRuns() {
  const runs = useRuns(RECENT_LIMIT);
  const done = (runs.data ?? []).filter((run) => run.state === 'succeeded').slice(0, SHOWN);
  if (!done.length) return null;
  return (
    <section className="recent" aria-labelledby="recent-title">
      <h2 className="recent-title" id="recent-title">
        Открыть готовый план
      </h2>
      <ul>
        {done.map((run) => {
          const count = run.summary?.placements;
          return (
            <li key={run.id}>
              <Link to={`/runs/${encodeURIComponent(run.id)}`} viewTransition>
                <span className="recent-name">{drawingName(run.source_name)}</span>
                <span className="recent-meta">
                  {typeof count === 'number'
                    ? `${integer(count)} ${plural(count, 'посадка', 'посадки', 'посадок')} · `
                    : ''}
                  {stamp(run.created_at)}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
