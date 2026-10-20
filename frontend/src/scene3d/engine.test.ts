/* Движок 3D-вида в jsdom: WebGL нет, поэтому рендерер three.js подменён записывающим фейком,
 * а то, что без видеокарты не живёт (небо с PMREM, модели ez-tree, постобработка, маска
 * видимости, загрузка фактур), - фейками с тем же интерфейсом. Сцену движок собирает сам из
 * настоящих модулей: дома, газон, борта, ограды, люди, машины, погода. */

import * as THREE from 'three';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { installCanvas } from '../test/canvas';
import type { ContextJson } from './context';
import {
  DEFAULT_SETTINGS,
  type EngineEvents,
  type Hover,
  overviewPose,
  SceneEngine,
  type Stage,
  webglAvailable,
} from './engine';
import type { Pose } from './freecam';
import type { MaskInfo, SurfaceImage } from './ground';
import { ASPHALT, GRASS, PAVERS } from './surfaceMask';
import type { Body3 } from './trees';
import type { Line, Plant, SceneSpeciesJson, World } from './types';

interface SkyCall {
  hour: number;
  season: string;
  turn: number;
  clouds: number;
  shadowSize: number;
  shadowExtent: number;
  fog: number;
  wind: number;
}

interface ForestCall {
  age?: number;
  season?: string;
  showExisting?: boolean;
  lodDistance?: number;
}

const fakes = vi.hoisted(() => {
  /** Рендерер без WebGL: помнит размер, плотность пикселей, кадры и цикл анимации. */
  class FakeRenderer {
    static last: FakeRenderer | null = null;
    static floatBuffers = true;
    static software = false;
    readonly options: unknown;
    readonly debug = { checkShaderErrors: true };
    outputColorSpace = '';
    toneMapping = 0;
    readonly shadowMap = { enabled: false, type: 0, autoUpdate: true };
    readonly info = {
      autoReset: true,
      resets: 0,
      render: { calls: 12, triangles: 3400 },
      reset: () => {
        this.info.resets += 1;
      },
    };
    readonly extensions = {
      has: (name: string) => name === 'EXT_color_buffer_float' && FakeRenderer.floatBuffers,
    };
    readonly capabilities = { getMaxAnisotropy: () => 16 };
    pixelRatio = 1;
    width = 0;
    height = 0;
    renders = 0;
    compiled = 0;
    disposed = false;
    loop: (() => void) | null = null;
    readonly ratios: number[] = [];
    readonly sizes: [number, number][] = [];

    constructor(options: unknown) {
      this.options = options;
      FakeRenderer.last = this;
    }
    setPixelRatio(ratio: number): void {
      this.pixelRatio = ratio;
      this.ratios.push(ratio);
    }
    getPixelRatio(): number {
      return this.pixelRatio;
    }
    setSize(width: number, height: number): void {
      this.width = width;
      this.height = height;
      this.sizes.push([width, height]);
    }
    getSize(target: { set(x: number, y: number): unknown }): unknown {
      return target.set(this.width, this.height);
    }
    render(): void {
      this.renders += 1;
    }
    compileAsync(): Promise<void> {
      this.compiled += 1;
      return Promise.resolve();
    }
    setAnimationLoop(loop: (() => void) | null): void {
      this.loop = loop;
    }
    getContext(): unknown {
      return {
        getExtension: (name: string) =>
          name === 'WEBGL_debug_renderer_info' ? { UNMASKED_RENDERER_WEBGL: 0x9246 } : null,
        getParameter: () =>
          FakeRenderer.software ? 'Google SwiftShader' : 'ANGLE (NVIDIA GeForce RTX 3060)',
      };
    }
    dispose(): void {
      this.disposed = true;
    }
  }

  return {
    FakeRenderer,
    sky: [] as SkyCall[],
    night: 0,
    forest: [] as ForestCall[],
    forestUpdates: 0,
    forestDisposed: 0,
    bodies: [] as Body3[],
    post: { created: 0, applied: [] as string[], renders: 0, disposed: 0 },
    share: 0.5,
    /** Маска видимости не рисуется: контекст WebGL потерян. */
    shareLost: false,
    mask: null as MaskInfo | null,
    materialsFail: false,
  };
});

vi.mock('three', async (importOriginal) => ({
  ...(await importOriginal<typeof import('three')>()),
  WebGLRenderer: fakes.FakeRenderer,
}));

vi.mock('./sky', async () => {
  const T = await import('three');
  class Atmosphere {
    readonly state = {
      direction: new T.Vector3(0.4, 0.8, 0.45).normalize(),
      elevation: 40,
      color: new T.Color(1, 0.95, 0.9),
      intensity: 3,
      night: 0,
    };
    apply(settings: SkyCall): void {
      fakes.sky.push(settings);
      this.state.night = fakes.night;
    }
    center(): void {
      /* небо за камерой: в тесте не нужно */
    }
    follow(): void {
      /* тени за камерой: в тесте не нужно */
    }
    dispose(): void {
      fakes.sky.length = 0;
    }
  }
  return { Atmosphere };
});

vi.mock('./trees', async () => {
  const T = await import('three');
  class Forest {
    readonly root = new T.Group();
    readonly wind = {
      uTime: { value: 0 },
      uWind: { value: 0.35 },
      uSunView: { value: new T.Vector3(0, 1, 0) },
      uSunColor: { value: new T.Color(1, 1, 1) },
      uSnow: { value: 0 },
    };
    constructor(readonly plants: readonly Plant[]) {
      this.root.name = 'plants';
    }
    build(onStep: (done: number, total: number) => void): Promise<void> {
      onStep(1, 2);
      onStep(2, 2);
      return Promise.resolve();
    }
    apply(settings: ForestCall): void {
      fakes.forest.push(settings);
    }
    update(): void {
      fakes.forestUpdates += 1;
    }
    bodies(): Body3[] {
      return fakes.bodies;
    }
    dispose(): void {
      fakes.forestDisposed += 1;
    }
  }
  return { Forest };
});

