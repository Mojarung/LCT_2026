/* Люди на тротуарах: случайная расстановка, часть гуляет туда и обратно вдоль тротуара.
 *
 * Места - пиксели маски, где покрытие - плитка тротуара (surfaceMask.ts): люди стоят там,
 * где ходят, а не посреди проезда и не на газоне. Направление прогулки - то из восьми, вдоль
 * которого плитки дальше всего: так человек идёт по тротуару, а не поперёк. Фигура собрана
 * из капсул (ноги, туловище, руки, голова), одежда - своя у каждого. Шаг, взмах рук и
 * разворот на конце пути считает вершинный шейдер от времени: на процессоре люди не стоят
 * ни миллисекунды, и тень идёт вместе с ногами - тот же шейдер у материала глубины. */

import * as THREE from 'three';

import { ASPHALT, PAVERS } from './surfaceMask';
import type { Flat } from './types';

export const PEOPLE_MAX = 450;
/** Доля гуляющих: остальные стоят - ждут, разговаривают, смотрят в телефон. */
const WALKING = 0.55;
const WALK_MS = 1.3;
/** Путь прогулки, метры: не длиннее, чтобы человек не уходил с тротуара. */
const MAX_WALK_M = 14;

export interface MaskGrid {
  kinds: Uint8Array;
  width: number;
  height: number;
  metresPerPx: number;
  rect: [number, number, number, number];
}

export interface Person {
  x: number;
  z: number;
  /** Курс лица, радианы: 0 - на юг (+z), как смотрит модель. */
  heading: number;
  /** Длина прогулки туда и обратно, 0 - стоит. */
  span: number;
  seed: number;
}

function rng(seed: number): () => number {
  let s = seed >>> 0 || 1;
  return () => {
    s = (s * 16807) % 2147483647;
    return s / 2147483647;
  };
}

/** Сколько метров плитки подряд от точки в направлении (dx, dz). */
function runLength(
  grid: MaskGrid,
  px: number,
  py: number,
  dx: number,
  dy: number,
  allowed: ReadonlySet<number>,
): number {
  const step = 0.5 / grid.metresPerPx;
  let run = 0;
  for (let k = 1; k * step * grid.metresPerPx <= MAX_WALK_M; k++) {
    const x = Math.round(px + dx * step * k);
    const y = Math.round(py + dy * step * k);
    if (x < 0 || y < 0 || x >= grid.width || y >= grid.height) break;
    if (!allowed.has(grid.kinds[y * grid.width + x] ?? -1)) break;
    run = k * step * grid.metresPerPx;
  }
  return run;
}

/** Расстановка: count людей по пикселям тротуаров (нет тротуаров - по площадкам). */
export function placePeople(grid: MaskGrid, count: number, seed = 20260926): Person[] {
  const random = rng(seed);
  let allowed: ReadonlySet<number> = new Set([PAVERS]);
  let cells: number[] = [];
  for (const kinds of [[PAVERS], [PAVERS, ASPHALT]]) {
    allowed = new Set(kinds);
    cells = [];
    for (let i = 0; i < grid.kinds.length; i++) if (allowed.has(grid.kinds[i] ?? -1)) cells.push(i);
    // Тротуаров хватает, если клеток плитки не меньше, чем людей: площадки - только без них.
    if (cells.length >= Math.max(50, count)) break;
  }
  if (!cells.length) return [];
  const people: Person[] = [];
  const dirs = Array.from(
    { length: 8 },
    (_, k) => [Math.cos((k * Math.PI) / 4), Math.sin((k * Math.PI) / 4)] as const,
  );
  for (let n = 0; n < count; n++) {
    const cell = cells[Math.floor(random() * cells.length)] ?? 0;
    const px = cell % grid.width;
    const py = Math.floor(cell / grid.width);
    let best = 0;
    let dir: readonly [number, number] = [1, 0];
    for (const d of dirs) {
      const run = runLength(grid, px, py, d[0], d[1], allowed);
      if (run > best) {
        best = run;
        dir = d;
      }
    }
    const walking = random() < WALKING && best > 3;
    const x = grid.rect[0] + (px + 0.5) * grid.metresPerPx;
    const z = grid.rect[1] + (py + 0.5) * grid.metresPerPx;
    // Модель смотрит в +z; курс поворачивает её лицом вдоль направления прогулки.
    const heading = walking ? Math.atan2(dir[0], dir[1]) : random() * Math.PI * 2;
    people.push({ x, z, heading, span: walking ? best : 0, seed: random() });
  }
  return people;
}

type Part = 'body' | 'legL' | 'legR' | 'armL' | 'armR';
const PART: Record<Part, number> = { body: 0, legL: 1, legR: 2, armL: 3, armR: 4 };
/** Чем красить вершину: 0 - своим цветом (кожа, волосы, обувь), 1 - верх одежды, 2 - низ. */
const OWN = 0;
const TOP = 1;
const BOTTOM = 2;

