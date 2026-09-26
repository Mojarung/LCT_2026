/* Посадки в 3D: процедурные кроны ez-tree (github.com/dgreenheck/ez-tree, MIT; кора - Poly
 * Haven и TextureCan, CC0), по одной модели на архетип и вариант, экземплярами.
 *
 * На улице тысячи кустов и сотни деревьев, у каждой кроны тысячи листьев. Поэтому:
 * - модель генерируется один раз на архетип (archetypes.ts) в двух вариантах ветвления, чтобы
 *   ряд не был клоном, и в двух детализациях: вблизи полная, дальше вдвое-втрое легче;
 * - каждое растение - экземпляр со своим размером (возраст и вид, growth.ts), поворотом и
 *   цветом листвы (вид, сезон, разброс);
 * - на кадр в буферы экземпляров попадает только то, что в поле зрения с запасом на тень, и
 *   каждое растение - ровно в одну детализацию по расстоянию до камеры.
 * Листва покачивается ветром в вершинном шейдере, против солнца просвечивает. */

import { Tree, TreePreset } from '@dgreenheck/ez-tree';
import * as THREE from 'three';

import {
  type Archetype,
  archetypeOf,
  foliageColor,
  leafless,
  type Season,
  SHRUBS,
} from './archetypes';
import { existingSize, isTreeForm, sizeAt, type Size } from './growth';
import { neutralLeaves } from './textures';
import type { Plant } from './types';

type Options = Tree['options'];
type Overrides = { [K in keyof Options]?: Partial<Options[K]> } & { seed?: number };

interface Spec {
  preset: keyof typeof TreePreset;
  overrides?: Overrides;
}

/** Архетип -> пресет ez-tree и поправки. Пресеты автора подобраны под лес, поправки - под
 *  городские посадки: у кроны улицы штамб выше и ветвление плотнее. */
const SPECS: Record<Archetype, Spec> = {
  broadleaf: { preset: 'Oak Medium', overrides: { leaves: { type: 'ash', count: 16, size: 3 } } },
  oak: { preset: 'Oak Large' },
  ash: { preset: 'Ash Medium' },
  birch: { preset: 'Aspen Medium', overrides: { bark: { type: 'birch' }, leaves: { count: 14 } } },
  poplar: { preset: 'Aspen Large' },
  small: { preset: 'Ash Small' },
  weeping: {
    preset: 'Aspen Medium',
    overrides: {
      bark: { type: 'willow' },
      branch: { force: { direction: { x: 0, y: -1, z: 0 }, strength: 0.04 } },
      leaves: { count: 18 },
    },
  },
  spruce: { preset: 'Pine Medium' },
  pine: { preset: 'Pine Large' },
  dwarf_conifer: { preset: 'Pine Small' },
  thuja: { preset: 'Pine Small', overrides: { leaves: { count: 26 } } },
  shrub: { preset: 'Bush 1' },
  shrub_dense: { preset: 'Bush 2' },
  creeper: { preset: 'Bush 3' },
};

/** Сколько вариантов ветвления у архетипа: два - уже не клоны, больше - дольше старт. */
const VARIANTS = 2;

export type Lod = 'hi' | 'lo';

/** Посадка для выбора прицелом: положение и размер в текущем возрасте. */
export interface Body3 {
  plant: Plant;
  x: number;
  z: number;
  height: number;
  radius: number;
}

function deepMerge(target: Record<string, unknown>, source: Record<string, unknown>): void {
  for (const [key, value] of Object.entries(source)) {
    const current = target[key];
    if (value && typeof value === 'object' && current && typeof current === 'object') {
      deepMerge(current as Record<string, unknown>, value as Record<string, unknown>);
    } else {
      target[key] = value;
    }
  }
}

/** Лёгкая детализация: втрое меньше листьев, каждый крупнее, ветви грубее. Издалека силуэт и
 *  плотность кроны те же. */
function lighten(options: Options): void {
  const leaves = options.leaves;
  leaves.count = Math.max(1, Math.round(leaves.count * 0.35));
  leaves.size *= 1.6;
  const branch = options.branch as unknown as Record<string, Record<string, number>>;
  for (const key of Object.keys(branch.sections ?? {})) {
    const sections = branch.sections;
    if (sections) sections[key] = Math.max(2, Math.round((sections[key] ?? 4) * 0.5));
  }
  for (const key of Object.keys(branch.segments ?? {})) {
    const segments = branch.segments;
    if (segments) segments[key] = Math.max(3, Math.round((segments[key] ?? 4) * 0.6));
  }
}

