/* Части левой панели прогона и подложки карты: шапка, сводка, предупреждения, статус. */

import { Link } from 'react-router';

import type { RunOut } from '../../api/types';
import { integer, plural } from '../../lib/format';
import { overrideLabel } from '../../lib/overrides';
import { keyNotices } from '../../lib/warnings';
import { useWorkspace } from '../../state/workspace';
import { IconChevron } from '../icons';

const num = (value: unknown): number => (typeof value === 'number' ? value : 0);

/** Свернуть панель - значок в её верхнем углу. Свёрнутая панель остаётся одной кнопкой, и вся
 *  ширина экрана уходит плану: на ленте улицы это решает, видно чертёж или нет. */
export function PanelToggle({ panel, label }: { panel: 'left' | 'right'; label: string }) {
  const collapsed = useWorkspace((s) => s.panels[panel]);
  const toggle = useWorkspace((s) => s.togglePanel);
  return (
    <button
      type="button"
      className="panel-toggle"
      aria-expanded={!collapsed}
      title={collapsed ? 'Развернуть панель' : 'Свернуть панель'}
      aria-label={`${collapsed ? 'Развернуть' : 'Свернуть'} ${label}`}
      onClick={() => {
        toggle(panel);
      }}
    >
      <IconChevron direction={panel} />
    </button>
  );
}

/** Имя чертежа без расширения: «.dxf» в заголовке каждого прогона ничего не различает.
 *  Пробел перед дефисом неразрывный: заголовок не повисает строкой, начатой с дефиса. */
const stem = (name: string) => name.replace(/\.(dxf|dwg)$/i, '').replaceAll(' - ', '\u00a0- ');

export function RunHeader({ run }: { run: RunOut }) {
  return (
    <div className="hud-head">
      <Link className="back" to="/">
        ← все прогоны
      </Link>
      <h1 title={run.source_name}>{stem(run.source_name)}</h1>
      <p className="run-sub">
        <span>{run.profile}</span>
        <span>{run.id.slice(0, 8)}</span>
        {Object.entries(run.overrides).map(([key, value]) => (
          <span key={key}>{overrideLabel(key, value)}</span>
        ))}
      </p>
    </div>
  );
}

/** Сводка: одно число крупно, остальное строкой под ним. Предупреждения, меняющие смысл плана,
 *  стоят рядом с числом: иначе «18 780 посадок» читается как результат работы, а не как
 *  следствие того, что участок ничем не ограничен. Индекс качества здесь не повторяется: он
 *  стоит крупно в правой панели на том же экране. Остальные записи прогона - под раскрытием
 *  «Как собран план»: это журнал приёмов и подбора, а не тревоги. */
export function RunMetrics({ run }: { run: RunOut }) {
  const summary = run.summary ?? {};
  const total = num(summary.placements);
  const approval = num(summary.needs_approval);
  const rejected = num(summary.rejections);
  const integrity = summary.integrity_ok === true;
  const stats = (summary.stats ?? {}) as Record<string, unknown>;
  const barrierPlaces = num(stats.barrier_places);
  const warnings = Array.isArray(summary.warnings) ? summary.warnings.map(String) : [];
  const notices = keyNotices(warnings);
  return (
    <>
      <p className="metric">
        <b>{integer(total)}</b>
        <span>
          {plural(total, 'посадка', 'посадки', 'посадок')} в плане
          {approval ? (
            `, ${integer(approval)} на согласование`
          ) : (
            <>
              , <em>все без ограничений</em>
            </>
          )}
        </span>
      </p>
      <p className="metric-sub">
        <b>{integer(rejected)}</b>{' '}
        {plural(rejected, 'место отклонено', 'места отклонено', 'мест отклонено')}. Подоснова{' '}
        <em className={integrity ? undefined : 'bad'}>{integrity ? 'цела' : 'нарушена'}</em>
      </p>
      {barrierPlaces ? (
        <p className="metric-sub quality-line">
          <b>{integer(barrierPlaces)}</b>{' '}
          {plural(barrierPlaces, 'место станет', 'места станут', 'мест станут')} допустимыми с
          прикорневым барьером
        </p>
      ) : null}
      {notices.length ? (
        <div className="notice">
          {notices.map((text) => (
            <p key={text}>{text}</p>
          ))}
        </div>
      ) : null}
      {warnings.length ? (
        <details className="hud-block fold">
          <summary>Как собран план: {warnings.length}</summary>
          <ul className="warn-list">
            {warnings.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </>
  );
}

/** Подложка, пока карте нечего показать: ход, причина неудачи или «загружаем». */
export function RunStatus({ run }: { run: RunOut }) {
  if (run.state === 'queued' || run.state === 'running') {
    const title =
      run.state === 'queued'
        ? 'В очереди'
        : run.progress?.stage
          ? run.progress.title
          : 'Читаем чертёж';
    return (
      <div className="status" data-state={run.state}>
        <span className="spinner" aria-hidden="true" />
        <div>
          <p className="status-title">{title}</p>
          <p className="hint">
            Чертёж появится здесь, как только будет прочитан. Ход расчёта показан в полосе внизу.
          </p>
        </div>
      </div>
    );
  }
  if (run.state === 'failed') {
    return (
      <div className="status" data-state="failed">
        <div>
          <p className="status-title">Прогон не удался</p>
          <p className="error-text">{run.error || 'Причина не записана.'}</p>
          <p className="hint">
            <Link to="/">К консоли запуска</Link>
          </p>
        </div>
      </div>
    );
  }
  return (
    <div className="status" data-state={run.state}>
      <span className="spinner" aria-hidden="true" />
      <span>Загружаем подоснову</span>
    </div>
  );
}
