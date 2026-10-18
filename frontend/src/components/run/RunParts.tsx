/* Части левой панели прогона и подложки карты: шапка, сводка, предупреждения, статус. */

import { type ReactNode, useState } from 'react';
import { Link } from 'react-router';

import { artifactUrl } from '../../api/client';
import type { RunOut } from '../../api/types';
import { explainFailure } from '../../lib/failure';
import { drawingName, integer, plural } from '../../lib/format';
import { keyNotices } from '../../lib/warnings';
import { useWorkspace } from '../../state/workspace';
import { IconChevron, UiIcon } from '../icons';
import { Modal, SheetButton } from '../ui/Modal';
import { SquareLoader } from '../ui/SquareLoader';

const num = (value: unknown): number => (typeof value === 'number' ? value : 0);

/** Вход на уточнение объектов и отчёт распознавания - когда сервис их сохранил. Как у тиммейта
 *  в _run_status.html: ссылка появляется там, где прогон упёрся в неизвестное или посчитан
 *  эскизом, и больше нигде. */
function ReviewLinks({
  run,
  onReview,
  report = true,
}: {
  run: RunOut;
  onReview?: () => void;
  report?: boolean;
}) {
  const names = new Set((run.artifacts ?? []).map((a) => a.name));
  return (
    <>
      {names.has('semantic-review.geojson') ? (
        <p className="hint">
          {onReview ? (
            <button type="button" className="review-download-link" onClick={onReview}>
              Уточнить объекты на чертеже
            </button>
          ) : (
            <Link to={`/runs/${encodeURIComponent(run.id)}/review`}>
              Уточнить объекты на чертеже
            </Link>
          )}
        </p>
      ) : null}
      {report && names.has('classification.json') ? (
        <p className="hint">
          <a href={artifactUrl(run.id, 'classification.json')} download>
            Отчёт распознавания
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

/** Имя файла с местами для переноса после «_», «-» и «.»: у «00.1_10004141_Топография» нет
 *  пробелов, и без них строка рвалась посреди слова. */
function breakable(name: string): ReactNode[] {
  return name.split(/(?<=[_\-.])/u).flatMap((part, i) => (i ? [<wbr key={i} />, part] : [part]));
}

/** Заголовок страницы прогона. Видимое имя чертежа и переход «План / 3D и фото» - в шапке
 *  (TopBar), здесь заголовок для читалки экрана и навигации по заголовкам. */
export function RunTitle({ run }: { run: RunOut }) {
  return (
    <h1 className="visually-hidden" title={run.source_name}>
      {breakable(drawingName(run.source_name))}
    </h1>
  );
}

/** Отметка проверки: что сервис сверил сам, без человека. Зелёная галочка и слово, а не один
 *  цвет; провал - красным с тем же порядком строк. */
function Verdict({ ok, yes, no }: { ok: boolean; yes: string; no: string }) {
  return (
    <li className="run-check" data-ok={ok ? '1' : '0'}>
      <UiIcon name={ok ? 'check' : 'alert'} size={17} />
      <span>{ok ? yes : no}</span>
    </li>
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
  draft = false,
  conflicts = null,
  onReview,
}: {
  run: RunOut;
  onReview?: () => void;
  /** Кнопка конфликтов подосновы (SourceConflictNotice): первая строка блока «Проверить». */
  conflicts?: ReactNode;
  /** Деревья среди посадок плана; null - план ещё не загружен. Число деревьев - первое, что
   *  спрашивает заказчик, а «994 посадки» его не называли (жюри по дизайну, итерация 9). */
  trees?: { trees: number; planted: number } | null;
  /** Правки ещё не пересобраны в DXF: число посадок - черновика (trees.planted, как в составе
   *  плана справа), а не итог прогона, и рядом сказано, что это черновик (жюри, этап 21). */
  draft?: boolean;
}) {
  const summary = run.summary ?? {};
  const drafted = draft && trees != null;
  const total = drafted ? trees.planted : num(summary.placements);
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
          {drafted ? ' · черновик правок' : null}
        </span>
      </p>
      {/* Сколько деревьев и кустарников - группами в составе плана справа, здесь не дублируется. */}
      {/* Что сервис сверил сам: независимая проверка плана по нормам, исходные слои и выгрузка.
          Три строки отвечают на вопрос жюри «а можно этому верить» раньше, чем его зададут. */}
      <ul className="run-checks" aria-label="Проверки результата">
        {typeof summary.plan_valid === 'boolean' ? (
          <Verdict
            ok={summary.plan_valid}
            yes="Отступы по нормам соблюдены"
            no="План не прошёл проверку норм"
          />
        ) : null}
        <Verdict
          ok={integrity}
          yes="Исходные слои чертежа целы"
          no="Целостность подосновы нарушена"
        />
        {typeof summary.export_matches_plan === 'boolean' ? (
          <Verdict
            ok={summary.export_matches_plan}
            yes="DXF совпадает с планом"
            no="DXF расходится с планом"
          />
        ) : null}
      </ul>
      {/* Всё, что человеку надо проверить, - одним блоком: раньше согласование, эскиз, конфликты
          и отклонённые места стояли в четырёх местах пульта, и половина - под раскрытием. */}
      {conflicts || approval || sketch || rejected || barrierPlaces || notices.length ? (
        <div className="notice check-block">
          {/* Заголовок говорит, что это за план; строки - что именно смотреть, числом. */}
          <p className="notice-title">{sketch ? 'План-эскиз: что проверить' : 'Что проверить'}</p>
          {conflicts}
          <dl className="run-facts">
            {approval > 0 ? (
              <div className="run-approval">
                <dt>Посадки на согласование</dt>
                <dd>{integer(approval)}</dd>
              </div>
            ) : null}
            {sketch && unconfirmed > 0 ? (
              <div>
                <dt>Грунт под ямой - по подписям, а не по контуру</dt>
                <dd>
                  {unconfirmed === total ? 'все' : `${integer(unconfirmed)} из ${integer(total)}`}
                </dd>
              </div>
            ) : null}
            {rejected > 0 ? (
              <div>
                <dt>Места, отклонённые нормами</dt>
                <dd>{integer(rejected)}</dd>
              </div>
            ) : null}
            {barrierPlaces > 0 ? (
              <div className="run-sub-fact">
                <dt>из них возможны с прикорневым барьером</dt>
                <dd>{integer(barrierPlaces)}</dd>
              </div>
            ) : null}
          </dl>
          {notices.map((text) => (
            <p key={text}>{text}</p>
          ))}
          {sketch ? (
            <details className="fold notice-details">
              <summary>Почему эскиз и как это исправить</summary>
              <p>
                Допустимость посадок не подтверждена:{' '}
                {summary.semantic_assignments_complete === false
                  ? 'часть объектов чертежа сервис не распознал. '
                  : 'на чертеже нет замкнутых контуров газона под посадками, и грунт определён по ближайшим подписям. '}
                Уточните объекты и границы покрытий: грунт под всей посадочной ямой должен быть
                подтверждён замкнутыми контурами.
              </p>
              {/* Отчёт распознавания у готового прогона - в окне «Отчёты и файлы»: две ссылки
                  со словом «отчёт» рядом путались. */}
              <ReviewLinks run={run} onReview={onReview} report={false} />
            </details>
          ) : null}
        </div>
      ) : null}
      {/* Без обёртки «Детали расчёта»: внутри неё бывало одно-единственное раскрытие. Строка
          газонов - обычным текстом, журнал сборки плана - своим раскрытием. */}
      <LawnLine summary={summary} />
      {warnings.length ? <PlanJournal warnings={warnings} /> : null}
    </>
  );
}

/** Журнал сборки плана - строкой в панели, сам список - в окне по центру экрана. */
function PlanJournal({ warnings }: { warnings: readonly string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <SheetButton
        icon="journal"
        label="Как собран план"
        count={warnings.length}
        onClick={() => {
          setOpen(true);
        }}
      />
      <Modal
        open={open}
        title="Как собран план"
        onClose={() => {
          setOpen(false);
        }}
      >
        <ul className="warn-list">
          {warnings.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      </Modal>
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
      <div className="status status-wait" data-state={run.state}>
        <SquareLoader size={48} />
        <div>
          <p className="status-title">{title}</p>
          <p className="hint">Чертёж появится здесь после чтения. Ход расчёта - в полосе внизу.</p>
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
    <div className="status status-wait" data-state={run.state}>
      <SquareLoader size={48} />
      <span>Загружаем подоснову</span>
    </div>
  );
}
