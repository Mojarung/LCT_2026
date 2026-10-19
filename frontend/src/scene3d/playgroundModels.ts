/* Модели оборудования площадок: простые формы по краскам, экземплярами. Оси модели: x - вдоль
 * предмета, y - вверх, z - поперёк; середина габарита в нуле. Облик - типовой московский двор:
 * стальные рамы с синими заглушками, деревянные стойки комплекса с зелёными крышами,
 * чёрные резиновые сиденья (пользователь, 19.10.2026, фото площадки у дома). */

import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import type { Item, ItemKind } from './playgrounds';

type Paint =
  | 'blue'
  | 'red'
  | 'yellow'
  | 'steel'
  | 'frame'
  | 'wood'
  | 'sand'
  | 'white'
  | 'rubber'
  | 'green'
  | 'cream'
  | 'deck'
  | 'net'
  | 'teal'
  | 'orange';

const PAINTS: Record<Paint, { color: number; roughness: number; metalness: number }> = {
  blue: { color: 0x2f6fb5, roughness: 0.5, metalness: 0.2 },
  red: { color: 0xc6372d, roughness: 0.5, metalness: 0.2 },
  yellow: { color: 0xf0b62c, roughness: 0.5, metalness: 0.1 },
  steel: { color: 0x9aa1a7, roughness: 0.35, metalness: 0.8 },
  frame: { color: 0x878e94, roughness: 0.5, metalness: 0.55 },
  wood: { color: 0xa9784a, roughness: 0.8, metalness: 0 },
  sand: { color: 0xe3cf9c, roughness: 1, metalness: 0 },
  white: { color: 0xf2f2ee, roughness: 0.4, metalness: 0.3 },
  rubber: { color: 0x1d1f22, roughness: 0.9, metalness: 0 },
  green: { color: 0x4f9b3e, roughness: 0.6, metalness: 0.05 },
  cream: { color: 0xe6d8a8, roughness: 0.7, metalness: 0 },
  deck: { color: 0x4d4743, roughness: 0.85, metalness: 0.05 },
  net: { color: 0x2f4f2c, roughness: 0.9, metalness: 0 },
  teal: { color: 0x2c6b5c, roughness: 0.5, metalness: 0.05 },
  orange: { color: 0xd8642a, roughness: 0.5, metalness: 0.2 },
};

type Parts = Partial<Record<Paint, THREE.BufferGeometry[]>>;

const v = (x: number, y: number, z: number) => new THREE.Vector3(x, y, z);

function tube(a: THREE.Vector3, b: THREE.Vector3, r: number, sides = 8): THREE.BufferGeometry {
  const len = a.distanceTo(b);
  const g = new THREE.CylinderGeometry(r, r, len, sides);
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

/** Брус от точки к точке: доска, скат горки, ступень тетивы. */
function beam(a: THREE.Vector3, b: THREE.Vector3, w: number, h: number): THREE.BufferGeometry {
  const len = a.distanceTo(b);
  const g = new THREE.BoxGeometry(w, len, h);
  const dir = b.clone().sub(a).normalize();
  g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir));
  const mid = a.clone().add(b).multiplyScalar(0.5);
  g.translate(mid.x, mid.y, mid.z);
  return g;
}

function cap(x: number, y: number, z: number): THREE.BufferGeometry {
  const g = new THREE.SphereGeometry(0.06, 8, 6);
  g.translate(x, y, z);
  return g;
}

function add(parts: Parts, paint: Paint, ...geometry: THREE.BufferGeometry[]): void {
  (parts[paint] ??= []).push(...geometry);
}

/** А-образная рама качелей: перекладина вдоль x на высоте top, ноги расходятся по z. */
function aFrame(parts: Parts, half: number, top: number, spread: number): void {
  add(parts, 'frame', tube(v(-half, top, 0), v(half, top, 0), 0.055));
  for (const x of [-half, half]) {
    add(
      parts,
      'frame',
      tube(v(x, top, 0), v(x * 1.06, 0, spread), 0.05),
      tube(v(x, top, 0), v(x * 1.06, 0, -spread), 0.05),
    );
    add(parts, 'blue', cap(x, top + 0.03, 0));
  }
}

