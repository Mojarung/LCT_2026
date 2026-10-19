/* Приствольные лунки существующих деревьев на покрытии (у посадок плана - решётки и мульча,
 * streetDetails.ts). На резине площадки и на плитке ствол стоит не в сплошном покрытии, а в
 * квадрате земли с бетонным бортиком (пользователь, 19.10.2026, фото двора: «деревья вот так
 * вот выделены»). Квадрат 1,6 м, стороны - вдоль ближайшего края части покрытия, как бортики
 * на фото идут вдоль краёв площадки. У края части лунка меньше, чтобы не вылезти на газон; ствол
 * ближе LAWN_EDGE_M к краю - стоит у газона, лунки нет. На проезде лунок не бывает. Осенью
 * земля в лунке под листьями (litter.ts). */

import * as THREE from 'three';

import { mainAxis } from './facades';
import { distanceToArea } from './playgrounds';
import type { Flat } from './types';

type Ring = readonly Flat[];

export interface PavedPart {
  rings: Ring[];
  kind: string;
}

export interface Pit {
  x: number;
  z: number;
  /** Поворот вокруг вертикали, как у предметов площадки. */
  angle: number;
  /** Сторона квадрата по внешнему краю бортика, м. */
  size: number;
  /** Высота покрытия части, на которой лунка, м. */
  lift: number;
}

export const PIT_SIZE_M = 1.6;
const PIT_MIN_M = 0.9;
const LAWN_EDGE_M = 0.5;
const BORDER_W_M = 0.08;
const STRAIGHT_M = 1.0;
const BORDER_H_M = 0.06;

/** Лунки стволов, стоящих внутри частей покрытия (кроме проезда). lifts - высота покрытия
 *  по виду части. */
export function pitsOnPaving(
  trees: readonly Flat[],
  parts: readonly PavedPart[],
  lifts: Readonly<Record<string, number>> = {},
): Pit[] {
  const usable = parts
    .filter((p) => p.kind !== 'road' && (p.rings[0]?.length ?? 0) >= 3)
    .map((p) => {
      const outer = p.rings[0] ?? [];
      const xs = outer.map((q) => q.x);
      const zs = outer.map((q) => q.z);
      const axis = mainAxis([...outer]);
      return {
        ...p,
        box: [Math.min(...xs), Math.max(...xs), Math.min(...zs), Math.max(...zs)] as const,
        angle: Math.atan2(-axis.dz, axis.dx),
      };
    });
  const pits: Pit[] = [];
  for (const tree of trees) {
    const part = usable.find(
      (p) =>
        tree.x >= p.box[0] &&
        tree.x <= p.box[1] &&
        tree.z >= p.box[2] &&
        tree.z <= p.box[3] &&
        distanceToArea(p.rings, tree) === 0,
    );
    if (!part) continue;
    const { edge, angle } = nearestEdge(part.rings, tree, part.angle);
    if (edge < LAWN_EDGE_M) continue;
    // Квадрат вписан в круг радиуса edge: по диагонали не вылезет за край части.
    const size = Math.min(PIT_SIZE_M, edge * Math.SQRT2 * 0.95);
    if (size < PIT_MIN_M) continue;
    pits.push({ x: tree.x, z: tree.z, angle, size, lift: lifts[part.kind] ?? 0 });
  }
  return pits;
}

/** Расстояние до края части и поворот лунки по ближайшей прямой стороне (не короче
 *  STRAIGHT_M: дуга скруглённого угла направления не задаёт); без такой - по оси части. */
function nearestEdge(
  rings: readonly Ring[],
  p: Flat,
  fallback: number,
): { edge: number; angle: number } {
  let edge = Infinity;
  let straight = Infinity;
  let angle = fallback;
  for (const ring of rings) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const a = ring[j] as Flat;
      const b = ring[i] as Flat;
      const vx = b.x - a.x;
      const vz = b.z - a.z;
      const len2 = vx * vx + vz * vz;
      const t =
        len2 > 0 ? Math.max(0, Math.min(1, ((p.x - a.x) * vx + (p.z - a.z) * vz) / len2)) : 0;
      const d = Math.hypot(p.x - (a.x + vx * t), p.z - (a.z + vz * t));
      edge = Math.min(edge, d);
      if (len2 >= STRAIGHT_M * STRAIGHT_M && d < straight) {
        straight = d;
        angle = Math.atan2(-vz, vx);
      }
    }
  }
  return { edge, angle };
}