vi.mock('./postprocessing', () => ({
  ScenePostprocessing: class {
    constructor() {
      fakes.post.created += 1;
    }
    apply(quality: string): void {
      fakes.post.applied.push(quality);
    }
    render(): void {
      fakes.post.renders += 1;
    }
    dispose(): void {
      fakes.post.disposed += 1;
    }
  },
}));

vi.mock('./visibility', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./visibility')>()),
  visibleShare: () => {
    if (fakes.shareLost) throw new Error('context lost');
    return fakes.share;
  },
}));

vi.mock('./materials', async () => {
  const T = await import('three');
  return {
    loadGroundMaterials: () => {
      if (fakes.materialsFail)
        return Promise.reject(new Error('Не удалось загрузить материалы 3D'));
      const textures = Array.from({ length: 9 }, () => new T.Texture());
      const [
        grass,
        asphalt,
        pavers,
        grassNormalMap,
        asphaltNormalMap,
        paversNormalMap,
        grassArmMap,
        asphaltArmMap,
        paversArmMap,
      ] = textures;
      return Promise.resolve({
        grass,
        asphalt,
        pavers,
        grassNormalMap,
        asphaltNormalMap,
        paversNormalMap,
        grassArmMap,
        asphaltArmMap,
        paversArmMap,
        textures,
      });
    },
  };
});

vi.mock('./ground', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./ground')>()),
  // Маска покрытий рисуется холстом 2D с чтением пикселей: в jsdom её задаёт тест.
  buildMask: () => {
    if (!fakes.mask) throw new Error('маска не задана');
    return fakes.mask;
  },
}));

// Сцена 120 x 80 м: тротуар (плитка) z 0..5, проезд z 5..15, остальное газон.
const MIN_X = -60;
const MIN_Z = -40;
const W = 120;
const H = 80;

function makeMask(): MaskInfo {
  const kinds = new Uint8Array(W * H).fill(GRASS);
  const road = new Uint8Array(W * H);
  const known = new Uint8Array(W * H);
  for (let pz = 0; pz < H; pz++) {
    for (let px = 0; px < W; px++) {
      const z = MIN_Z + pz + 0.5;
      const i = pz * W + px;
      if (z >= 0 && z < 5) kinds[i] = PAVERS;
      if (z >= 5 && z < 15) {
        kinds[i] = ASPHALT;
        road[i] = 1;
      }
      // Съёмка знает середину сцены, края - нет: там город вокруг ставит свои дороги.
      if (px > 10 && px < W - 10 && pz > 10 && pz < H - 10) known[i] = 1;
    }
  }
  const line = (points: [number, number][]): Line => ({
    points: points.map(([x, z]) => ({ x, z })),
  });
  return {
    roadContours: [
      line([
        [-55, 5],
        [55, 5],
        [55, 15],
        [-55, 15],
        [-55, 5],
      ]),
    ],
    texture: new THREE.DataTexture(new Uint8Array(4), 1, 1),
    grass: new THREE.DataTexture(new Uint8Array(4), 1, 1),
    cut: new THREE.DataTexture(new Uint8Array(4), 1, 1),
    rect: [MIN_X, MIN_Z, W, H],
    kinds,
    known,
    road,
    edges: {
      road: [
        line([
          [-55, 5],
          [55, 5],
        ]),
      ],
      garden: [
        line([
          [-55, 0],
          [55, 0],
        ]),
      ],
    },
    width: W,
    height: H,
    metresPerPx: 1,
  };
}

const linden: SceneSpeciesJson = {
  name_ru: 'Липа мелколистная',
  name_lat: 'Tilia cordata',
  life_form: 'tree_large',
  height_m: 25,
  crown_diameter_m: 6,
  crown_mature_m: 12,
  evergreen: false,
  conifer: false,
  growth: 'medium',
  genus: 'tilia',
  family: 'Malvaceae',
};

const lilac: SceneSpeciesJson = {
  ...linden,
  name_ru: 'Сирень обыкновенная',
  name_lat: 'Syringa vulgaris',
  life_form: 'shrub_medium',
  height_m: 3,
  crown_diameter_m: 1.5,
  crown_mature_m: 2.5,
  genus: 'syringa',
};

function plant(id: string, x: number, z: number, extra: Partial<Plant> = {}): Plant {
  return {
    id,
    x,
    z,
    type: 'tree',
    code: 'tilia_cordata',
    name: 'Липа',
    species: linden,
    existing: false,
    seed: 7,
    ...extra,
  };
}

const square = (x0: number, z0: number, x1: number, z1: number) => [
  { x: x0, z: z0 },
  { x: x1, z: z0 },
  { x: x1, z: z1 },
  { x: x0, z: z1 },
];

function makeWorld(over: Partial<World> = {}): World {
  const lineOf = (points: [number, number][]): Line => ({
    points: points.map(([x, z]) => ({ x, z })),
  });
  return {
    origin: [0, 0],
    bounds: [MIN_X, MIN_Z, MIN_X + W, MIN_Z + H],
    buildings: [
      {
        rings: [square(10, -35, 40, -15)],
        height: 27,
        floors: 9,
        source: 'label',
        kind: 'building',
        wall: 'brick',
        use: 'residential',
        seed: 3,
      },
    ],
    plants: [
      plant('t1', -30, 2),
      plant('t2', -20, 2),
      plant('t3', 0, -8, { type: 'existing_tree', existing: true, existingRadius: 3 }),
      plant('s1', -10, -5, { type: 'shrub', code: 'syringa', name: 'Сирень', species: lilac }),
    ],
    curbs: [
      lineOf([
        [-55, 5],
        [55, 5],
      ]),
    ],
    utilities: [
      {
        kind: 'utility.access',
        lines: [
          lineOf([
            [-40, 10],
            [40, 10],
          ]),
        ],
      },
    ],
    boundary: [
      lineOf([
        [-58, -38],
        [58, -38],
        [58, 38],
      ]),
    ],
    fences: [
      lineOf([
        [-50, -12],
        [-30, -12],
        [-30, -2],
      ]),
    ],
    poles: [{ x: 5, z: 4.5 }],
    lawns: [],
    sidewalks: [],
    roads: [],
    benches: [{ x: -40, z: 1, angle: 0 }],
    groundLabels: [{ x: -45, z: -25, kind: 'kids' }],
    flowerbeds: [[square(-5, -30, 0, -25)]],
    canopies: [square(45, -30, 50, -25)],
    floorsBy: { label: 1, neighbor: 0, letter: 0, assumed: 0 },
    fallback: false,
    ...over,
  };
}

