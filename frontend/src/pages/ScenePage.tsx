/* 3D-вид прогона: улица с посадками плана, зданиями и покрытиями, свободный полёт и снимки.
 *
 * Страница грузится отдельным чанком (router.ts, lazy): three.js и модели крон весят больше
 * всего остального интерфейса, и тем, кто 3D не открывает, их качать незачем. */

import '../styles/scene.css';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router';

import type { BasemapJson, PlanJson, SurfaceMeta } from '../api/artifacts';
import { artifactUrl } from '../api/client';
import { useArtifact, useRun } from '../api/queries';
import { ScenePanel, type Shot } from '../components/scene/ScenePanel';
import {
  type CameraState,
  DEFAULT_SETTINGS,
  type FrameStats,
  type Hover,
  SceneEngine,
  type Stage,
  type ViewSettings,
  webglAvailable,
} from '../scene3d/engine';
import { FLY_SPEED_DEFAULT } from '../scene3d/freecam';
import type { SurfaceImage } from '../scene3d/ground';
import { clock } from '../scene3d/solar';
import { formatView, parseView } from '../scene3d/viewHash';
import type { SceneJson } from '../scene3d/types';
import { buildWorld } from '../scene3d/world';

const STAGE_TITLES: Record<Stage, string> = {
  textures: 'Фактуры покрытий',
  ground: 'Газоны, тротуары и борта',
  buildings: 'Здания',
  plants: 'Кроны деревьев и кустарников',
  ready: 'Готово',
};

const TYPE_TITLES: Record<string, string> = {
  tree: 'дерево',
  shrub: 'кустарник',
  hedge: 'живая изгородь',
  existing_tree: 'существующее дерево',
  existing_shrub: 'существующий кустарник',
};

/** Сколько последних снимков держит лента пульта. */
const MAX_SHOTS = 12;

const metres = (value: number) => value.toLocaleString('ru-RU', { maximumFractionDigits: 1 });

