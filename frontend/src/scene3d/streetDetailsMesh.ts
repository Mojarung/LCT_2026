/* Геометрия мелочей улицы (streetDetails.ts): приствольная решётка, круг мульчи, люк,
 * скамейка, урна. Всё экземплярами - сотни штук одним вызовом отрисовки на вид. */

import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

import type { Spot } from './streetDetails';
import type { Flat } from './types';

/** Чугун решётки и люка: щели и рёбра рисуются в текстуре, а не геометрией. */
function ironTexture(kind: 'grate' | 'manhole'): THREE.CanvasTexture {
  const size = 256;
  const c = document.createElement('canvas');
  c.width = size;
  c.height = size;
  const ctx = c.getContext('2d');
  if (ctx) {
    const mid = size / 2;
    ctx.fillStyle = '#2b2c2d';
    ctx.fillRect(0, 0, size, size);
    if (kind === 'grate') {
      // Решётка «лучи»: щели от центра, в центре - грунт под ствол.
      ctx.strokeStyle = '#121313';
      ctx.lineWidth = 7;
      for (let k = 0; k < 32; k++) {
        const a = (k / 32) * Math.PI * 2;
        ctx.beginPath();
        ctx.moveTo(mid + Math.cos(a) * 52, mid + Math.sin(a) * 52);
        ctx.lineTo(mid + Math.cos(a) * 118, mid + Math.sin(a) * 118);
        ctx.stroke();
      }
      ctx.strokeStyle = '#3a3b3c';
      ctx.lineWidth = 6;
      ctx.strokeRect(3, 3, size - 6, size - 6);
      ctx.fillStyle = '#3d2f23';
      ctx.beginPath();
      ctx.arc(mid, mid, 46, 0, Math.PI * 2);
      ctx.fill();
    } else {
      // Люк: кольцо, сетка рифления и надпись-пояс как на московских крышках.
      ctx.fillStyle = '#323334';
      ctx.beginPath();
      ctx.arc(mid, mid, 124, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#1b1c1c';
      ctx.lineWidth = 3;
      for (let v = 30; v < size - 30; v += 16) {
        ctx.beginPath();
        ctx.moveTo(v, 20);
        ctx.lineTo(v, size - 20);
        ctx.moveTo(20, v);
        ctx.lineTo(size - 20, v);
        ctx.stroke();
      }
      ctx.lineWidth = 10;
      ctx.strokeStyle = '#3e3f40';
      ctx.beginPath();
      ctx.arc(mid, mid, 118, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(mid, mid, 70, 0, Math.PI * 2);
      ctx.stroke();
    }
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

function placed(
  geometry: THREE.BufferGeometry,
  material: THREE.Material,
  spots: readonly Spot[],
  y: (s: Spot) => number,
  name: string,
): THREE.InstancedMesh {
  const mesh = new THREE.InstancedMesh(geometry, material, Math.max(1, spots.length));
  const m = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);
  const one = new THREE.Vector3(1, 1, 1);
  spots.forEach((s, i) => {
    q.setFromAxisAngle(up, s.angle);
    mesh.setMatrixAt(i, m.compose(new THREE.Vector3(s.x, y(s), s.z), q, one));
  });
  mesh.count = spots.length;
  mesh.name = name;
  mesh.receiveShadow = true;
  return mesh;
}

/** Парковая скамейка: чугунные боковины, рейки сиденья и спинки. Сиденьем в +z. Без
 *  спинки - лавка из пяти реек на двух опорах (benchBack: спинка только у ограды). */
function benchGeometry(back = true): { wood: THREE.BufferGeometry; metal: THREE.BufferGeometry } {
  const slats: THREE.BufferGeometry[] = [];
  const legs: THREE.BufferGeometry[] = [];
  if (back) {
    for (let k = 0; k < 3; k++) {
      const g = new THREE.BoxGeometry(1.8, 0.035, 0.11);
      g.translate(0, 0.45, -0.16 + k * 0.14);
      slats.push(g);
    }
    for (let k = 0; k < 2; k++) {
      const g = new THREE.BoxGeometry(1.8, 0.1, 0.03);
      g.rotateX(-0.25);
      g.translate(0, 0.62 + k * 0.15, -0.27 - k * 0.04);
      slats.push(g);
    }
    for (const x of [-0.75, 0.75]) {
      const side = new THREE.BoxGeometry(0.06, 0.45, 0.5);
      side.translate(x, 0.225, -0.02);
      const rest = new THREE.BoxGeometry(0.06, 0.45, 0.06);
      rest.rotateX(-0.25);
      rest.translate(x, 0.66, -0.29);
      legs.push(side, rest);
    }
  } else {
    for (let k = 0; k < 5; k++) {
      const g = new THREE.BoxGeometry(1.8, 0.035, 0.085);
      g.translate(0, 0.45, -0.2 + k * 0.1);
      slats.push(g);
    }
    for (const x of [-0.7, 0.7]) {
      const side = new THREE.BoxGeometry(0.07, 0.43, 0.42);
      side.translate(x, 0.215, 0);
      legs.push(side);
    }
  }
  const wood = mergeGeometries(slats);
  const metal = mergeGeometries(legs);
  for (const g of [...slats, ...legs]) g.dispose();
  return { wood, metal };
}

export interface StreetDetailInput {
  grates: Flat[];
  mulch: Flat[];
  manholes: Spot[];
  benches: Spot[];
  bins: Spot[];
  /** Скамейки нарисованы в съёмке: они не условные (переключатель «добавленные объекты»). */
  benchesDrawn?: boolean;
  /** Люки - по колодцам съёмки, а не условные по шагу трассы. */
  manholesDrawn?: boolean;
  /** Высота земли в точке: проезд ниже тротуара на высоту борта. */
  levelAt: (x: number, z: number) => number;
}

export function streetDetails(input: StreetDetailInput): THREE.Group {
  const group = new THREE.Group();
  group.name = 'street-details';
  const lift = (s: Spot) => input.levelAt(s.x, s.z);
  const flat = (points: readonly Flat[]): Spot[] => points.map((p) => ({ ...p, angle: 0 }));
  const decal = (map: THREE.Texture | null, color: number) =>
    new THREE.MeshStandardMaterial({
      color,
      map,
      roughness: 0.75,
      metalness: map ? 0.35 : 0,
      polygonOffset: true,
      polygonOffsetFactor: -2,
      polygonOffsetUnits: -2,
    });
  if (input.grates.length) {
    const g = new THREE.BoxGeometry(1.5, 0.02, 1.5);
    group.add(
      placed(
        g,
        decal(ironTexture('grate'), 0xffffff),
        flat(input.grates),
        (s) => lift(s) + 0.01,
        'tree-grates',
      ),
    );
  }
  if (input.mulch.length) {
    const g = new THREE.CircleGeometry(0.75, 24);
    g.rotateX(-Math.PI / 2);
    group.add(
      placed(g, decal(null, 0x4a3628), flat(input.mulch), (s) => lift(s) + 0.012, 'tree-mulch'),
    );
  }
  if (input.manholes.length) {
    const g = new THREE.CylinderGeometry(0.34, 0.34, 0.02, 28);
    group.add(
      placed(
        g,
        decal(ironTexture('manhole'), 0xffffff),
        input.manholes,
        (s) => lift(s) + 0.008,
        'manholes',
      ),
    );
  }
  for (const back of [true, false]) {
    const benches = input.benches.filter((b) => (b.back ?? true) === back);
    if (!benches.length) continue;
    const { wood, metal } = benchGeometry(back);
    const woodMesh = placed(
      wood,
      new THREE.MeshStandardMaterial({ color: 0x8a5a36, roughness: 0.8 }),
      benches,
      lift,
      back ? 'benches' : 'benches-flat',
    );
    const metalMesh = placed(
      metal,
      new THREE.MeshStandardMaterial({ color: 0x1f2222, roughness: 0.5, metalness: 0.6 }),
      benches,
      lift,
      back ? 'bench-legs' : 'bench-flat-legs',
    );
    woodMesh.castShadow = true;
    metalMesh.castShadow = true;
    woodMesh.userData.extra = !input.benchesDrawn;
    metalMesh.userData.extra = !input.benchesDrawn;
    group.add(woodMesh, metalMesh);
  }
  if (input.bins.length) {
    const g = new THREE.CylinderGeometry(0.22, 0.2, 0.72, 16);
    g.translate(0, 0.36, 0);
    const bins = placed(
      g,
      new THREE.MeshStandardMaterial({ color: 0x2c3a33, roughness: 0.55, metalness: 0.5 }),
      input.bins,
      lift,
      'bins',
    );
    bins.castShadow = true;
    group.add(bins);
  }
  // Решётки, мульча, люки и урны в чертеже не нарисованы: они условные, их можно скрыть.
  for (const child of group.children) {
    if (
      ['tree-grates', 'tree-mulch', 'bins'].includes(child.name) ||
      (child.name === 'manholes' && !input.manholesDrawn)
    ) {
      child.userData.extra = true;
    }
  }
  return group;
}