function piece(
  geometry: THREE.BufferGeometry,
  at: [number, number, number],
  part: Part,
  tint: number,
  color: string,
): THREE.BufferGeometry {
  const g = geometry.index ? geometry.toNonIndexed() : geometry;
  g.translate(...at);
  const n = g.getAttribute('position').count;
  const c = new THREE.Color(color).convertSRGBToLinear();
  g.setAttribute(
    'aPart',
    new THREE.Float32BufferAttribute(new Array<number>(n).fill(PART[part]), 1),
  );
  g.setAttribute('aTint', new THREE.Float32BufferAttribute(new Array<number>(n).fill(tint), 1));
  g.setAttribute(
    'aBase',
    new THREE.Float32BufferAttribute(Array.from({ length: n }, () => [c.r, c.g, c.b]).flat(), 3),
  );
  g.deleteAttribute('uv');
  return g;
}

/** Фигура ростом 1,75 м, лицом в +z, ступни на нуле. */
export function personGeometry(): THREE.BufferGeometry {
  const parts = [
    piece(new THREE.CapsuleGeometry(0.075, 0.72, 3, 8), [-0.1, 0.46, 0], 'legL', BOTTOM, '#000'),
    piece(new THREE.CapsuleGeometry(0.075, 0.72, 3, 8), [0.1, 0.46, 0], 'legR', BOTTOM, '#000'),
    piece(new THREE.BoxGeometry(0.12, 0.07, 0.24), [-0.1, 0.035, 0.04], 'legL', OWN, '#2a2622'),
    piece(new THREE.BoxGeometry(0.12, 0.07, 0.24), [0.1, 0.035, 0.04], 'legR', OWN, '#2a2622'),
    piece(new THREE.CapsuleGeometry(0.16, 0.42, 4, 10), [0, 1.2, 0], 'body', TOP, '#000'),
    piece(new THREE.CapsuleGeometry(0.045, 0.56, 3, 8), [-0.215, 1.16, 0], 'armL', TOP, '#000'),
    piece(new THREE.CapsuleGeometry(0.045, 0.56, 3, 8), [0.215, 1.16, 0], 'armR', TOP, '#000'),
    piece(new THREE.SphereGeometry(0.105, 12, 10), [0, 1.62, 0], 'body', OWN, '#e0b08f'),
    piece(
      new THREE.SphereGeometry(0.11, 12, 6, 0, Math.PI * 2, 0, Math.PI * 0.55),
      [0, 1.645, -0.01],
      'body',
      OWN,
      '#3a2a1c',
    ),
  ];
  const merged = new THREE.BufferGeometry();
  for (const name of ['position', 'normal', 'aPart', 'aTint', 'aBase']) {
    const size = parts[0]?.getAttribute(name).itemSize ?? 1;
    const data = parts.flatMap((p) => Array.from(p.getAttribute(name).array));
    merged.setAttribute(name, new THREE.Float32BufferAttribute(data, size));
  }
  merged.computeBoundingSphere();
  return merged;
}

/** Одежда: неяркая городская палитра, изредка яркая куртка. */
const TOPS = [
  '#2f3b4c',
  '#5b2d2d',
  '#3d4a3a',
  '#c9c3b6',
  '#1f1f22',
  '#7a5a3a',
  '#2d5d8a',
  '#b8413a',
  '#d6a93a',
  '#6b6f75',
];
const BOTTOMS = ['#1d2230', '#2b2b2e', '#3b3f4a', '#5a4a3a', '#20262f', '#6f6a60'];

/* Шаг: нога качается вокруг тазобедренного сустава, рука - вокруг плеча в противофазе.
 * Путь туда и обратно: треугольная волна по времени, на обратном пути фигура развёрнута. */
const WALK_VERTEX_HEAD = /* glsl */ `
attribute float aPart;
attribute vec4 aWalk;
uniform float uTime;
vec3 walkPose(vec3 p) {
  float span = aWalk.x;
  float speed = aWalk.y;
  float phase = aWalk.z;
  if (span <= 0.0) {
    // Стоящий чуть переминается: руки качаются едва заметно.
    float idle = sin(uTime * 0.8 + phase * 6.28) * 0.04;
    if (aPart > 2.5) p.z += idle * (p.y - 1.45);
    return p;
  }
  float period = 2.0 * span / speed;
  float t = fract(uTime / period + phase);
  float along = t < 0.5 ? t * 2.0 : 2.0 - t * 2.0;
  float back = step(0.5, t);
  float swing = sin(uTime * speed * 5.2 + phase * 20.0) * 0.45;
  float hip = 0.9;
  float shoulder = 1.45;
  if (aPart > 0.5 && aPart < 2.5) {
    float a = aPart < 1.5 ? swing : -swing;
    float dy = p.y - hip;
    p = vec3(p.x, hip + dy * cos(a), p.z + dy * sin(a));
  } else if (aPart > 2.5) {
    float a = (aPart < 3.5 ? -swing : swing) * 0.8;
    float dy = p.y - shoulder;
    p = vec3(p.x, shoulder + dy * cos(a), p.z + dy * sin(a));
  }
  // Небольшое покачивание корпуса в такт шагу.
  p.y += abs(sin(uTime * speed * 5.2 + phase * 20.0)) * 0.03;
  if (back > 0.5) p.xz = -p.xz;
  p.z += (along - 0.5) * span;
  return p;
}
`;