export interface Model {
  branches: THREE.BufferGeometry;
  leaves: THREE.BufferGeometry;
  bark: string;
  leafType: string;
  /** Высота и ширина кроны модели в её единицах: по ним экземпляр масштабируется в метры. */
  height: number;
  width: number;
  barkMaps: {
    map: THREE.Texture | null;
    normalMap: THREE.Texture | null;
    aoMap: THREE.Texture | null;
  };
  leafMap: THREE.Texture | null;
}

/** Нормали листвы от центра кроны: плоский квадрат листа освещается как часть объёма, и крона
 *  выглядит шаром листвы, а не ворохом картонок. */
function roundNormals(geometry: THREE.BufferGeometry): void {
  geometry.computeBoundingBox();
  const box = geometry.boundingBox;
  if (!box) return;
  const center = box.getCenter(new THREE.Vector3());
  const pos = geometry.getAttribute('position');
  const nor = geometry.getAttribute('normal');
  const v = new THREE.Vector3();
  const n = new THREE.Vector3();
  for (let i = 0; i < pos.count; i++) {
    v.set(pos.getX(i), pos.getY(i), pos.getZ(i)).sub(center).normalize();
    n.set(nor.getX(i), nor.getY(i), nor.getZ(i));
    n.multiplyScalar(0.3).addScaledVector(v, 0.7).normalize();
    nor.setXYZ(i, n.x, n.y, n.z);
  }
  nor.needsUpdate = true;
}

export function generateModel(archetype: Archetype, variant: number, lod: Lod): Model {
  const spec = SPECS[archetype];
  const tree = new Tree();
  tree.options.copy(structuredClone(TreePreset[spec.preset]) as unknown as Options);
  if (spec.overrides) deepMerge(tree.options as unknown as Record<string, unknown>, spec.overrides);
  tree.options.seed = (tree.options.seed || 1) + variant * 7717;
  if (lod === 'lo') lighten(tree.options);
  tree.generate();
  const branches = tree.branchesMesh.geometry;
  const leaves = tree.leavesMesh.geometry;
  roundNormals(leaves);
  branches.computeBoundingBox();
  leaves.computeBoundingBox();
  const box = new THREE.Box3();
  if (branches.boundingBox) box.union(branches.boundingBox);
  if (leaves.boundingBox) box.union(leaves.boundingBox);
  const crown = leaves.boundingBox && !leaves.boundingBox.isEmpty() ? leaves.boundingBox : box;
  const width = Math.max(crown.max.x - crown.min.x, crown.max.z - crown.min.z, 1e-3);
  const barkMaterial = tree.branchesMesh.material as THREE.MeshPhongMaterial;
  const leafMaterial = tree.leavesMesh.material as THREE.MeshPhongMaterial;
  const model: Model = {
    branches,
    leaves,
    bark: tree.options.bark.type,
    leafType: tree.options.leaves.type,
    height: Math.max(box.max.y, 1e-3),
    width,
    barkMaps: {
      map: barkMaterial.map,
      normalMap: barkMaterial.normalMap,
      aoMap: barkMaterial.aoMap,
    },
    leafMap: leafMaterial.map,
  };
  // Материалы ez-tree не нужны: у сцены свои, с ветром и просвечиванием. Текстуры общие у
  // всех деревьев библиотеки, их не освобождаем.
  barkMaterial.dispose();
  leafMaterial.dispose();
  return model;
}

export interface WindUniforms {
  uTime: { value: number };
  uWind: { value: number };
  uSunView: { value: THREE.Vector3 };
  uSunColor: { value: THREE.Color };
  /** Снег на верхней стороне крон, 0..1. */
  uSnow: { value: number };
}

/* Ветер в мировых координатах после матрицы экземпляра: качание растёт с высотой, фаза - от
 * места, поэтому соседние деревья качаются вразнобой. Листья ещё и трепещут. */
