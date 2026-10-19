/* Оборудование детских и спортивных площадок. Чертёж даёт контур резины (part вида special в
 * surface.json) и подписи «ДЕТ.ПЛ.» и «СПОРТ ПЛ.», но не сами качели и ворота: площадка в 3D
 * стояла пустой резиной (пользователь, 19.10.2026: «качели, горку, песочницу и пару скамеек
 * по бокам, как везде»). Набор - типовой: на детской качели, горка, песочница и две скамейки,
 * на спортивной ворота у торцов и турники. Места ищутся внутри контура с запасом от края, от
 * деревьев, опор и друг от друга; не влезло - предмет пропускается. */

import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import { mainAxis } from './facades';
import type { Flat } from './types';

type Ring = readonly Flat[];

export type GroundKind = 'kids' | 'sports';
export type ItemKind = 'swing' | 'slide' | 'sandbox' | 'goal' | 'bars' | 'bench';

export interface GroundLabel {
  x: number;
  z: number;
  kind: GroundKind;
}

export interface Ground {
  rings: Ring[];
  kind: GroundKind;
  anchor: Flat;
}

export interface Item {
  kind: ItemKind;
  x: number;
  z: number;
  /** Поворот вокруг вертикали: ось x модели - вдоль, у скамейки сиденье смотрит в +z. */
  angle: number;
}

/** Габарит предмета в плане (вдоль, поперёк) и свободная зона вокруг, м. */
const FOOT: Record<ItemKind, { len: number; wid: number; clear: number; height: number }> = {
  swing: { len: 3.2, wid: 1.8, clear: 1.2, height: 2.3 },
  slide: { len: 4.0, wid: 1.2, clear: 0.8, height: 2.6 },
  sandbox: { len: 2.0, wid: 2.0, clear: 0.6, height: 0.3 },
  goal: { len: 3.0, wid: 1.0, clear: 0.6, height: 2.0 },
  bars: { len: 2.6, wid: 0.6, clear: 0.8, height: 2.3 },
  bench: { len: 1.8, wid: 0.6, clear: 0.2, height: 0.9 },
};
/** Предмет не ближе этого к краю контура площадки, м. */
const EDGE_M = 0.5;
const GRID_M = 0.5;
/** Подпись площадки дальше этого от контура резины - не этой площадки, м. */
const LABEL_REACH_M = 1.0;
/** Две подписи одного вида ближе этого - одна площадка, м. */
const SAME_GROUND_M = 8.0;

export function groundKind(text: string): GroundKind | null {
  const t = text.trim().toUpperCase();
  if (/^ДЕТ\W*ПЛ/.test(t)) return 'kids';
  if (/^СПОРТ\W*ПЛ/.test(t)) return 'sports';
  return null;
}

/** Площадки: контур резины и подписи на нём. Подпись каждого вида даёт свой набор. */
export function groundsOf(parts: readonly Ring[][], labels: readonly GroundLabel[]): Ground[] {
  const out: Ground[] = [];
  for (const rings of parts) {
    const own: GroundLabel[] = [];
    for (const label of labels) {
      if (distanceToArea(rings, label) > LABEL_REACH_M) continue;
      const twin = own.some(
        (o) => o.kind === label.kind && Math.hypot(o.x - label.x, o.z - label.z) < SAME_GROUND_M,
      );
      if (!twin) own.push(label);
    }
    for (const label of own) out.push({ rings: [...rings], kind: label.kind, anchor: label });
  }
  return out;
}

interface Placed {
  x: number;
  z: number;
  r: number;
}

/** Расстановка набора площадки. avoid - деревья, опоры, нарисованные скамейки (центр и
 *  радиус), taken - уже поставленное на других наборах той же резины. */
