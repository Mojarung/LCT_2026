/* 3D-вид прогона: улица с посадками плана, зданиями и покрытиями, свободный полёт и снимки.
 *
 * Страница грузится отдельным чанком (router.ts, lazy): three.js и модели крон весят больше
 * всего остального интерфейса, и тем, кто 3D не открывает, их качать незачем. */

import { SourceConflictNotice } from '../components/run/SourceConflictNotice';
import '../styles/scene.css';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';

import type { BasemapJson, PlanJson, SurfaceMeta } from '../api/artifacts';
import { artifactUrl } from '../api/client';
import {
  useArtifact,
  useCreatePhoto,
  useDeletePhoto,
  usePhotos,
  usePromptPreview,
  useRun,
} from '../api/queries';
import { BarButton } from '../components/scene/BarButton';
import { MediaPanel } from '../components/scene/MediaPanel';
import { MediaViewer } from '../components/scene/MediaViewer';
import { type PromptDraft, PromptDialog } from '../components/scene/PromptDialog';
import { ScenePanel } from '../components/scene/ScenePanel';
import { SideToggle } from '../components/scene/SideToggle';
import { useSideCollapsed } from '../hooks/useSideCollapsed';
import { type GalleryShot, ShotGallery } from '../components/scene/ShotGallery';
import { plural } from '../lib/format';
import { SHOT_HEIGHT, SHOT_WIDTH, type ShotTarget } from '../scene3d/autoshots';
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
import { mediaItems, type Shot } from '../lib/media';
import { fitForPhoto } from '../lib/photos';
import { clock } from '../scene3d/solar';
import { formatView, parseView } from '../scene3d/viewHash';
import type { Plant, SceneJson } from '../scene3d/types';
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

/** Сколько держится строка уведомления над полосой. */
const NOTICE_MS = 6000;

/** Кадр для нейросети: картинка и что в ней, из галереи, снимка или текущего вида. */
interface PhotoFrame {
  blob: Blob;
  viewpoint: 'aerial' | 'ground';
  trees: string[];
  shrubs: string[];
}