const WIND_VERTEX = /* glsl */ `
vec4 mvPosition = vec4( transformed, 1.0 );
#ifdef USE_INSTANCING
  mvPosition = instanceMatrix * mvPosition;
#endif
vec4 windWorld = modelMatrix * mvPosition;
float windH = max(windWorld.y, 0.0);
float windPhase = dot(windWorld.xz, vec2(0.11, 0.07));
float gust = 0.65 + 0.35 * sin(uTime * 0.23 + windPhase * 0.3);
vec2 sway = vec2(0.8, 0.6) * (sin(uTime * 1.05 + windPhase) * 0.6 + sin(uTime * 2.1 + windPhase * 1.7) * 0.25);
windWorld.xz += sway * uWind * gust * 0.006 * windH * windH / (1.0 + windH * 0.04);
#ifdef GREEN_LEAF
  float flutter = sin(uTime * 7.0 + windPhase * 13.0 + windWorld.y * 2.3);
  windWorld.xyz += vec3(0.6, 0.4, 0.5) * flutter * uWind * gust * 0.035 * min(windH, 3.0);
#endif
mvPosition = viewMatrix * windWorld;
gl_Position = projectionMatrix * mvPosition;
`;

function windHead(leaf: boolean): string {
  return `#include <common>\n${leaf ? '#define GREEN_LEAF\n' : ''}uniform float uTime;\nuniform float uWind;`;
}

export function barkMaterial(
  maps: Model['barkMaps'],
  wind: WindUniforms,
): THREE.MeshStandardMaterial {
  const m = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    map: maps.map,
    normalMap: maps.normalMap,
    aoMap: maps.aoMap,
    roughness: 0.92,
    metalness: 0,
  });
  m.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, wind);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', windHead(false))
      .replace('#include <project_vertex>', WIND_VERTEX);
    // Снег на ветвях - по их верхней стороне, после карты нормалей коры.
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nuniform float uSnow;')
      .replace(
        '#include <normal_fragment_maps>',
        '#include <normal_fragment_maps>\n' +
          'float snowUp = dot(normal, normalize((viewMatrix * vec4(0.0, 1.0, 0.0, 0.0)).xyz));\n' +
          'diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.93, 0.94, 0.97), uSnow * 0.85 * smoothstep(0.25, 0.75, snowUp));',
      );
  };
  m.customProgramCacheKey = () => 'green-bark';
  return m;
}

export function leafMaterial(
  map: THREE.Texture | null,
  wind: WindUniforms,
): THREE.MeshStandardMaterial {
  const m = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    map,
    alphaTest: 0.5,
    side: THREE.DoubleSide,
    roughness: 0.88,
    metalness: 0,
    envMapIntensity: 0.7,
  });
  m.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, wind);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', windHead(true))
      .replace('#include <project_vertex>', WIND_VERTEX);
    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        '#include <common>\nuniform vec3 uSunView;\nuniform vec3 uSunColor;\nuniform float uSnow;',
      )
      // Двусторонний лист с нормалью от центра кроны: изнанку не переворачиваем, иначе
      // половина кроны темнеет пятнами.
      .replace(
        '#include <normal_fragment_begin>',
        '#include <normal_fragment_begin>\nnormal = normalize(vNormal);\n' +
          'float snowUp = max(dot(normal, normalize((viewMatrix * vec4(0.0, 1.0, 0.0, 0.0)).xyz)), 0.0);\n' +
          'diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.93, 0.94, 0.97), uSnow * 0.75 * smoothstep(0.15, 0.7, snowUp));',
      )
      .replace(
        '#include <emissivemap_fragment>',
        `#include <emissivemap_fragment>
float backLit = pow(max(dot(normalize(-vViewPosition), uSunView), 0.0), 4.0);
totalEmissiveRadiance += diffuseColor.rgb * uSunColor * (0.05 + 0.4 * backLit);`,
      );
  };
  m.customProgramCacheKey = () => 'green-leaf';
  return m;
}

interface Pair {
  branches: THREE.InstancedMesh;
  leaves: THREE.InstancedMesh;
  count: number;
}

interface Group {
  archetype: Archetype;
  variant: number;
  hi: Pair;
  lo: Pair;
  capacity: number;
}

interface Instance {
  plant: Plant;
  group: Group;
  matrix: THREE.Matrix4;
  color: THREE.Color;
  size: Size;
  center: THREE.Vector3;
  radius: number;
  hidden: boolean;
}

export interface ForestSettings {
  age: number;
  season: Season;
  showExisting: boolean;
  lodDistance: number;
  cullDistance: number;
}