const BEGIN = '#include <begin_vertex>\ntransformed = walkPose(transformed);';

export class People {
  readonly root = new THREE.Group();
  private readonly mesh: THREE.InstancedMesh;
  private readonly time = { value: 0 };

  constructor(people: readonly Person[]) {
    this.root.name = 'people';
    const geometry = personGeometry();
    const walk = new Float32Array(Math.max(1, people.length) * 4);
    const tops = new Float32Array(Math.max(1, people.length) * 3);
    const bottoms = new Float32Array(Math.max(1, people.length) * 3);
    people.forEach((p, i) => {
      walk.set([p.span, WALK_MS * (0.8 + p.seed * 0.5), p.seed, 0], i * 4);
      const top = new THREE.Color(
        TOPS[Math.floor(p.seed * 997) % TOPS.length],
      ).convertSRGBToLinear();
      const bottom = new THREE.Color(
        BOTTOMS[Math.floor(p.seed * 7919) % BOTTOMS.length],
      ).convertSRGBToLinear();
      tops.set([top.r, top.g, top.b], i * 3);
      bottoms.set([bottom.r, bottom.g, bottom.b], i * 3);
    });
    geometry.setAttribute('aWalk', new THREE.InstancedBufferAttribute(walk, 4));
    geometry.setAttribute('aTop', new THREE.InstancedBufferAttribute(tops, 3));
    geometry.setAttribute('aBottom', new THREE.InstancedBufferAttribute(bottoms, 3));
    const material = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.85 });
    material.onBeforeCompile = (shader) => {
      shader.uniforms.uTime = this.time;
      shader.vertexShader = shader.vertexShader
        .replace(
          '#include <common>',
          `#include <common>\n${WALK_VERTEX_HEAD}\nattribute float aTint;\nattribute vec3 aBase;\nattribute vec3 aTop;\nattribute vec3 aBottom;\nvarying vec3 vCloth;`,
        )
        .replace(
          '#include <begin_vertex>',
          `${BEGIN}\nvCloth = aTint > 1.5 ? aBottom : (aTint > 0.5 ? aTop : aBase);`,
        );
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', '#include <common>\nvarying vec3 vCloth;')
        .replace('#include <map_fragment>', 'diffuseColor.rgb *= vCloth;');
    };
    material.customProgramCacheKey = () => 'green-people';
    const depth = new THREE.MeshDepthMaterial({ depthPacking: THREE.RGBADepthPacking });
    depth.onBeforeCompile = (shader) => {
      shader.uniforms.uTime = this.time;
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', `#include <common>\n${WALK_VERTEX_HEAD}`)
        .replace('#include <begin_vertex>', BEGIN);
    };
    depth.customProgramCacheKey = () => 'green-people-depth';
    this.mesh = new THREE.InstancedMesh(geometry, material, Math.max(1, people.length));
    this.mesh.customDepthMaterial = depth;
    const m = new THREE.Matrix4();
    people.forEach((p, i) => {
      const s = 0.92 + p.seed * 0.16;
      m.makeRotationY(p.heading)
        .scale(new THREE.Vector3(s, s, s))
        .setPosition(p.x, 0, p.z);
      this.mesh.setMatrixAt(i, m);
    });
    this.mesh.count = 0;
    this.mesh.castShadow = true;
    this.mesh.receiveShadow = true;
    this.mesh.frustumCulled = false;
    this.root.add(this.mesh);
    this.total = people.length;
  }

  private readonly total: number;

  /** Сколько людей на улице: доля от расставленных, расстановка не меняется. */
  setDensity(share: number): void {
    this.mesh.count = Math.round(this.total * Math.min(1, Math.max(0, share)));
  }

  update(time: number): void {
    this.time.value = time;
  }

  dispose(): void {
    this.mesh.geometry.dispose();
    (this.mesh.material as THREE.Material).dispose();
    this.mesh.customDepthMaterial?.dispose();
    this.mesh.dispose();
  }
}

/** Точка в координатах сцены для пикселя маски - для тестов и отладки расстановки. */
export function cellPoint(grid: MaskGrid, cell: number): Flat {
  const px = cell % grid.width;
  const py = Math.floor(cell / grid.width);
  return {
    x: grid.rect[0] + (px + 0.5) * grid.metresPerPx,
    z: grid.rect[1] + (py + 0.5) * grid.metresPerPx,
  };
}