function timeOfDay(date: Date): string {
  return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

/** Сколько последних снимков держит лента пульта. */
const MAX_SHOTS = 12;

const metres = (value: number) => value.toLocaleString('ru-RU', { maximumFractionDigits: 1 });
const count = (n: number, one: string, few: string, many: string) =>
  `${n} ${plural(n, one, few, many)}`;

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
  const [search] = useSearchParams();
  const [gallery, setGallery] = useState<{
    title: string;
    shots: GalleryShot[];
    busy: boolean;
    error: string | null;
  } | null>(null);
  const [scenery, setScenery] = useState(false);
  const [modern, setModern] = useState(true);
  const [headCollapsed, toggleHead] = useSideCollapsed('green-scene-head');
  const [mediaCollapsed, toggleMedia] = useSideCollapsed('green-scene-media');
  const [shotScale, setShotScale] = useState(1);
  const [promptOpen, setPromptOpen] = useState(false);
  const [promptDraft, setPromptDraft] = useState<PromptDraft | null>(null);
  const [requested, setRequested] = useState<Record<string, string>>({});
  const lastPlant = useRef<Plant | null>(null);
  const photos = usePhotos(runId, done);
  const media = useMemo(
    () => mediaItems(shots, photos.data?.photos ?? []),
    [shots, photos.data?.photos],
  );
  const photosAvailable = photos.data?.available ?? false;
  const promptPreview = usePromptPreview(
    runId,
    { scenery, modern, season: settings.season, hour: settings.hour },
    photosAvailable && promptOpen,
  );
  const photoBusy = (photos.data?.photos ?? []).filter(
    (p) => p.state === 'queued' || p.state === 'running',
  ).length;
  const [notice, setNotice] = useState<string | null>(null);
  const noticeTimer = useRef(0);
  const toast = (text: string) => {
    setNotice(text);
    window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => {
      setNotice(null);
    }, NOTICE_MS);
  };
  const createPhoto = useCreatePhoto(runId);
  const deletePhoto = useDeletePhoto(runId);
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
        if (!alive) return;
        setHover(h);
        if (h) lastPlant.current = h.plant;
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
      const here = e.speciesHere();
      setShots((list) => {
        const next = [{ id: Date.now(), url, name, blob, ...here, ...size }, ...list];
        // Снимок, выпавший из ленты, файлом уже скачан: его адрес в памяти больше не нужен.
        for (const old of next.slice(MAX_SHOTS)) URL.revokeObjectURL(old.url);
        return next.slice(0, MAX_SHOTS);
      });
      setFlash((n) => n + 1);
      toast('Снимок - в панели «Снимки и фото» слева.');
    } catch (error: unknown) {
      // Сбой снимка - строка поверх сцены, а не «3D-вид не собрался»: сцена цела.
      toast(error instanceof Error ? error.message : String(error));
    } finally {
      setShooting(false);
    }
  };
  const galleryUrls = useRef<string[]>([]);
  const openGallery = async (target: ShotTarget, title: string) => {
    const e = engine.current;
    if (!e) return;
    setGallery({ title, shots: [], busy: true, error: null });
    try {
      const planned = e.planShots(target);
      if (!planned.length) {
        setGallery({
          title,
          shots: [],
          busy: false,
          error: 'В сцене нет посадок.',
        });
        return;
      }
      const blobs = await e.renderViews(
        planned.map((p) => p.pose),
        SHOT_WIDTH,
        SHOT_HEIGHT,
      );
      for (const url of galleryUrls.current) URL.revokeObjectURL(url);
      const shots = planned.slice(0, blobs.length).map((p, i) => {
        const blob = blobs[i] as Blob;
        return { ...p, blob, url: URL.createObjectURL(blob) };
      });
      galleryUrls.current = shots.map((s) => s.url);
      setGallery({ title, shots, busy: false, error: null });
    } catch (error: unknown) {
      setGallery({
        title,
        shots: [],
        busy: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  };
  // Пока открыта галерея, сцена не рисуется: видеокарта нужна модели фото, а не кадру за панелью.
  const [viewer, setViewer] = useState<number | null>(null);
  const galleryOpen = gallery !== null || viewer !== null;
  useEffect(() => {
    engine.current?.setPaused(galleryOpen);
  }, [galleryOpen]);
  const openGalleryRef = useRef(openGallery);
  useEffect(() => {
    openGalleryRef.current = openGallery;
  });
  useEffect(
    () => () => {
      for (const url of galleryUrls.current) URL.revokeObjectURL(url);
    },
    [],
  );

  /** Все три пути в нейросеть - галерея, снимок, текущий вид - одной очередью сервера. */
  const sendPhoto = (
    frame: PhotoFrame,
    label: string,
    done?: (photoId: string) => void,
  ): Promise<void> =>
    createPhoto
      .mutateAsync({
        image: frame.blob,
        scenery,
        season: settings.season,
        hour: settings.hour,
        viewpoint: frame.viewpoint,
        species: frame.trees,
        shrubs: frame.shrubs,
        shot: label,
        modern,
        prompt: promptDraft?.text ?? '',
        negative: promptDraft?.negative ?? '',
      })
      .then((photo) => {
        done?.(photo.id);
        toast('Кадр ушёл в нейросеть: ход и готовое фото - в панели «Снимки и фото» слева.');
      })
      .catch((error: unknown) => {
        toast(error instanceof Error ? error.message : String(error));
      });

  const orderPhoto = (shot: GalleryShot) => {
    void sendPhoto(shot, `${gallery?.title ?? ''}. ${shot.label}`, (id) => {
      setRequested((r) => ({ ...r, [shot.key]: id }));
    });
  };

  const [sendingView, setSendingView] = useState(false);
  const photoFromView = async () => {
    const e = engine.current;
    if (!e || sendingView || !photosAvailable) return;
    setSendingView(true);
    try {
      await sendPhoto(await e.viewShot(), `Вид из 3D, ${timeOfDay(new Date())}`);
    } catch (error: unknown) {
      toast(error instanceof Error ? error.message : String(error));
    } finally {
      setSendingView(false);
    }
  };

  const photoFromSnapshot = async (shot: Shot) => {
    try {
      const blob = await fitForPhoto(shot.blob);
      await sendPhoto({ ...shot, blob }, `Снимок ${timeOfDay(new Date(shot.id))}`);
    } catch (error: unknown) {
      toast(error instanceof Error ? error.message : String(error));
    }
  };

  const shootRef = useRef(shoot);
  const shotScaleRef = useRef(shotScale);
  const photoViewRef = useRef(photoFromView);
  useEffect(() => {
    shootRef.current = shoot;
    shotScaleRef.current = shotScale;
    photoViewRef.current = photoFromView;
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
      // Под открытым окном (галерея кадров, просмотр) клавиши сцены молчат.
      if (document.querySelector('dialog[open]')) return;
      const e = engine.current;
      if (!e) return;
      if (event.code === 'Escape') setGallery(null);
      else if (event.code === 'KeyK') {
        const plant = lastPlant.current;
        void openGalleryRef.current(
          plant ? { kind: 'plant', id: plant.id } : { kind: 'street' },
          plant ? plantTitle(plant) : 'Кадры улицы',
        );
      } else if (event.code === 'KeyF') void photoViewRef.current();
      else if (event.code === 'KeyP') void shootRef.current(shotScaleRef.current);
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
  // Ссылка с карты открывает кадры сразу, до свободного полёта: ?plant=<id> или ?shots=street.
  const autoTarget = search.get('plant');
  const autoStreet = search.get('shots') === 'street';
  const autoOpened = useRef(false);
  useEffect(() => {
    if (!readyToFly || autoOpened.current || (!autoTarget && !autoStreet)) return;
    autoOpened.current = true;
    const plant = world?.plants.find((p) => p.id === autoTarget);
    void openGalleryRef.current(
      autoTarget ? { kind: 'plant', id: autoTarget } : { kind: 'street' },
      autoTarget ? (plant ? plantTitle(plant) : 'Кадры посадки') : 'Кадры улицы',
    );
  }, [readyToFly, autoTarget, autoStreet, world]);
  const counts = world
    ? {
        trees: world.plants.filter((p) => !p.existing && p.type === 'tree').length,
        shrubs: world.plants.filter((p) => !p.existing && p.type !== 'tree').length,
        existing: world.plants.filter((p) => p.existing).length,
        buildings: world.buildings.filter((b) => b.kind === 'building').length,
      }
    : null;

  return (
    <div
      className="workspace page-scene"
      data-hud={hudHidden ? 'hidden' : 'shown'}
      data-gallery={gallery ? 'open' : undefined}
    >
      <div className="canvas-holder" ref={holder} />
      {flash ? <div key={flash} className="scene-flash" aria-hidden="true" /> : null}
      {cam.locked && readyToFly ? <div className="scene-crosshair" aria-hidden="true" /> : null}
      {!hudHidden ? (
        <>
          <div className="scene-left">
            <aside
              className={
                headCollapsed ? 'hud hud-left scene-head collapsed' : 'hud hud-left scene-head'
              }
              aria-label="Прогон"
            >
              <SideToggle
                side="left"
                collapsed={headCollapsed}
                label="карточку улицы"
                icon="street"
                onToggle={toggleHead}
              />
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
                  <SourceConflictNotice report={basemap.data?.source_conflicts} runId={runId} />
                  <p>
                    {count(counts.trees, 'дерево', 'дерева', 'деревьев')} и{' '}
                    {count(counts.shrubs, 'кустарник', 'кустарника', 'кустарников')} плана,{' '}
                    {count(
                      counts.existing,
                      'отдельная отметка',
                      'отдельные отметки',
                      'отдельных отметок',
                    )}{' '}
                    насаждений, {count(counts.buildings, 'здание', 'здания', 'зданий')}.
                    {!!world.shrubStrips?.length &&
                      ` Кустарниковые полосы: ${world.shrubStrips.length}. Высота и ширина показаны условно; порода и число кустов не заданы.`}
                    {!!world.treeStrips?.length &&
                      ` Полосы насаждений: ${world.treeStrips.length}. Показаны условными знаками на земле; число стволов не задано.`}
                  </p>
                  <details className="scene-more">
                    <summary>Этажность и допущения</summary>
                    <p className="hint">
                      {floorsLine(world.floorsBy)} Фасады условные: в съёмке их нет.
                    </p>
                  </details>
                  {world.fallback ? (
                    <p className="notice">
                      Прогон сделан прежней версией сервиса: здания только замкнутые, этажность по
                      площади, размеры растений по жизненной форме. Перезапустите прогон для точной
                      сцены.
                    </p>
                  ) : null}
                </div>
              ) : null}
            </aside>
            {readyToFly ? (
              <MediaPanel
                items={media}
                photos={photos.data?.photos ?? []}
                available={photosAvailable}
                reason={photos.data?.reason ?? null}
                scenery={scenery}
                onScenery={setScenery}
                modern={modern}
                onModern={setModern}
                customPrompt={promptDraft !== null}
                onPrompt={() => {
                  setPromptOpen(true);
                }}
                collapsed={mediaCollapsed}
                onToggle={toggleMedia}
                shotScale={shotScale}
                onShotScale={setShotScale}
                shooting={shooting}
                sending={sendingView}
                onShot={() => {
                  void shoot(shotScale);
                }}
                onPhotoView={() => {
                  void photoFromView();
                }}
                photoBusy={photoBusy}
                onShots={() => {
                  void openGallery({ kind: 'street' }, 'Кадры улицы');
                }}
                onRemoveShot={(id) => {
                  setShots((list) => {
                    const gone = list.find((s) => s.id === id);
                    if (gone) URL.revokeObjectURL(gone.url);
                    return list.filter((s) => s.id !== id);
                  });
                }}
                onDeletePhoto={(id) => {
                  if (!window.confirm('Удалить фото с сервера? Вернуть его будет нельзя.')) return;
                  deletePhoto.mutate(id, {
                    onError: (error) => {
                      toast(error.message);
                    },
                  });
                }}
                onPhoto={(shot) => {
                  void photoFromSnapshot(shot);
                }}
                onOpen={setViewer}
              />
            ) : null}
          </div>
          {readyToFly ? (
            <ScenePanel
              settings={settings}
              onChange={change}
              speed={cam.speed}
              onSpeed={(speed) => engine.current?.setSpeed(speed)}
            />
          ) : null}
          {readyToFly ? (
            <div className="hud hud-bottom scene-bar" role="toolbar" aria-label="Камера и снимки">
              <div className="bar-group" role="group" aria-label="Режим камеры">
                <BarButton
                  icon="fly"
                  label="полёт"
                  keyHint="G"
                  pressed={cam.mode === 'fly'}
                  title="Свободный полёт"
                  onClick={() => engine.current?.setMode('fly')}
                />
                <BarButton
                  icon="walk"
                  label="пешеход"
                  keyHint="G"
                  pressed={cam.mode === 'walk'}
                  title="Пешеход на высоте глаз 1,7 м"
                  onClick={() => engine.current?.setMode('walk')}
                />
              </div>
              <div className="bar-group" role="group" aria-label="Куда смотреть">
                <BarButton
                  icon="overview"
                  label="общий вид"
                  keyHint="R"
                  title="Вернуться к общему виду"
                  onClick={() => engine.current?.resetView()}
                />
                <BarButton
                  icon="tour"
                  label="облёт"
                  keyHint="T"
                  pressed={cam.touring}
                  title="Облёт над улицей; мышь или WASD - взять управление"
                  onClick={() => {
                    const e = engine.current;
                    if (!e) return;
                    if (cam.touring) e.stopTour();
                    else e.startTour();
                  }}
                />
              </div>
              <div className="bar-group" role="group" aria-label="Панели">
                <BarButton
                  icon="hide"
                  label="без панелей"
                  keyHint="H"
                  title="Скрыть панели для чистого кадра"
                  onClick={() => {
                    setHudHidden(true);
                  }}
                />
              </div>
              <span className="bar-meta" title="Скорость полёта (колесо мыши) и кадров в секунду">
                {cam.mode === 'fly' ? `${String(Math.round(cam.speed))} м/с` : 'шаг'}
                {stats ? ` · ${String(stats.fps)} к/с` : ''}
              </span>
            </div>
          ) : null}
          {notice && readyToFly ? (
            <div className="hud scene-toast" role="status">
              {notice}
            </div>
          ) : null}
          {readyToFly && !cam.locked && !everLocked ? (
            <div className="hud scene-help" role="note">
              <p>
                <strong>Щёлкните по сцене</strong> и управляйте мышью, Esc - отпустить.
              </p>
              <p className="scene-keys">
                <kbd>W</kbd>
                <kbd>A</kbd>
                <kbd>S</kbd>
                <kbd>D</kbd> движение · <kbd>E</kbd>/<kbd>Q</kbd> высота · <kbd>Shift</kbd> быстрее
                · колесо - скорость · правая кнопка - обзор без захвата
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
      {gallery && readyToFly ? (
        <ShotGallery
          title={gallery.title}
          shots={gallery.shots}
          busy={gallery.busy}
          error={gallery.error}
          photos={photos.data?.photos ?? []}
          requested={requested}
          available={photos.data?.available ?? false}
          reason={photos.data?.reason ?? null}
          scenery={scenery}
          onScenery={setScenery}
          onPhoto={orderPhoto}
          onOpen={(shot) => {
            setGallery(null);
            engine.current?.setView(shot.pose, 'fly');
          }}
          onStreet={
            gallery.title === 'Кадры улицы'
              ? undefined
              : () => {
                  void openGallery({ kind: 'street' }, 'Кадры улицы');
                }
          }
          onClose={() => {
            setGallery(null);
          }}
        />
      ) : null}
      {promptOpen && photosAvailable ? (
        <PromptDialog
          auto={promptPreview.data}
          draft={promptDraft}
          onDraft={setPromptDraft}
          onClose={() => {
            setPromptOpen(false);
          }}
        />
      ) : null}
      {viewer !== null && readyToFly && media.length ? (
        <MediaViewer
          items={media}
          index={Math.min(viewer, media.length - 1)}
          photos={photos.data?.photos ?? []}
          onIndex={setViewer}
          onClose={() => {
            setViewer(null);
          }}
          onPhoto={
            photosAvailable
              ? (shot) => {
                  void photoFromSnapshot(shot);
                }
              : undefined
          }
        />
      ) : null}
      {hover && readyToFly && !gallery ? (
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
            высота {metres(hover.height)} м, крона {metres(hover.crown)} м{' '}
            {hover.plant.existing
              ? '(по съёмке)'
              : settings.age
                ? `в возрасте ${settings.age} лет`
                : 'при посадке'}
            {`, ${metres(hover.distance)} м от вас`}
          </span>
          <span className="hint">K - кадры этого растения</span>
        </div>
      ) : null}
      {!readyToFly ? (
        <div className="scene-loading" role="status" aria-live="polite">
          {!supported ? (
            <p className="notice">В браузере нет WebGL 2, 3D-вид недоступен.</p>
          ) : loadError ? (
            <p className="notice">Не загрузился {loadError}, сцену не построить.</p>
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

/** Откуда этажность, без нулевых источников: «по соседнему корпусу - 0» ничего не сообщает. */
function floorsLine(by: Record<'label' | 'neighbor' | 'letter' | 'assumed', number>): string {
  const parts = (
    [
      ['по подписи чертежа', by.label],
      ['по соседнему корпусу', by.neighbor],
      ['по признаку «жилое»', by.letter],
      ['по площади', by.assumed],
    ] as const
  )
    .filter(([, n]) => n > 0)
    .map(([what, n]) => `${what} - ${String(n)}`);
  return parts.length ? `Этажность зданий: ${parts.join(', ')}.` : '';
}

/** Заголовок галереи посадки: номер, как на карте и в выгрузках, и вид. */
function plantTitle(plant: Plant): string {
  return `Кадры: ${plant.number ? `№ ${String(plant.number)}. ` : ''}${plant.name}`;
}