/** Растения сцены: генерация моделей, экземпляры, детализация по расстоянию. */
export class Forest {
  readonly root = new THREE.Group();
  readonly wind: WindUniforms = {
    uTime: { value: 0 },
    uWind: { value: 0.35 },
    uSunView: { value: new THREE.Vector3(0, 1, 0) },
    uSunColor: { value: new THREE.Color(1, 1, 1) },
    uSnow: { value: 0 },
  };
  private readonly groups = new Map<string, Group>();
  private readonly instances: Instance[] = [];
  private readonly frustum = new THREE.Frustum();
  private readonly projScreen = new THREE.Matrix4();
  private settings: ForestSettings = {
    age: 10,
    season: 'summer',
    showExisting: true,
    lodDistance: 60,
    cullDistance: 900,
  };
  private readonly barkMaterials = new Map<string, THREE.MeshStandardMaterial>();
  private readonly leafMaterials = new Map<string, THREE.MeshStandardMaterial>();
  private readonly extras: Extras;
  private dirty = true;
  private bodyCache: Body3[] | null = null;
  private readonly lastCamera = new THREE.Matrix4();

  constructor(private readonly plants: readonly Plant[]) {
    this.root.name = 'plants';
    this.extras = new Extras(plants.filter((p) => !p.existing && isTreeForm(p.species.life_form)));
    this.root.add(this.extras.root);
  }

  /** Сколько моделей нужно сгенерировать: по ним интерфейс показывает ход. */
  get jobs(): { archetype: Archetype; variant: number }[] {
    const needed = new Set<string>();
    for (const p of this.plants) needed.add(`${archetypeOf(p)}:${p.seed % VARIANTS}`);
    return [...needed].map((key) => {
      const [archetype, variant] = key.split(':');
      return { archetype: archetype as Archetype, variant: Number(variant) };
    });
  }

