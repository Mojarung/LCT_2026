/* Движок 3D-вида без React: рендерер, сцена, камера, цикл кадра, снимок.
 *
 * Страница (pages/ScenePage.tsx) создаёт движок на своём canvas, передаёт настройки пульта
 * и забирает события: ход подготовки, что под прицелом, счётчики кадра. Всё, что зависит
 * от WebGL, живёт здесь; чистая логика - в соседних модулях с тестами. */

import * as THREE from 'three';

import { type AutoShot, obstaclesOf, plantShots, type ShotTarget, streetShots } from './autoshots';
import { buildingGeometry, facadeMaterial, roofMaterial } from './buildings';
import { Walls } from './collide';
import { Freecam, type Mode, type Pose } from './freecam';
import {
  buildMask,
  type MaskInfo,
  CURB_H,
  CURB_W,
  fenceGeometry,
  groundMesh,
  ribbonBox,
  type SurfaceImage,
} from './ground';
import { pick } from './pick';
import { Atmosphere } from './sky';
import type { Season } from './solar';
import { asphalt, concrete, fenceBars, grass, noiseTexture, pavers } from './textures';
import { People, PEOPLE_MAX, placePeople } from './people';
import { StreetLights } from './streetlights';
import { atmosphereOf, Weather } from './weather';
import { clearance, type Route, tourPose, tourRoute, tourStart } from './tour';
import { Forest } from './trees';
import { GRASS_PRESETS, GrassField } from './grass';
import type { Plant, World } from './types';

export type Quality = 'low' | 'medium' | 'high';

/** Снежный покров зимой без снегопада: белое, но с проталинами у проезжей части. */
const WINTER_COVER = 0.85;

export interface ViewSettings {
  hour: number;
  season: Season;
  age: number;
  clouds: number;
  quality: Quality;
  showExisting: boolean;
  /** Погода, 0..1: сила ветра, дождя, снега и листопада. */
  wind: number;
  rain: number;
  snow: number;
  leaves: number;
  /** Сколько людей на тротуарах: доля от расставленных. */
  people: number;
}

export const DEFAULT_SETTINGS: ViewSettings = {
  hour: 11,
  season: 'summer',
  age: 10,
  clouds: 0.3,
  quality: 'medium',
  showExisting: true,
  wind: 0.3,
  rain: 0,
  snow: 0,
  leaves: 0,
  people: 0.4,
};

interface QualityPreset {
  pixelRatio: number;
  shadowSize: number;
  shadowExtent: number;
  lodDistance: number;
}