/** Кольцо сцены (x, z) - в координатах чертежа (X, Y = -z) для surface.json. */
const drawing = (x0: number, z0: number, x1: number, z1: number) => [
  [
    [x0, -z0],
    [x1, -z0],
    [x1, -z1],
    [x0, -z1],
    [x0, -z0],
  ],
];

function makeSurface(): SurfaceImage {
  return {
    img: new Image(),
    origin: [MIN_X, -(MIN_Z + H)],
    cell: 1,
    width: W,
    height: H,
    areas: {
      soil: [],
      paved: [drawing(-55, 0, 55, 5), drawing(-55, 15, 55, 20), drawing(-55, -32, -35, -18)],
      paved_kind: ['pavers', 'asphalt', 'special'],
      flowerbeds: [drawing(20, 25, 25, 30)],
    },
  };
}

class RecordingObserver {
  static last: RecordingObserver | null = null;
  observed: Element[] = [];
  disconnected = false;
  constructor(readonly callback: () => void) {
    RecordingObserver.last = this;
  }
  observe(el: Element): void {
    this.observed.push(el);
  }
  unobserve(): void {
    /* не нужно */
  }
  disconnect(): void {
    this.disconnected = true;
  }
}

let now = 0;

function must<T>(value: T | null | undefined): T {
  if (value === null || value === undefined) throw new Error('нет значения');
  return value;
}

function setup(): { canvas: HTMLCanvasElement; parent: HTMLDivElement } {
  installCanvas();
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    queueMicrotask(() => {
      cb(0);
    });
    return 1;
  });
  vi.stubGlobal('ResizeObserver', RecordingObserver);
  vi.spyOn(performance, 'now').mockImplementation(() => now);
  const parent = document.createElement('div');
  Object.defineProperty(parent, 'clientWidth', { configurable: true, value: 800 });
  Object.defineProperty(parent, 'clientHeight', { configurable: true, value: 450 });
  const canvas = document.createElement('canvas');
  canvas.toBlob = (callback: BlobCallback) => {
    callback(new Blob(['png'], { type: 'image/png' }));
  };
  parent.append(canvas);
  document.body.append(parent);
  return { canvas, parent };
}

function renderer(): InstanceType<typeof fakes.FakeRenderer> {
  const r = fakes.FakeRenderer.last;
  if (!r) throw new Error('рендерер не создан');
  return r;
}

/** Кадр цикла анимации через dt секунд. */
function tick(dt = 1 / 60): void {
  now += dt * 1000;
  const loop = renderer().loop;
  if (!loop) throw new Error('цикл кадра остановлен');
  loop();
}

interface Recorded {
  progress: [Stage, number, number][];
  hover: (Hover | null)[];
  camera: { mode: string; touring: boolean; locked: boolean; speed: number }[];
  frame: { fps: number; drawCalls: number; triangles: number; scale: number }[];
  pose: [Pose, string][];
}

function recorder(): { events: EngineEvents; got: Recorded } {
  const got: Recorded = { progress: [], hover: [], camera: [], frame: [], pose: [] };
  return {
    got,
    events: {
      progress: (stage, done, total) => got.progress.push([stage, done, total]),
      hover: (h) => got.hover.push(h),
      camera: (c) => got.camera.push(c),
      frame: (f) => got.frame.push(f),
      pose: (p, mode) => got.pose.push([p, mode]),
    },
  };
}

async function engineOf(
  world = makeWorld(),
  surface: SurfaceImage | null = makeSurface(),
): Promise<{ engine: SceneEngine; got: Recorded; canvas: HTMLCanvasElement }> {
  const { canvas } = setup();
  const { events, got } = recorder();
  const engine = await SceneEngine.create(canvas, world, surface, events);
  opened.push(engine);
  return { engine, got, canvas };
}

const opened: SceneEngine[] = [];

beforeEach(() => {
  now = 1000;
  fakes.FakeRenderer.last = null;
  fakes.FakeRenderer.floatBuffers = true;
  fakes.FakeRenderer.software = false;
  fakes.sky.length = 0;
  fakes.night = 0;
  fakes.forest.length = 0;
  fakes.forestUpdates = 0;
  fakes.forestDisposed = 0;
  fakes.bodies = [];
  fakes.post = { created: 0, applied: [], renders: 0, disposed: 0 };
  fakes.share = 0.5;
  fakes.shareLost = false;
  fakes.mask = makeMask();
  fakes.materialsFail = false;
  RecordingObserver.last = null;
});

afterEach(() => {
  for (const engine of opened.splice(0)) engine.dispose();
  document.body.innerHTML = '';
});

