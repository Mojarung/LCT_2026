/* Движок 3D-вида без React: рендерер, сцена, камера, цикл кадра, снимок.
 *
 * Страница (pages/ScenePage.tsx) создаёт движок на своём canvas, передаёт настройки пульта
 * и забирает события: ход подготовки, что под прицелом, счётчики кадра. Всё, что зависит
 * от WebGL, живёт здесь; чистая логика - в соседних модулях с тестами. */

import * as THREE from 'three';

import {
  type AutoShot,
  buildingsInView,
  obstaclesOf,
  plantShots,
  SHOT_HEIGHT,
  SHOT_WIDTH,
  speciesInView,
  type ShotTarget,
  streetShots,
} from './autoshots';
import { buildingGeometry, facadeMaterial, roofMaterial } from './buildings';
import { carGroup } from './cars';
import {
  apronGeometry,
  APRON_W_M,
  curbProfile,
  groundCutRings,
  gutterGeometry,
  GUTTER_W_M,
  LOW_CURB_M,
  sceneRoadEdges,
  type RoadEdge,
  TRANSITION_M,
} from './edges';

import { ASPHALT, GRASS, PAVERS } from './surfaceMask';
import { benchSpots, type Ground, manholeSpots, treePits } from './streetDetails';
import { streetDetails } from './streetDetailsMesh';
import { keepSegments } from './contours';
import { chainFences, dropTwinFences } from './fences';
import { picketSpots, splitPlaygroundFences } from './fenceKinds';
import { boundaryOverlay, utilityOverlay } from './overlays';
import { type ContextJson, contextScene } from './context';
import { disposeGroup, facadeModules, moduleMaterial, parapetGeometry } from './facadeModules';
import { CAR_LENGTH_M, CAR_WIDTH_M, parkingSpots } from './parking';
import { Walls } from './collide';
import { nearPlane } from './depth';
import { flowerbedGroup } from './flowerbeds';
import { edgeCurbs, pavingGeometry } from './paving';
import { Freecam, type Mode, type Pose } from './freecam';
import {
  buildMask,
  type MaskInfo,
  CURB_ABOVE_WALK_M,
  CURB_H,
  ROAD_DROP_M,
  CURB_W,
  contextPaintable,
  fenceBarSpots,
  fenceFrame,
  GARDEN_CURB_H,
  GARDEN_CURB_W,
  groundMesh,
  groundGeometry,
  pavedOnLeft,
  paintContextRoads,
  ribbonBox,
  specialGeometry,
  type SurfaceImage,
} from './ground';
import { pick } from './pick';
import type { ScenePostprocessing } from './postprocessing';
import { AdaptiveQuality } from './adaptive';
import { Atmosphere } from './sky';
import type { Season } from './solar';
import {
  CURB_STONES_PER_TEXTURE,
  curbStone,
  gutterShade,
  noiseTexture,
  rubberCrumb,
} from './textures';
import { loadGroundMaterials } from './materials';
import { People, PEOPLE_MAX, placePeople } from './people';
import { StreetLights } from './streetlights';
import { atmosphereOf, Weather } from './weather';
import { clearance, type Route, tourPose, tourRoute, tourStart } from './tour';
import { Forest } from './trees';
import { GRASS_PRESETS, GrassField } from './grass';
import type { Line, Plant, World } from './types';
import { frameAt } from './world';

export type Quality = 'low' | 'medium' | 'high';

/** Выше этой высоты камера для промпта фото - дрон, ниже - человек на тротуаре. */
const DRONE_FROM_M = 6;

export interface ViewShot {
  blob: Blob;
  viewpoint: 'aerial' | 'ground';
  trees: string[];
  shrubs: string[];
  /** Есть ли в кадре здания: без них промпт фото не говорит о фасадах. */
  buildings: boolean;
}

/** Снежный покров зимой без снегопада: белое, но с проталинами у проезжей части. */
const WINTER_COVER = 0.85;

export interface ViewSettings {
  hour: number;
  /** Поворот солнца по азимуту, градусы (-180..180): тени в другую сторону при том же часе. */
  sunTurn: number;
  season: Season;
  age: number;
  clouds: number;
  quality: Quality;
  /** Contact light, HDR and antialiasing; disabled in the fast preset. */
  enhanced: boolean;
  showExisting: boolean;
  /** Погода, 0..1: сила ветра, дождя, снега и листопада. */
  wind: number;
  rain: number;
  snow: number;
  leaves: number;
  /** Сколько людей на тротуарах: доля от расставленных. */
  people: number;
  /** Условные машины вдоль бортов: в подоснове их нет, показ - по желанию. */
  cars: boolean;
  /** Город вокруг съёмки из OpenStreetMap: дома, дороги и стоянки квартала. */
  city: boolean;
  /** Рабочие слои: подземные сети и граница работ поверх земли. */
  utilities: boolean;
  boundary: boolean;
}

/** Скорость, с которой свет догоняет час с пульта (1/с), и порог, после которого он встаёт. */
const HOUR_EASE = 4;
const HOUR_SNAP = 0.01;

export const DEFAULT_SETTINGS: ViewSettings = {
  hour: 11,
  sunTurn: 0,
  season: 'summer',
  age: 10,
  clouds: 0.3,
  quality: 'medium',
  enhanced: true,
  showExisting: true,
  wind: 0.3,
  rain: 0,
  snow: 0,
  leaves: 0,
  people: 0.4,
  cars: true,
  // Город OpenStreetMap - по желанию: по умолчанию сцена только из чертежа.
  city: false,
  utilities: false,
  boundary: false,
};

interface QualityPreset {
  pixelRatio: number;
  shadowSize: number;
  shadowExtent: number;
  lodDistance: number;
  pixels: number;
}

const QUALITY: Record<Quality, QualityPreset> = {
  low: { pixelRatio: 1, shadowSize: 2048, shadowExtent: 110, lodDistance: 35, pixels: 1920 * 1080 },
  medium: {
    pixelRatio: 1.5,
    shadowSize: 4096,
    shadowExtent: 150,
    lodDistance: 60,
    pixels: 1920 * 1080,
  },
  high: {
    pixelRatio: 2,
    shadowSize: 4096,
    shadowExtent: 110,
    lodDistance: 110,
    pixels: 2560 * 1440,
  },
};

export type Stage = 'textures' | 'ground' | 'buildings' | 'plants' | 'ready';

export interface Hover {
  plant: Plant;
  height: number;
  crown: number;
  distance: number;
}

export interface EngineEvents {
  progress?: (stage: Stage, done: number, total: number) => void;
  hover?: (hover: Hover | null) => void;
  camera?: (state: CameraState) => void;
  frame?: (stats: FrameStats) => void;
  /** Поза камеры, не чаще двух раз в секунду: для адреса страницы. */
  pose?: (pose: Pose, mode: Mode) => void;
}

export interface CameraState {
  mode: Mode;
  speed: number;
  locked: boolean;
  touring: boolean;
}

export interface FrameStats {
  fps: number;
  drawCalls: number;
  triangles: number;
  /** Доля разрешения, которую оставило адаптивное качество (1 - полное). */
  scale: number;
}

export function webglAvailable(): boolean {
  if (typeof WebGL2RenderingContext === 'undefined') return false;
  try {
    const c = document.createElement('canvas');
    return Boolean(c.getContext('webgl2'));
  } catch {
    return false;
  }
}

