/* Движок 3D-вида без React: рендерер, сцена, камера, цикл кадра, снимок.
 *
 * Страница (pages/ScenePage.tsx) создаёт движок на своём canvas, передаёт настройки пульта
 * и забирает события: ход подготовки, что под прицелом, счётчики кадра. Всё, что зависит
 * от WebGL, живёт здесь; чистая логика - в соседних модулях с тестами. */

import * as THREE from 'three';

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
  nearestCurbDirection,
  ribbonBox,
  streetLightGeometry,
  type SurfaceImage,
} from './ground';
import { pick } from './pick';
import { Atmosphere } from './sky';
import type { Season } from './solar';
import { asphalt, concrete, fenceBars, grass, noiseTexture, pavers } from './textures';
import { Forest } from './trees';
import { GRASS_PRESETS, GrassField } from './grass';
import type { Plant, World } from './types';

export type Quality = 'low' | 'medium' | 'high';

export interface ViewSettings {
  hour: number;
  season: Season;
  age: number;
  clouds: number;
  quality: Quality;
  showExisting: boolean;
}

export const DEFAULT_SETTINGS: ViewSettings = {
  hour: 11,
  season: 'summer',
  age: 10,
  clouds: 0.3,
  quality: 'medium',
  showExisting: true,
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
  camera?: (state: { mode: Mode; speed: number; locked: boolean }) => void;
  frame?: (stats: FrameStats) => void;
  /** Поза камеры, не чаще двух раз в секунду: для адреса страницы. */
  pose?: (pose: Pose, mode: Mode) => void;
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
  private lamps: THREE.InstancedMesh | null = null;
  private grassField: GrassField | null = null;
  private grassQuality: Quality | null = null;
  private mask: MaskInfo | null = null;
  private noise: THREE.Texture | null = null;
  /** Курсор над сценой в координатах NDC, пока мышь не захвачена: подпись - того, что под ним. */
  private pointer: THREE.Vector2 | null = null;
  private readonly raycaster = new THREE.Raycaster();
  private lastPoseAt = 0;
  private lastPose = '';
  private running = false;

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
    const ground = groundMesh(this.world, mask, tex);
    this.add(ground);
    this.addStreetFurniture();
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
    this.renderer.setAnimationLoop(() => {
      this.frame();
    });
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
    if (world.poles.length) {
      const geometry = streetLightGeometry();
      const material = new THREE.MeshStandardMaterial({
        color: 0x5b6166,
        roughness: 0.45,
        metalness: 0.7,
      });
      const lamps = new THREE.InstancedMesh(geometry, material, world.poles.length);
      const m = new THREE.Matrix4();
      world.poles.forEach((p, i) => {
        const angle = nearestCurbDirection(p, world.curbs) ?? 0;
        m.makeRotationY(angle).setPosition(p.x, 0, p.z);
        lamps.setMatrixAt(i, m);
      });
      lamps.castShadow = true;
      lamps.name = 'lamps';
      this.lamps = lamps;
      this.add(lamps);
    }
  }

  private addBuildings(noise: THREE.Texture): void {
    if (!this.world.buildings.length) return;
    const { walls, roofs } = buildingGeometry(this.world.buildings);
    const wallMesh = new THREE.Mesh(walls, facadeMaterial(this.facade));
    const roofMesh = new THREE.Mesh(roofs, roofMaterial(noise));
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
    this.atmosphere.apply({
      hour: s.hour,
      season: s.season,
      clouds: s.clouds,
      shadowSize: q.shadowSize,
      shadowExtent: q.shadowExtent,
    });
    this.facade.uNight.value = this.atmosphere.state.night;
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
    this.freecam.update(dt);
    this.applyPose();
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
    this.renderer.render(this.scene, this.camera);
    this.tickStats();
    this.tickHover();
    this.tickPose();
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

  private emitCamera(): void {
    this.events.camera?.({
      mode: this.freecam.mode,
      speed: this.freecam.flySpeed,
      locked: this.freecam.locked,
    });
  }

  /** Снимок кадра в PNG. scale 2 - вдвое больше пикселей, чем на экране: для слайда. */
  private isRunning(): boolean {
    return this.running;
  }

  async capture(scale = 1): Promise<Blob> {
    if (!this.running) throw new Error('3D-вид закрыт: снимать нечего');
    // Цикл кадра на время снимка стоит: иначе следующий кадр перерисует холст до того, как
    // браузер его прочтёт, а экран мигнёт увеличенным разрешением.
    this.renderer.setAnimationLoop(null);
    const before = this.renderer.getPixelRatio();
    const target = Math.min(before * scale, 4);
    try {
      if (target !== before) this.renderer.setPixelRatio(target);
      this.resize();
      this.applyPose();
      this.forest.update(this.camera, this.clock.getElapsed());
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
        this.renderer.setAnimationLoop(() => {
          this.frame();
        });
      }
    }
  }

  dispose(): void {
    this.running = false;
    this.renderer.setAnimationLoop(null);
    this.resizeObserver?.disconnect();
    this.freecam.dispose();
    this.forest.dispose();
    this.atmosphere.dispose();
    this.lamps?.dispose();
    this.grassField?.dispose();
    for (const d of this.disposables) d.dispose();
    this.renderer.dispose();
  }
}
