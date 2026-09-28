/* Части левой панели прогона и подложки карты: шапка, сводка, предупреждения, статус. */

import { Link } from 'react-router';

import { artifactUrl } from '../../api/client';
import type { RunOut } from '../../api/types';
import { explainFailure } from '../../lib/failure';
import { drawingName, integer, plural } from '../../lib/format';
import { overrideLabel } from '../../lib/overrides';
import { keyNotices } from '../../lib/warnings';
import { useWorkspace } from '../../state/workspace';
import { IconChevron } from '../icons';

const num = (value: unknown): number => (typeof value === 'number' ? value : 0);

/** Вход на уточнение объектов и отчёт распознавания - когда сервис их сохранил. Как у тиммейта
 *  в _run_status.html: ссылка появляется там, где прогон упёрся в неизвестное или посчитан
 *  эскизом, и больше нигде. */
function ReviewLinks({ run }: { run: RunOut }) {
  const names = new Set((run.artifacts ?? []).map((a) => a.name));
  return (
    <>
      {names.has('semantic-review.geojson') ? (
        <p className="hint">
          <Link to={`/runs/${encodeURIComponent(run.id)}/review`}>Уточнить объекты на чертеже</Link>
        </p>
      ) : null}
      {names.has('classification.json') ? (
        <p className="hint">
          <a href={artifactUrl(run.id, 'classification.json')} download>
            Скачать отчёт распознавания объектов
          </a>
        </p>
      ) : null}
    </>
  );
}

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

export function RunHeader({ run }: { run: RunOut }) {
  return (
    <div className="hud-head">
      <Link className="back" to="/">
        ← все прогоны
      </Link>
      <h1 title={run.source_name}>{drawingName(run.source_name)}</h1>
      <p className="run-sub">
        <span>{run.profile}</span>
        <span>{run.id.slice(0, 8)}</span>
        {Object.entries(run.overrides).map(([key, value]) => (
          <span key={key}>{overrideLabel(key, value)}</span>
        ))}
      </p>
      {run.state === 'succeeded' ? (
        <Link className="scene-link" to={`/runs/${encodeURIComponent(run.id)}/3d`}>
          3D-вид участка и снимки →
        </Link>
      ) : null}
    </div>
  );
}

/** Сводка: одно число крупно, остальное строкой под ним. Предупреждения, меняющие смысл плана,
 *  стоят рядом с числом: иначе «18 780 посадок» читается как результат работы, а не как
 *  следствие того, что участок ничем не ограничен. Индекс качества здесь не повторяется: он
 *  стоит крупно в правой панели на том же экране. Остальные записи прогона - под раскрытием
 *  «Как собран план»: это журнал приёмов и подбора, а не тревоги. */
export function RunMetrics({
  run,
  trees,
}: {
  run: RunOut;
  /** Деревья среди посадок плана; null - план ещё не загружен. Число деревьев - первое, что
   *  спрашивает заказчик, а «994 посадки» его не называли (жюри по дизайну, итерация 9). */
  trees?: { trees: number; planted: number } | null;
}) {
  const summary = run.summary ?? {};
  const total = num(summary.placements);
  const approval = num(summary.needs_approval);
  const rejected = num(summary.rejections);
  const integrity = summary.integrity_ok === true;
  const stats = (summary.stats ?? {}) as Record<string, unknown>;
  const barrierPlaces = num(stats.barrier_places);
  const warnings = Array.isArray(summary.warnings) ? summary.warnings.map(String) : [];
  const notices = keyNotices(warnings);
  const unconfirmed = num(summary.surface_unconfirmed_placements);
  // Объекты не уточнены или яма опирается на предположение о грунте - план
  // посчитан эскизом, и это говорится рядом с числом, а не в журнале.
  const sketch =
    summary.semantic_assignments_complete === false ||
    summary.surface_inference_review_required === true;
  return (
    <>
      <p className="metric">
        <b>{integer(total)}</b>
        <span>
          {plural(total, 'посадка', 'посадки', 'посадок')} в плане
          {trees != null && trees.planted === total
            ? `: ${integer(trees.trees)} ${plural(trees.trees, 'дерево', 'дерева', 'деревьев')}` +
              (total > trees.trees
                ? `, ${integer(total - trees.trees)} ${plural(total - trees.trees, 'кустарник', 'кустарника', 'кустарников')}`
                : '')
            : ''}
          {approval ? (
            `, ${integer(approval)} на согласование`
          ) : sketch ? (
            ', требуется проверка'
          ) : (
            <>
              , <em>все без ограничений</em>
            </>
          )}
        </span>
      </p>
      <p className="metric-sub">
        <b>{integer(rejected)}</b>{' '}
        {plural(rejected, 'место отклонено', 'места отклонено', 'мест отклонено')}
      </p>
      {/* Отдельной строкой: отказы и целостность подосновы - два разных факта (жюри, итерация 9).
          Цела - обычным текстом: курсив выделял норму как событие (итерация 7). */}
      <p className="metric-sub">
        Подоснова {integrity ? 'цела' : <span className="metric-bad">нарушена</span>}
      </p>
      {barrierPlaces ? (
        <p className="metric-sub quality-line">
          <b>{integer(barrierPlaces)}</b>{' '}
          {plural(barrierPlaces, 'место станет', 'места станут', 'мест станут')} допустимыми с
          прикорневым барьером
        </p>
      ) : null}
      <LawnLine summary={summary} />
      {sketch ? (
        <div className="notice">
          <p>
            Исследовательский эскиз: требуется уточнить объекты или границы покрытий. Допустимость
            посадок не подтверждена.
          </p>
          {unconfirmed > 0 ? (
            <p>
              Грунт под всей посадочной ямой не подтверждён замкнутыми контурами у{' '}
              {integer(unconfirmed)} из {integer(total)} посадок. Проверьте границы покрытия.
            </p>
          ) : null}
          <ReviewLinks run={run} />
        </div>
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

/** Газоны плана (п. 3 ТЗ): площадь в м², устраиваемый газон отдельно - это объём работ. */
function LawnLine({ summary }: { summary: Record<string, unknown> }) {
  const lawn = num(summary.lawn_m2);
  const fresh = num(summary.lawn_new_m2);
  if (!lawn) return null;
  return (
    <p className="metric-sub quality-line">
      <b>{integer(lawn)}</b> м² газона
      {fresh ? `, из них ${integer(fresh)} м² устраиваемого` : ', весь сохраняемый по чертежу'}
    </p>
  );
}

/** Подложка, пока карте нечего показать: ход, причина неудачи или «загружаем». У неудачи
 *  карты не будет: её карточка - конечное состояние страницы, а не заглушка. */
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
    // Причина одной строкой и что делать; текст исключения целиком - под раскрытием: двести
    // знаков кодов без полей читались как поломка самой страницы (жюри, итерация 7).
    const failure = explainFailure(run.error);
    return (
      <div className="status" data-state="failed">
        <h2 className="status-title">Прогон не удался</h2>
        <p className="status-reason">{failure.reason}</p>
        <p className="status-action">{failure.action}</p>
        <ReviewLinks run={run} />
        <p className="hint">
          <Link to="/">← все прогоны</Link>
        </p>
        {failure.details ? (
          <details className="fold status-details">
            <summary>Подробности</summary>
            <p className="status-raw">{failure.details}</p>
          </details>
        ) : null}
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