export function furnish(
  ground: Ground,
  avoid: readonly Placed[],
  taken: Placed[] = [],
  withBenches = true,
): Item[] {
  const outer = ground.rings[0];
  if (!outer || outer.length < 3) return [];
  const axis = mainAxis([...outer]);
  const along = { x: axis.dx, z: axis.dz };
  const across = { x: -axis.dz, z: axis.dx };
  const yaw = Math.atan2(-along.z, along.x);
  const center = { x: axis.cx, z: axis.cz };
  // Набор строится вокруг подписи, но не дальше середины контура, чем на треть длины.
  const reach = axis.length / 3;
  const du = (ground.anchor.x - center.x) * along.x + (ground.anchor.z - center.z) * along.z;
  const origin = {
    x: center.x + along.x * Math.max(-reach, Math.min(reach, du)),
    z: center.z + along.z * Math.max(-reach, Math.min(reach, du)),
  };
  const at = (base: Flat, u: number, v: number): Flat => ({
    x: base.x + along.x * u + across.x * v,
    z: base.z + along.z * u + across.z * v,
  });
  const wishes: { kind: ItemKind; p: Flat; angle: number }[] = [];
  const step = Math.min(4.5, axis.length / 3);
  if (ground.kind === 'kids') {
    wishes.push({ kind: 'slide', p: origin, angle: yaw });
    wishes.push({ kind: 'swing', p: at(origin, step, 0), angle: yaw });
    wishes.push({ kind: 'sandbox', p: at(origin, -step, 0), angle: yaw });
  } else {
    const end = axis.length / 2 - FOOT.goal.wid - EDGE_M;
    if (axis.length >= 14) {
      // Ворота у торцов, лицом в поле: ось x ворот поперёк длины площадки.
      wishes.push({ kind: 'goal', p: at(center, end, 0), angle: yaw - Math.PI / 2 });
      wishes.push({ kind: 'goal', p: at(center, -end, 0), angle: yaw + Math.PI / 2 });
    }
    wishes.push({ kind: 'bars', p: at(center, 0, axis.width / 2 - 1.5), angle: yaw });
  }
  if (withBenches) {
    // Скамейки по длинным сторонам, сиденьем к середине площадки.
    for (const side of [1, -1]) {
      const p = at(center, 0, side * (axis.width / 2 - FOOT.bench.wid));
      const angle = Math.atan2(-side * across.x, -side * across.z);
      wishes.push({ kind: 'bench', p, angle: angle });
    }
  }
  const candidates = gridInside(ground.rings, GRID_M);
  const items: Item[] = [];
  for (const wish of wishes) {
    const foot = FOOT[wish.kind];
    const r = Math.hypot(foot.len, foot.wid) / 2 + foot.clear;
    const ordered = [...candidates].sort(
      (a, b) =>
        Math.hypot(a.x - wish.p.x, a.z - wish.p.z) - Math.hypot(b.x - wish.p.x, b.z - wish.p.z),
    );
    const spot = ordered.find(
      (p) =>
        fits(ground.rings, p, wish.angle, foot) &&
        [...avoid, ...taken].every((o) => Math.hypot(o.x - p.x, o.z - p.z) >= o.r + r),
    );
    if (!spot) continue;
    items.push({ kind: wish.kind, x: spot.x, z: spot.z, angle: wish.angle });
    taken.push({ x: spot.x, z: spot.z, r });
  }
  return items;
}

function gridInside(rings: readonly Ring[], step: number): Flat[] {
  const outer = rings[0] ?? [];
  const xs = outer.map((p) => p.x);
  const zs = outer.map((p) => p.z);
  const out: Flat[] = [];
  for (let x = Math.min(...xs); x <= Math.max(...xs); x += step) {
    for (let z = Math.min(...zs); z <= Math.max(...zs); z += step) {
      if (distanceToArea(rings, { x, z }) === 0) out.push({ x, z });
    }
  }
  return out;
}