/** Точка обзора по умолчанию: с юга над посадками, как фотограф с квадрокоптера. */
export function overviewPose(world: World): Pose {
  const trees = world.plants.filter((p) => !p.existing);
  const xs = trees.map((p) => p.x).sort((a, b) => a - b);
  const zs = trees.map((p) => p.z).sort((a, b) => a - b);
  const cx = xs.length ? (xs[xs.length >> 1] ?? 0) : 0;
  const cz = zs.length ? (zs[zs.length >> 1] ?? 0) : 0;
  const spread = xs.length
    ? Math.min(220, Math.max(40, ((xs[xs.length - 1] ?? 0) - (xs[0] ?? 0)) * 0.35))
    : 60;
  return { x: cx, y: spread * 0.55, z: cz + spread, yaw: 0, pitch: -0.5 };
}

export class SceneEngine {
  private edges: RoadEdge[] = [];

  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(55, 1, 0.1, 6000);
  readonly freecam: Freecam;
  private readonly atmosphere: Atmosphere;
  private readonly forest: Forest;
  private readonly walls: Walls;
  private readonly facade = {
    uNight: { value: 0 },
    uNoise: { value: null as unknown as THREE.Texture },
  };
  private readonly disposables: { dispose(): void }[] = [];
  private settings: ViewSettings = { ...DEFAULT_SETTINGS };
  /** Час, который сейчас показан светом: догоняет выбранный на пульте плавно, а не скачком. */
  private hourShown = DEFAULT_SETTINGS.hour;
  private readonly clock = new THREE.Timer();
  private resizeObserver: ResizeObserver | null = null;
  private frames = 0;
  private fpsStart = 0;
  private lastHover: string | null = null;
  private hoverTick = 0;
  private lights: StreetLights | null = null;
  /** Облёт: маршрут, пройденный путь и сглаженный курс - разворот на концах идёт плавно. */
  private tour: { route: Route; heights: number[]; travelled: number; yaw: number } | null = null;
  private tourPlan: { route: Route; heights: number[] } | null | undefined = undefined;
  private grassField: GrassField | null = null;
  private readonly weather = new Weather();
  private people: People | null = null;
  /** Погода на земле и крышах: общие uniform-ы шейдеров земли, крыш и крон. */
  private readonly groundWeather = { uWet: { value: 0 }, uSnow: { value: 0 } };
  private grassQuality: Quality | null = null;
  private mask: MaskInfo | null = null;
  private noise: THREE.Texture | null = null;
  /** Курсор над сценой в координатах NDC, пока мышь не захвачена: подпись - того, что под ним. */
  private pointer: THREE.Vector2 | null = null;
  private readonly raycaster = new THREE.Raycaster();
  private lastPoseAt = 0;
  private lastPose = '';
  private running = false;
  /** Цикл кадра остановлен: галерея поверх сцены, видеокарта отдана модели фото. */
  private paused = false;
  private postprocessing: ScenePostprocessing | null = null;
  /** Город вокруг уже добавлен: второй раз не строится. */
  private cityAdded = false;
  /** Кадр держится не ниже порога: разрешение и дальность крон подстраиваются сами. */
  private readonly adaptive = new AdaptiveQuality();
  /** Дома города вокруг: для фото они тоже «здания в кадре». */
  private contextBuildings: World['buildings'] = [];
  private effects: typeof ScenePostprocessing | null = null;

