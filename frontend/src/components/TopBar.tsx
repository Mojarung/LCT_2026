import { lazy, Suspense, useState } from 'react';
import { Link, NavLink, useMatch } from 'react-router';

import { useRun } from '../api/queries';
import { drawingName } from '../lib/format';
import { overrideLabel } from '../lib/overrides';
import { profileTitle } from '../lib/profiles';
import { UiIcon } from './icons';
import { ThemeToggle } from './ThemeToggle';
import { Modal } from './ui/Modal';
import { SquareLoader } from './ui/SquareLoader';

// Каталог тянет код карты (спрайты моделей): грузится, только когда окно открыли.
const ModelsCatalog = lazy(() => import('./ModelsCatalog'));

/** На прогоне «Модели растений» открывают окно поверх плана: переход на /models уводил с
 *  рабочего места, и настроенный вид терялся. */
function ModelsButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="topbar-link"
        aria-haspopup="dialog"
        onClick={() => {
          setOpen(true);
        }}
      >
        Модели растений
      </button>
      <Modal
        open={open}
        title="Модели растений"
        wide
        onClose={() => {
          setOpen(false);
        }}
      >
        <Suspense fallback={<SquareLoader size={48} label="Загружаем каталог" />}>
          <ModelsCatalog />
        </Suspense>
      </Modal>
    </>
  );
}

/** Шапка во всю ширину на каждом экране. Слева - знак сервиса и где ты сейчас: на прогоне это
 *  путь «Прогоны / имя чертежа» и переход «План / 3D и фото» на одном месте для обоих видов
 *  (раньше он жил в левой панели и на 3D-виде съезжал в другой угол). Справа - справочное:
 *  модели растений, API и тема. */
export function TopBar() {
  const match = useMatch('/runs/:runId/*');
  const runId = match?.params.runId;
  return (
    <header className="topbar">
      {/* Имя сервиса на каждом экране: на защите скриншот рабочего места без него - просто
          карта. Ведёт к консоли запуска. */}
      <Link className="brand" to="/" aria-label="GREEN_, консоль запуска">
        {/* Знак с именем - картинкой логотипа, светлая и тёмная версии по теме. */}
        <img className="theme-light" src="/brand.webp" width={125} height={40} alt="" />
        <img className="theme-dark" src="/brand-dark.webp" width={125} height={40} alt="" />
      </Link>
      {runId ? <RunCrumbs runId={runId} /> : <MainNav />}
      <nav className="topbar-end" aria-label="Справка">
        {runId ? <ModelsButton /> : null}
        {/* Обычная ссылка, а не переход роутера: /docs отдаёт сервер. */}
        <a
          className="topbar-link"
          href="/docs"
          title="Документация HTTP API (Swagger)"
          aria-label="Документация API"
        >
          <UiIcon name="docs" />
          <span>API</span>
        </a>
        <ThemeToggle />
      </nav>
    </header>
  );
}

function MainNav() {
  return (
    <nav className="topbar-tabs" aria-label="Разделы">
      <NavLink to="/" end viewTransition>
        Прогоны
      </NavLink>
      <NavLink to="/models" viewTransition>
        Модели растений
      </NavLink>
    </nav>
  );
}

// Служебные параметры пересчёта с уточнениями: ссылки на объекты и хеш исходника. В шапке
// вместо них одна подпись «уточнено объектов: N».
const REVIEW_KEYS = new Set([
  'feature_classes',
  'label_roles',
  'semantic_source_sha256',
  'require_reviewed_objects',
  'require_known_objects',
]);

function reviewLabel(overrides: Record<string, unknown>): string[] {
  const assigned = overrides.feature_classes;
  if (!assigned || typeof assigned !== 'object') return [];
  return [`уточнено объектов: ${String(Object.keys(assigned).length)}`];
}

/** Путь до прогона и его виды. Имя чертежа приходит из того же запроса, что у страницы
 *  прогона (кэш TanStack Query), второго обращения к API нет. */
function RunCrumbs({ runId }: { runId: string }) {
  const run = useRun(runId).data;
  const base = `/runs/${encodeURIComponent(runId)}`;
  const params = run
    ? [
        profileTitle(run.profile),
        ...Object.entries(run.overrides)
          .filter(([k]) => !REVIEW_KEYS.has(k))
          .map(([k, v]) => overrideLabel(k, v)),
        ...reviewLabel(run.overrides),
      ]
    : [];
  return (
    <>
      <nav className="crumbs" aria-label="Путь">
        <Link to="/">Прогоны</Link>
        <span className="crumbs-sep" aria-hidden="true">
          /
        </span>
        <span className="crumbs-here" title={run ? `${run.source_name} · прогон ${run.id}` : runId}>
          <span className="crumbs-name">{run ? drawingName(run.source_name) : 'Прогон'}</span>
          {params.length ? (
            <span className="crumbs-meta" title={params.join(' · ')}>
              {params.join(' · ')}
            </span>
          ) : null}
        </span>
      </nav>
      {run?.state === 'succeeded' ? (
        <nav className="topbar-tabs view-switch" aria-label="Вид прогона">
          <NavLink to={base} end viewTransition>
            <UiIcon name="plan" />
            План
          </NavLink>
          <NavLink to={`${base}/3d`} viewTransition>
            <UiIcon name="scene" />
            3D и фото
          </NavLink>
        </nav>
      ) : null}
    </>
  );
}