/** Прямоугольник предмета с запасом от края целиком в контуре. */
function fits(
  rings: readonly Ring[],
  p: Flat,
  angle: number,
  foot: { len: number; wid: number },
): boolean {
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  const hl = foot.len / 2;
  const hw = foot.wid / 2;
  for (const [u, v] of [
    [-hl, -hw],
    [hl, -hw],
    [hl, hw],
    [-hl, hw],
    [0, -hw],
    [0, hw],
    [-hl, 0],
    [hl, 0],
  ] as const) {
    // Поворот вокруг вертикали как у three.js: x' = x cos + z sin, z' = -x sin + z cos.
    const q = { x: p.x + u * c + v * s, z: p.z - u * s + v * c };
    if (distanceToArea(rings, q) > 0) return false;
    if (edgeDistance(rings, q) < EDGE_M) return false;
  }
  return true;
}

function edgeDistance(rings: readonly Ring[], p: Flat): number {
  let best = Infinity;
  for (const ring of rings) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const a = ring[j] as Flat;
      const b = ring[i] as Flat;
      const vx = b.x - a.x;
      const vz = b.z - a.z;
      const len2 = vx * vx + vz * vz;
      const t =
        len2 > 0 ? Math.max(0, Math.min(1, ((p.x - a.x) * vx + (p.z - a.z) * vz) / len2)) : 0;
      best = Math.min(best, Math.hypot(p.x - (a.x + vx * t), p.z - (a.z + vz * t)));
    }
  }
  return best;
}

/** Контур предмета в плане для твёрдой камеры: прямоугольник и высота. */
export function itemFootprint(item: Item): { ring: Flat[]; height: number } {
  const foot = FOOT[item.kind];
  const c = Math.cos(item.angle);
  const s = Math.sin(item.angle);
  const hl = foot.len / 2;
  const hw = foot.wid / 2;
  const ring = (
    [
      [-hl, -hw],
      [hl, -hw],
      [hl, hw],
      [-hl, hw],
    ] as const
  ).map(([u, v]) => ({ x: item.x + u * c + v * s, z: item.z - u * s + v * c }));
  return { ring, height: foot.height };
}

// --- Модели -------------------------------------------------------------------------------

type Paint = 'blue' | 'red' | 'yellow' | 'steel' | 'wood' | 'sand' | 'white' | 'rubber';

const PAINTS: Record<Paint, { color: number; roughness: number; metalness: number }> = {
  blue: { color: 0x2f6fb5, roughness: 0.5, metalness: 0.2 },
  red: { color: 0xc6372d, roughness: 0.5, metalness: 0.2 },
  yellow: { color: 0xf0b62c, roughness: 0.5, metalness: 0.1 },
  steel: { color: 0x8c949b, roughness: 0.35, metalness: 0.8 },
  wood: { color: 0xa9784a, roughness: 0.8, metalness: 0 },
  sand: { color: 0xe3cf9c, roughness: 1, metalness: 0 },
  white: { color: 0xf2f2ee, roughness: 0.4, metalness: 0.3 },
  rubber: { color: 0x1d1f22, roughness: 0.9, metalness: 0 },
};

function tube(a: THREE.Vector3, b: THREE.Vector3, r: number): THREE.BufferGeometry {
  const len = a.distanceTo(b);
  const g = new THREE.CylinderGeometry(r, r, len, 8);
  const mid = a.clone().add(b).multiplyScalar(0.5);
  const dir = b.clone().sub(a).normalize();
  g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir));
  g.translate(mid.x, mid.y, mid.z);
  return g;
}

function block(
  w: number,
  h: number,
  d: number,
  x: number,
  y: number,
  z: number,
): THREE.BufferGeometry {
  const g = new THREE.BoxGeometry(w, h, d);
  g.translate(x, y, z);
  return g;
}

const v = (x: number, y: number, z: number) => new THREE.Vector3(x, y, z);