  /** Сгенерировать модели и разложить экземпляры. onStep зовётся после каждой модели:
   *  генерация идёт в главном потоке, и между моделями страница успевает перерисоваться. */
  async build(onStep: (done: number, total: number) => void): Promise<void> {
    const jobs = this.jobs;
    const members = new Map<string, Plant[]>();
    for (const p of this.plants) {
      const key = `${archetypeOf(p)}:${p.seed % VARIANTS}`;
      const list = members.get(key);
      if (list) list.push(p);
      else members.set(key, [p]);
    }
    let done = 0;
    for (const job of jobs) {
      const key = `${job.archetype}:${job.variant}`;
      const list = members.get(key) ?? [];
      const hi = generateModel(job.archetype, job.variant, 'hi');
      const lo = generateModel(job.archetype, job.variant, 'lo');
      const group: Group = {
        archetype: job.archetype,
        variant: job.variant,
        hi: await this.pair(hi, list.length),
        lo: await this.pair(lo, list.length),
        capacity: list.length,
      };
      this.groups.set(key, group);
      for (const plant of list) this.instances.push(this.instanceOf(plant, group, hi));
      done += 1;
      onStep(done, jobs.length);
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
    this.refreshAll();
  }

  private async pair(model: Model, capacity: number): Promise<Pair> {
    const bark = this.barkMaterial(model);
    const leaf = await this.leafMaterial(model);
    const branches = new THREE.InstancedMesh(model.branches, bark, Math.max(1, capacity));
    const leaves = new THREE.InstancedMesh(model.leaves, leaf, Math.max(1, capacity));
    // Одна матрица экземпляра на ветви и листву: один буфер, одна выгрузка на GPU.
    leaves.instanceMatrix = branches.instanceMatrix;
    leaves.instanceColor = new THREE.InstancedBufferAttribute(
      new Float32Array(Math.max(1, capacity) * 3),
      3,
    );
    for (const mesh of [branches, leaves]) {
      mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      mesh.count = 0;
      mesh.frustumCulled = false;
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      this.root.add(mesh);
    }
    branches.userData.model = model;
    return { branches, leaves, count: 0 };
  }

  private barkMaterial(model: Model): THREE.MeshStandardMaterial {
    const found = this.barkMaterials.get(model.bark);
    if (found) return found;
    const m = barkMaterial(model.barkMaps, this.wind);
    this.barkMaterials.set(model.bark, m);
    return m;
  }

  private async leafMaterial(model: Model): Promise<THREE.MeshStandardMaterial> {
    const found = this.leafMaterials.get(model.leafType);
    if (found) return found;
    const map = model.leafMap ? await neutralLeaves(model.leafMap) : null;
    const again = this.leafMaterials.get(model.leafType);
    if (again) return again;
    const m = leafMaterial(map, this.wind);
    this.leafMaterials.set(model.leafType, m);
    return m;
  }

  private instanceOf(plant: Plant, group: Group, model: Model): Instance {
    const instance: Instance = {
      plant,
      group,
      matrix: new THREE.Matrix4(),
      color: new THREE.Color(),
      size: { height: 1, crown: 1 },
      center: new THREE.Vector3(),
      radius: 1,
      hidden: false,
    };
    this.place(instance, model);
    return instance;
  }

  sizeOf(plant: Plant): Size {
    if (plant.existing)
      return existingSize(plant.existingRadius ?? 2.5, plant.type === 'existing_shrub', plant.seed);
    return sizeAt(plant.species, this.settings.age);
  }

  private place(instance: Instance, model: Model): void {
    const plant = instance.plant;
    const size = this.sizeOf(plant);
    const archetype = instance.group.archetype;
    const jitter = 0.92 + (((plant.seed >>> 4) % 1000) / 1000) * 0.16;
    const height = size.height * jitter;
    // Стелющийся можжевельник ниже своей ширины втрое: у модели куста пропорция другая.
    const flatten = archetype === 'creeper' ? 0.35 : 1;
    const crown = size.crown * jitter;
    const sx = crown / model.width;
    const sy = (height * flatten) / model.height;
    const angle = ((plant.seed % 3600) / 3600) * Math.PI * 2;
    const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), angle);
    instance.matrix.compose(
      new THREE.Vector3(plant.x, 0, plant.z),
      q,
      new THREE.Vector3(sx, sy, sx),
    );
    instance.size = { height: height * flatten, crown };
    instance.center.set(plant.x, (height * flatten) / 2, plant.z);
    // Запас на тень: дерево за краем кадра отбрасывает её в кадр.
    instance.radius = Math.max(height, crown) * 0.75 + height * 1.2;
    instance.color.copy(this.colorOf(plant));
    instance.hidden = plant.existing && !this.settings.showExisting;
  }

  private colorOf(plant: Plant): THREE.Color {
    const c = foliageColor(plant, this.settings.season);
    return new THREE.Color().setRGB(c.r, c.g, c.b, THREE.SRGBColorSpace);
  }

  apply(settings: Partial<ForestSettings>): void {
    const before = this.settings;
    this.settings = { ...before, ...settings };
    if (
      before.age !== this.settings.age ||
      before.season !== this.settings.season ||
      before.showExisting !== this.settings.showExisting
    ) {
      this.refreshAll();
    }
  }

  private refreshAll(): void {
    for (const instance of this.instances) {
      const model = instance.group.hi.branches.userData.model as Model;
      this.place(instance, model);
    }
    this.extras.update(this.settings.age, (p) => this.sizeOf(p));
    this.dirty = true;
    this.bodyCache = null;
  }

  /** Разложить экземпляры по детализациям для этого кадра. */
  update(camera: THREE.Camera, time: number): void {
    this.wind.uTime.value = time;
    if (!this.dirty && this.lastCamera.equals(camera.matrixWorld)) return;
    this.lastCamera.copy(camera.matrixWorld);
    this.dirty = false;
    this.projScreen.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    this.frustum.setFromProjectionMatrix(this.projScreen);
    const eye = new THREE.Vector3().setFromMatrixPosition(camera.matrixWorld);
    for (const group of this.groups.values()) {
      group.hi.count = 0;
      group.lo.count = 0;
    }
    const sphere = new THREE.Sphere();
    for (const instance of this.instances) {
      if (instance.hidden) continue;
      sphere.set(instance.center, instance.radius);
      if (!this.frustum.intersectsSphere(sphere)) continue;
      const d = eye.distanceTo(instance.center);
      if (d > this.settings.cullDistance) continue;
      // Кусту хватает лёгкой модели раньше, чем дереву: он меньше на экране.
      const near = SHRUBS.has(instance.group.archetype)
        ? this.settings.lodDistance * 0.5
        : this.settings.lodDistance;
      const pair = d < near ? instance.group.hi : instance.group.lo;
      pair.branches.setMatrixAt(pair.count, instance.matrix);
      pair.leaves.setColorAt(pair.count, instance.color);
      pair.count += 1;
    }
    for (const group of this.groups.values()) {
      // Зимой у лиственных листвы нет: рисуются только ветви, и тень от них же.
      const bare = leafless(group.archetype, this.settings.season);
      for (const pair of [group.hi, group.lo]) {
        pair.branches.count = pair.count;
        pair.leaves.count = bare ? 0 : pair.count;
        pair.branches.instanceMatrix.needsUpdate = true;
        if (pair.leaves.instanceColor) pair.leaves.instanceColor.needsUpdate = true;
      }
    }
  }

  /** Посадки для выбора прицелом: положение и размер в текущем возрасте. */
  bodies(): Body3[] {
    if (this.bodyCache) return this.bodyCache;
    this.bodyCache = this.instances
      .filter((i) => !i.hidden)
      .map((i) => ({
        plant: i.plant,
        x: i.plant.x,
        z: i.plant.z,
        height: i.size.height,
        radius: i.size.crown / 2,
      }));
    return this.bodyCache;
  }

  dispose(): void {
    for (const group of this.groups.values()) {
      for (const pair of [group.hi, group.lo]) {
        pair.branches.geometry.dispose();
        pair.leaves.geometry.dispose();
        pair.branches.dispose();
        pair.leaves.dispose();
      }
    }
    for (const m of [...this.barkMaterials.values(), ...this.leafMaterials.values()]) {
      if (m.map && m.map instanceof THREE.CanvasTexture) m.map.dispose();
      m.dispose();
    }
    this.extras.dispose();
  }
}