describe('сборка сцены', () => {
  it('проходит этапы по порядку и запускает цикл кадра', async () => {
    const { got } = await engineOf();
    const stages = got.progress.map(([stage]) => stage);
    expect(stages).toEqual(['textures', 'ground', 'buildings', 'plants', 'plants', 'ready']);
    expect(got.progress).toContainEqual(['plants', 2, 2]);
    const r = renderer();
    expect(r.compiled).toBe(1);
    expect(r.loop).not.toBeNull();
    expect(r.shadowMap.enabled).toBe(true);
    expect(r.toneMapping).toBe(THREE.ACESFilmicToneMapping);
    expect(r.info.autoReset).toBe(false);
    // Камера сообщила о себе после сборки: полёт, не облёт.
    expect(got.camera.at(-1)).toMatchObject({ mode: 'fly', touring: false, locked: false });
  });

  it('наполняет сцену домами, газоном, бортами, оградами, людьми, машинами и погодой', async () => {
    const { engine } = await engineOf();
    const names = new Set<string>();
    engine.scene.traverse((o) => {
      if (o.name) names.add(o.name);
    });
    for (const name of [
      'green-3d',
      'walls',
      'roofs',
      'plants',
      'weather',
      'curbs',
      'garden-curbs',
      'fences',
      'gutters',
      'paving-pavers',
      'paving-asphalt',
      'special-cover',
      'grass',
      'overlay-utilities',
      'overlay-boundary',
    ]) {
      expect(names, name).toContain(name);
    }
    // Рабочие слои по умолчанию скрыты.
    expect(engine.scene.getObjectByName('overlay-utilities')?.visible).toBe(false);
    expect(engine.scene.getObjectByName('overlay-boundary')?.visible).toBe(false);
    // Отрисованное - на холсте родителя: 800 x 450 и камера с тем же соотношением.
    expect(renderer().width).toBe(800);
    expect(renderer().height).toBe(450);
    expect(engine.camera.aspect).toBeCloseTo(800 / 450);
    // Наблюдатель размеров следит за родителем холста.
    expect(RecordingObserver.last?.observed).toEqual([engine.canvas.parentElement]);
  });

  it('без карты покрытий строит сцену по маске: без сеток плитки и резины', async () => {
    const { engine } = await engineOf(makeWorld({ benches: [], fenceAxes: true }), null);
    expect(engine.scene.getObjectByName('paving-pavers')).toBeUndefined();
    expect(engine.scene.getObjectByName('special-cover')).toBeUndefined();
    expect(engine.scene.getObjectByName('walls')).toBeDefined();
    expect(renderer().loop).not.toBeNull();
  });

  it('пустой мир без домов, оград и проезда тоже открывается', async () => {
    const mask = makeMask();
    mask.road.fill(0);
    mask.roadContours = [];
    mask.edges = { road: [], garden: [] };
    fakes.mask = mask;
    const { engine } = await engineOf(
      makeWorld({
        buildings: [],
        plants: [],
        curbs: [],
        fences: [],
        poles: [],
        benches: undefined,
        groundLabels: undefined,
        flowerbeds: undefined,
        canopies: undefined,
        utilities: undefined,
        boundary: undefined,
      }),
      null,
    );
    expect(engine.scene.getObjectByName('walls')).toBeUndefined();
    expect(engine.scene.getObjectByName('curbs')).toBeUndefined();
    expect(engine.scene.getObjectByName('fences')).toBeUndefined();
    // Облетать нечего: ни посадок, ни домов.
    expect(engine.startTour()).toBe(false);
  });

  it('ошибка загрузки материалов освобождает рендерер и пробрасывается', async () => {
    fakes.materialsFail = true;
    const { canvas } = setup();
    await expect(SceneEngine.create(canvas, makeWorld(), null, {})).rejects.toThrow(
      'Не удалось загрузить материалы 3D',
    );
    expect(renderer().disposed).toBe(true);
    expect(renderer().loop).toBeNull();
  });

  it('без буферов с плавающей точкой постобработка не создаётся, кадр рисует рендерер', async () => {
    fakes.FakeRenderer.floatBuffers = false;
    const { engine } = await engineOf();
    expect(fakes.post.created).toBe(0);
    const before = renderer().renders;
    tick();
    expect(renderer().renders).toBe(before + 1);
    expect(engine.touring).toBe(false);
  });
});