/** Модель предмета: куски по краскам, в осях модели (x - вдоль, y - вверх). */
function model(kind: ItemKind): Partial<Record<Paint, THREE.BufferGeometry[]>> {
  switch (kind) {
    case 'swing': {
      const frame = [tube(v(-1.5, 2.2, 0), v(1.5, 2.2, 0), 0.05)];
      for (const x of [-1.5, 1.5]) {
        frame.push(
          tube(v(x, 2.2, 0), v(x, 0, 0.85), 0.045),
          tube(v(x, 2.2, 0), v(x, 0, -0.85), 0.045),
        );
      }
      const chains: THREE.BufferGeometry[] = [];
      const seats: THREE.BufferGeometry[] = [];
      for (const x of [-0.65, 0.65]) {
        chains.push(tube(v(x - 0.22, 2.2, 0), v(x - 0.22, 0.47, 0), 0.008));
        chains.push(tube(v(x + 0.22, 2.2, 0), v(x + 0.22, 0.47, 0), 0.008));
        seats.push(block(0.5, 0.04, 0.2, x, 0.45, 0));
      }
      return { blue: frame, steel: chains, rubber: seats };
    }
    case 'slide': {
      // Площадка с крышей на четырёх стойках, лесенка сзади, скат вперёд по +x.
      const posts: THREE.BufferGeometry[] = [];
      for (const [x, z] of [
        [-1.6, -0.5],
        [-0.6, -0.5],
        [-1.6, 0.5],
        [-0.6, 0.5],
      ] as const) {
        posts.push(tube(v(x, 0, z), v(x, 2.2, z), 0.05));
      }
      const deck = [block(1.0, 0.08, 1.0, -1.1, 1.2, 0)];
      const rails = [
        block(1.0, 0.05, 0.04, -1.1, 1.75, -0.5),
        block(1.0, 0.05, 0.04, -1.1, 1.75, 0.5),
      ];
      const roof = new THREE.ConeGeometry(0.85, 0.5, 4);
      roof.rotateY(Math.PI / 4);
      roof.translate(-1.1, 2.45, 0);
      const ladder: THREE.BufferGeometry[] = [
        tube(v(-1.6, 1.2, -0.25), v(-2.0, 0, -0.25), 0.03),
        tube(v(-1.6, 1.2, 0.25), v(-2.0, 0, 0.25), 0.03),
      ];
      for (let k = 1; k <= 4; k++) {
        const t = k / 5;
        ladder.push(
          tube(
            v(-1.6 - 0.4 * t, 1.2 - 1.2 * t, -0.25),
            v(-1.6 - 0.4 * t, 1.2 - 1.2 * t, 0.25),
            0.02,
          ),
        );
      }
      const chute = new THREE.BoxGeometry(2.6, 0.04, 0.5);
      const sides = [
        new THREE.BoxGeometry(2.6, 0.18, 0.04),
        new THREE.BoxGeometry(2.6, 0.18, 0.04),
      ];
      const tilt = -Math.atan2(1.05, 2.4);
      chute.rotateZ(tilt);
      chute.translate(0.6, 0.68, 0);
      sides.forEach((g, i) => {
        g.rotateZ(tilt);
        g.translate(0.6, 0.76, i ? 0.25 : -0.25);
      });
      return {
        steel: [...posts, ...ladder],
        wood: deck,
        blue: rails,
        red: [roof],
        yellow: [chute, ...sides],
      };
    }
    case 'sandbox': {
      const boards = [
        block(2.0, 0.25, 0.12, 0, 0.125, -0.94),
        block(2.0, 0.25, 0.12, 0, 0.125, 0.94),
        block(0.12, 0.25, 1.76, -0.94, 0.125, 0),
        block(0.12, 0.25, 1.76, 0.94, 0.125, 0),
      ];
      return { wood: boards, sand: [block(1.76, 0.1, 1.76, 0, 0.12, 0)] };
    }
    case 'goal': {
      const frame = [
        tube(v(-1.5, 0, 0), v(-1.5, 2.0, 0), 0.04),
        tube(v(1.5, 0, 0), v(1.5, 2.0, 0), 0.04),
        tube(v(-1.5, 2.0, 0), v(1.5, 2.0, 0), 0.04),
        tube(v(-1.5, 2.0, 0), v(-1.5, 0, -0.9), 0.025),
        tube(v(1.5, 2.0, 0), v(1.5, 0, -0.9), 0.025),
        tube(v(-1.5, 0, -0.9), v(1.5, 0, -0.9), 0.025),
      ];
      return { white: frame };
    }
    case 'bars': {
      const posts = [-1.2, -0.4, 0.4, 1.2].map((x, i) =>
        tube(v(x, 0, 0), v(x, [1.7, 2.3, 2.3, 2.0][i] ?? 2, 0), 0.05),
      );
      const bars = [
        tube(v(-1.2, 1.65, 0), v(-0.4, 1.65, 0), 0.02),
        tube(v(-0.4, 2.25, 0), v(0.4, 2.25, 0), 0.02),
        tube(v(0.4, 1.95, 0), v(1.2, 1.95, 0), 0.02),
      ];
      return { blue: posts, steel: bars };
    }
    case 'bench': {
      const slats = [0, 1, 2].map((k) => block(1.8, 0.035, 0.11, 0, 0.45, -0.16 + k * 0.14));
      const back = [0, 1].map((k) => {
        const g = new THREE.BoxGeometry(1.8, 0.1, 0.03);
        g.rotateX(-0.25);
        g.translate(0, 0.62 + k * 0.15, -0.27 - k * 0.04);
        return g;
      });
      const legs = [-0.75, 0.75].map((x) => block(0.06, 0.45, 0.5, x, 0.225, -0.02));
      return { wood: [...slats, ...back], rubber: legs };
    }
  }
}