/** Башня комплекса: четыре стойки, настил, бортики и двускатная крыша (конёк вдоль x). */
function tower(parts: Parts, x: number, z: number, deck: number): void {
  const h = 0.65;
  for (const [dx, dz] of [
    [-h, -h],
    [h, -h],
    [-h, h],
    [h, h],
  ] as const) {
    add(parts, 'wood', block(0.09, deck + 1.55, 0.09, x + dx, (deck + 1.55) / 2, z + dz));
  }
  add(parts, 'wood', block(1.3, 0.06, 1.3, x, deck, z));
  const top = deck + 1.55;
  for (const side of [-1, 1]) {
    const roof = new THREE.BoxGeometry(1.6, 0.04, 0.95);
    roof.rotateX(side * 0.62);
    roof.translate(x, top + 0.27, z + side * 0.38);
    add(parts, 'green', roof);
  }
  // Фронтоны и щиты бортиков.
  for (const side of [-1, 1]) {
    const gable = new THREE.BufferGeometry();
    const gx = x + side * h;
    gable.setAttribute(
      'position',
      new THREE.Float32BufferAttribute(
        [gx, top, z - h - 0.05, gx, top, z + h + 0.05, gx, top + 0.55, z],
        3,
      ),
    );
    gable.setAttribute('uv', new THREE.Float32BufferAttribute([0, 0, 1, 0, 0.5, 1], 2));
    gable.computeVertexNormals();
    add(parts, 'cream', gable, block(0.03, 0.6, 1.2, gx, deck + 0.4, z));
  }
}

