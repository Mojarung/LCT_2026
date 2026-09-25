import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router';

import type { BasemapJson, PlanJson, QualityJson, RulesJson, SurfaceMeta } from '../api/artifacts';
import { ApiError } from '../api/client';
import { keys, useArtifact, useRun } from '../api/queries';
import { DetailPanel } from '../components/detail/DetailPanel';
import { Downloads } from '../components/run/Downloads';
import { EditBar } from '../components/run/EditBar';
import { Legend } from '../components/run/Legend';
import { MapHud } from '../components/run/MapHud';
import { type Choice, PickChooser } from '../components/run/PickChooser';
import { PlanMap } from '../components/run/PlanMap';
import { ProgressHud } from '../components/run/ProgressHud';
import { PanelToggle, RunHeader, RunMetrics, RunStatus } from '../components/run/RunParts';
import { useOverflowMark } from '../hooks/useOverflowMark';
import { describeItem } from '../lib/checks';
import type { PlanEngine } from '../map/engine';
import { loadSurface, toMapItems } from '../map/items';
import type { EngineHooks, MapItem } from '../map/types';
import { PlanEditor } from '../state/editor';
import { EngineContext } from '../state/engine';
import { useWorkspace } from '../state/workspace';

const NO_ITEMS: MapItem[] = [];
const NO_IDS: ReadonlySet<string> = new Set();

const idle: EngineHooks = {
  select: () => undefined,
  probe: () => undefined,
  move: () => undefined,
  remove: () => undefined,
  viewChanged: () => undefined,
  placingChanged: () => undefined,
  ambiguous: () => undefined,
};

/** Фокус обратно на карту: после выбора из списка стрелки и Delete снова работают по ней. */
function focusMap(): void {
  document.getElementById('plan-canvas')?.focus({ preventScroll: true });
}

/** Рабочее место прогона: план во весь экран, панели поверх. Пока прогон идёт - ход расчёта и
 *  чертёж на карте сразу после чтения; когда готов - план, объяснения и правка. Переход из
 *  одного в другое идёт без перезагрузки: вид, который человек настроил, сохраняется. */
/** На узком экране панель посадки стоит под картой, за сгибом: касание кроны ничего видимого
 *  не меняло, пока к панели не прокрутить (жюри дизайна, итерация 6). */
function revealDetail(): void {
  if (!window.matchMedia('(max-width: 1080px)').matches) return;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  requestAnimationFrame(() => {
    document
      .querySelector('.hud-right')
      ?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
  });
}