/** Все предметы площадок одной группой: по краске одна сетка на вид предмета, экземпляры. */
export function playgroundGroup(items: readonly Item[], level = 0): THREE.Group | null {
  if (!items.length) return null;
  const group = new THREE.Group();
  group.name = 'playgrounds';
  const materials = new Map<Paint, THREE.MeshStandardMaterial>();
  const material = (paint: Paint) => {
    let m = materials.get(paint);
    if (!m) {
      m = new THREE.MeshStandardMaterial(PAINTS[paint]);
      materials.set(paint, m);
    }
    return m;
  };
  const kinds = [...new Set(items.map((i) => i.kind))];
  const matrix = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);
  const one = new THREE.Vector3(1, 1, 1);
  for (const kind of kinds) {
    const mine = items.filter((i) => i.kind === kind);
    for (const [paint, parts] of Object.entries(model(kind)) as [Paint, THREE.BufferGeometry[]][]) {
      if (!parts.length) continue;
      const geometry = mergeGeometries(parts.map((p) => p.toNonIndexed()));
      for (const p of parts) p.dispose();
      const mesh = new THREE.InstancedMesh(geometry, material(paint), mine.length);
      mine.forEach((item, k) => {
        q.setFromAxisAngle(up, item.angle);
        mesh.setMatrixAt(k, matrix.compose(new THREE.Vector3(item.x, level, item.z), q, one));
      });
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.name = `playground-${kind}-${paint}`;
      group.add(mesh);
    }
  }
  return group;
}

/** Расстояние от точки до многоугольника с дырами: 0 внутри. */
export function distanceToArea(rings: readonly Ring[], p: Flat): number {
  let inside = false;
  let best = Infinity;
  for (const ring of rings) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const a = ring[i] as Flat;
      const b = ring[j] as Flat;
      if (a.z > p.z !== b.z > p.z && p.x < ((b.x - a.x) * (p.z - a.z)) / (b.z - a.z) + a.x) {
        inside = !inside;
      }
      best = Math.min(best, segmentDistance(p, a, b));
    }
  }
  return inside ? 0 : best;
}

function segmentDistance(p: Flat, a: Flat, b: Flat): number {
  const vx = b.x - a.x;
  const vz = b.z - a.z;
  const len2 = vx * vx + vz * vz;
  const t = len2 > 0 ? Math.max(0, Math.min(1, ((p.x - a.x) * vx + (p.z - a.z) * vz) / len2)) : 0;
  return Math.hypot(p.x - (a.x + vx * t), p.z - (a.z + vz * t));
}
