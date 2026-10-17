/* Модули фасада в 3D: лоджии, подъезды, машинные помещения на крыше и парапеты.
 *
 * Где стоит каждый модуль, решает facades.ts. Здесь - их геометрия и отрисовка: лоджий на
 * улице тысячи, поэтому каждая - экземпляр одной сетки со своей матрицей и цветом ограждения,
 * всё вместе - несколько вызовов отрисовки. Модуль построен в своих осях: x вдоль стены, y
 * вверх, z наружу от стены; размеры лоджии - в долях, масштаб экземпляра даёт метры. */

import * as THREE from 'three';

import {
  facadePlan,
  type Loggia,
  type Module,
  type Rgb,
  paletteOf,
  seriesOf,
  wallsOf,
} from './facades';
import { pitchedRoof } from './buildings';
import type { Building, Line } from './types';

interface Parts {
  pos: number[];
  nor: number[];
  color: number[];
  accent: number[];
}

function parts(): Parts {
  return { pos: [], nor: [], color: [], accent: [] };
}

function linear(rgb: Rgb): [number, number, number] {
  const c = new THREE.Color().setRGB(rgb[0], rgb[1], rgb[2], THREE.SRGBColorSpace);
  return [c.r, c.g, c.b];
}

/** Параллелепипед по углам [x0, x1] x [y0, y1] x [z0, z1], все шесть граней наружу. */
function box(
  out: Parts,
  [x0, x1]: [number, number],
  [y0, y1]: [number, number],
  [z0, z1]: [number, number],
  color: readonly [number, number, number],
  accent = 0,
): void {
  const faces: [number[][], number[]][] = [
    [
      [
        [x0, y0, z1],
        [x1, y0, z1],
        [x1, y1, z1],
        [x0, y1, z1],
      ],
      [0, 0, 1],
    ],
    [
      [
        [x1, y0, z0],
        [x0, y0, z0],
        [x0, y1, z0],
        [x1, y1, z0],
      ],
      [0, 0, -1],
    ],
    [
      [
        [x0, y1, z1],
        [x1, y1, z1],
        [x1, y1, z0],
        [x0, y1, z0],
      ],
      [0, 1, 0],
    ],
    [
      [
        [x0, y0, z0],
        [x1, y0, z0],
        [x1, y0, z1],
        [x0, y0, z1],
      ],
      [0, -1, 0],
    ],
    [
      [
        [x1, y0, z1],
        [x1, y0, z0],
        [x1, y1, z0],
        [x1, y1, z1],
      ],
      [1, 0, 0],
    ],
    [
      [
        [x0, y0, z0],
        [x0, y0, z1],
        [x0, y1, z1],
        [x0, y1, z0],
      ],
      [-1, 0, 0],
    ],
  ];
  for (const [quad, n] of faces) {
    for (const i of [0, 1, 2, 0, 2, 3]) {
      const p = quad[i] ?? [0, 0, 0];
      out.pos.push(p[0] ?? 0, p[1] ?? 0, p[2] ?? 0);
      out.nor.push(n[0] ?? 0, n[1] ?? 0, n[2] ?? 0);
      out.color.push(...color);
      out.accent.push(accent);
    }
  }
}

function geometryOf(p: Parts): THREE.BufferGeometry {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(p.pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(p.nor, 3));
  g.setAttribute('color', new THREE.Float32BufferAttribute(p.color, 3));
  g.setAttribute('aAccent', new THREE.Float32BufferAttribute(p.accent, 1));
  g.computeBoundingSphere();
  return g;
}

const CONCRETE = linear([0.66, 0.64, 0.6]);
const PARTITION = linear([0.8, 0.79, 0.76]);
const FRAME = linear([0.9, 0.9, 0.88]);
const WHITE: [number, number, number] = [1, 1, 1];
const DOOR = linear([0.24, 0.2, 0.17]);
const RAIL = linear([0.2, 0.22, 0.23]);

/** Лоджия в долях: пол, перегородки по бокам, ограждение цвета дома, у остеклённой -
 *  импосты рам (стекло - отдельной сеткой, у него свой материал). */
export function loggiaGeometry(glazed: boolean): THREE.BufferGeometry {
  const p = parts();
  box(p, [-0.5, 0.5], [0, 0.06], [0, 1], CONCRETE);
  box(p, [-0.5, -0.46], [0.06, 1], [0, 1], PARTITION);
  box(p, [0.46, 0.5], [0.06, 1], [0, 1], PARTITION);
  box(p, [-0.46, 0.46], [0.06, 0.36], [0.93, 0.99], WHITE, 1);
  if (glazed) {
    for (const x of [-0.46, -0.155, 0.155])
      box(p, [x, x + 0.012], [0.36, 0.97], [0.955, 0.985], FRAME);
    box(p, [0.448, 0.46], [0.36, 0.97], [0.955, 0.985], FRAME);
    box(p, [-0.46, 0.46], [0.36, 0.38], [0.94, 0.99], FRAME);
    box(p, [-0.46, 0.46], [0.95, 0.97], [0.94, 0.99], FRAME);
  } else {
    box(p, [-0.46, 0.46], [0.36, 0.39], [0.95, 1.0], RAIL);
  }
  return geometryOf(p);
}

