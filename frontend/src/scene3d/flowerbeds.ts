/* Цветники в 3D: земля клумбы и россыпь многолетников - кустики листвы и цветки.
 *
 * Источник - цветники плана (plan.json, lawns с kind = flowerbed, слой GREEN_FLOWERBED) и
 * существующие клумбы съёмки (surface.json, areas.flowerbeds: газон-остров среди покрытия с
 * подписью «КЛУМБА»). Пользователь, 19.10.2026: клумба у площадки дома 1А пропала из 3D. Виды
 * многолетников цветник плана знает, но в 3D они условные: цвета смесей проекта Куликовской. */

import * as THREE from 'three';

import { rng } from './textures';
import type { Flat, Ring } from './types';

/** Кустиков листвы и цветков на квадратный метр, предел на сцену. */
const LEAVES_PER_M2 = 9;
const FLOWERS_PER_M2 = 28;
const MAX_LEAVES = 12_000;
const MAX_FLOWERS = 30_000;
/** Земля клумбы над газоном, м: без мерцания с землёй сцены. */
const BED_LIFT_M = 0.012;
const BLOOM: readonly number[] = [0xd64a7f, 0xc8283a, 0xf2c230, 0xf1efe6, 0x8a5cc2, 0xe8822a];

/** Точка внутри многоугольника с дырами (правило чёт-нечет по всем кольцам). */
export function insideRings(rings: readonly Ring[], p: Flat): boolean {
  let inside = false;
  for (const ring of rings) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const a = ring[i] as Flat;
      const b = ring[j] as Flat;
      if (a.z > p.z !== b.z > p.z && p.x < ((b.x - a.x) * (p.z - a.z)) / (b.z - a.z) + a.x) {
        inside = !inside;
      }
    }
  }
  return inside;
}

function ringArea(ring: Ring): number {
  let s = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[i] as Flat;
    const b = ring[j] as Flat;
    s += (b.x - a.x) * (b.z + a.z);
  }
  return Math.abs(s / 2);
}

/** Равномерная россыпь точек внутри контура: perM2 на квадратный метр, не больше cap. */
export function scatterInRings(
  rings: readonly Ring[],
  perM2: number,
  cap: number,
  seed: number,
): Flat[] {
  const outer = rings[0];
  if (!outer || outer.length < 3) return [];
  const area = ringArea(outer) - rings.slice(1).reduce((s, r) => s + ringArea(r), 0);
  const want = Math.min(cap, Math.round(Math.max(0, area) * perM2));
  const xs = outer.map((p) => p.x);
  const zs = outer.map((p) => p.z);
  const [x0, x1, z0, z1] = [Math.min(...xs), Math.max(...xs), Math.min(...zs), Math.max(...zs)];
  const random = rng(seed);
  const out: Flat[] = [];
  for (let tries = 0; out.length < want && tries < want * 20; tries++) {
    const p = { x: x0 + random() * (x1 - x0), z: z0 + random() * (z1 - z0) };
    if (insideRings(rings, p)) out.push(p);
  }
  return out;
}

function bedGeometry(beds: readonly Ring[][]): THREE.BufferGeometry | null {
  const toVec = (ring: Ring) => ring.map((p) => new THREE.Vector2(p.x, -p.z));
  const shapes = beds
    .filter((rings) => (rings[0]?.length ?? 0) >= 3)
    .map((rings) => {
      const shape = new THREE.Shape(toVec(rings[0] ?? []));
      shape.holes = rings.slice(1).map((ring) => new THREE.Path(toVec(ring)));
      return shape;
    });
  if (!shapes.length) return null;
  const geometry = new THREE.ShapeGeometry(shapes);
  geometry.rotateX(-Math.PI / 2);
  geometry.translate(0, BED_LIFT_M, 0);
  return geometry;
}

/** Земля клумб, кустики листвы и цветки одной группой (три вызова отрисовки). */
export function flowerbedGroup(beds: readonly Ring[][], seed = 7): THREE.Group | null {
  const soil = bedGeometry(beds);
  if (!soil) return null;
  const group = new THREE.Group();
  group.name = 'flowerbeds';
  const ground = new THREE.Mesh(
    soil,
    new THREE.MeshStandardMaterial({
      color: 0x3b2a1e,
      roughness: 1,
      metalness: 0,
      polygonOffset: true,
      polygonOffsetFactor: -2,
      polygonOffsetUnits: -2,
    }),
  );
  ground.receiveShadow = true;
  group.add(ground);
  const leaves: Flat[] = [];
  const flowers: Flat[] = [];
  beds.forEach((rings, i) => {
    leaves.push(...scatterInRings(rings, LEAVES_PER_M2, MAX_LEAVES - leaves.length, seed + i));
    flowers.push(
      ...scatterInRings(rings, FLOWERS_PER_M2, MAX_FLOWERS - flowers.length, seed + 97 + i),
    );
  });
  const random = rng(seed + 13);
  const place = (
    points: readonly Flat[],
    geometry: THREE.BufferGeometry,
    color: () => number,
    height: () => number,
    scale: () => number,
  ) => {
    const mesh = new THREE.InstancedMesh(
      geometry,
      new THREE.MeshStandardMaterial({ roughness: 0.8, metalness: 0 }),
      points.length,
    );
    const m = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const up = new THREE.Vector3(0, 1, 0);
    const c = new THREE.Color();
    points.forEach((p, i) => {
      const s = scale();
      q.setFromAxisAngle(up, random() * Math.PI * 2);
      m.compose(new THREE.Vector3(p.x, height(), p.z), q, new THREE.Vector3(s, s * 0.7, s));
      mesh.setMatrixAt(i, m);
      mesh.setColorAt(i, c.setHex(color()));
    });
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    group.add(mesh);
  };
  if (leaves.length) {
    place(
      leaves,
      new THREE.IcosahedronGeometry(0.13, 0),
      () => 0x3f6b2e,
      () => 0.07 + random() * 0.05,
      () => 0.8 + random() * 0.5,
    );
  }
  if (flowers.length) {
    place(
      flowers,
      new THREE.IcosahedronGeometry(0.035, 0),
      () => BLOOM[Math.floor(random() * BLOOM.length)] ?? 0xd64a7f,
      () => 0.16 + random() * 0.18,
      () => 0.8 + random() * 0.6,
    );
  }
  return group;
}