/** Сетки лунок: земля и бортик, экземплярами. soil - материал земли (цвет меняет сезон). */
export function pitGroup(
  pits: readonly Pit[],
): { group: THREE.Group; soil: THREE.MeshStandardMaterial } | null {
  if (!pits.length) return null;
  const group = new THREE.Group();
  group.name = 'tree-pits';
  // Земля чуть выше покрытия и с большим сдвигом глубины, чем плитка и резина (у них -1 и -2):
  // под косым взглядом она не тонет в покрытии.
  const soil = new THREE.MeshStandardMaterial({
    color: 0x3e3128,
    roughness: 1,
    polygonOffset: true,
    polygonOffsetFactor: -4,
    polygonOffsetUnits: -4,
  });
  const concrete = new THREE.MeshStandardMaterial({ color: 0x9c9c97, roughness: 0.85 });
  const ground = new THREE.PlaneGeometry(1, 1);
  ground.rotateX(-Math.PI / 2);
  // Бортик - рамка из четырёх брусков вокруг единичного квадрата; размер - масштабом по x и z,
  // а высота бруска - нет, поэтому рамка строится на каждый размер свой (их немного).
  const soilMesh = new THREE.InstancedMesh(ground, soil, pits.length);
  soilMesh.name = 'tree-pit-soil';
  soilMesh.receiveShadow = true;
  const matrix = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);
  pits.forEach((pit, k) => {
    q.setFromAxisAngle(up, pit.angle);
    const inner = pit.size - 2 * BORDER_W_M;
    soilMesh.setMatrixAt(
      k,
      matrix.compose(
        new THREE.Vector3(pit.x, pit.lift + 0.008, pit.z),
        q,
        new THREE.Vector3(inner, 1, inner),
      ),
    );
  });
  group.add(soilMesh);
  const bySize = new Map<number, Pit[]>();
  for (const pit of pits) {
    const key = Math.round(pit.size * 20) / 20;
    bySize.set(key, [...(bySize.get(key) ?? []), pit]);
  }
  for (const [size, same] of bySize) {
    const half = size / 2 - BORDER_W_M / 2;
    const bars = [
      new THREE.BoxGeometry(size, BORDER_H_M, BORDER_W_M).translate(0, BORDER_H_M / 2, -half),
      new THREE.BoxGeometry(size, BORDER_H_M, BORDER_W_M).translate(0, BORDER_H_M / 2, half),
      new THREE.BoxGeometry(BORDER_W_M, BORDER_H_M, size - 2 * BORDER_W_M).translate(
        -half,
        BORDER_H_M / 2,
        0,
      ),
      new THREE.BoxGeometry(BORDER_W_M, BORDER_H_M, size - 2 * BORDER_W_M).translate(
        half,
        BORDER_H_M / 2,
        0,
      ),
    ];
    const frame = mergeBoxes(bars);
    const mesh = new THREE.InstancedMesh(frame, concrete, same.length);
    mesh.name = 'tree-pit-border';
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    same.forEach((pit, k) => {
      q.setFromAxisAngle(up, pit.angle);
      mesh.setMatrixAt(
        k,
        matrix.compose(new THREE.Vector3(pit.x, pit.lift, pit.z), q, new THREE.Vector3(1, 1, 1)),
      );
    });
    group.add(mesh);
  }
  return { group, soil };
}

function mergeBoxes(boxes: THREE.BufferGeometry[]): THREE.BufferGeometry {
  const positions: number[] = [];
  const normals: number[] = [];
  for (const box of boxes) {
    const flat = box.toNonIndexed();
    positions.push(...(flat.getAttribute('position').array as Float32Array));
    normals.push(...(flat.getAttribute('normal').array as Float32Array));
    flat.dispose();
    box.dispose();
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
  return g;
}