export function loggiaGlassGeometry(): THREE.BufferGeometry {
  const p = parts();
  box(p, [-0.455, 0.455], [0.37, 0.965], [0.962, 0.97], WHITE);
  return geometryOf(p);
}

/** Подъезд в метрах: крыльцо, козырёк на консолях, тамбур с дверью. */
export function entranceGeometry(): THREE.BufferGeometry {
  const p = parts();
  box(p, [-1.4, 1.4], [0, 0.16], [0, 1.7], CONCRETE);
  box(p, [-1.45, 1.45], [2.6, 2.78], [0, 1.6], CONCRETE);
  box(p, [-1.45, 1.45], [2.78, 2.86], [1.5, 1.6], PARTITION);
  box(p, [-0.62, 0.62], [0.16, 2.3], [0, 0.06], DOOR);
  box(p, [-0.8, -0.62], [0.16, 2.45], [0, 0.1], PARTITION);
  box(p, [0.62, 0.8], [0.16, 2.45], [0, 0.1], PARTITION);
  box(p, [-0.8, 0.8], [2.3, 2.6], [0, 0.1], PARTITION);
  // Табличка с номером квартир и фонарь над дверью.
  box(p, [-0.25, 0.25], [2.38, 2.5], [0.1, 0.12], [0.9, 0.9, 0.9]);
  return geometryOf(p);
}

/** Машинное помещение: короб в долях с дверью на торце, центр - в точке модуля. */
export function roofBoxGeometry(): THREE.BufferGeometry {
  const p = parts();
  box(p, [-0.5, 0.5], [0, 1], [-0.5, 0.5], WHITE, 1);
  box(p, [-0.52, 0.52], [1, 1.04], [-0.52, 0.52], CONCRETE);
  box(p, [-0.1, 0.1], [0, 0.8], [0.5, 0.51], DOOR);
  return geometryOf(p);
}

/** Парапет по контуру крыши: стенка внутрь от плоскости фасада, цвета стены. */
export function parapetGeometry(buildings: readonly Building[]): THREE.BufferGeometry {
  const p = parts();
  for (const b of buildings) {
    const series = seriesOf(b);
    // Двускатной крыше парапет не нужен: карниз со свесом.
    if (series === 'porch' || b.floors < 2 || pitchedRoof(b)) continue;
    const outer = b.rings[0];
    if (!outer) continue;
    const wall = linear(paletteOf(b, series).wall).map((v) => v * 0.86) as [number, number, number];
    const rise = series === 'tower' || series === 'slab' ? 0.9 : 0.55;
    const thick = 0.25;
    const y0 = b.height;
    const y1 = b.height + rise;
    for (const w of wallsOf(outer, false)) {
      const ix = -w.nx * thick;
      const iz = -w.nz * thick;
      const a = w.a;
      const c = w.b;
      const quad = (q: number[][], n: number[]) => {
        for (const i of [0, 1, 2, 0, 2, 3]) {
          const v = q[i] ?? [0, 0, 0];
          p.pos.push(v[0] ?? 0, v[1] ?? 0, v[2] ?? 0);
          p.nor.push(n[0] ?? 0, n[1] ?? 0, n[2] ?? 0);
          p.color.push(...wall);
          p.accent.push(0);
        }
      };
      const n = [w.nx, 0, w.nz];
      const outerFace = [
        [a.x, y0, a.z],
        [c.x, y0, c.z],
        [c.x, y1, c.z],
        [a.x, y1, a.z],
      ];
      const innerFace = [
        [c.x + ix, y0, c.z + iz],
        [a.x + ix, y0, a.z + iz],
        [a.x + ix, y1, a.z + iz],
        [c.x + ix, y1, c.z + iz],
      ];
      const top = [
        [a.x, y1, a.z],
        [c.x, y1, c.z],
        [c.x + ix, y1, c.z + iz],
        [a.x + ix, y1, a.z + iz],
      ];
      // Порядок вершин подобран так, чтобы лицевая сторона смотрела по нормали.
      const facing = (q: number[][], normal: number[]) => {
        const [p0, p1, p2] = q as [number[], number[], number[]];
        const ux = (p1[0] ?? 0) - (p0[0] ?? 0);
        const uy = (p1[1] ?? 0) - (p0[1] ?? 0);
        const uz = (p1[2] ?? 0) - (p0[2] ?? 0);
        const vx = (p2[0] ?? 0) - (p0[0] ?? 0);
        const vy = (p2[1] ?? 0) - (p0[1] ?? 0);
        const vz = (p2[2] ?? 0) - (p0[2] ?? 0);
        const [nx = 0, ny = 0, nz = 0] = normal;
        const dot = (uy * vz - uz * vy) * nx + (uz * vx - ux * vz) * ny + (ux * vy - uy * vx) * nz;
        quad(dot >= 0 ? q : [...q].reverse(), normal);
      };
      facing(outerFace, n);
      facing(innerFace, [-w.nx, 0, -w.nz]);
      facing(top, [0, 1, 0]);
    }
  }
  return geometryOf(p);
}