  private constructor(
    readonly canvas: HTMLCanvasElement,
    readonly world: World,
    private readonly events: EngineEvents,
  ) {
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      powerPreference: 'high-performance',
    });
    // getProgramInfoLog на каждую программу блокировал страницу на 1,3 с при первом кадре.
    this.renderer.debug.checkShaderErrors = import.meta.env.DEV;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.renderer.info.autoReset = false;
    this.scene.name = 'green-3d';
    this.atmosphere = new Atmosphere(this.renderer, this.scene);
    this.forest = new Forest(world.plants);
    this.scene.add(this.forest.root);
    this.walls = new Walls(world.buildings);
    this.freecam = new Freecam({
      element: canvas,
      pose: overviewPose(world),
      collide: (from, to, y) => this.walls.resolve(from, to, y),
      roof: (p) => this.walls.roofAt(p),
      onChange: () => {
        this.emitCamera();
      },
      onInput: () => {
        this.stopTour();
      },
    });
  }

  static async create(
    canvas: HTMLCanvasElement,
    world: World,
    surface: SurfaceImage | null,
    events: EngineEvents,
  ): Promise<SceneEngine> {
    const engine = new SceneEngine(canvas, world, events);
    try {
      await engine.build(surface);
      return engine;
    } catch (error) {
      engine.dispose();
      throw error;
    }
  }

  private step(stage: Stage, done = 0, total = 1): Promise<void> {
    this.events.progress?.(stage, done, total);
    return new Promise((resolve) => {
      requestAnimationFrame(() => {
        resolve();
      });
    });
  }

  private async build(surface: SurfaceImage | null): Promise<void> {
    await this.step('textures');
    if (this.renderer.extensions.has('EXT_color_buffer_float')) {
      this.effects = (await import('./postprocessing')).ScenePostprocessing;
    }
    const anisotropy = Math.min(8, this.renderer.capabilities.getMaxAnisotropy());
    const noise = noiseTexture();
    this.disposables.push(noise);
    const materials = await loadGroundMaterials(anisotropy);
    const tex = { ...materials, noise };
    this.facade.uNoise.value = noise;
    this.disposables.push(...materials.textures);
    await this.step('ground');
    const mask = buildMask(this.world, surface);
    this.disposables.push(mask.texture, mask.cut);
    this.mask = mask;
    this.noise = noise;
    // Проезд ниже тротуара на высоту борта: своя плоскость асфальта под землёй, земля на
    // уровне тротуара вырезает её по маске (mask.cut), по краю выреза стоит бортовой камень.
    this.edges = sceneRoadEdges(surface?.areas, this.world.origin, mask);
    const lowered = this.edges.length > 0;
    const ground = groundMesh(this.world, mask, tex, this.groundWeather, {
      geometry: lowered
        ? groundGeometry(this.world.bounds, groundCutRings(this.edges, APRON_W_M, TRANSITION_M))
        : undefined,
    });
    this.add(ground);
    if (lowered) this.add(groundMesh(this.world, mask, tex, this.groundWeather, { road: true }));
    this.addPaving(surface, mask, tex);
    this.addSpecialCover(surface);
    this.addFlowerbeds(surface);
    if (this.edges.some((edge) => edge.lowered.some(Boolean))) {
      this.add(
        groundMesh(this.world, mask, tex, this.groundWeather, {
          geometry: apronGeometry(
            this.edges,
            APRON_W_M,
            CURB_ABOVE_WALK_M,
            LOW_CURB_M - ROAD_DROP_M,
            TRANSITION_M,
          ),
          name: 'aprons',
        }),
      );
    }
    this.addStreetFurniture(mask, surface);
    this.addStreetDetails(mask);
    for (const overlay of [
      utilityOverlay(this.world.utilities ?? []),
      boundaryOverlay(this.world.boundary ?? []),
    ]) {
      overlay.visible = false;
      this.scene.add(overlay);
      this.disposables.push({
        dispose: () => {
          disposeGroup(overlay);
        },
      });
    }
    this.addCars(mask);
    this.people = new People(placePeople({ ...mask }, PEOPLE_MAX));
    this.scene.add(this.people.root, this.weather.root);
    await this.step('buildings');
    this.addBuildings(noise);
    // Стволы и опоры - препятствия: квадрат вокруг ствола до высоты нижних ветвей.
    const post = (p: { x: number; z: number }, r: number) => [
      { x: p.x - r, z: p.z - r },
      { x: p.x + r, z: p.z - r },
      { x: p.x + r, z: p.z + r },
      { x: p.x - r, z: p.z + r },
    ];
    this.walls.addRings(
      this.world.plants.filter((p) => !/shrub|hedge/.test(p.type)).map((p) => post(p, 0.25)),
      3,
    );
    this.walls.addRings(
      this.world.poles.map((p) => post(p, 0.15)),
      8,
    );
    await this.forest.build((done, total) => {
      this.events.progress?.('plants', done, total);
    });
    this.resize();
    this.resizeObserver = new ResizeObserver(() => {
      this.resize();
    });
    if (this.canvas.parentElement) this.resizeObserver.observe(this.canvas.parentElement);
    this.trackPointer();
    this.apply(this.settings);
    // Программы шейдеров собираются параллельно (KHR_parallel_shader_compile), а не в первом
    // кадре одной длинной задачей.
    await this.renderer.compileAsync(this.scene, this.camera);
    this.events.progress?.('ready', 1, 1);
    this.running = true;
    this.startLoop();
    this.emitCamera();
  }

  private add(
    object: THREE.Object3D & {
      geometry?: THREE.BufferGeometry;
      material?: THREE.Material | THREE.Material[];
    },
  ): void {
    this.scene.add(object);
    if (object.geometry) this.disposables.push(object.geometry);
    const m = object.material;
    if (m) for (const one of Array.isArray(m) ? m : [m]) this.disposables.push(one);
  }

  /** Бортовой камень - по границе проезда на карте покрытий: от асфальта (ниже на высоту
   *  борта) до верха тротуара и газона с запасом 3 см; поребрик - между плиткой и газоном.
   *  Линии борта подосновы рисуются, только если границы проезда на карте нет. */
  /** Что лежит в точке по итоговой маске: за её краем - газон. */
  private groundAt(mask: MaskInfo, x: number, z: number): Ground {
    const [minX, minZ] = mask.rect;
    const px = Math.floor((x - minX) / mask.metresPerPx);
    const py = Math.floor((z - minZ) / mask.metresPerPx);
    if (px < 0 || py < 0 || px >= mask.width || py >= mask.height) return 'grass';
    const i = py * mask.width + px;
    if (mask.road[i]) return 'road';
    const kind = mask.kinds[i];
    if (kind === PAVERS) return 'pavers';
    if (kind === ASPHALT) return 'asphalt';
    return 'grass';
  }

  /** Лунки посадок плана, люки на трассах сетей, скамейки и урны у дорожек (streetDetails.ts). */
  private addStreetDetails(mask: MaskInfo): void {
    const at = (x: number, z: number) => this.groundAt(mask, x, z);
    const { grates, mulch } = treePits(this.world.plants, at);
    const obstacles = [
      ...this.world.poles,
      ...this.world.plants.filter((p) => p.type === 'tree').map((p) => ({ x: p.x, z: p.z })),
    ];
    // Скамейки съёмки - туда, где нарисованы, сиденьем к покрытию; без них - по правилу у
    // края газона.
    const drawn = (this.world.benches ?? []).map((b) => {
      const paved = (k: number) => {
        const g = at(b.x + Math.sin(b.angle) * k, b.z + Math.cos(b.angle) * k);
        return g === 'pavers' || g === 'asphalt';
      };
      return !paved(1) && paved(-1) ? { ...b, angle: b.angle + Math.PI } : b;
    });
    const { benches, bins } = drawn.length
      ? {
          benches: drawn,
          bins: drawn.map((b) => ({
            x: b.x + Math.cos(b.angle) * 1.4,
            z: b.z - Math.sin(b.angle) * 1.4,
            angle: b.angle,
          })),
        }
      : benchSpots(mask.edges.garden, at, obstacles);
    const group = streetDetails({
      grates,
      mulch,
      manholes: manholeSpots(this.world.utilities ?? [], at),
      benches,
      bins,
      levelAt: (x, z) => (at(x, z) === 'road' ? -ROAD_DROP_M : 0),
    });
    this.scene.add(group);
    this.disposables.push({
      dispose: () => {
        disposeGroup(group);
      },
    });
  }

  /** Цветники плана и клумбы съёмки: земля и многолетники (flowerbeds.ts). */
  private addFlowerbeds(surface: SurfaceImage | null): void {
    const [ox, oy] = this.world.origin;
    const fromDrawing = (surface?.areas?.flowerbeds ?? []).map((rings) =>
      rings.map((ring) => ring.map(([x = 0, y = 0]) => ({ x: x - ox, z: -(y - oy) }))),
    );
    const group = flowerbedGroup([...(this.world.flowerbeds ?? []), ...fromDrawing]);
    if (!group) return;
    this.scene.add(group);
    this.disposables.push({
      dispose: () => {
        disposeGroup(group);
      },
    });
  }

  /** Резиновое покрытие площадок «СПЕЦ.ПОКР.» поверх плитки маски, по контуру чертежа. */
  private addSpecialCover(surface: SurfaceImage | null): void {
    const geometry = surface?.areas ? specialGeometry(surface.areas, this.world.origin) : null;
    if (!geometry) return;
    const map = rubberCrumb();
    map.repeat.set(0.5, 0.5);
    map.anisotropy = 8;
    this.disposables.push(map);
    const mesh = new THREE.Mesh(
      geometry,
      new THREE.MeshStandardMaterial({
        map,
        roughness: 0.96,
        metalness: 0,
        polygonOffset: true,
        polygonOffsetFactor: -2,
        polygonOffsetUnits: -2,
      }),
    );
    mesh.name = 'special-cover';
    mesh.receiveShadow = true;
    this.add(mesh);
  }

  /** Плитка и асфальт тротуаров сетками по контурам частей surface.json (paving.ts). */
  private addPaving(
    surface: SurfaceImage | null,
    mask: MaskInfo,
    tex: Parameters<typeof groundMesh>[2],
  ): void {
    if (!surface?.areas) return;
    for (const cover of ['pavers', 'asphalt'] as const) {
      const geometry = pavingGeometry(surface.areas, this.world.origin, cover);
      if (!geometry) continue;
      const mesh = groundMesh(this.world, mask, tex, this.groundWeather, {
        geometry,
        cover,
        name: `paving-${cover}`,
      });
      const material = mesh.material as THREE.MeshStandardMaterial;
      material.polygonOffset = true;
      material.polygonOffsetFactor = -1;
      material.polygonOffsetUnits = -1;
      this.add(mesh);
    }
  }

  /** Деревянный штакетник площадки: доски 7,5 см через 13 см высотой 0,9 м на столбах. */
  private addPicketFence(lines: Line[]): void {
    const wood = new THREE.MeshStandardMaterial({ color: 0xcfa36e, roughness: 0.85, metalness: 0 });
    const plank = new THREE.BoxGeometry(0.075, 0.9, 0.02);
    plank.translate(0, 0.48, 0);
    const spots = picketSpots(lines, 0.13);
    const pickets = new THREE.InstancedMesh(plank, wood, Math.max(1, spots.length));
    const m = new THREE.Matrix4();
    const turn = new THREE.Matrix4();
    spots.forEach((p, i) => {
      pickets.setMatrixAt(i, m.makeTranslation(p.x, 0, p.z).multiply(turn.makeRotationY(p.yaw)));
    });
    pickets.count = spots.length;
    pickets.computeBoundingSphere();
    const frame = new THREE.Mesh(fenceFrame(lines), wood);
    for (const mesh of [pickets, frame] as THREE.Mesh[]) {
      mesh.castShadow = true;
      mesh.name = 'playground-fences';
      this.add(mesh);
    }
  }

  private addStreetFurniture(mask: MaskInfo, surface: SurfaceImage | null): void {
    const world = this.world;
    const hasRoads = this.edges.length > 0;
    const curbLines = hasRoads
      ? this.edges.map((edge) =>
          curbProfile(edge, CURB_ABOVE_WALK_M, LOW_CURB_M - ROAD_DROP_M, TRANSITION_M),
        )
      : world.curbs;
    // Садовый борт - по контурам частей покрытия, где снаружи газон (paving.ts): тот же край,
    // что у сетки плитки. Без контуров (старые прогоны) - по краю маски газона.
    const [minX, minZ] = mask.rect;
    const lawnAt = (p: { x: number; z: number }) => {
      const col = Math.floor((p.x - minX) / mask.metresPerPx);
      const row = Math.floor((p.z - minZ) / mask.metresPerPx);
      if (col < 0 || row < 0 || col >= mask.width || row >= mask.height) return false;
      return mask.kinds[row * mask.width + col] === GRASS;
    };
    const gardenLines = surface?.areas
      ? edgeCurbs(surface.areas, world.origin, lawnAt)
      : pavedOnLeft(mask.edges.garden, mask);
    if (curbLines.length || gardenLines.length) {
      // Гранит: камни по метру со швами и зерном, рельеф из той же текстуры, фаска по рёбрам.
      const stoneTex = curbStone();
      stoneTex.anisotropy = 8;
      stoneTex.repeat.set(1 / CURB_STONES_PER_TEXTURE, 0.05);
      this.disposables.push(stoneTex);
      // Дорожный борт с проезжей частью стоит от асфальта проезда, верх вровень с тротуаром.
      const roadLift = hasRoads ? -ROAD_DROP_M : 0;
      const roadHeight = hasRoads ? ROAD_DROP_M + CURB_ABOVE_WALK_M : CURB_H;
      // Газонная грань (aShade из ribbonBox) затенена, будто засыпана землёй; у дорожного
      // борта ещё подошва у асфальта грязная и мокрая: нижние 7 см темнее.
      const stoneMaterial = (foot: number | null) => {
        const material = new THREE.MeshStandardMaterial({
          color: 0xffffff,
          map: stoneTex,
          bumpMap: stoneTex,
          bumpScale: 1.5,
          roughness: 0.92,
          metalness: 0,
          // Брус без дна: с какой стороны ни смотреть, грань видна - иначе при обратном ходе
          // линии борт просвечивал насквозь.
          side: THREE.DoubleSide,
        });
        material.onBeforeCompile = (shader) => {
          shader.vertexShader = shader.vertexShader
            .replace(
              '#include <common>',
              '#include <common>\nattribute float aShade;\nvarying float vCurbY;\nvarying float vShade;',
            )
            .replace(
              '#include <worldpos_vertex>',
              '#include <worldpos_vertex>\nvCurbY = (modelMatrix * vec4(transformed, 1.0)).y;\nvShade = aShade;',
            );
          const footLine =
            foot === null
              ? ''
              : `\ndiffuseColor.rgb *= mix(0.58, 1.0, smoothstep(${foot.toFixed(3)}, ${(foot + 0.07).toFixed(3)}, vCurbY));`;
          shader.fragmentShader = shader.fragmentShader
            .replace(
              '#include <common>',
              '#include <common>\nvarying float vCurbY;\nvarying float vShade;',
            )
            .replace(
              '#include <map_fragment>',
              `#include <map_fragment>${footLine}\ndiffuseColor.rgb *= mix(1.0, 0.45, vShade);`,
            );
        };
        return material;
      };
      const roadStone = stoneMaterial(roadLift);
      // Верх борта в плоскости земли: борт выигрывает глубину, иначе мерцание с газоном.
      roadStone.polygonOffset = true;
      roadStone.polygonOffsetFactor = -1;
      roadStone.polygonOffsetUnits = -1;
      for (const [lines, width, height, lift, bevel, name, material, sides] of [
        [curbLines, CURB_W, roadHeight, roadLift, 0.02, 'curbs', roadStone, 'left'],
        [
          gardenLines,
          GARDEN_CURB_W,
          GARDEN_CURB_H,
          0,
          0.01,
          'garden-curbs',
          stoneMaterial(null),
          'left',
        ],
      ] as const) {
        if (!lines.length) {
          material.dispose();
          continue;
        }
        const mesh = new THREE.Mesh(ribbonBox(lines, width, height, lift, bevel, sides), material);
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        mesh.name = name;
        this.add(mesh);
      }
    }
    if (hasRoads && this.edges.length) {
      // Лоток: вдоль полного борта асфальт темнее от воды и грязи, к середине проезда светлеет.
      const shade = gutterShade();
      this.disposables.push(shade);
      const gutter = new THREE.Mesh(
        gutterGeometry(this.edges, GUTTER_W_M, 0.004 - ROAD_DROP_M),
        new THREE.MeshBasicMaterial({
          color: 0x0a0c0e,
          transparent: true,
          opacity: 0.4,
          alphaMap: shade,
          depthWrite: false,
          polygonOffset: true,
          polygonOffsetFactor: -1,
          polygonOffsetUnits: -1,
        }),
      );
      gutter.name = 'gutters';
      gutter.renderOrder = 1;
      this.add(gutter);
    }
    if (world.fences.length) {
      // Пунктир съёмки - сплошной оградой; столбы и перила объёмом видны на любой дальности,
      // решётка между ними - текстурой с прозрачностью.
      const allFences = world.fenceAxes ? world.fences : dropTwinFences(chainFences(world.fences));
      this.walls.addLines(allFences, 1.2);
      // Ограда детской площадки - деревянный штакетник (fenceKinds.ts), остальные - решётка.
      const [ox, oy] = world.origin;
      const playgrounds = (surface?.areas?.paved ?? [])
        .filter((_, i) => surface?.areas?.paved_kind?.[i] === 'special')
        .map((rings) =>
          rings.map((ring) => ring.map(([x = 0, y = 0]) => ({ x: x - ox, z: -(y - oy) }))),
        );
      const { playground: woodLines, other: fenceLines } = splitPlaygroundFences(
        allFences,
        playgrounds,
      );
      if (woodLines.length) this.addPicketFence(woodLines);
      const metal = new THREE.MeshStandardMaterial({
        color: 0x24292b,
        roughness: 0.55,
        metalness: 0.6,
      });
      // Прутья - геометрией: прозрачная текстура на косом взгляде и вдали становилась то
      // пустотой, то сплошной серой плитой.
      const spots = fenceBarSpots(fenceLines, 0.13);
      const bar = new THREE.BoxGeometry(0.018, 0.86, 0.018);
      bar.translate(0, 0.53, 0);
      const lattice = new THREE.InstancedMesh(bar, metal, Math.max(1, spots.length));
      const m = new THREE.Matrix4();
      spots.forEach((p, i) => {
        lattice.setMatrixAt(i, m.makeTranslation(p.x, 0, p.z));
      });
      lattice.count = spots.length;
      lattice.computeBoundingSphere();
      const frame = new THREE.Mesh(fenceFrame(fenceLines), metal);
      for (const mesh of [lattice, frame] as THREE.Mesh[]) {
        mesh.castShadow = true;
        mesh.name = 'fences';
        this.add(mesh);
      }
    }
    this.lights = new StreetLights(world.poles, world.curbs);
    this.scene.add(this.lights.root);
  }

  /** Город вокруг съёмки из OpenStreetMap: дома, дороги за краем съёмки и фоновые деревья.
   *  Приходит после открытия сцены (первый запрос к карте - до минуты), добавляется один раз. */
  addContext(json: ContextJson): number {
    const mask = this.mask;
    if (!this.running || this.cityAdded || !this.noise || !mask) return 0;
    this.cityAdded = true;
    const [minX, minZ] = mask.rect;
    // Дороги, стоянки и машины карты - только на дальнем поле, не ближе CONTEXT_CLEAR_M к
    // тому, что знает съёмка: пустое внутри съёмки - газон, а не место для тропы карты.
    const free = contextPaintable(mask.known, mask.width, mask.height, mask.metresPerPx);
    const surveyed = (p: { x: number; z: number }) => {
      const px = Math.floor((p.x - minX) / mask.metresPerPx);
      const py = Math.floor((p.z - minZ) / mask.metresPerPx);
      if (px < 0 || py < 0 || px >= mask.width || py >= mask.height) return false;
      const i = py * mask.width + px;
      // Снято - и то, что знает карта покрытий, и проезд с тротуаром из полигонов подосновы:
      // дорога карты над опущенным проездом висела бы в воздухе.
      return free[i] === 0 || mask.road[i] === 1 || mask.kinds[i] === PAVERS;
    };
    const city = contextScene(json, frameAt(this.world.origin), surveyed);
    this.contextBuildings = city.buildings;
    const group = new THREE.Group();
    group.name = 'city-context';
    if (city.buildings.length) {
      const { walls, roofs } = buildingGeometry(city.buildings);
      const wallMesh = new THREE.Mesh(walls, facadeMaterial(this.facade));
      const roofMesh = new THREE.Mesh(roofs, roofMaterial(this.noise, this.groundWeather.uSnow));
      const parapets = new THREE.Mesh(parapetGeometry(city.buildings), moduleMaterial());
      for (const mesh of [wallMesh, roofMesh, parapets]) {
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        group.add(mesh);
      }
      // Ближние к съёмке соседи - с лоджиями и подъездами, дальние - объёмом с окнами.
      const [bx0, bz0, bx1, bz1] = this.world.bounds;
      const near = city.buildings.filter((b) =>
        (b.rings[0] ?? []).some(
          (p) => p.x > bx0 - 120 && p.x < bx1 + 120 && p.z > bz0 - 120 && p.z < bz1 + 120,
        ),
      );
      group.add(facadeModules(near, this.world.curbs, { parapets: false }));
    }
    // В пределах маски дороги карты - фактурой земли (paintContextRoads), лентой - только за
    // её краем, на дальнем поле.
    paintContextRoads(mask, city.roads);
    const [rx, rz, rw, rh] = mask.rect;
    const beyond = (a: { x: number; z: number }, b: { x: number; z: number }) => {
      const x = (a.x + b.x) / 2;
      const z = (a.z + b.z) / 2;
      return x < rx || z < rz || x > rx + rw || z > rz + rh;
    };
    for (const roads of city.roads) {
      const lines = keepSegments(roads.lines, beyond);
      if (!lines.length) continue;
      const mesh = new THREE.Mesh(
        ribbonBox(lines, roads.width, 0.02),
        new THREE.MeshStandardMaterial({
          color: roads.paved === 'asphalt' ? 0x8e9092 : 0xa49f97,
          roughness: 0.95,
          polygonOffset: true,
          polygonOffsetFactor: -1,
          polygonOffsetUnits: -1,
          side: THREE.DoubleSide,
        }),
      );
      mesh.receiveShadow = true;
      group.add(mesh);
    }
    if (city.parkings.length) {
      const shapes = city.parkings.map(
        (ring) => new THREE.Shape(ring.map((p) => new THREE.Vector2(p.x, -p.z))),
      );
      const lots = new THREE.ShapeGeometry(shapes);
      // Фигура строится в плоскости (x, -z), поворот кладёт её на землю лицом вверх.
      lots.rotateX(-Math.PI / 2);
      lots.translate(0, 0.015, 0);
      const mesh = new THREE.Mesh(
        lots,
        new THREE.MeshStandardMaterial({
          color: 0x8e9092,
          roughness: 0.95,
          polygonOffset: true,
          polygonOffsetFactor: -1,
          polygonOffsetUnits: -1,
        }),
      );
      mesh.receiveShadow = true;
      group.add(mesh);
    }
    const parked = carGroup(city.cars);
    parked.name = 'city-cars';
    parked.visible = this.settings.cars;
    group.add(parked);
    this.scene.add(group);
    this.disposables.push({
      dispose: () => {
        disposeGroup(group);
      },
    });
    this.showCity(this.settings.city);
    return city.buildings.length;
  }

  private showOverlays(utilities: boolean, boundary: boolean): void {
    const u = this.scene.getObjectByName('overlay-utilities');
    if (u) u.visible = utilities;
    const b = this.scene.getObjectByName('overlay-boundary');
    if (b) b.visible = boundary;
  }

  private showCity(visible: boolean): void {
    const city = this.scene.getObjectByName('city-context');
    if (city) city.visible = visible;
  }

  private forestSettings(): {
    age: number;
    season: ViewSettings['season'];
    showExisting: boolean;
    lodDistance: number;
  } {
    const s = this.settings;
    return {
      age: s.age,
      season: s.season,
      showExisting: s.showExisting,
      lodDistance: this.lodDistance(),
    };
  }

  private get allBuildings(): World['buildings'] {
    return this.contextBuildings.length
      ? [...this.world.buildings, ...this.contextBuildings]
      : this.world.buildings;
  }

  /** Машины у бортов проезда - по карте покрытий, только на асфальт. */
  private addCars(mask: MaskInfo): void {
    const [minX, minZ] = mask.rect;
    const asphaltAt = (x: number, z: number) => {
      const px = Math.floor((x - minX) / mask.metresPerPx);
      const py = Math.floor((z - minZ) / mask.metresPerPx);
      if (px < 0 || py < 0 || px >= mask.width || py >= mask.height) return false;
      return mask.road[py * mask.width + px] === 1;
    };
    const paved = mask.road;
    // Машины стоят на асфальте, а он ниже тротуара на высоту борта.
    const lowered = mask.edges.road.length ? -ROAD_DROP_M : 0;
    const spots = parkingSpots(
      {
        curbs: this.world.curbs,
        asphaltAt,
        poles: this.world.poles,
        plants: this.world.plants,
        walls: this.world.buildings.flatMap((b) => (b.rings[0] ? [b.rings[0]] : [])),
        fences: this.world.fences,
      },
      {
        paved,
        width: mask.width,
        height: mask.height,
        minX,
        minZ,
        metresPerPx: mask.metresPerPx,
      },
    );
    const cars = carGroup(spots, lowered);
    // Машина - препятствие: корпус по месту и углу стоянки, высотой 1,5 м.
    this.walls.addRings(
      spots.map((s) => {
        const ux = Math.cos(s.angle);
        const uz = -Math.sin(s.angle);
        const hl = CAR_LENGTH_M / 2;
        const hw = CAR_WIDTH_M / 2;
        return [
          [hl, hw],
          [hl, -hw],
          [-hl, -hw],
          [-hl, hw],
        ].map(([a = 0, b = 0]) => ({ x: s.x + ux * a - uz * b, z: s.z + uz * a + ux * b }));
      }),
      1.5,
    );
    this.scene.add(cars);
    this.disposables.push({
      dispose: () => {
        disposeGroup(cars);
      },
    });
  }

  private addBuildings(noise: THREE.Texture): void {
    if (!this.world.buildings.length) return;
    const { walls, roofs } = buildingGeometry(this.world.buildings);
    const wallMesh = new THREE.Mesh(walls, facadeMaterial(this.facade));
    const roofMesh = new THREE.Mesh(roofs, roofMaterial(noise, this.groundWeather.uSnow));
    for (const mesh of [wallMesh, roofMesh]) {
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      this.add(mesh);
    }
    wallMesh.name = 'walls';
    roofMesh.name = 'roofs';
    // Лоджии, подъезды, парапеты и машинные помещения - объёмом, по серии дома.
    const modules = facadeModules(this.world.buildings, this.world.curbs);
    this.scene.add(modules);
    this.disposables.push({
      dispose: () => {
        disposeGroup(modules);
      },
    });
  }

  apply(settings: Partial<ViewSettings>): void {
    this.settings = { ...this.settings, ...settings };
    const s = this.settings;
    // Ползунок часа меняет только свет: лес, трава и разрешение не пересобираются, а солнце
    // доезжает до нового часа в кадрах (stepHour). Остальные настройки ставят час сразу.
    const keys = Object.keys(settings);
    if (keys.length === 1 && keys[0] === 'hour') return;
    // Поворот солнца - тоже только свет, без пересборки сцены.
    if (keys.length === 1 && keys[0] === 'sunTurn') {
      this.lightAt(this.hourShown);
      return;
    }
    this.hourShown = s.hour;
    if (settings.quality) this.adaptive.reset();
    const shrubBands = this.scene.getObjectByName('shrub-strip-bands');
    if (shrubBands) shrubBands.visible = s.showExisting;
    for (const name of ['cars', 'city-cars']) {
      const cars = this.scene.getObjectByName(name);
      if (cars) cars.visible = s.cars;
    }
    this.showCity(s.city);
    this.showOverlays(s.utilities, s.boundary);
    this.resize();
    if (s.enhanced && s.quality !== 'low' && this.effects) {
      this.postprocessing ??= new this.effects(this.renderer, this.scene, this.camera);
      this.postprocessing.apply(s.quality);
    } else if (this.postprocessing) {
      this.postprocessing.dispose();
      this.postprocessing = null;
    }
    const weather = this.lightAt(s.hour);
    this.weather.apply(s, weather);
    this.groundWeather.uWet.value = weather.wet;
    // Зимой снег лежит и без снегопада: московский январь белый.
    const cover = Math.max(weather.snowCover, s.season === 'winter' ? WINTER_COVER : 0);
    this.groundWeather.uSnow.value = cover;
    this.forest.wind.uWind.value = weather.sway;
    this.forest.wind.uSnow.value = cover;
    this.people?.setDensity(s.people);
    this.forest.apply(this.forestSettings());
    this.setGrass(s.quality);
    if (this.grassField) {
      this.grassField.uniforms.uWind.value = s.wind;
      // Под снегом травинок не видно: газон белый, поле травы уходит вместе с ним.
      this.grassField.uniforms.uGrow.value = Math.max(0, 1 - cover * 1.4);
    }
  }

  /** Свет, небо и ночная подсветка на заданный час; погода - по текущему пульту. */
  private lightAt(hour: number): ReturnType<typeof atmosphereOf> {
    const s = { ...this.settings, hour };
    const q = QUALITY[s.quality];
    const weather = atmosphereOf(s, s.clouds);
    this.atmosphere.apply({
      hour,
      season: s.season,
      turn: s.sunTurn,
      clouds: weather.clouds,
      shadowSize: q.shadowSize,
      shadowExtent: q.shadowExtent,
      fog: weather.fog,
      wind: s.wind,
    });
    this.facade.uNight.value = this.atmosphere.state.night;
    this.lights?.setNight(this.atmosphere.state.night);
    this.forest.wind.uSunColor.value
      .copy(this.atmosphere.state.color)
      .multiplyScalar(this.atmosphere.state.intensity * 0.35);
    return weather;
  }

  /** Час на свету догоняет выбранный: около секунды на любой сдвиг, через полночь - короче. */
  private stepHour(dt: number): void {
    const target = this.settings.hour;
    if (this.hourShown === target) return;
    let diff = target - this.hourShown;
    if (diff > 12) diff -= 24;
    else if (diff < -12) diff += 24;
    this.hourShown =
      Math.abs(diff) < HOUR_SNAP
        ? target
        : (this.hourShown + diff * (1 - Math.exp(-dt * HOUR_EASE)) + 24) % 24;
    this.lightAt(this.hourShown);
  }

  /** Поле травинок по качеству: на «быстро» газон - только фактура земли. */
  private setGrass(quality: Quality): void {
    if (quality === this.grassQuality || !this.mask || !this.noise) return;
    this.grassQuality = quality;
    if (this.grassField) {
      this.scene.remove(this.grassField.mesh);
      this.grassField.dispose();
      this.grassField = null;
    }
    const preset = GRASS_PRESETS[quality];
    if (!preset) return;
    this.grassField = new GrassField(this.mask, this.noise, preset);
    this.scene.add(this.grassField.mesh);
  }

  setMode(mode: Mode): void {
    this.freecam.setMode(mode);
  }

  resetView(): void {
    this.freecam.setMode('fly');
    this.freecam.setPose(overviewPose(this.world));
  }

  setView(pose: Pose, mode: Mode): void {
    this.freecam.setMode(mode);
    this.freecam.setPose(pose);
  }

  private trackPointer(): void {
    const move = (e: PointerEvent) => {
      const r = this.canvas.getBoundingClientRect();
      this.pointer = new THREE.Vector2(
        ((e.clientX - r.left) / r.width) * 2 - 1,
        -((e.clientY - r.top) / r.height) * 2 + 1,
      );
    };
    const leave = () => {
      this.pointer = null;
    };
    this.canvas.addEventListener('pointermove', move);
    this.canvas.addEventListener('pointerleave', leave);
    this.disposables.push({
      dispose: () => {
        this.canvas.removeEventListener('pointermove', move);
        this.canvas.removeEventListener('pointerleave', leave);
      },
    });
  }

  private resize(captureRatio?: number): void {
    const parent = this.canvas.parentElement;
    const w = parent?.clientWidth ?? this.canvas.clientWidth;
    const h = parent?.clientHeight ?? this.canvas.clientHeight;
    if (!w || !h) return;
    const q = QUALITY[this.settings.quality];
    const ratio = Math.min(
      Math.max(window.devicePixelRatio || 1, this.settings.quality === 'high' ? 1.35 : 1),
      q.pixelRatio,
      Math.sqrt(q.pixels / (w * h)),
    );
    this.renderer.setPixelRatio(captureRatio ?? ratio * this.adaptive.scale);
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  private applyPose(): void {
    const p = this.freecam.pose;
    this.camera.position.set(p.x, p.y, p.z);
    this.camera.rotation.set(p.pitch, p.yaw, 0, 'YXZ');
    this.fitDepth();
    this.camera.updateMatrixWorld();
  }

  /** Ближняя плоскость по высоте камеры: издалека земля не мерцает (depth.ts). */
  private fitDepth(): void {
    const near = nearPlane(this.camera.position.y);
    if (Math.abs(near - this.camera.near) <= this.camera.near * 0.05) return;
    this.camera.near = near;
    this.camera.updateProjectionMatrix();
  }

  private render(): void {
    this.renderer.info.reset();
    if (this.postprocessing) this.postprocessing.render();
    else this.renderer.render(this.scene, this.camera);
  }

  private frame(): void {
    if (!this.running) return;
    this.clock.update();
    const dt = this.clock.getDelta();
    const t = this.clock.getElapsed();
    if (this.tour) this.stepTour(dt);
    else this.freecam.update(dt);
    this.stepHour(dt);
    if (this.adaptive.sample(dt, t)) this.adapt();
    this.applyPose();
    this.prepare(t);
    this.render();
    this.tickStats();
    this.tickHover();
    this.tickPose();
  }

  /** Всё, что зависит от положения камеры: тени, небо, детализация крон, трава, погода. */
  private prepare(t: number): void {
    this.atmosphere.center(this.camera);
    const focus = new THREE.Vector3(0, 0, -Math.min(60, 20 + this.camera.position.y)).applyMatrix4(
      this.camera.matrixWorld,
    );
    focus.y = 0;
    this.atmosphere.follow(focus, t);
    const sunView = this.atmosphere.state.direction
      .clone()
      .transformDirection(this.camera.matrixWorldInverse);
    this.forest.wind.uSunView.value.copy(sunView);
    this.forest.update(this.camera, t);
    this.grassField?.update(this.camera, t);
    this.people?.update(t);
    this.weather.update(this.camera, t, this.particleLight);
  }

  /** Применить подбор адаптивного качества: разрешение и дальность крон. */
  /** Браузер рисует без видеокарты (программный WebGL): начинать сразу с «быстро». */
  get softwareRendering(): boolean {
    const gl = this.renderer.getContext();
    const info = gl.getExtension('WEBGL_debug_renderer_info');
    const name = info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : '';
    return /swiftshader|llvmpipe|softpipe|software|basic render/i.test(name);
  }

  private adapt(): void {
    this.resize();
    this.forest.apply({ lodDistance: this.lodDistance() });
  }

  private lodDistance(): number {
    return QUALITY[this.settings.quality].lodDistance * this.adaptive.lod;
  }

  private tickPose(): void {
    const now = performance.now();
    if (!this.events.pose || now - this.lastPoseAt < 500) return;
    this.lastPoseAt = now;
    const p = this.freecam.pose;
    const key = [p.x, p.y, p.z, p.yaw, p.pitch].map((v) => v.toFixed(2)).join() + this.freecam.mode;
    if (key === this.lastPose) return;
    this.lastPose = key;
    this.events.pose(p, this.freecam.mode);
  }

  private tickStats(): void {
    this.frames += 1;
    const now = performance.now();
    if (!this.fpsStart) this.fpsStart = now;
    if (now - this.fpsStart < 1000) return;
    const info = this.renderer.info.render;
    this.events.frame?.({
      fps: Math.round((this.frames * 1000) / (now - this.fpsStart)),
      drawCalls: info.calls,
      triangles: info.triangles,
      scale: this.adaptive.scale,
    });
    this.frames = 0;
    this.fpsStart = now;
  }

  /** Что под прицелом - раз в шесть кадров: подписи хватает, луч на каждый кадр не нужен. */
  private tickHover(): void {
    this.hoverTick = (this.hoverTick + 1) % 6;
    if (this.hoverTick || !this.events.hover) return;
    let dir: THREE.Vector3;
    if (this.freecam.locked) {
      dir = new THREE.Vector3(0, 0, -1).transformDirection(this.camera.matrixWorld);
    } else if (this.pointer) {
      this.raycaster.setFromCamera(this.pointer, this.camera);
      dir = this.raycaster.ray.direction;
    } else {
      if (this.lastHover !== null) {
        this.lastHover = null;
        this.events.hover(null);
      }
      return;
    }
    const o = this.camera.position;
    const bodies = this.forest.bodies();
    const index = pick({ ox: o.x, oy: o.y, oz: o.z, dx: dir.x, dy: dir.y, dz: dir.z }, bodies);
    const body = bodies[index];
    const id = body ? body.plant.id : null;
    if (id === this.lastHover) return;
    this.lastHover = id;
    this.events.hover(
      body
        ? {
            plant: body.plant,
            height: body.height,
            crown: body.radius * 2,
            distance: Math.hypot(body.x - o.x, body.z - o.z),
          }
        : null,
    );
  }

  /** Свет частиц погоды: днём они светлые, ночью едва видны - иначе снег светится сам. */
  private get particleLight(): THREE.Color {
    const night = this.atmosphere.state.night;
    return new THREE.Color().setScalar(1 - 0.8 * night);
  }

  private emitCamera(): void {
    this.events.camera?.({
      mode: this.freecam.mode,
      speed: this.freecam.flySpeed,
      locked: this.freecam.locked,
      touring: this.tour !== null,
    });
  }

  setSpeed(speed: number): void {
    this.freecam.setSpeed(speed);
  }

  /** Облёт над осью улицы. Маршрут строится по посадкам плана один раз; без посадок - по
   *  зданиям. Возвращает false, если облетать нечего. */
  startTour(): boolean {
    if (this.tourPlan === undefined) this.tourPlan = this.planTour();
    const plan = this.tourPlan;
    if (!plan) return false;
    this.freecam.setMode('fly');
    const travelled = tourStart(plan.route, plan.heights);
    this.tour = { ...plan, travelled, yaw: tourPose(plan.route, travelled, plan.heights).yaw };
    this.emitCamera();
    return true;
  }

  /** Маршрут над осью улицы и высота на нём: выше крыш, мимо которых он идёт. */
  private planTour(): { route: Route; heights: number[] } | null {
    const planted = this.world.plants.filter((p) => !p.existing);
    const points = planted.length
      ? planted
      : this.world.buildings.flatMap((b) => b.rings[0]?.slice(0, 1) ?? []);
    const route = tourRoute(points);
    if (!route) return null;
    const obstacles = this.world.buildings.map((b) => {
      const ring = b.rings[0] ?? [];
      const xs = ring.map((p) => p.x);
      const zs = ring.map((p) => p.z);
      return {
        minX: Math.min(...xs),
        minZ: Math.min(...zs),
        maxX: Math.max(...xs),
        maxZ: Math.max(...zs),
        height: b.height,
      };
    });
    return { route, heights: clearance(route, obstacles) };
  }

  get touring(): boolean {
    return this.tour !== null;
  }

  stopTour(): void {
    if (!this.tour) return;
    this.tour = null;
    this.emitCamera();
  }

  private stepTour(dt: number): void {
    const tour = this.tour;
    if (!tour) return;
    tour.travelled += this.freecam.flySpeed * Math.min(dt, 0.1);
    const pose = tourPose(tour.route, tour.travelled, tour.heights);
    // Курс догоняет направление маршрута за доли секунды: на конце разворот, а не рывок.
    let delta = pose.yaw - tour.yaw;
    delta = Math.atan2(Math.sin(delta), Math.cos(delta));
    tour.yaw += delta * (1 - Math.exp(-dt / 0.9));
    this.freecam.setPose({ ...pose, yaw: tour.yaw });
  }

  /** Кадр текущего вида для фото нейросетью: 1536 x 864 с позы камеры человека и виды в
   *  нём. Выше 6 м - съёмка с дрона, ниже - с тротуара: от этого зависит промпт. */
  async viewShot(): Promise<ViewShot> {
    const pose = { ...this.freecam.pose };
    const [blob] = await this.renderViews([pose], SHOT_WIDTH, SHOT_HEIGHT);
    if (!blob) throw new Error('Браузер не отдал кадр: фото не получится');
    return {
      blob,
      viewpoint: pose.y > DRONE_FROM_M ? 'aerial' : 'ground',
      ...speciesInView(this.forest.bodies(), pose),
      buildings: buildingsInView(this.allBuildings, pose),
    };
  }

  /** Виды плана в кадре с текущей позы: подпись снимка, который потом уйдёт на фото. */
  speciesHere(): {
    trees: string[];
    shrubs: string[];
    viewpoint: 'aerial' | 'ground';
    buildings: boolean;
  } {
    const pose = this.freecam.pose;
    const { trees, shrubs } = speciesInView(this.forest.bodies(), pose);
    return {
      trees,
      shrubs,
      viewpoint: pose.y > DRONE_FROM_M ? 'aerial' : 'ground',
      buildings: buildingsInView(this.allBuildings, pose),
    };
  }

  /** Ракурсы для галереи: улица отрезками или посадка по кругу. Солнце ночью не учитывается. */
  planShots(target: ShotTarget): AutoShot[] {
    const state = this.atmosphere.state;
    const sun = state.night > 0.5 ? null : { x: state.direction.x, z: state.direction.z };
    const obstacles = obstaclesOf(this.world);
    const bodies = this.forest.bodies();
    const shots =
      target.kind === 'street'
        ? streetShots(bodies, obstacles, sun)
        : plantShots(bodies, target.id, obstacles, sun);
    return shots.map((s) => ({ ...s, buildings: buildingsInView(this.allBuildings, s.pose) }));
  }

  /** Кадры заданных поз в PNG заданного размера, без панелей и без сдвига камеры человека.
   *  Кроны в кадре - в полной детализации до края: на снимке нет спешки кадра в секунду. */
  async renderViews(poses: readonly Pose[], width: number, height: number): Promise<Blob[]> {
    if (!this.running) throw new Error('3D-вид закрыт: снимать нечего');
    this.freecam.releaseKeys();
    this.renderer.setAnimationLoop(null);
    const ratio = this.renderer.getPixelRatio();
    const lod = this.lodDistance();
    const out: Blob[] = [];
    // Рабочие слои - для работы, не для фото: в кадр для модели они не идут.
    this.showOverlays(false, false);
    try {
      this.forest.apply({ lodDistance: QUALITY.high.lodDistance * 2 });
      this.renderer.setPixelRatio(1);
      this.renderer.setSize(width, height, false);
      this.camera.aspect = width / height;
      this.camera.updateProjectionMatrix();
      const t = this.clock.getElapsed();
      for (const pose of poses) {
        this.camera.position.set(pose.x, pose.y, pose.z);
        this.camera.rotation.set(pose.pitch, pose.yaw, 0, 'YXZ');
        this.fitDepth();
        this.camera.updateMatrixWorld();
        this.prepare(t);
        this.render();
        const blob = await new Promise<Blob | null>((resolve) => {
          this.canvas.toBlob(resolve, 'image/png');
        });
        if (!blob) throw new Error('Браузер не отдал кадр: снимок не получился');
        out.push(blob);
        if (!this.isRunning()) break;
      }
      return out;
    } finally {
      this.showOverlays(this.settings.utilities, this.settings.boundary);
      if (this.isRunning()) {
        this.forest.apply({ lodDistance: lod });
        this.renderer.setPixelRatio(ratio);
        this.resize();
        this.startLoop();
      }
    }
  }

  private isRunning(): boolean {
    return this.running;
  }

  /** PNG for presentations, up to 4K worth of pixels to bound HDR buffer memory. */
  async capture(scale = 1): Promise<Blob> {
    if (!this.running) throw new Error('3D-вид закрыт: снимать нечего');
    // Скачивание снимка уводит фокус, и keyup зажатой клавиши может потеряться.
    this.freecam.releaseKeys();
    // Цикл кадра на время снимка стоит: иначе следующий кадр перерисует холст до того, как
    // браузер его прочтёт, а экран мигнёт увеличенным разрешением.
    this.renderer.setAnimationLoop(null);
    const before = this.renderer.getPixelRatio();
    const size = this.renderer.getSize(new THREE.Vector2());
    const target = Math.min(before * scale, 4, Math.sqrt((3840 * 2160) / (size.x * size.y)));
    try {
      if (target !== before) this.renderer.setPixelRatio(target);
      this.resize(target);
      this.applyPose();
      this.prepare(this.clock.getElapsed());
      this.render();
      const blob = await new Promise<Blob | null>((resolve) => {
        this.canvas.toBlob(resolve, 'image/png');
      });
      if (!blob) throw new Error('Браузер не отдал кадр: снимок не получился');
      return blob;
    } finally {
      // За время кодирования страницу могли закрыть: закрытый движок не перезапускаем.
      if (this.isRunning()) {
        if (target !== before) this.renderer.setPixelRatio(before);
        this.resize();
        this.startLoop();
      }
    }
  }

  private startLoop(): void {
    if (this.paused) {
      // Смена размера холста стирает кадр: на паузе под галереей остаётся один неподвижный.
      this.applyPose();
      this.prepare(this.clock.getElapsed());
      this.render();
      return;
    }
    this.clock.update();
    this.renderer.setAnimationLoop(() => {
      this.frame();
    });
  }

  /** Остановить или продолжить цикл кадра. Остановленная сцена держит последний кадр. */
  setPaused(paused: boolean): void {
    if (paused === this.paused || !this.running) {
      this.paused = paused;
      return;
    }
    this.paused = paused;
    if (paused) this.renderer.setAnimationLoop(null);
    else this.startLoop();
  }

  dispose(): void {
    this.running = false;
    this.renderer.setAnimationLoop(null);
    this.resizeObserver?.disconnect();
    this.freecam.dispose();
    this.forest.dispose();
    this.atmosphere.dispose();
    this.lights?.dispose();
    this.grassField?.dispose();
    this.weather.dispose();
    this.people?.dispose();
    for (const d of this.disposables) d.dispose();
    this.postprocessing?.dispose();
    this.renderer.dispose();
  }
}
