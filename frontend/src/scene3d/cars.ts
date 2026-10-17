/* Машины в 3D: условное наполнение вдоль бортов (места - parking.ts).
 *
 * Модели процедурные, без чужих ассетов: боковой профиль кузова выдавливается на ширину
 * машины, стёкла - отдельным профилем чуть снаружи кузова, колёса и фары - простые тела.
 * Три кузова (седан, хэтчбек, кроссовер), цвет - из обычной для Москвы палитры: больше
 * всего белых, серебристых, чёрных и серых. Каждый кузов - сетка экземпляров. */

import * as THREE from 'three';

import { moduleMaterial } from './facadeModules';
import type { CarSpot } from './parking';

type Xy = readonly [number, number];

interface Body {
  outline: Xy[];
  glass: Xy[];
  length: number;
  wheelX: number;
  lightY: number;
}

/* Профили: x - вперёд, y - вверх, метры. Стекло лежит на 2-3 см снаружи кузова, поэтому
 * видно и сбоку, и через лобовое; крыша над стеклом остаётся цвета кузова. */
const BODIES: Body[] = [
  {
    outline: [
      [-2.3, 0.32],
      [2.3, 0.32],
      [2.33, 0.55],
      [2.25, 0.78],
      [1.0, 0.92],
      [0.25, 1.42],
      [-0.95, 1.44],
      [-1.7, 0.98],
      [-2.28, 0.92],
      [-2.33, 0.6],
    ],
    glass: [
      [1.02, 0.93],
      [0.36, 1.36],
      [-1.085, 1.37],
      [-1.7, 0.99],
    ],
    length: 4.6,
    wheelX: 1.4,
    lightY: 0.66,
  },
  {
    outline: [
      [-2.05, 0.33],
      [2.05, 0.33],
      [2.08, 0.58],
      [1.98, 0.82],
      [0.85, 0.95],
      [0.15, 1.45],
      [-1.6, 1.45],
      [-2.02, 1.05],
      [-2.08, 0.62],
    ],
    glass: [
      [0.86, 0.96],
      [0.255, 1.39],
      [-1.685, 1.39],
      [-2.05, 1.0],
    ],
    length: 4.1,
    wheelX: 1.28,
    lightY: 0.68,
  },
  {
    outline: [
      [-2.35, 0.4],
      [2.35, 0.4],
      [2.38, 0.7],
      [2.3, 0.98],
      [1.25, 1.1],
      [0.55, 1.72],
      [-1.95, 1.74],
      [-2.33, 1.25],
      [-2.38, 0.75],
    ],
    glass: [
      [1.27, 1.11],
      [0.64, 1.66],
      [-2.03, 1.67],
      [-2.36, 1.2],
    ],
    length: 4.7,
    wheelX: 1.45,
    lightY: 0.82,
  },
];

const WIDTH = 1.76;

/** Палитра и доли цветов: sRGB и вес. */
const PAINT: [string, number][] = [
  ['#e9e9e6', 25],
  ['#a8acb0', 20],
  ['#1d1f22', 20],
  ['#6b7075', 14],
  ['#263a5c', 8],
  ['#8b1e1e', 5],
  ['#b8a88b', 5],
  ['#e1b11d', 3],
];
const PAINT_TOTAL = PAINT.reduce((sum, [, w]) => sum + w, 0);

export function paintOf(seed: number): string {
  let pick = (seed >>> 3) % PAINT_TOTAL;
  for (const [color, weight] of PAINT) {
    if (pick < weight) return color;
    pick -= weight;
  }
  return PAINT[0]?.[0] ?? '#ffffff';
}

interface Parts {
  pos: number[];
  nor: number[];
  color: number[];
  accent: number[];
}

function append(
  out: Parts,
  g: THREE.BufferGeometry,
  color: readonly number[],
  accent: number,
): void {
  const flat = g.index ? g.toNonIndexed() : g;
  flat.computeVertexNormals();
  const p = flat.getAttribute('position');
  const n = flat.getAttribute('normal');
  for (let i = 0; i < p.count; i++) {
    out.pos.push(p.getX(i), p.getY(i), p.getZ(i));
    out.nor.push(n.getX(i), n.getY(i), n.getZ(i));
    out.color.push(color[0] ?? 1, color[1] ?? 1, color[2] ?? 1);
    out.accent.push(accent);
  }
}

function extrude(points: readonly Xy[], depth: number): THREE.BufferGeometry {
  const shape = new THREE.Shape(points.map(([x, y]) => new THREE.Vector2(x, y)));
  const g = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false, curveSegments: 1 });
  g.translate(0, 0, -depth / 2);
  return g;
}

/** Сетка кузова: локальная +x - вперёд, центр - в середине машины на земле. */
export function carGeometry(index: number): THREE.BufferGeometry {
  const body = BODIES[index % BODIES.length] ?? BODIES[0];
  if (!body) throw new Error('нет профиля кузова');
  const out: Parts = { pos: [], nor: [], color: [], accent: [] };
  append(out, extrude(body.outline, WIDTH), [1, 1, 1], 1);
  append(out, extrude(body.glass, WIDTH + 0.03), [0.07, 0.08, 0.09], 0);
  const tire: number[] = [0.04, 0.04, 0.045];
  for (const x of [-body.wheelX, body.wheelX]) {
    for (const z of [-0.79, 0.79]) {
      const wheel = new THREE.CylinderGeometry(0.33, 0.33, 0.22, 14);
      wheel.rotateX(Math.PI / 2);
      wheel.translate(x, 0.33, z);
      append(out, wheel, tire, 0);
    }
  }
  const half = body.length / 2;
  for (const z of [-0.62, 0.62]) {
    const head = new THREE.BoxGeometry(0.06, 0.12, 0.34);
    head.translate(half + 0.01, body.lightY, z);
    append(out, head, [0.95, 0.95, 0.9], 0);
    const tail = new THREE.BoxGeometry(0.06, 0.12, 0.3);
    tail.translate(-half - 0.01, body.lightY + 0.06, z);
    append(out, tail, [0.55, 0.04, 0.04], 0);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(out.pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(out.nor, 3));
  g.setAttribute('color', new THREE.Float32BufferAttribute(out.color, 3));
  g.setAttribute('aAccent', new THREE.Float32BufferAttribute(out.accent, 1));
  g.computeBoundingSphere();
  return g;
}

/** Все машины сцены: по сетке экземпляров на кузов. */
export function carGroup(spots: readonly CarSpot[], y = 0): THREE.Group {
  const group = new THREE.Group();
  group.name = 'cars';
  if (!spots.length) return group;
  const material = moduleMaterial({ roughness: 0.38, metalness: 0.35 });
  const color = new THREE.Color();
  const m = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);
  const one = new THREE.Vector3(1, 1, 1);
  BODIES.forEach((_, index) => {
    const mine = spots.filter((s) => s.seed % BODIES.length === index);
    if (!mine.length) return;
    const mesh = new THREE.InstancedMesh(carGeometry(index), material, mine.length);
    mine.forEach((s, i) => {
      q.setFromAxisAngle(up, s.angle + ((s.seed >>> 7) % 2 ? Math.PI : 0));
      mesh.setMatrixAt(i, m.compose(new THREE.Vector3(s.x, y, s.z), q, one));
      mesh.setColorAt(i, color.set(paintOf(s.seed)));
    });
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.name = `cars-${index}`;
    mesh.computeBoundingSphere();
    group.add(mesh);
  });
  return group;
}