/** Материал модулей: цвет вершин, а там, где aAccent = 1, ещё и цвет экземпляра. */
export function moduleMaterial({
  roughness = 0.82,
  metalness = 0,
}: { roughness?: number; metalness?: number } = {}): THREE.MeshStandardMaterial {
  const m = new THREE.MeshStandardMaterial({ vertexColors: true, roughness, metalness });
  m.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nattribute float aAccent;')
      .replace(
        '#include <color_vertex>',
        `#if defined( USE_COLOR ) || defined( USE_INSTANCING_COLOR )
  vColor = vec4( 1.0 );
#endif
#ifdef USE_COLOR
  vColor.rgb *= color.rgb;
#endif
#ifdef USE_INSTANCING_COLOR
  vColor.rgb = mix( vColor.rgb, vColor.rgb * instanceColor.rgb, aAccent );
#endif`,
      );
  };
  m.customProgramCacheKey = () => 'green-facade-module';
  return m;
}

export function glassMaterial(): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({
    // Стекло лоджии отражает небо и соседние дома, а не чернеет дырой.
    color: 0x6a7884,
    roughness: 0.1,
    metalness: 0.1,
    envMapIntensity: 1.1,
  });
}

function matrixOf(m: Module, sx: number, sy: number, sz: number): THREE.Matrix4 {
  return new THREE.Matrix4().compose(
    new THREE.Vector3(m.x, m.y, m.z),
    new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), m.angle),
    new THREE.Vector3(sx, sy, sz),
  );
}

function instanced(
  geometry: THREE.BufferGeometry,
  material: THREE.Material,
  modules: readonly Module[],
  scale: (m: Module) => [number, number, number],
  name: string,
  accent: boolean,
): THREE.InstancedMesh {
  const mesh = new THREE.InstancedMesh(geometry, material, Math.max(1, modules.length));
  const color = new THREE.Color();
  modules.forEach((m, i) => {
    mesh.setMatrixAt(i, matrixOf(m, ...scale(m)));
    if (accent) mesh.setColorAt(i, color.setRGB(...linear(m.accent)));
  });
  mesh.count = modules.length;
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  mesh.name = name;
  mesh.computeBoundingSphere();
  return mesh;
}

/** Все модули фасадов улицы: несколько сеток экземпляров. */
export function facadeModules(
  buildings: readonly Building[],
  curbs: readonly Line[],
  { parapets: withParapets = true }: { parapets?: boolean } = {},
): THREE.Group {
  const loggias: Loggia[] = [];
  const entrances: Module[] = [];
  const roofs: Module[] = [];
  for (const b of buildings) {
    const plan = facadePlan(b, curbs);
    loggias.push(...plan.loggias);
    entrances.push(...plan.entrances);
    roofs.push(...plan.roofBoxes);
  }
  const group = new THREE.Group();
  group.name = 'facade-modules';
  const body = moduleMaterial();
  const glazed = loggias.filter((l) => l.glazed);
  const open = loggias.filter((l) => !l.glazed);
  const size = (m: Module): [number, number, number] => [m.width, m.height, m.depth];
  if (glazed.length) {
    group.add(instanced(loggiaGeometry(true), body, glazed, size, 'loggias-glazed', true));
    group.add(
      instanced(loggiaGlassGeometry(), glassMaterial(), glazed, size, 'loggia-glass', false),
    );
  }
  if (open.length)
    group.add(instanced(loggiaGeometry(false), body, open, size, 'loggias-open', true));
  if (entrances.length) {
    group.add(instanced(entranceGeometry(), body, entrances, () => [1, 1, 1], 'entrances', false));
  }
  if (roofs.length) {
    group.add(instanced(roofBoxGeometry(), body, roofs, size, 'roof-boxes', true));
  }
  const parapets = withParapets ? parapetGeometry(buildings) : null;
  if (parapets?.getAttribute('position').count) {
    const mesh = new THREE.Mesh(parapets, body);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.name = 'parapets';
    group.add(mesh);
  }
  return group;
}

export function disposeGroup(group: THREE.Group): void {
  const materials = new Set<THREE.Material>();
  group.traverse((o) => {
    if (!(o instanceof THREE.Mesh) && !(o instanceof THREE.LineSegments)) return;
    const mesh = o as THREE.Mesh;
    mesh.geometry.dispose();
    const m = mesh.material;
    for (const one of Array.isArray(m) ? m : [m]) materials.add(one);
    if (o instanceof THREE.InstancedMesh) o.dispose();
  });
  for (const m of materials) m.dispose();
}