function stamp(date: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}${p(date.getMonth() + 1)}${p(date.getDate())}-${p(date.getHours())}${p(date.getMinutes())}${p(date.getSeconds())}`;
}

function slug(name: string): string {
  return (
    name
      .replace(/\.(dxf|dwg)$/i, '')
      .replace(/[^\p{L}\p{N}]+/gu, '-')
      .replace(/^-|-$/g, '')
      .slice(0, 48) || 'scene'
  );
}

async function loadSurfaceImage(runId: string, meta: SurfaceMeta): Promise<SurfaceImage | null> {
  const img = new Image();
  img.src = artifactUrl(runId, 'surface.png');
  try {
    await img.decode();
  } catch {
    return null;
  }
  return { img, origin: meta.origin, cell: meta.cell_m, width: meta.width, height: meta.height };
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target instanceof HTMLInputElement)
    return !['range', 'checkbox', 'radio', 'button'].includes(target.type);
  return target.isContentEditable || ['TEXTAREA', 'SELECT'].includes(target.tagName);
}

export function ScenePage() {
  const { runId = '' } = useParams();
  const run = useRun(runId);
  const data = run.data;
  const done = data?.state === 'succeeded';
  const names = useMemo(
    () => new Set((data?.artifacts ?? []).map((a) => a.name)),
    [data?.artifacts],
  );
  const hasScene = names.has('scene.json');
  const scene = useArtifact<SceneJson>(runId, 'scene.json', done && hasScene);
  const plan = useArtifact<PlanJson>(
    runId,
    'plan.json',
    done && !hasScene && names.has('plan.json'),
  );
  const basemap = useArtifact<BasemapJson>(
    runId,
    'basemap.geojson',
    done && names.has('basemap.geojson'),
  );
  const surfaceMeta = useArtifact<SurfaceMeta>(
    runId,
    'surface.json',
    done && names.has('surface.json'),
  );
  const needsSurface = names.has('surface.json');
  const [loadedSurface, setLoadedSurface] = useState<{
    runId: string;
    image: SurfaceImage | null;
  } | null>(null);

  useEffect(() => {
    document.body.classList.add('shell-map');
    return () => {
      document.body.classList.remove('shell-map');
    };
  }, []);

  useEffect(() => {
    const meta = surfaceMeta.data;
    if (!meta) return;
    let alive = true;
    void loadSurfaceImage(runId, meta).then((image) => {
      if (alive) setLoadedSurface({ runId, image });
    });
    return () => {
      alive = false;
    };
  }, [runId, surfaceMeta.data]);

  // Карта покрытий не обязательна: без неё земля - асфальт с газонами подосновы.
  // Не загрузилась привязка карты покрытий - земля без неё, а не вечная загрузка.
  const surfaceFailed = surfaceMeta.isError;
  const surfaceReady = useMemo(
    () =>
      !done
        ? null
        : !needsSurface || surfaceFailed
          ? { image: null }
          : loadedSurface?.runId === runId
            ? { image: loadedSurface.image }
            : null,
    [done, needsSurface, surfaceFailed, loadedSurface, runId],
  );

  // Артефакт, который не загрузился, - это причина, а не вечная загрузка: план обязателен,
  // подоснова и карта покрытий - нет, без них сцена беднее, но строится.
  const planReady = hasScene ? Boolean(scene.data) : Boolean(plan.data) || !names.has('plan.json');
  const basemapReady = Boolean(basemap.data) || basemap.isError || !names.has('basemap.geojson');
  const loadError = scene.isError ? 'scene.json' : plan.isError ? 'plan.json' : null;
  const ready = done && planReady && basemapReady && surfaceReady !== null;
  const world = useMemo(
    () =>
      ready
        ? buildWorld({
            scene: scene.data ?? null,
            plan: plan.data ?? null,
            basemap: basemap.data ?? null,
          })
        : null,
    [ready, scene.data, plan.data, basemap.data],
  );

  const holder = useRef<HTMLDivElement>(null);
  const engine = useRef<SceneEngine | null>(null);
  const [progress, setProgress] = useState<{ stage: Stage; done: number; total: number }>({
    stage: 'textures',
    done: 0,
    total: 1,
  });
  const [failure, setFailure] = useState<string | null>(null);
  const [hover, setHover] = useState<Hover | null>(null);
  const [cam, setCam] = useState<CameraState>({
    mode: 'fly',
    speed: FLY_SPEED_DEFAULT,
    locked: false,
    touring: false,
  });
  const [stats, setStats] = useState<FrameStats | null>(null);
  const [settings, setSettings] = useState<ViewSettings>(DEFAULT_SETTINGS);
  const [shots, setShots] = useState<Shot[]>([]);
  const [shooting, setShooting] = useState(false);
  const [hudHidden, setHudHidden] = useState(false);
  const [flash, setFlash] = useState(0);
  const [everLocked, setEverLocked] = useState(false);
  const settingsRef = useRef(settings);
  useEffect(() => {
    settingsRef.current = settings;
  }, [settings]);

  const supported = useMemo(() => webglAvailable(), []);

  useEffect(() => {
    const box = holder.current;
    if (!world || !box || !surfaceReady || !supported) return;
    let alive = true;
    const canvas = document.createElement('canvas');
    canvas.className = 'scene-canvas';
    canvas.tabIndex = 0;
    canvas.setAttribute('aria-label', '3D-вид участка. Щёлкните, чтобы управлять камерой');
    box.appendChild(canvas);
    let created: SceneEngine | null = null;
    SceneEngine.create(canvas, world, surfaceReady.image, {
      progress: (stage, n, total) => {
        if (alive) setProgress({ stage, done: n, total });
      },
      hover: (h) => {
        if (alive) setHover(h);
      },
      camera: (state) => {
        if (!alive) return;
        setCam(state);
        if (state.locked) setEverLocked(true);
      },
      frame: (s) => {
        if (alive) setStats(s);
      },
      pose: (pose, mode) => {
        if (alive)
          window.history.replaceState(window.history.state, '', `#${formatView(pose, mode)}`);
      },
    })
      .then((e) => {
        created = e;
        if (!alive) {
          e.dispose();
          return;
        }
        e.apply(settingsRef.current);
        const view = parseView(window.location.hash);
        if (view) e.setView(view.pose, view.mode);
        engine.current = e;
      })
      .catch((error: unknown) => {
        if (alive) setFailure(error instanceof Error ? error.message : String(error));
      });
    return () => {
      alive = false;
      engine.current = null;
      created?.dispose();
      canvas.remove();
    };
  }, [world, surfaceReady, supported]);

  const change = (patch: Partial<ViewSettings>) => {
    setSettings((s) => ({ ...s, ...patch }));
    engine.current?.apply(patch);
  };

  const shoot = async (scale: number) => {
    const e = engine.current;
    if (!e || shooting) return;
    setShooting(true);
    try {
      const blob = await e.capture(scale);
      const url = URL.createObjectURL(blob);
      const name = `3d-${slug(data?.source_name ?? 'scene')}-${stamp(new Date())}.png`;
      const size = await createImageBitmap(blob).then((b) => {
        const out = { width: b.width, height: b.height };
        b.close();
        return out;
      });
      setShots((list) => {
        const next = [{ id: Date.now(), url, name, ...size }, ...list];
        // Снимок, выпавший из ленты, файлом уже скачан: его адрес в памяти больше не нужен.
        for (const old of next.slice(MAX_SHOTS)) URL.revokeObjectURL(old.url);
        return next.slice(0, MAX_SHOTS);
      });
      setFlash((n) => n + 1);
      const a = document.createElement('a');
      a.href = url;
      a.download = name;
      a.click();
    } catch (error: unknown) {
      setFailure(error instanceof Error ? error.message : String(error));
    } finally {
      setShooting(false);
    }
  };
  const shootRef = useRef(shoot);
  useEffect(() => {
    shootRef.current = shoot;
  });

  // Ракурс из адреса: ссылку вставили в ту же вкладку - камера переезжает без перезагрузки.
  useEffect(() => {
    const onHash = () => {
      const view = parseView(window.location.hash);
      if (view) engine.current?.setView(view.pose, view.mode);
    };
    window.addEventListener('hashchange', onHash);
    return () => {
      window.removeEventListener('hashchange', onHash);
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (isTyping(event.target) || event.repeat) return;
      const e = engine.current;
      if (!e) return;
      if (event.code === 'KeyP') void shootRef.current(1);
      else if (event.code === 'KeyH') setHudHidden((v) => !v);
      else if (event.code === 'KeyG') e.setMode(e.freecam.mode === 'walk' ? 'fly' : 'walk');
      else if (event.code === 'KeyR') e.resetView();
      else if (event.code === 'KeyT') {
        if (e.touring) e.stopTour();
        else e.startTour();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
    };
  }, []);

  const shotUrls = useRef<string[]>([]);
  useEffect(() => {
    shotUrls.current = shots.map((s) => s.url);
  }, [shots]);
  useEffect(
    () => () => {
      for (const url of shotUrls.current) URL.revokeObjectURL(url);
    },
    [],
  );

  const live = data?.state === 'queued' || data?.state === 'running';
  const title = data?.source_name.replace(/\.(dxf|dwg)$/i, '') ?? 'Прогон';
  const readyToFly = progress.stage === 'ready' && !failure;
  const counts = world
    ? {
        trees: world.plants.filter((p) => !p.existing && p.type === 'tree').length,
        shrubs: world.plants.filter((p) => !p.existing && p.type !== 'tree').length,
        existing: world.plants.filter((p) => p.existing).length,
        buildings: world.buildings.filter((b) => b.kind === 'building').length,
      }
    : null;

  return (
    <div className="workspace page-scene" data-hud={hudHidden ? 'hidden' : 'shown'}>
      <div className="canvas-holder" ref={holder} />
      {flash ? <div key={flash} className="scene-flash" aria-hidden="true" /> : null}
      {cam.locked && readyToFly ? <div className="scene-crosshair" aria-hidden="true" /> : null}
      {!hudHidden ? (
        <>
          <aside className="hud hud-left scene-head" aria-label="Прогон">
            <div className="hud-head">
              <Link className="back" to={`/runs/${encodeURIComponent(runId)}`}>
                ← план прогона
              </Link>
              <h1 title={data?.source_name}>{title}</h1>
              <p className="run-sub">
                <span>3D-вид</span>
                <span>{runId.slice(0, 8)}</span>
              </p>
            </div>
            {counts && world ? (
              <div className="hud-scroll scene-facts">
                <p>
                  {counts.trees} деревьев и {counts.shrubs} кустарников плана, {counts.existing}{' '}
                  отдельных отметок насаждений, {counts.buildings} зданий.
                  {!!world.shrubStrips?.length &&
                    ` Кустарниковые полосы: ${world.shrubStrips.length}. Высота и ширина показаны условно; порода и число кустов не заданы.`}
                  {!!world.treeStrips?.length &&
                    ` Полосы насаждений: ${world.treeStrips.length}. Показаны условными знаками на земле; число стволов не задано.`}
                </p>
                <p className="hint">
                  Этажность: по подписи чертежа у {world.floorsBy.label}, от соседнего корпуса у{' '}
                  {world.floorsBy.neighbor}, по признаку «жилое» у {world.floorsBy.letter}, по
                  площади у {world.floorsBy.assumed}. Фасады условные: съёмка их не несёт.
                </p>
                {world.fallback ? (
                  <p className="notice">
                    Прогон записан до появления scene.json: здания только замкнутые, этажность по
                    площади, размеры видов - по жизненной форме. Перезапустите прогон для точной
                    сцены.
                  </p>
                ) : null}
              </div>
            ) : null}
          </aside>
          {readyToFly ? (
            <ScenePanel
              settings={settings}
              onChange={change}
              shots={shots}
              onShot={(scale) => {
                void shoot(scale);
              }}
              busy={shooting}
              speed={cam.speed}
              onSpeed={(speed) => engine.current?.setSpeed(speed)}
            />
          ) : null}
          {readyToFly ? (
            <div className="hud hud-bottom scene-bar" role="toolbar" aria-label="Камера">
              <button
                type="button"
                aria-pressed={cam.mode === 'fly'}
                title="Свободный полёт, клавиша G"
                onClick={() => engine.current?.setMode('fly')}
              >
                полёт
              </button>
              <button
                type="button"
                aria-pressed={cam.mode === 'walk'}
                title="Пешеход на высоте глаз 1,7 м, клавиша G"
                onClick={() => engine.current?.setMode('walk')}
              >
                пешеход
              </button>
              <button
                type="button"
                title="Общий вид, клавиша R"
                onClick={() => engine.current?.resetView()}
              >
                общий вид
              </button>
              <button
                type="button"
                aria-pressed={cam.touring}
                title="Облёт над улицей туда и обратно, клавиша T; мышь или WASD - взять управление"
                onClick={() => {
                  const e = engine.current;
                  if (!e) return;
                  if (cam.touring) e.stopTour();
                  else e.startTour();
                }}
              >
                облёт
              </button>
              <button
                type="button"
                title="Скрыть панели для чистого кадра, клавиша H"
                onClick={() => {
                  setHudHidden(true);
                }}
              >
                без панелей
              </button>
              <span className="scene-speed" title="Скорость полёта: колесо мыши">
                {cam.mode === 'fly' ? `${Math.round(cam.speed)} м/с` : 'шаг'}
              </span>
              {stats ? (
                <span className="scene-speed" title="Кадров в секунду и вызовов отрисовки">
                  {stats.fps} к/с
                </span>
              ) : null}
            </div>
          ) : null}
          {readyToFly && !cam.locked ? (
            <div className="hud scene-help" role="note">
              <p>
                <strong>{everLocked ? 'Камера отпущена.' : 'Щёлкните по сцене'}</strong>{' '}
                {everLocked
                  ? 'Щёлкните по сцене, чтобы снова управлять.'
                  : 'и управляйте мышью, Esc - отпустить.'}
              </p>
              <p className="scene-keys">
                <kbd>W</kbd>
                <kbd>A</kbd>
                <kbd>S</kbd>
                <kbd>D</kbd> движение · <kbd>E</kbd>/<kbd>Q</kbd> вверх и вниз · <kbd>Shift</kbd>{' '}
                быстрее · колесо - скорость · <kbd>G</kbd> пешеход · <kbd>P</kbd> снимок ·{' '}
                <kbd>H</kbd> панели · <kbd>R</kbd> общий вид · <kbd>T</kbd> облёт. Правой кнопкой
                можно осматриваться без захвата мыши.
              </p>
            </div>
          ) : null}
        </>
      ) : (
        <button
          type="button"
          className="hud scene-unhide"
          onClick={() => {
            setHudHidden(false);
          }}
        >
          панели · H
        </button>
      )}
      {hover && readyToFly ? (
        <div
          className="hud scene-hover"
          role="status"
          data-anchor={cam.locked ? 'crosshair' : 'top'}
        >
          <strong>{hover.plant.name}</strong>
          <span>
            {TYPE_TITLES[hover.plant.type] ?? hover.plant.type}
            {hover.plant.species.name_lat ? `, ${hover.plant.species.name_lat}` : ''}
          </span>
          <span>
            высота {metres(hover.height)} м, крона {metres(hover.crown)} м
            {hover.plant.existing ? ' (по съёмке)' : ` в возрасте ${settings.age} лет`},{' '}
            {metres(hover.distance)} м от вас
          </span>
        </div>
      ) : null}
      {!readyToFly ? (
        <div className="scene-loading" role="status" aria-live="polite">
          {!supported ? (
            <p className="notice">
              Браузер не дал WebGL 2: 3D-вид недоступен. План и выгрузки - на странице прогона.
            </p>
          ) : loadError ? (
            <p className="notice">Не загрузился {loadError}: сцену строить не из чего.</p>
          ) : failure ? (
            <p className="notice">3D-вид не собрался: {failure}</p>
          ) : run.isError ? (
            <p className="notice">Прогон не найден.</p>
          ) : live ? (
            <p>Прогон ещё считается: 3D-вид откроется, когда план будет готов.</p>
          ) : data?.state === 'failed' ? (
            <p className="notice">Прогон завершился ошибкой: строить нечего.</p>
          ) : (
            <>
              <p>
                {world ? STAGE_TITLES[progress.stage] : 'Загрузка плана и подосновы'}
                {world && progress.stage === 'plants'
                  ? ` · ${progress.done} из ${progress.total}`
                  : ''}
              </p>
              <div className="scene-progress">
                <span style={{ width: `${world ? stageShare(progress) * 100 : 4}%` }} />
              </div>
            </>
          )}
          <Link to={`/runs/${encodeURIComponent(runId)}`}>← к плану прогона</Link>
        </div>
      ) : null}
      <span className="visually-hidden" aria-live="polite">
        {readyToFly ? `3D-вид готов, ${clock(settings.hour)}` : ''}
      </span>
    </div>
  );
}

function stageShare(p: { stage: Stage; done: number; total: number }): number {
  const order: Stage[] = ['textures', 'ground', 'buildings', 'plants', 'ready'];
  const base = [0.05, 0.15, 0.25, 0.35, 1][order.indexOf(p.stage)] ?? 0;
  return p.stage === 'plants' ? base + 0.62 * (p.done / Math.max(1, p.total)) : base;
}