describe('пульт', () => {
  it('сезон, возраст и показ существующих уходят в лес', async () => {
    const { engine } = await engineOf();
    engine.apply({ season: 'autumn', age: 25, showExisting: false });
    expect(fakes.forest.at(-1)).toMatchObject({
      age: 25,
      season: 'autumn',
      showExisting: false,
      lodDistance: 60,
    });
    expect(fakes.sky.at(-1)?.season).toBe('autumn');
  });

  it('зимой снег лежит и на земле, и на кронах, трава под ним уходит', async () => {
    const { engine } = await engineOf();
    const forest = (engine as unknown as { forest: { wind: { uSnow: { value: number } } } }).forest;
    engine.apply({ season: 'winter' });
    expect(forest.wind.uSnow.value).toBeCloseTo(0.85);
    engine.apply({ season: 'summer' });
    expect(forest.wind.uSnow.value).toBe(0);
  });

  it('ползунок часа меняет свет плавно: солнце догоняет выбранный час в кадрах', async () => {
    const { engine } = await engineOf();
    const applied = fakes.sky.length;
    engine.apply({ hour: 15 });
    // Сам вызов ничего не пересобирает и не двигает солнце.
    expect(fakes.sky.length).toBe(applied);
    tick(0.1);
    const first = fakes.sky.at(-1)?.hour ?? 0;
    expect(first).toBeGreaterThan(11);
    expect(first).toBeLessThan(15);
    for (let i = 0; i < 60; i++) tick(0.1);
    expect(fakes.sky.at(-1)?.hour).toBe(15);
    // Час встал: новых пересчётов света нет.
    const settled = fakes.sky.length;
    tick(0.1);
    expect(fakes.sky.length).toBe(settled);
  });

  it('через полночь солнце идёт коротким путём', async () => {
    const { engine } = await engineOf();
    engine.apply({ season: 'summer', hour: 23 });
    engine.apply({ hour: 1 });
    tick(0.1);
    const hour = fakes.sky.at(-1)?.hour ?? 0;
    // С 23 к 1 вперёд через 0, а не назад через полдень.
    expect(hour > 23 || hour < 1).toBe(true);
    engine.apply({ hour: 22 });
    tick(0.1);
    const back = fakes.sky.at(-1)?.hour ?? 0;
    expect(back > 22 || back < 2).toBe(true);
  });

  it('поворот солнца - только свет, без пересборки леса', async () => {
    const { engine } = await engineOf();
    const forestCalls = fakes.forest.length;
    engine.apply({ sunTurn: 90 });
    expect(fakes.sky.at(-1)?.turn).toBe(90);
    expect(fakes.forest.length).toBe(forestCalls);
  });

  it('качество меняет разрешение, тени, траву и постобработку', async () => {
    const { engine } = await engineOf();
    expect(fakes.post.created).toBe(1);
    expect(fakes.post.applied.at(-1)).toBe('medium');
    engine.apply({ quality: 'high' });
    expect(fakes.post.applied.at(-1)).toBe('high');
    expect(fakes.forest.at(-1)?.lodDistance).toBe(110);
    expect(renderer().pixelRatio).toBeCloseTo(1.35);
    engine.apply({ quality: 'low' });
    // На «быстро» постобработки нет, травинок нет, тени меньше.
    expect(fakes.post.disposed).toBe(1);
    expect(engine.scene.getObjectByName('grass')).toBeUndefined();
    expect(fakes.sky.at(-1)?.shadowSize).toBe(2048);
    const before = renderer().renders;
    tick();
    expect(renderer().renders).toBe(before + 1);
    engine.apply({ enhanced: true, quality: 'medium' });
    expect(fakes.post.created).toBe(2);
    expect(engine.scene.getObjectByName('grass')).toBeDefined();
    const posts = fakes.post.renders;
    tick();
    expect(fakes.post.renders).toBe(posts + 1);
  });

  it('погода: дождь мочит землю, ветер качает траву', async () => {
    const { engine } = await engineOf();
    const ground = (engine as unknown as { groundWeather: { uWet: { value: number } } })
      .groundWeather;
    engine.apply({ rain: 1, wind: 0.9 });
    expect(ground.uWet.value).toBeGreaterThan(0);
    const field = (
      engine as unknown as {
        grassField: { uniforms: { uWind: { value: number }; uGrow: { value: number } } };
      }
    ).grassField;
    expect(field.uniforms.uWind.value).toBe(0.9);
    expect(field.uniforms.uGrow.value).toBe(1);
    engine.apply({ rain: 0, snow: 1 });
    expect(ground.uWet.value).toBe(0);
    // Снегопад укрывает газон: травинки уходят под снег.
    expect(field.uniforms.uGrow.value).toBeLessThan(1);
  });

  it('машины, город, рабочие слои и объекты не из чертежа включаются флажками', async () => {
    const { engine } = await engineOf();
    engine.apply({ utilities: true, boundary: true, cars: false, extras: false });
    expect(engine.scene.getObjectByName('overlay-utilities')?.visible).toBe(true);
    expect(engine.scene.getObjectByName('overlay-boundary')?.visible).toBe(true);
    const extras: THREE.Object3D[] = [];
    engine.scene.traverse((o) => {
      if (o.userData.extra === true) extras.push(o);
    });
    expect(extras.length).toBeGreaterThan(0);
    expect(extras.every((o) => !o.visible)).toBe(true);
    engine.apply({ extras: true });
    expect(extras.every((o) => o.visible)).toBe(true);
  });

  it('ночью свет фасадов и фонарей включается, частицы погоды темнеют', async () => {
    const { engine } = await engineOf();
    fakes.night = 1;
    engine.apply({ hour: 23, clouds: 0.1 });
    const facade = (engine as unknown as { facade: { uNight: { value: number } } }).facade;
    expect(facade.uNight.value).toBe(1);
    const light = (engine as unknown as { particleLight: THREE.Color }).particleLight;
    expect(light.r).toBeCloseTo(0.2);
  });

  it('программный WebGL распознаётся по имени рендерера', async () => {
    const { engine } = await engineOf();
    expect(engine.softwareRendering).toBe(false);
    fakes.FakeRenderer.software = true;
    expect(engine.softwareRendering).toBe(true);
  });
});

describe('камера', () => {
  it('режимы полёта и пешехода, скорость и сброс вида сообщаются странице', async () => {
    const { engine, got } = await engineOf();
    engine.setMode('walk');
    expect(got.camera.at(-1)?.mode).toBe('walk');
    expect(engine.freecam.pose.y).toBeGreaterThanOrEqual(1.7);
    engine.setSpeed(30);
    expect(got.camera.at(-1)?.speed).toBe(30);
    engine.resetView();
    expect(engine.freecam.mode).toBe('fly');
    expect(engine.freecam.pose).toEqual(overviewPose(engine.world));
    const pose: Pose = { x: 1, y: 2, z: 3, yaw: 0.5, pitch: -0.1 };
    engine.setView(pose, 'walk');
    expect(engine.freecam.mode).toBe('walk');
    expect(engine.freecam.pose).toEqual(pose);
  });

  it('кадр ставит камеру по позе и подбирает ближнюю плоскость по высоте', async () => {
    const { engine } = await engineOf();
    engine.setView({ x: 5, y: 300, z: 7, yaw: 0, pitch: -1 }, 'fly');
    tick();
    expect(engine.camera.position.x).toBeCloseTo(5);
    expect(engine.camera.position.y).toBeCloseTo(300);
    const far = engine.camera.near;
    engine.setView({ x: 5, y: 2, z: 7, yaw: 0, pitch: 0 }, 'fly');
    tick();
    expect(engine.camera.near).toBeLessThan(far);
    expect(fakes.forestUpdates).toBeGreaterThan(0);
  });

  it('облёт идёт по маршруту, а клавиша движения его прерывает', async () => {
    // Аллея вдоль всего борта: маршрут облёта длиннее 20 м.
    const alley = Array.from({ length: 11 }, (_, i) => plant(`a${String(i)}`, -50 + i * 10, 2));
    const { engine, got } = await engineOf(makeWorld({ plants: alley }));
    expect(engine.startTour()).toBe(true);
    expect(engine.touring).toBe(true);
    expect(got.camera.at(-1)?.touring).toBe(true);
    const start = { ...engine.freecam.pose };
    for (let i = 0; i < 20; i++) tick(0.05);
    const moved = engine.freecam.pose;
    expect(Math.hypot(moved.x - start.x, moved.z - start.z)).toBeGreaterThan(0.1);
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyW' }));
    expect(engine.touring).toBe(false);
    expect(got.camera.at(-1)?.touring).toBe(false);
    // Второй стоп ничего не шлёт.
    const events = got.camera.length;
    engine.stopTour();
    expect(got.camera.length).toBe(events);
    // Маршрут строится один раз и переиспользуется.
    expect(engine.startTour()).toBe(true);
  });

  it('без посадок плана облёт идёт по домам', async () => {
    const { engine } = await engineOf(
      makeWorld({
        plants: [plant('old', 0, -8, { existing: true, type: 'existing_tree' })],
        buildings: [
          ...makeWorld().buildings,
          {
            ...must(makeWorld().buildings[0]),
            rings: [square(-50, -35, -30, -20)],
          },
        ],
      }),
    );
    expect(engine.startTour()).toBe(true);
  });

  it('поза камеры уходит странице не чаще двух раз в секунду и только при изменении', async () => {
    const { engine, got } = await engineOf();
    tick(0.6);
    expect(got.pose).toHaveLength(1);
    tick(0.1);
    expect(got.pose).toHaveLength(1);
    tick(0.6);
    // Камера не двигалась: та же поза второй раз не шлётся.
    expect(got.pose).toHaveLength(1);
    engine.setView({ x: 9, y: 20, z: 9, yaw: 1, pitch: -0.3 }, 'fly');
    tick(0.6);
    expect(got.pose).toHaveLength(2);
    expect(got.pose[1]?.[1]).toBe('fly');
  });

  it('раз в секунду страница получает счётчики кадра', async () => {
    const { got } = await engineOf();
    for (let i = 0; i < 70; i++) tick(1 / 60);
    expect(got.frame.length).toBeGreaterThanOrEqual(1);
    const stats = got.frame[0];
    expect(stats?.drawCalls).toBe(12);
    expect(stats?.triangles).toBe(3400);
    expect(stats?.fps).toBeGreaterThan(30);
    expect(stats?.scale).toBe(1);
  });

  it('медленные кадры снижают разрешение адаптивным качеством', async () => {
    const { got } = await engineOf();
    const before = renderer().pixelRatio;
    for (let i = 0; i < 150; i++) tick(1 / 20);
    expect(renderer().pixelRatio).toBeLessThan(before);
    expect(fakes.forest.length).toBeGreaterThan(0);
    expect(got.frame.at(-1)?.scale).toBeLessThan(1);
  });

  it('ресайз родителя меняет размер холста и соотношение камеры', async () => {
    const { engine } = await engineOf();
    const parent = must(engine.canvas.parentElement);
    Object.defineProperty(parent, 'clientWidth', { configurable: true, value: 400 });
    Object.defineProperty(parent, 'clientHeight', { configurable: true, value: 400 });
    RecordingObserver.last?.callback();
    expect(renderer().width).toBe(400);
    expect(engine.camera.aspect).toBe(1);
    // Нулевой размер (вкладка свёрнута) холст не трогает.
    Object.defineProperty(parent, 'clientWidth', { configurable: true, value: 0 });
    const sizes = renderer().sizes.length;
    RecordingObserver.last?.callback();
    expect(renderer().sizes.length).toBe(sizes);
  });
});