export function RunPage() {
  const { runId = '' } = useParams();
  const location = useLocation();
  const client = useQueryClient();
  const enter = useWorkspace((s) => s.enter);
  const panels = useWorkspace((s) => s.panels);
  const layers = useWorkspace((s) => s.layers);
  const speciesOff = useWorkspace((s) => s.speciesOff);
  const highlight = useWorkspace((s) => s.highlight);
  const editing = useWorkspace((s) => s.editing);
  const selected = useWorkspace((s) => s.selected);
  // Отметка изменяемая: после переноса у неё новый вердикт, и объявление обязано его назвать.
  useWorkspace((s) => s.revision);

  useEffect(() => {
    enter(runId);
  }, [enter, runId]);

  const run = useRun(runId);

  // Рабочее место занимает весь экран: под планом ничего нет, прокрутки у страницы нет.
  // Ошибка загрузки - обычная страница с шапкой и подвалом.
  const failed = run.isError;
  useEffect(() => {
    if (failed) return;
    document.body.classList.add('shell-map');
    return () => {
      document.body.classList.remove('shell-map');
    };
  }, [failed]);
  const data = run.data;
  const state = data?.state;
  const live = state === 'queued' || state === 'running';
  const done = state === 'succeeded';
  // Неудача - конечное состояние: карты не будет, заглушек загрузки тоже (жюри, итерация 7).
  const broken = state === 'failed';
  const names = useMemo(
    () => new Set((data?.artifacts ?? []).map((a) => a.name)),
    [data?.artifacts],
  );

  const basemap = useArtifact<BasemapJson>(
    runId,
    'basemap.geojson',
    !broken && names.has('basemap.geojson'),
  );
  const plan = useArtifact<PlanJson>(runId, 'plan.json', done && names.has('plan.json'));
  const rules = useArtifact<RulesJson>(runId, 'rules.json', done && names.has('rules.json'));
  const quality = useArtifact<QualityJson>(
    runId,
    'quality.json',
    done && names.has('quality.json'),
  );
  const surface = useArtifact<SurfaceMeta>(
    runId,
    'surface.json',
    done && names.has('surface.json'),
  );

  // Отметки карты - изменяемые объекты: перенос двигает их на месте. Удалённые отбрасываются
  // по id, пока не пришёл пересобранный план.
  const items = useMemo(() => (plan.data ? toMapItems(plan.data) : null), [plan.data]);
  const [removed, setRemoved] = useState<{
    source: PlanJson | undefined;
    ids: ReadonlySet<string>;
  }>({
    source: undefined,
    ids: NO_IDS,
  });
  const removedIds = removed.source === plan.data ? removed.ids : NO_IDS;
  const placements = useMemo(
    () => (items ? items.placements.filter((p) => !removedIds.has(p.id)) : NO_ITEMS),
    [items, removedIds],
  );
  const rejections = items?.rejections ?? NO_ITEMS;

  const engine = useRef<PlanEngine | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const hooks = useRef<EngineHooks>(idle);
  const leftScroll = useOverflowMark<HTMLDivElement>();
  const planData = useRef(plan.data);
  const hashApplied = useRef(false);
  // Спорный щелчок: под курсором стволы нескольких посадок. id меняется на каждый щелчок, и
  // список монтируется заново с первого пункта.
  const [choice, setChoice] = useState<(Choice & { id: number }) | null>(null);
  const closeChoice = useCallback(() => {
    setChoice(null);
    focusMap();
  }, []);

  const editor = useMemo(() => new PlanEditor(runId), [runId]);

  useLayoutEffect(
    () =>
      editor.attach({
        dragVerdict: (verdict) => engine.current?.setDragVerdict(verdict),
        itemsChanged: () => engine.current?.touchItems(),
        removed: (item) => {
          setRemoved((previous) => {
            const source = planData.current;
            const ids = new Set(previous.source === source ? previous.ids : NO_IDS);
            ids.add(item.id);
            return { source, ids };
          });
        },
      }),
    [editor],
  );

  useLayoutEffect(() => {
    planData.current = plan.data;
    hooks.current = {
      select: (item) => {
        useWorkspace.getState().select(item);
        if (item) revealDetail();
      },
      probe: (item, x, y) => void editor.probe(item, x, y),
      move: (item, x, y) => void editor.move(item, x, y),
      remove: (item) => void editor.remove(item),
      viewChanged: () => {
        const current = engine.current;
        if (current) useWorkspace.getState().setZoomShare(current.zoomShare());
      },
      placingChanged: (on) => {
        useWorkspace.getState().setPlacing(on);
      },
      ambiguous: (candidates, x, y) => {
        setChoice((previous) => ({ items: candidates, x, y, id: (previous?.id ?? 0) + 1 }));
      },
    };
  });

  // Данные -> движок.
  useEffect(() => {
    if (!basemap.data) return;
    engine.current?.setBasemap(basemap.data);
    useWorkspace.getState().setOrientation(engine.current?.orientation() ?? 'street');
    if (!hashApplied.current && !done && engine.current?.applyHash(location.hash))
      hashApplied.current = true;
  }, [basemap.data, done, location.hash]);

  useEffect(() => {
    if (!items) return;
    engine.current?.setPlan(placements, rejections);
    if (!hashApplied.current && engine.current?.applyHash(location.hash))
      hashApplied.current = true;
    useWorkspace.getState().setOrientation(engine.current?.orientation() ?? 'street');
  }, [items, placements, rejections, location.hash]);

  useEffect(() => {
    const meta = surface.data;
    if (!meta) return;
    let cancelled = false;
    void loadSurface(runId, meta).then((image) => {
      if (!cancelled) engine.current?.setSurface(image);
    });
    return () => {
      cancelled = true;
    };
  }, [runId, surface.data]);

  useEffect(() => engine.current?.setLayers(layers), [layers]);
  useEffect(() => engine.current?.setSpeciesOff(speciesOff), [speciesOff]);
  useEffect(() => engine.current?.setHighlight(highlight), [highlight]);
  useEffect(() => engine.current?.setEditing(editing), [editing]);
  useEffect(() => engine.current?.setSelected(selected), [selected]);

  // Панели сменили размер: вид удерживается за центр свободной области.
  useLayoutEffect(() => {
    engine.current?.relayout();
  }, [panels.left, panels.right, panels.legend, live, done]);

  const rebuilt = () => {
    void client.invalidateQueries({ queryKey: keys.run(runId) });
    void client.invalidateQueries({ queryKey: keys.artifacts(runId) });
  };

  if (run.isError) {
    const missing = run.error instanceof ApiError && run.error.status === 404;
    return (
      <div className="launch">
        <div className="panel" style={{ maxWidth: 560, margin: '0 auto' }}>
          <h1 className="start-title">{missing ? 'Такого прогона нет' : 'Прогон не загрузился'}</h1>
          <p className="hint">
            {missing ? `Прогона ${runId} нет в хранилище сервиса.` : run.error.message}
          </p>
          <p className="hint">
            <Link to="/">К консоли запуска</Link>
          </p>
        </div>
      </div>
    );
  }

  const mapReady = done ? Boolean(items && basemap.data) : live && Boolean(basemap.data);
  const withMap = done || live;

  return (
    <EngineContext.Provider value={engine}>
      <div
        className={`workspace page-run${withMap && panels.legend ? ' legend-on' : ''}`}
        data-state={state}
        ref={root}
      >
        {/* Живая область стоит в разметке с первой отрисовки: читалка экрана объявляет только
            изменения в уже существующем узле, а выбор идёт стрелками по холсту без видимого текста. */}
        <p id="selection-announce" className="visually-hidden" role="status">
          {selected ? describeItem(selected) : ''}
        </p>
        <div className="canvas-holder">
          <PlanMap root={root} hooks={hooks} interactive={done} />
          {mapReady ? null : (
            <div className="map-loading" data-state={state}>
              {data ? <RunStatus run={data} /> : <span className="spinner" aria-hidden="true" />}
            </div>
          )}
          {withMap ? <MapHud /> : null}
          {withMap ? <Legend done={done} /> : null}
          {choice ? (
            <PickChooser
              key={choice.id}
              choice={choice}
              onChoose={(item) => {
                setChoice(null);
                hooks.current.select(item);
                focusMap();
              }}
              onClose={closeChoice}
            />
          ) : null}
        </div>

        {live && data ? <ProgressHud run={data} fetchedAt={run.dataUpdatedAt} /> : null}

        <aside
          className={`hud hud-left${panels.left ? ' collapsed' : ''}`}
          data-map-obstacle="side"
          aria-label="Прогон"
        >
          <PanelToggle panel="left" label="панель прогона" />
          {data ? <RunHeader run={data} /> : null}
          <div className="hud-scroll" ref={leftScroll} hidden={broken}>
            {done && data ? (
              <RunMetrics run={data} />
            ) : broken ? null : (
              <p className="metric">
                <b>
                  <i className="skeleton" />
                </b>
                <span>посадок в плане</span>
              </p>
            )}
          </div>
          {done ? <EditBar editor={editor} onRebuilt={rebuilt} /> : null}
        </aside>

        {done && data ? (
          <aside
            className={`hud hud-right detail${panels.right ? ' collapsed' : ''}`}
            data-map-obstacle="side"
            aria-label="Состав плана"
          >
            <PanelToggle panel="right" label="панель состава плана" />
            <DetailPanel
              placements={placements}
              rules={rules.data?.rules ?? {}}
              quality={quality.data}
            />
            <Downloads
              artifacts={data.artifacts ?? []}
              notes={
                Array.isArray(data.summary?.load_notes) ? data.summary.load_notes.map(String) : []
              }
            />
          </aside>
        ) : null}
      </div>
    </EngineContext.Provider>
  );
}