/** Приствольный круг и опоры молодого дерева: у посадки первых лет - мульча и три кола с
 *  обвязкой, как на улице после озеленения. С возрастом колья снимают, круг зарастает. */
class Extras {
  readonly root = new THREE.Group();
  private readonly mulch: THREE.InstancedMesh;
  private readonly stakes: THREE.InstancedMesh;

  constructor(private readonly trees: readonly Plant[]) {
    const disc = new THREE.CircleGeometry(1, 20);
    disc.rotateX(-Math.PI / 2);
    const mulchMaterial = new THREE.MeshStandardMaterial({
      color: 0x3b2c20,
      roughness: 1,
      polygonOffset: true,
      polygonOffsetFactor: -2,
      polygonOffsetUnits: -2,
    });
    this.mulch = new THREE.InstancedMesh(disc, mulchMaterial, Math.max(1, trees.length));
    this.mulch.receiveShadow = true;
    this.mulch.position.y = 0.012;
    const stake = new THREE.CylinderGeometry(0.035, 0.04, 2.2, 6);
    stake.translate(0, 1.1, 0);
    const stakeMaterial = new THREE.MeshStandardMaterial({ color: 0x9a7a55, roughness: 0.9 });
    this.stakes = new THREE.InstancedMesh(stake, stakeMaterial, Math.max(1, trees.length * 3));
    this.stakes.castShadow = true;
    for (const mesh of [this.mulch, this.stakes]) {
      mesh.frustumCulled = false;
      mesh.count = 0;
      this.root.add(mesh);
    }
  }

  update(age: number, sizeOf: (p: Plant) => Size): void {
    const m = new THREE.Matrix4();
    const one = new THREE.Quaternion();
    let discs = 0;
    let stakes = 0;
    const showMulch = age <= 15;
    const showStakes = age <= 3;
    for (const p of this.trees) {
      const crown = sizeOf(p).crown;
      if (showMulch) {
        const r = Math.min(1.2, Math.max(0.7, crown * 0.3));
        m.compose(new THREE.Vector3(p.x, 0, p.z), one, new THREE.Vector3(r, 1, r));
        this.mulch.setMatrixAt(discs++, m);
      }
      if (showStakes) {
        for (let k = 0; k < 3; k++) {
          const a = (k / 3) * Math.PI * 2 + (p.seed % 628) / 100;
          const lean = new THREE.Quaternion().setFromAxisAngle(
            new THREE.Vector3(Math.cos(a), 0, -Math.sin(a)),
            0.05,
          );
          m.compose(
            new THREE.Vector3(p.x + Math.sin(a) * 0.45, 0, p.z + Math.cos(a) * 0.45),
            lean,
            new THREE.Vector3(1, 1, 1),
          );
          this.stakes.setMatrixAt(stakes++, m);
        }
      }
    }
    this.mulch.count = discs;
    this.stakes.count = stakes;
    this.mulch.instanceMatrix.needsUpdate = true;
    this.stakes.instanceMatrix.needsUpdate = true;
  }

  dispose(): void {
    for (const mesh of [this.mulch, this.stakes]) {
      mesh.geometry.dispose();
      (mesh.material as THREE.Material).dispose();
      mesh.dispose();
    }
  }
}