describe('прицел', () => {
  const body = (id: string, x: number, z: number): Body3 => ({
    plant: plant(id, x, z),
    x,
    z,
    height: 10,
    radius: 3,
  });

  it('под курсором - посадка: подпись и рамка размеров, уход курсора - снять', async () => {
    const { engine, got, canvas } = await engineOf();
    fakes.bodies = [body('t1', 0, -20)];
    engine.setView({ x: 0, y: 6, z: 0, yaw: 0, pitch: 0 }, 'fly');
    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 800, 450));
    canvas.dispatchEvent(new MouseEvent('pointermove', { clientX: 400, clientY: 225 }));
    for (let i = 0; i < 6; i++) tick();
    const hover = got.hover.at(-1);
    expect(hover?.plant.id).toBe('t1');
    expect(hover?.crown).toBe(6);
    expect(hover?.distance).toBeCloseTo(20);
    const guide = (engine as unknown as { guide: { group: THREE.Object3D } }).guide.group;
    expect(guide.visible).toBe(true);
    // Та же посадка повторно не сообщается.
    const count = got.hover.length;
    for (let i = 0; i < 6; i++) tick();
    expect(got.hover.length).toBe(count);
    canvas.dispatchEvent(new MouseEvent('pointerleave'));
    for (let i = 0; i < 6; i++) tick();
    expect(got.hover.at(-1)).toBeNull();
    expect(guide.visible).toBe(false);
  });

  it('с захваченной мышью смотрит центр кадра; мимо посадок - пусто', async () => {
    const { engine, got, canvas } = await engineOf();
    fakes.bodies = [body('t2', 0, -20)];
    engine.setView({ x: 0, y: 6, z: 0, yaw: 0, pitch: 0 }, 'fly');
    Object.defineProperty(document, 'pointerLockElement', { configurable: true, value: canvas });
    try {
      for (let i = 0; i < 6; i++) tick();
      expect(got.hover.at(-1)?.plant.id).toBe('t2');
      engine.setView({ x: 0, y: 6, z: 0, yaw: Math.PI, pitch: 0 }, 'fly');
      for (let i = 0; i < 6; i++) tick();
      expect(got.hover.at(-1)).toBeNull();
    } finally {
      Reflect.deleteProperty(document, 'pointerLockElement');
    }
  });
});