const QUALITY: Record<Quality, QualityPreset> = {
  low: { pixelRatio: 1, shadowSize: 2048, shadowExtent: 110, lodDistance: 35 },
  medium: { pixelRatio: 1.5, shadowSize: 4096, shadowExtent: 150, lodDistance: 60 },
  high: { pixelRatio: 2, shadowSize: 4096, shadowExtent: 200, lodDistance: 110 },
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
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.scene.name = 'green-3d';
    this.atmosphere = new Atmosphere(this.renderer, this.scene);
    this.forest = new Forest(world.plants);
    this.scene.add(this.forest.root);
    this.walls = new Walls(world.buildings);
    this.freecam = new Freecam({
      element: canvas,
      pose: overviewPose(world),
      collide: (from, to) => this.walls.resolve(from, to),
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
    await engine.build(surface);
    return engine;
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
    const anisotropy = Math.min(8, this.renderer.capabilities.getMaxAnisotropy());
    const noise = noiseTexture();
    const tex = { grass: grass(), asphalt: asphalt(), pavers: pavers(), noise };
    for (const t of [tex.grass, tex.asphalt, tex.pavers]) t.anisotropy = anisotropy;
    this.facade.uNoise.value = noise;
    this.disposables.push(noise, tex.grass, tex.asphalt, tex.pavers);
    await this.step('ground');
    const mask = buildMask(this.world, surface);
    this.disposables.push(mask.texture);
    this.mask = mask;
    this.noise = noise;
    const ground = groundMesh(this.world, mask, tex, this.groundWeather);
    this.add(ground);
    this.addStreetFurniture();
    this.people = new People(placePeople({ ...mask }, PEOPLE_MAX));
    this.scene.add(this.people.root, this.weather.root);
    await this.step('buildings');
    this.addBuildings(noise);
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

  private addStreetFurniture(): void {
    const world = this.world;
    if (world.curbs.length) {
      const curbTex = concrete();
      curbTex.anisotropy = 4;
      this.disposables.push(curbTex);
      const curbs = new THREE.Mesh(
        ribbonBox(world.curbs, CURB_W, CURB_H),
        new THREE.MeshStandardMaterial({ color: 0xd0cec8, map: curbTex, roughness: 0.85 }),
      );
      curbs.castShadow = true;
      curbs.receiveShadow = true;
      curbs.name = 'curbs';
      this.add(curbs);
    }
    if (world.fences.length) {
      const bars = fenceBars();
      this.disposables.push(bars);
      const fences = new THREE.Mesh(
        fenceGeometry(world.fences, 1.0, 1.0),
        new THREE.MeshStandardMaterial({
          color: 0x24292b,
          map: bars,
          alphaTest: 0.5,
          side: THREE.DoubleSide,
          roughness: 0.55,
          metalness: 0.6,
        }),
      );
      fences.castShadow = true;
      fences.name = 'fences';
      this.add(fences);
    }
    this.lights = new StreetLights(world.poles, world.curbs);
    this.scene.add(this.lights.root);
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
  }

  apply(settings: Partial<ViewSettings>): void {
    this.settings = { ...this.settings, ...settings };
    const s = this.settings;
    const q = QUALITY[s.quality];
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, q.pixelRatio));
    this.resize();
    const weather = atmosphereOf(s, s.clouds);
    this.atmosphere.apply({
      hour: s.hour,
      season: s.season,
      clouds: weather.clouds,
      shadowSize: q.shadowSize,
      shadowExtent: q.shadowExtent,
      fog: weather.fog,
      wind: s.wind,
    });
    this.weather.apply(s, weather);
    this.groundWeather.uWet.value = weather.wet;
    // Зимой снег лежит и без снегопада: московский январь белый.
    const cover = Math.max(weather.snowCover, s.season === 'winter' ? WINTER_COVER : 0);
    this.groundWeather.uSnow.value = cover;
    this.forest.wind.uWind.value = weather.sway;
    this.forest.wind.uSnow.value = cover;
    this.people?.setDensity(s.people);
    this.facade.uNight.value = this.atmosphere.state.night;
    this.lights?.setNight(this.atmosphere.state.night);
    this.forest.apply({
      age: s.age,
      season: s.season,
      showExisting: s.showExisting,
      lodDistance: q.lodDistance,
    });
    this.forest.wind.uSunColor.value
      .copy(this.atmosphere.state.color)
      .multiplyScalar(this.atmosphere.state.intensity * 0.35);
    this.setGrass(s.quality);
    if (this.grassField) {
      this.grassField.uniforms.uWind.value = s.wind;
      // Под снегом травинок не видно: газон белый, поле травы уходит вместе с ним.
      this.grassField.uniforms.uGrow.value = Math.max(0, 1 - cover * 1.4);
    }
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

  private resize(): void {
    const parent = this.canvas.parentElement;
    const w = parent?.clientWidth ?? this.canvas.clientWidth;
    const h = parent?.clientHeight ?? this.canvas.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  private applyPose(): void {
    const p = this.freecam.pose;
    this.camera.position.set(p.x, p.y, p.z);
    this.camera.rotation.set(p.pitch, p.yaw, 0, 'YXZ');
    this.camera.updateMatrixWorld();
  }

  private frame(): void {
    if (!this.running) return;
    this.clock.update();
    const dt = this.clock.getDelta();
    const t = this.clock.getElapsed();
    if (this.tour) this.stepTour(dt);
    else this.freecam.update(dt);
    this.applyPose();
    this.prepare(t);
    this.renderer.render(this.scene, this.camera);
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

  /** Ракурсы для галереи: улица отрезками или посадка по кругу. Солнце ночью не учитывается. */
  planShots(target: ShotTarget): AutoShot[] {
    const state = this.atmosphere.state;
    const sun = state.night > 0.5 ? null : { x: state.direction.x, z: state.direction.z };
    const obstacles = obstaclesOf(this.world);
    const bodies = this.forest.bodies();
    return target.kind === 'street'
      ? streetShots(bodies, obstacles, sun)
      : plantShots(bodies, target.id, obstacles, sun);
  }

  /** Кадры заданных поз в PNG заданного размера, без панелей и без сдвига камеры человека.
   *  Кроны в кадре - в полной детализации до края: на снимке нет спешки кадра в секунду. */
  async renderViews(poses: readonly Pose[], width: number, height: number): Promise<Blob[]> {
    if (!this.running) throw new Error('3D-вид закрыт: снимать нечего');
    this.freecam.releaseKeys();
    this.renderer.setAnimationLoop(null);
    const ratio = this.renderer.getPixelRatio();
    const lod = QUALITY[this.settings.quality].lodDistance;
    const out: Blob[] = [];
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
        this.camera.updateMatrixWorld();
        this.prepare(t);
        this.renderer.render(this.scene, this.camera);
        const blob = await new Promise<Blob | null>((resolve) => {
          this.canvas.toBlob(resolve, 'image/png');
        });
        if (!blob) throw new Error('Браузер не отдал кадр: снимок не получился');
        out.push(blob);
        if (!this.isRunning()) break;
      }
      return out;
    } finally {
      if (this.isRunning()) {
        this.forest.apply({ lodDistance: lod });
        this.renderer.setPixelRatio(ratio);
        this.resize();
        this.startLoop();
      }
    }
  }

  /** Снимок кадра в PNG. scale 2 - вдвое больше пикселей, чем на экране: для слайда. */
  private isRunning(): boolean {
    return this.running;
  }

  async capture(scale = 1): Promise<Blob> {
    if (!this.running) throw new Error('3D-вид закрыт: снимать нечего');
    // Скачивание снимка уводит фокус, и keyup зажатой клавиши может потеряться.
    this.freecam.releaseKeys();
    // Цикл кадра на время снимка стоит: иначе следующий кадр перерисует холст до того, как
    // браузер его прочтёт, а экран мигнёт увеличенным разрешением.
    this.renderer.setAnimationLoop(null);
    const before = this.renderer.getPixelRatio();
    const target = Math.min(before * scale, 4);
    try {
      if (target !== before) this.renderer.setPixelRatio(target);
      this.resize();
      this.applyPose();
      this.prepare(this.clock.getElapsed());
      this.renderer.render(this.scene, this.camera);
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
      this.renderer.render(this.scene, this.camera);
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
    this.renderer.dispose();
  }
}
