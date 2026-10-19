/* Навесы: контур пунктиром на слое зданий, отдельно от стен. Топоплан рисует пунктиром то, что
 * над землёй (Мосгеотрест - слой «Навесы», паспорт ОГХ - тип линии с разрывами у слоя «Навес»),
 * поэтому покрытие площадки идёт под навес, а в 3D это кровля на стойках. Пунктир, касающийся
 * стены, - козырёк, балкон или эркер дома на неизвестной высоте: его здесь нет.
 *
 * Высоты и стоек в съёмке нет: лист на 2,6 м и стойки по углам и через 4 м - типовой навес
 * детской площадки и остановки, условно. */

import * as THREE from 'three';

import type { Flat, Ring } from './types';

export const CANOPY_HEIGHT_M = 2.6;
const ROOF_M = 0.08;
const POST_R = 0.05;
const POST_STEP_M = 4;
/** Стойка стоит чуть внутри контура: кровля выступает над ней. */
const POST_INSET_M = 0.15;
const CORNER_TURN = Math.PI / 6;
/** Меньше - знак, больше - уже не навес, а здание без подписи; стена ближе - выступ дома. */
export const CANOPY_MIN_M2 = 2;
export const CANOPY_MAX_M2 = 400;
export const CANOPY_WALL_GAP_M = 0.5;

export function ringArea(ring: readonly Flat[]): number {
  let s = 0;
  for (let i = 0; i < ring.length; i += 1) {
    const a = ring[i] as Flat;
    const b = ring[(i + 1) % ring.length] as Flat;
    s += a.x * b.z - b.x * a.z;
  }
  return s / 2;
}

function segmentDistance(p: Flat, a: Flat, b: Flat): number {
  const dx = b.x - a.x;
  const dz = b.z - a.z;
  const len = dx * dx + dz * dz;
  const t = len ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.z - a.z) * dz) / len)) : 0;
  return Math.hypot(p.x - a.x - t * dx, p.z - a.z - t * dz);
}

function inside(p: Flat, ring: readonly Flat[]): boolean {
  let hit = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const a = ring[i] as Flat;
    const b = ring[j] as Flat;
    if (a.z > p.z !== b.z > p.z && p.x < ((b.x - a.x) * (p.z - a.z)) / (b.z - a.z) + a.x)
      hit = !hit;
  }
  return hit;
}

/** Контур касается стены или лежит в доме: это часть дома над землёй, а не отдельный навес. */
function touchesWall(ring: readonly Flat[], walls: readonly (readonly Flat[])[]): boolean {
  return walls.some(
    (wall) =>
      ring.some((p) => inside(p, wall)) ||
      ring.some((p) =>
        wall.some(
          (a, i) => segmentDistance(p, a, wall[(i + 1) % wall.length] as Flat) < CANOPY_WALL_GAP_M,
        ),
      ),
  );
}

/** Навесы среди замкнутых пунктирных контуров зданий: по площади и в стороне от стен. */
export function freeCanopies(rings: readonly Ring[], walls: readonly (readonly Flat[])[]): Ring[] {
  return rings.filter((ring) => {
    const area = Math.abs(ringArea(ring));
    return (
      ring.length >= 3 &&
      area >= CANOPY_MIN_M2 &&
      area <= CANOPY_MAX_M2 &&
      !touchesWall(ring, walls)
    );
  });
}

/** Стойки: на изломах контура и через POST_STEP_M по длинной стороне, чуть внутри. */
export function canopyPosts(ring: readonly Flat[]): Flat[] {
  const n = ring.length;
  const cx = ring.reduce((s, p) => s + p.x, 0) / n;
  const cz = ring.reduce((s, p) => s + p.z, 0) / n;
  const toward = (p: Flat): Flat => {
    const d = Math.hypot(cx - p.x, cz - p.z) || 1;
    const k = Math.min(POST_INSET_M, d / 2) / d;
    return { x: p.x + (cx - p.x) * k, z: p.z + (cz - p.z) * k };
  };
  const corners: number[] = [];
  for (let i = 0; i < n; i += 1) {
    const a = ring[(i + n - 1) % n] as Flat;
    const b = ring[i] as Flat;
    const c = ring[(i + 1) % n] as Flat;
    const turn = Math.abs(
      Math.atan2(
        (b.x - a.x) * (c.z - b.z) - (b.z - a.z) * (c.x - b.x),
        (b.x - a.x) * (c.x - b.x) + (b.z - a.z) * (c.z - b.z),
      ),
    );
    if (turn >= CORNER_TURN) corners.push(i);
  }
  if (corners.length < 3) return [];
  const posts: Flat[] = [];
  corners.forEach((start, k) => {
    const end = corners[(k + 1) % corners.length] as number;
    const a = ring[start] as Flat;
    const b = ring[end] as Flat;
    posts.push(toward(a));
    const parts = Math.ceil(Math.hypot(b.x - a.x, b.z - a.z) / POST_STEP_M);
    for (let s = 1; s < parts; s += 1) {
      const t = s / parts;
      posts.push(toward({ x: a.x + (b.x - a.x) * t, z: a.z + (b.z - a.z) * t }));
    }
  });
  return posts;
}

/** Площадь под навесом точками через метр: оборудование площадки обходит её, как ствол. */
export function canopyCover(ring: readonly Flat[]): { x: number; z: number; r: number }[] {
  const xs = ring.map((p) => p.x);
  const zs = ring.map((p) => p.z);
  const out: { x: number; z: number; r: number }[] = [];
  for (let x = Math.min(...xs); x <= Math.max(...xs); x += 1) {
    for (let z = Math.min(...zs); z <= Math.max(...zs); z += 1) {
      if (inside({ x, z }, ring)) out.push({ x, z, r: 0.8 });
    }
  }
  return out;
}

/** Кровли и стойки всех навесов: две сетки на улицу. */
export function canopyGroup(rings: readonly Ring[]): THREE.Group {
  const group = new THREE.Group();
  group.name = 'canopies';
  if (!rings.length) return group;
  const roofs: THREE.BufferGeometry[] = [];
  const posts: Flat[] = [];
  for (const ring of rings) {
    const shape = new THREE.Shape(ring.map((p) => new THREE.Vector2(p.x, -p.z)));
    const roof = new THREE.ExtrudeGeometry(shape, { depth: ROOF_M, bevelEnabled: false });
    // Плоскость фигуры (x, y) ложится на землю (x, -z), глубина выдавливания уходит вверх.
    roof.rotateX(-Math.PI / 2);
    roof.translate(0, CANOPY_HEIGHT_M, 0);
    roofs.push(roof);
    posts.push(...canopyPosts(ring));
  }
  const roofMaterial = new THREE.MeshStandardMaterial({
    color: 0x55655c,
    roughness: 0.55,
    metalness: 0.35,
    side: THREE.DoubleSide,
  });
  for (const geometry of roofs) {
    const mesh = new THREE.Mesh(geometry, roofMaterial);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    group.add(mesh);
  }
  if (posts.length) {
    const post = new THREE.CylinderGeometry(POST_R, POST_R, CANOPY_HEIGHT_M, 8);
    post.translate(0, CANOPY_HEIGHT_M / 2, 0);
    const mesh = new THREE.InstancedMesh(
      post,
      new THREE.MeshStandardMaterial({ color: 0x3b4044, roughness: 0.5, metalness: 0.5 }),
      posts.length,
    );
    const m = new THREE.Matrix4();
    posts.forEach((p, i) => mesh.setMatrixAt(i, m.makeTranslation(p.x, 0, p.z)));
    mesh.castShadow = true;
    group.add(mesh);
  }
  return group;
}