describe('снимки', () => {
  it('capture рисует кадр в повышенном разрешении и возвращает цикл', async () => {
    const { engine } = await engineOf();
    const ratio = renderer().pixelRatio;
    const blob = await engine.capture(2);
    expect(blob.type).toBe('image/png');
    expect(renderer().ratios).toContain(ratio * 2);
    expect(renderer().pixelRatio).toBeCloseTo(ratio);
    expect(renderer().loop).not.toBeNull();
  });

  it('браузер не отдал кадр - понятная ошибка, цикл восстановлен', async () => {
    const { engine, canvas } = await engineOf();
    canvas.toBlob = (callback: BlobCallback) => {
      callback(null);
    };
    await expect(engine.capture()).rejects.toThrow('Браузер не отдал кадр');
    expect(renderer().loop).not.toBeNull();
    await expect(engine.renderViews([engine.freecam.pose], 64, 36)).rejects.toThrow(
      'снимок не получился',
    );
    await expect(engine.viewShot()).rejects.toThrow('Браузер не отдал кадр');
  });

  it('renderViews снимает каждую позу без рабочих слоёв и рамки размеров', async () => {
    const { engine } = await engineOf();
    engine.apply({ utilities: true });
    const overlay = must(engine.scene.getObjectByName('overlay-utilities'));
    const seen: boolean[] = [];
    engine.canvas.toBlob = (callback: BlobCallback) => {
      seen.push(overlay.visible);
      callback(new Blob(['png'], { type: 'image/png' }));
    };
    const poses: Pose[] = [
      { x: 0, y: 2, z: 0, yaw: 0, pitch: 0 },
      { x: 10, y: 40, z: 10, yaw: 1, pitch: -0.8 },
    ];
    const blobs = await engine.renderViews(poses, 1536, 864);
    expect(blobs).toHaveLength(2);
    expect(seen).toEqual([false, false]);
    expect(renderer().sizes).toContainEqual([1536, 864]);
    // После снимков - снова экран и рабочие слои.
    expect(overlay.visible).toBe(true);
    expect(renderer().width).toBe(800);
    expect(fakes.forest.at(-1)?.lodDistance).toBe(60);
  });

  it('viewShot: с высоты - дрон, с тротуара - человек; дома в кадре по маске', async () => {
    const { engine } = await engineOf();
    fakes.bodies = [
      { plant: plant('t1', 0, -20), x: 0, z: -20, height: 10, radius: 3 },
      {
        plant: plant('s1', 2, -18, { type: 'shrub', species: lilac }),
        x: 2,
        z: -18,
        height: 2,
        radius: 1,
      },
    ];
    engine.setView({ x: 0, y: 30, z: 0, yaw: 0, pitch: -0.4 }, 'fly');
    const aerial = await engine.viewShot();
    expect(aerial.viewpoint).toBe('aerial');
    expect(aerial.trees).toContain('Tilia cordata');
    expect(aerial.shrubs).toContain('Syringa vulgaris');
    engine.setView({ x: 25, y: 1.7, z: 10, yaw: 0, pitch: 0 }, 'walk');
    const here = engine.speciesHere();
    expect(here.viewpoint).toBe('ground');
    expect(here.buildings).toBe(true);
    // Дом заслонён: маска видимости говорит «почти не виден».
    fakes.share = 0;
    expect(engine.speciesHere().buildings).toBe(false);
    // Маска не нарисовалась - ответ проекции.
    fakes.shareLost = true;
    expect(engine.speciesHere().buildings).toBe(true);
    // Камера человека после проверки на месте.
    expect(engine.camera.aspect).toBeCloseTo(800 / 450);
    // Спиной к дому - домов нет без маски.
    engine.setView({ x: 25, y: 1.7, z: 10, yaw: Math.PI, pitch: 0 }, 'walk');
    expect(engine.speciesHere().buildings).toBe(false);
  });

  it('ракурсы улицы и посадки для галереи, ночью без солнца', async () => {
    const { engine } = await engineOf();
    fakes.bodies = [
      { plant: plant('t1', -30, 2), x: -30, z: 2, height: 10, radius: 3 },
      { plant: plant('t2', -20, 2), x: -20, z: 2, height: 10, radius: 3 },
      { plant: plant('t4', 20, 2), x: 20, z: 2, height: 10, radius: 3 },
    ];
    const street = engine.planShots({ kind: 'street' });
    expect(street.length).toBeGreaterThan(0);
    expect(street.every((s) => typeof s.buildings === 'boolean')).toBe(true);
    fakes.night = 1;
    engine.apply({ hour: 2 });
    const one = engine.planShots({ kind: 'plant', id: 't1' });
    expect(one.length).toBeGreaterThan(0);
  });

  it('пауза держит кадр: снимок на паузе цикл не запускает', async () => {
    const { engine } = await engineOf();
    engine.setPaused(true);
    expect(renderer().loop).toBeNull();
    // Повторная пауза ничего не меняет.
    engine.setPaused(true);
    const renders = fakes.post.renders;
    await engine.capture();
    expect(renderer().loop).toBeNull();
    // Снимок и после него один неподвижный кадр на паузе - оба через постобработку.
    expect(fakes.post.renders).toBe(renders + 2);
    engine.setPaused(false);
    expect(renderer().loop).not.toBeNull();
  });

  it('закрытый движок снимать отказывается', async () => {
    const { engine } = await engineOf();
    engine.dispose();
    await expect(engine.capture()).rejects.toThrow('3D-вид закрыт');
    await expect(engine.renderViews([], 10, 10)).rejects.toThrow('3D-вид закрыт');
    // Пауза закрытого движка цикл не трогает.
    engine.setPaused(false);
    expect(renderer().loop).toBeNull();
  });

  it('закрытие во время кодирования кадра не перезапускает цикл', async () => {
    const { engine } = await engineOf();
    engine.canvas.toBlob = (callback: BlobCallback) => {
      engine.dispose();
      callback(new Blob(['png'], { type: 'image/png' }));
    };
    await engine.capture();
    expect(renderer().loop).toBeNull();
    const blobs = await new Promise<Blob[]>((resolve, reject) => {
      // Второй снимок уже закрытого движка - отказ.
      engine.renderViews([engine.freecam.pose], 10, 10).then(resolve, reject);
    }).catch((e: unknown) => e);
    expect(blobs).toBeInstanceOf(Error);
  });

  it('renderViews прерывается, если движок закрыли между позами', async () => {
    const { engine } = await engineOf();
    let shots = 0;
    engine.canvas.toBlob = (callback: BlobCallback) => {
      shots += 1;
      engine.dispose();
      callback(new Blob(['png'], { type: 'image/png' }));
    };
    const pose = engine.freecam.pose;
    const blobs = await engine.renderViews([pose, pose, pose], 10, 10);
    expect(blobs).toHaveLength(1);
    expect(shots).toBe(1);
    expect(renderer().loop).toBeNull();
  });
});