/** Модель предмета по краскам. */
function model(kind: ItemKind): Parts {
  const parts: Parts = {};
  switch (kind) {
    case 'complex': {
      // Две башни, мост-сетка между ними, горка с левой башни, лестница с правой, рукоход.
      const deck = 1.2;
      tower(parts, -1.9, 0.6, deck);
      tower(parts, 1.9, 0.6, deck);
      add(parts, 'wood', block(2.5, 0.06, 0.9, 0, deck - 0.05, 0.6));
      for (const z of [0.15, 1.05]) {
        add(parts, 'green', block(2.5, 0.07, 0.07, 0, deck + 0.8, z));
        for (let k = 0; k <= 8; k++) {
          const x = -1.2 + k * 0.3;
          add(parts, 'net', tube(v(x, deck, z), v(x, deck + 0.8, z), 0.012, 4));
        }
        add(parts, 'net', tube(v(-1.25, deck + 0.4, z), v(1.25, deck + 0.4, z), 0.012, 4));
      }
      // Горка: скат с настила левой башни в сторону -z.
      const from = v(-1.9, deck + 0.02, -0.05);
      const to = v(-1.9, 0.3, -2.25);
      add(parts, 'green', beam(from, to, 0.55, 0.04));
      for (const side of [-0.29, 0.29]) {
        add(
          parts,
          'green',
          beam(v(-1.9 + side, deck + 0.14, -0.05), v(-1.9 + side, 0.42, -2.25), 0.04, 0.18),
        );
      }
      add(parts, 'steel', block(0.55, 0.04, 0.4, -1.9, 0.28, -2.43));
      // Лестница с правой башни в сторону +z.
      for (const side of [-0.32, 0.32]) {
        add(parts, 'wood', beam(v(1.9 + side, deck, 1.25), v(1.9 + side, 0, 2.4), 0.06, 0.16));
      }
      for (let k = 1; k <= 4; k++) {
        const t = k / 5;
        add(parts, 'wood', block(0.6, 0.04, 0.2, 1.9, deck * (1 - t), 1.25 + 1.15 * t));
      }
      add(parts, 'cream', beam(v(2.24, deck + 0.8, 1.25), v(2.24, 0.8, 2.4), 0.05, 0.08));
      // Рукоход от правой башни по +x.
      for (const z of [0.25, 0.95]) {
        add(parts, 'steel', tube(v(2.55, 2.0, z), v(3.35, 2.0, z), 0.025));
        add(parts, 'wood', block(0.09, 2.0, 0.09, 3.35, 1.0, z));
      }
      for (let k = 0; k < 3; k++) {
        const x = 2.7 + k * 0.28;
        add(parts, 'steel', tube(v(x, 2.0, 0.25), v(x, 2.0, 0.95), 0.018));
      }
      break;
    }
    case 'slide': {
      // Площадка с крышей на четырёх стойках, лесенка сзади, скат вперёд по +x.
      for (const [x, z] of [
        [-1.6, -0.5],
        [-0.6, -0.5],
        [-1.6, 0.5],
        [-0.6, 0.5],
      ] as const) {
        add(parts, 'wood', block(0.08, 2.2, 0.08, x, 1.1, z));
      }
      add(parts, 'wood', block(1.0, 0.06, 1.0, -1.1, 1.2, 0));
      add(
        parts,
        'green',
        block(1.0, 0.05, 0.04, -1.1, 1.75, -0.5),
        block(1.0, 0.05, 0.04, -1.1, 1.75, 0.5),
      );
      for (const side of [-1, 1]) {
        const roof = new THREE.BoxGeometry(1.25, 0.04, 0.75);
        roof.rotateX(side * 0.62);
        roof.translate(-1.1, 2.42, side * 0.3);
        add(parts, 'green', roof);
      }
      add(
        parts,
        'wood',
        tube(v(-1.6, 1.2, -0.25), v(-2.0, 0, -0.25), 0.03),
        tube(v(-1.6, 1.2, 0.25), v(-2.0, 0, 0.25), 0.03),
      );
      for (let k = 1; k <= 4; k++) {
        const t = k / 5;
        add(
          parts,
          'steel',
          tube(
            v(-1.6 - 0.4 * t, 1.2 - 1.2 * t, -0.25),
            v(-1.6 - 0.4 * t, 1.2 - 1.2 * t, 0.25),
            0.02,
          ),
        );
      }
      add(parts, 'green', beam(v(-0.6, 1.2, 0), v(1.6, 0.3, 0), 0.5, 0.04));
      for (const z of [-0.26, 0.26]) {
        add(parts, 'green', beam(v(-0.6, 1.32, z), v(1.6, 0.42, z), 0.04, 0.18));
      }
      add(parts, 'steel', block(0.5, 0.04, 0.5, 1.85, 0.28, 0));
      break;
    }
    case 'swing': {
      aFrame(parts, 1.55, 2.2, 0.85);
      for (const x of [-0.7, 0.7]) {
        add(
          parts,
          'steel',
          tube(v(x - 0.22, 2.2, 0), v(x - 0.22, 0.47, 0), 0.008),
          tube(v(x + 0.22, 2.2, 0), v(x + 0.22, 0.47, 0), 0.008),
        );
        add(parts, 'rubber', block(0.48, 0.04, 0.18, x, 0.45, 0));
      }
      break;
    }
    case 'nest': {
      aFrame(parts, 1.25, 2.1, 0.85);
      const ring = new THREE.TorusGeometry(0.5, 0.05, 6, 20);
      ring.rotateX(Math.PI / 2);
      ring.translate(0, 0.55, 0);
      const mesh = new THREE.CircleGeometry(0.48, 16);
      mesh.rotateX(-Math.PI / 2);
      mesh.translate(0, 0.53, 0);
      add(parts, 'rubber', ring, mesh);
      for (const [x, z] of [
        [-0.35, -0.35],
        [0.35, -0.35],
        [-0.35, 0.35],
        [0.35, 0.35],
      ] as const) {
        add(parts, 'rubber', tube(v(x * 0.4, 2.1, 0), v(x, 0.56, z), 0.012, 4));
      }
      break;
    }
    case 'carousel': {
      const base = new THREE.CylinderGeometry(0.85, 0.85, 0.06, 24);
      base.translate(0, 0.14, 0);
      const table = new THREE.CylinderGeometry(0.25, 0.25, 0.04, 16);
      table.translate(0, 0.72, 0);
      add(parts, 'deck', base, table);
      const seat = new THREE.TorusGeometry(0.55, 0.13, 3, 20, Math.PI * 1.45);
      seat.rotateX(Math.PI / 2);
      seat.scale(1, 0.25, 1);
      seat.translate(0, 0.45, 0);
      add(parts, 'white', seat);
      const rail = new THREE.TorusGeometry(0.78, 0.028, 6, 28);
      rail.rotateX(Math.PI / 2);
      rail.translate(0, 0.95, 0);
      add(parts, 'steel', rail, tube(v(0, 0.17, 0), v(0, 0.72, 0), 0.05));
      for (let k = 0; k < 6; k++) {
        const a = (k / 6) * Math.PI * 2;
        const x = Math.cos(a) * 0.78;
        const z = Math.sin(a) * 0.78;
        add(parts, 'steel', tube(v(x, 0.17, z), v(x, 0.95, z), 0.024));
      }
      add(parts, 'frame', tube(v(0, 0, 0), v(0, 0.11, 0), 0.12));
      break;
    }
    case 'seesaw': {
      // Балансир-«лошадки»: стойка, брус, сиденья и головы на концах, покрышки-упоры.
      add(parts, 'frame', tube(v(0, 0, 0), v(0, 0.52, 0), 0.06));
      add(parts, 'wood', beam(v(-1.5, 0.42, 0), v(1.5, 0.66, 0), 0.14, 0.09));
      for (const x of [-1.25, 1.25]) {
        const y = 0.54 + (x / 1.5) * 0.12;
        add(parts, 'white', block(0.42, 0.03, 0.3, x, y + 0.07, 0));
        const head = x < 0 ? x + 0.32 : x - 0.32;
        add(parts, 'cream', block(0.06, 0.5, 0.36, head, y + 0.3, 0));
        add(parts, 'steel', tube(v(head, y + 0.3, -0.18), v(head, y + 0.3, 0.18), 0.018));
        const tyre = new THREE.TorusGeometry(0.11, 0.045, 6, 12);
        tyre.translate(x * 1.12, 0.15, 0);
        add(parts, 'rubber', tyre);
      }
      add(parts, 'cream', block(0.9, 0.22, 0.04, 0, 0.72, 0));
      break;
    }
    case 'rocker': {
      add(parts, 'red', tube(v(0, 0, 0), v(0, 0.42, 0), 0.1, 10));
      add(
        parts,
        'yellow',
        block(0.9, 0.22, 0.32, 0, 0.55, 0),
        block(0.08, 0.38, 0.32, 0.4, 0.82, 0),
      );
      add(parts, 'steel', tube(v(0.3, 0.85, -0.15), v(0.3, 0.85, 0.15), 0.018));
      break;
    }
    case 'sandbox': {
      add(
        parts,
        'wood',
        block(2.0, 0.25, 0.12, 0, 0.125, -0.94),
        block(2.0, 0.25, 0.12, 0, 0.125, 0.94),
        block(0.12, 0.25, 1.76, -0.94, 0.125, 0),
        block(0.12, 0.25, 1.76, 0.94, 0.125, 0),
      );
      add(parts, 'sand', block(1.76, 0.1, 1.76, 0, 0.12, 0));
      break;
    }
    case 'goal': {
      add(
        parts,
        'white',
        tube(v(-1.5, 0, 0), v(-1.5, 2.0, 0), 0.04),
        tube(v(1.5, 0, 0), v(1.5, 2.0, 0), 0.04),
        tube(v(-1.5, 2.0, 0), v(1.5, 2.0, 0), 0.04),
        tube(v(-1.5, 2.0, 0), v(-1.5, 0, -0.9), 0.025),
        tube(v(1.5, 2.0, 0), v(1.5, 0, -0.9), 0.025),
        tube(v(-1.5, 0, -0.9), v(1.5, 0, -0.9), 0.025),
      );
      break;
    }
    case 'bars': {
      [-1.2, -0.4, 0.4, 1.2].forEach((x, i) => {
        add(parts, 'blue', tube(v(x, 0, 0), v(x, [1.7, 2.3, 2.3, 2.0][i] ?? 2, 0), 0.05));
      });
      add(
        parts,
        'steel',
        tube(v(-1.2, 1.65, 0), v(-0.4, 1.65, 0), 0.02),
        tube(v(-0.4, 2.25, 0), v(0.4, 2.25, 0), 0.02),
        tube(v(0.4, 1.95, 0), v(1.2, 1.95, 0), 0.02),
      );
      break;
    }
    case 'hoop': {
      // Стойка сзади, щит и кольцо - в сторону +z.
      add(
        parts,
        'frame',
        tube(v(0, 0, -0.6), v(0, 3.0, -0.6), 0.07),
        tube(v(0, 2.85, -0.6), v(0, 2.85, 0.05), 0.04),
      );
      add(parts, 'white', block(1.2, 0.9, 0.04, 0, 3.05, 0.08));
      const ring = new THREE.TorusGeometry(0.23, 0.015, 6, 20);
      ring.rotateX(Math.PI / 2);
      ring.translate(0, 3.05, 0.35);
      add(parts, 'orange', ring);
      break;
    }
    case 'table': {
      add(parts, 'teal', block(2.74, 0.04, 1.525, 0, 0.74, 0));
      add(parts, 'white', block(0.02, 0.15, 1.65, 0, 0.84, 0));
      for (const x of [-1.0, 1.0]) add(parts, 'frame', block(0.08, 0.72, 1.1, x, 0.36, 0));
      break;
    }
    case 'bench': {
      for (let k = 0; k < 3; k++)
        add(parts, 'wood', block(1.8, 0.035, 0.11, 0, 0.45, -0.16 + k * 0.14));
      for (let k = 0; k < 2; k++) {
        const g = new THREE.BoxGeometry(1.8, 0.1, 0.03);
        g.rotateX(-0.25);
        g.translate(0, 0.62 + k * 0.15, -0.27 - k * 0.04);
        add(parts, 'wood', g);
      }
      add(
        parts,
        'rubber',
        block(0.06, 0.45, 0.5, -0.75, 0.225, -0.02),
        block(0.06, 0.45, 0.5, 0.75, 0.225, -0.02),
      );
      break;
    }
    case 'seat': {
      // Лавка без спинки: пять реек на двух опорах (спинка - только у ограды, benchBack).
      for (let k = 0; k < 5; k++)
        add(parts, 'wood', block(1.8, 0.035, 0.085, 0, 0.45, -0.2 + k * 0.1));
      add(
        parts,
        'rubber',
        block(0.07, 0.43, 0.42, -0.7, 0.215, 0),
        block(0.07, 0.43, 0.42, 0.7, 0.215, 0),
      );
      break;
    }
    case 'bin': {
      const can = new THREE.CylinderGeometry(0.19, 0.17, 0.6, 14, 1, true);
      can.translate(0, 0.4, 0);
      add(parts, 'rubber', can);
      add(
        parts,
        'frame',
        tube(v(-0.23, 0, 0), v(-0.23, 0.75, 0), 0.02),
        tube(v(0.23, 0, 0), v(0.23, 0.75, 0), 0.02),
        tube(v(-0.23, 0.75, 0), v(0.23, 0.75, 0), 0.02),
      );
      break;
    }
  }
  return parts;
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
      m = new THREE.MeshStandardMaterial({ ...PAINTS[paint], side: THREE.DoubleSide });
      materials.set(paint, m);
    }
    return m;
  };
  const matrix = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);
  const one = new THREE.Vector3(1, 1, 1);
  for (const kind of new Set(items.map((i) => i.kind))) {
    const mine = items.filter((i) => i.kind === kind);
    for (const [paint, parts] of Object.entries(model(kind)) as [Paint, THREE.BufferGeometry[]][]) {
      if (!parts.length) continue;
      const geometry = mergeGeometries(parts.map((p) => (p.index ? p.toNonIndexed() : p)));
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