describe('город вокруг', () => {
  const context: ContextJson = {
    version: 1,
    source: 'osm',
    buildings: [
      {
        ring: [
          [70, -10],
          [90, -10],
          [90, 10],
          [70, 10],
        ],
        levels: 5,
        kind: 'apartments',
      },
      {
        ring: [
          [400, 300],
          [420, 300],
          [420, 320],
          [400, 320],
        ],
        levels: null,
        kind: 'yes',
      },
    ],
    // Дерево карты внутри съёмки отбрасывается, на дальнем поле - остаётся.
    trees: [
      [80, 40],
      [0, -20],
      [-58, 38],
    ],
    roads: [
      {
        line: [
          [-200, 60],
          [200, 60],
        ],
        width_m: 7,
        kind: 'residential',
      },
    ],
    parkings: [
      {
        ring: [
          [-150, 80],
          [-120, 80],
          [-120, 100],
          [-150, 100],
        ],
        kind: 'surface',
      },
    ],
    notes: [],
  };

  it('добавляется один раз и показывается флажком «город»', async () => {
    const { engine } = await engineOf();
    const count = engine.addContext(context);
    expect(count).toBeGreaterThan(0);
    const city = engine.scene.getObjectByName('city-context');
    expect(city).toBeDefined();
    expect(city?.visible).toBe(false);
    expect(engine.scene.getObjectByName('city-cars')?.visible).toBe(true);
    engine.apply({ city: true, cars: false });
    expect(city?.visible).toBe(true);
    expect(engine.scene.getObjectByName('city-cars')?.visible).toBe(false);
    // Повторно не строится.
    expect(engine.addContext(context)).toBe(0);
    // Дома города - тоже «здания в кадре» для фото.
    engine.setView({ x: 50, y: 2, z: 0, yaw: -Math.PI / 2, pitch: 0 }, 'walk');
    expect(engine.speciesHere().buildings).toBe(true);
  });

  it('закрытому движку город не нужен', async () => {
    const { engine } = await engineOf();
    engine.dispose();
    expect(engine.addContext(context)).toBe(0);
  });
});

describe('бортовой камень', () => {
  const shaderOf = (mesh: THREE.Mesh) => {
    const material = mesh.material as THREE.MeshStandardMaterial;
    const shader = {
      vertexShader: ['#include <common>', '#include <worldpos_vertex>'].join('\n'),
      fragmentShader: ['#include <common>', '#include <map_fragment>'].join('\n'),
      uniforms: {},
    };
    material.onBeforeCompile(
      shader as unknown as Parameters<THREE.Material['onBeforeCompile']>[0],
      renderer() as unknown as THREE.WebGLRenderer,
    );
    return shader;
  };

  it('дорожный борт темнеет у асфальта, садовый - только с газонной грани', async () => {
    const { engine } = await engineOf();
    const road = shaderOf(engine.scene.getObjectByName('curbs') as THREE.Mesh);
    expect(road.vertexShader).toContain('attribute float aShade;');
    expect(road.vertexShader).toContain('vCurbY = (modelMatrix');
    // Подошва дорожного борта - от асфальта проезда, на 15 см ниже тротуара.
    expect(road.fragmentShader).toContain('smoothstep(-0.150, -0.080, vCurbY)');
    expect(road.fragmentShader).toContain('mix(1.0, 0.45, vShade)');
    const garden = shaderOf(engine.scene.getObjectByName('garden-curbs') as THREE.Mesh);
    expect(garden.fragmentShader).not.toContain('smoothstep');
    expect(garden.fragmentShader).toContain('mix(1.0, 0.45, vShade)');
  });

  it('без края плитки у газона садового борта нет, дорожный остаётся', async () => {
    const mask = makeMask();
    mask.edges = { ...mask.edges, garden: [] };
    fakes.mask = mask;
    const { engine } = await engineOf(makeWorld(), null);
    expect(engine.scene.getObjectByName('curbs')).toBeDefined();
    expect(engine.scene.getObjectByName('garden-curbs')).toBeUndefined();
  });
});

describe('закрытие', () => {
  it('снимает слушатели, наблюдатель размеров и освобождает ресурсы', async () => {
    const { engine, canvas, got } = await engineOf();
    const removed = vi.spyOn(canvas, 'removeEventListener');
    const disposed = vi.fn();
    const ground = engine.scene.getObjectByName('walls') as THREE.Mesh;
    ground.geometry.addEventListener('dispose', disposed);
    engine.dispose();
    expect(renderer().disposed).toBe(true);
    expect(renderer().loop).toBeNull();
    expect(RecordingObserver.last?.disconnected).toBe(true);
    expect(fakes.forestDisposed).toBe(1);
    expect(fakes.post.disposed).toBe(1);
    expect(disposed).toHaveBeenCalled();
    expect(removed.mock.calls.map(([type]) => type)).toEqual(
      expect.arrayContaining(['pointermove', 'pointerleave', 'click', 'wheel']),
    );
    // Кадр после закрытия ничего не рисует и не шлёт.
    const renders = renderer().renders;
    const frames = got.frame.length;
    (engine as unknown as { frame(): void }).frame();
    expect(renderer().renders).toBe(renders);
    expect(got.frame.length).toBe(frames);
  });
});

describe('вспомогательные функции', () => {
  it('webglAvailable: без WebGL2 - нет, с контекстом - да, исключение - нет', () => {
    expect(webglAvailable()).toBe(typeof WebGL2RenderingContext !== 'undefined');
    vi.stubGlobal('WebGL2RenderingContext', {});
    const spy = vi.spyOn(HTMLCanvasElement.prototype, 'getContext');
    spy.mockReturnValue({} as RenderingContext);
    expect(webglAvailable()).toBe(true);
    spy.mockReturnValue(null);
    expect(webglAvailable()).toBe(false);
    spy.mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(webglAvailable()).toBe(false);
  });

  it('overviewPose смотрит с юга на середину посадок, без посадок - на начало', () => {
    const pose = overviewPose(makeWorld());
    expect(pose.x).toBe(-20);
    expect(pose.pitch).toBe(-0.5);
    expect(pose.z).toBeGreaterThan(2);
    const empty = overviewPose(makeWorld({ plants: [] }));
    expect(empty).toEqual({ x: 0, y: 33, z: 60, yaw: 0, pitch: -0.5 });
  });

  it('настройки по умолчанию: лето, 11 часов, город выключен', () => {
    expect(DEFAULT_SETTINGS).toMatchObject({ season: 'summer', hour: 11, city: false });
  });
});
