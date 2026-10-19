/* Здания 3D-вида: объём по контуру чертежа и высоте из scene.json, фасад рисуется шейдером.
 *
 * Стены строятся не ExtrudeGeometry: у неё развёртка стены идёт по проекции на ось x или z,
 * и на косой стене окна растягиваются. Здесь u - метры вдоль контура, v - метры от земли,
 * поэтому окно на любой стене одного размера, а этаж ровно 3 м, как у здания в чертеже.
 * Все здания сливаются в две сетки (стены и крыши): тысяча домов - два вызова отрисовки.
 *
 * Фасад процедурный: серия дома (facades.ts) по этажности и назначению задаёт рисунок -
 * панельная башня и пластина, пятиэтажка, кирпичный дом, павильон с витринами, ангар - и цвет
 * стены и акцента. Лоджии, подъезды и парапеты - объёмом (facadeModules.ts). Это не фотография
 * конкретного дома: съёмка Мосгеотреста фасадов не несёт, и выдавать догадку за точность
 * нельзя. */

import * as THREE from 'three';
import { bayOf, mainAxis, paletteOf, type Rgb, seriesOf, STYLE_OF } from './facades';
import { RELIEF_NORMAL } from './relief';

import type { Building, Flat, Ring } from './types';

/** Стиль фасада, номер уходит в шейдер атрибутом. */
export const STYLE = {
  panel: 0,
  brick: 1,
  pavilion: 2,
  metal: 3,
  porch: 4,
  khrushchev: 5,
} as const;
export type Style = (typeof STYLE)[keyof typeof STYLE];

export function styleOf(b: Building): Style {
  return STYLE_OF[seriesOf(b)] as Style;
}

function ringArea(ring: readonly Flat[]): number {
  let sum = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i];
    const b = ring[(i + 1) % ring.length];
    if (a && b) sum += a.x * b.z - b.x * a.z;
  }
  return sum / 2;
}

interface Buffers {
  pos: number[];
  nor: number[];
  uv: number[];
  info: number[];
  /** Цвет стены и акцента (ограждения лоджий, цоколь, вывеска), линейный. */
  colors: number[];
}

/** Атрибуты вершины дома: стиль, этажность, высота, разброс; цвет стены; цвет акцента; пролёт. */
type VertexInfo = [number[], number[]];

/** Стены одного кольца. Нормаль наружу: у внешнего контура и у двора обход противоположный,
 *  поэтому сторона выбирается по знаку площади кольца, а не по порядку в данных. */
function pushWalls(
  out: Buffers,
  ring: Ring,
  height: number,
  hole: boolean,
  [info, colors]: VertexInfo,
): void {
  // В координатах сцены (x, z) площадь > 0 - обход по часовой, если смотреть сверху.
  // У такого кольца внутренность справа по ходу, наружу - нормаль (dz, -dx); у двора наоборот.
  const clockwise = ringArea(ring) > 0;
  const outwardSign = clockwise !== hole ? 1 : -1;
  let along = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i];
    const b = ring[(i + 1) % ring.length];
    if (!a || !b) continue;
    const dx = b.x - a.x;
    const dz = b.z - a.z;
    const len = Math.hypot(dx, dz);
    if (len < 0.05) continue;
    const nx = (dz / len) * outwardSign;
    const nz = (-dx / len) * outwardSign;
    const u0 = along;
    const u1 = along + len;
    along = u1;
    // Лицевая сторона треугольника - обход против часовой, если смотреть с конца нормали.
    const quad: [Flat, number, number][] =
      outwardSign > 0
        ? [
            [a, u0, 0],
            [a, u0, height],
            [b, u1, height],
            [a, u0, 0],
            [b, u1, height],
            [b, u1, 0],
          ]
        : [
            [a, u0, 0],
            [b, u1, 0],
            [b, u1, height],
            [a, u0, 0],
            [b, u1, height],
            [a, u0, height],
          ];
    for (const [p, u, v] of quad) {
      // Низ стены - на 20 см под землёй: дом у опущенного проезда не висит над асфальтом.
      out.pos.push(p.x, v > 0 ? v : -0.2, p.z);
      out.nor.push(nx, 0, nz);
      out.uv.push(u, v);
      out.info.push(...info);
      out.colors.push(...colors);
    }
  }
}

function geometryOf(b: Buffers): THREE.BufferGeometry {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(b.pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(b.nor, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(b.uv, 2));
  g.setAttribute('aInfo', new THREE.Float32BufferAttribute(b.info, 4));
  // Семь чисел на вершину в двух атрибутах: больше четырёх в один WebGL не берёт.
  const wall: number[] = [];
  const accent: number[] = [];
  for (let i = 0; i + 6 < b.colors.length; i += 7) {
    wall.push(b.colors[i] ?? 0, b.colors[i + 1] ?? 0, b.colors[i + 2] ?? 0);
    accent.push(
      b.colors[i + 3] ?? 0,
      b.colors[i + 4] ?? 0,
      b.colors[i + 5] ?? 0,
      b.colors[i + 6] ?? 3,
    );
  }
  g.setAttribute('aWall', new THREE.Float32BufferAttribute(wall, 3));
  g.setAttribute('aAccent', new THREE.Float32BufferAttribute(accent, 4));
  g.computeBoundingSphere();
  return g;
}

/** Крыша: плоская, треугольники контура с дворами. */
function pushRoof(out: Buffers, b: Building, [info, colors]: VertexInfo): void {
  const [outer, ...holes] = b.rings;
  if (!outer || outer.length < 3) return;
  const contour = outer.map((p) => new THREE.Vector2(p.x, p.z));
  const holeVecs = holes
    .filter((h) => h.length >= 3)
    .map((h) => h.map((p) => new THREE.Vector2(p.x, p.z)));
  const all = [contour, ...holeVecs].flat();
  const faces = THREE.ShapeUtils.triangulateShape(contour, holeVecs);
  for (const face of faces) {
    // Треугольник смотрит вверх при обходе против часовой в (x, -z), иначе переворачиваем.
    const a = all[face[0] ?? 0];
    const c = all[face[1] ?? 0];
    const d = all[face[2] ?? 0];
    if (!a || !c || !d) continue;
    const cross = (c.x - a.x) * (d.y - a.y) - (c.y - a.y) * (d.x - a.x);
    const tri = cross > 0 ? [a, d, c] : [a, c, d];
    for (const p of tri) {
      out.pos.push(p.x, b.height, p.y);
      out.nor.push(0, 1, 0);
      out.uv.push(p.x, p.y);
      out.info.push(...info);
      out.colors.push(...colors);
    }
  }
}

export interface BuildingMeshes {
  walls: THREE.BufferGeometry;
  roofs: THREE.BufferGeometry;
}

function linear(rgb: Rgb): number[] {
  const c = new THREE.Color().setRGB(rgb[0], rgb[1], rgb[2], THREE.SRGBColorSpace);
  return [c.r, c.g, c.b];
}

/** Двускатная крыша - у малоэтажного жилого или кирпичного дома почти прямоугольного плана
 *  шириной 4-20 м: так выглядят частные и двухэтажные дома (идея и правило - ветка
 *  fix/final-wave1). Панельные, высокие и сложные по плану дома - с плоской крышей. */
export function pitchedRoof(b: Building): boolean {
  const [outer, ...holes] = b.rings;
  if (!outer || outer.length < 4 || holes.length || b.floors > 3 || b.kind !== 'building') {
    return false;
  }
  if (b.use !== 'residential' && b.wall !== 'brick') return false;
  const axis = mainAxis(outer);
  if (axis.width < 4 || axis.width > 20) return false;
  return Math.abs(ringArea(outer)) >= 0.85 * axis.length * axis.width;
}

/** Вальмовая крыша со срезанным верхом - у низкого (до 2 этажей) кирпичного или жилого дома
 *  сложного плана, которому не подошла двускатная: так накрыт дом 1А на Харьковской на
 *  панораме Яндекса (2023), а плоская крыша делала его коробкой. Скаты от стен к контуру,
 *  отступившему внутрь на HIP_INSET_M (меньше, если план узкий), с уклоном около 22°. */
const HIP_INSETS_M = [2.5, 2, 1.5, 1.2] as const;
const HIP_SLOPE = Math.tan((22 * Math.PI) / 180);

export function hipRoof(b: Building): { inset: Flat[]; rise: number } | null {
  const [outer, ...holes] = b.rings;
  if (!outer || outer.length < 4 || holes.length || b.kind !== 'building' || b.floors > 2) {
    return null;
  }
  if (b.use !== 'residential' && b.wall !== 'brick') return null;
  if (pitchedRoof(b)) return null;
  const ring = openRing(outer);
  for (const d of HIP_INSETS_M) {
    const inset = insetRing(ring, d);
    if (inset) return { inset, rise: d * HIP_SLOPE };
  }
  return null;
}

function openRing(ring: Ring): Flat[] {
  const first = ring[0];
  const last = ring[ring.length - 1];
  const closed = first && last && Math.hypot(first.x - last.x, first.z - last.z) < 1e-6;
  return closed ? ring.slice(0, -1) : [...ring];
}

/** Контур, отступивший внутрь на d (пересечение сдвинутых сторон). null - если стороны
 *  перевернулись или контур пересёк себя: план уже 2d в каком-то месте. */
export function insetRing(ring: readonly Flat[], d: number): Flat[] | null {
  const n = ring.length;
  if (n < 3) return null;
  const sign = ringArea(ring) > 0 ? 1 : -1;
  const lines = ring.map((a, i) => {
    const b = ring[(i + 1) % n] as Flat;
    const len = Math.hypot(b.x - a.x, b.z - a.z) || 1;
    const dx = (b.x - a.x) / len;
    const dz = (b.z - a.z) / len;
    // Нормаль внутрь: для обхода со знаком площади sign - поворот направления.
    const nx = -dz * sign;
    const nz = dx * sign;
    return { x: a.x + nx * d, z: a.z + nz * d, dx, dz };
  });
  const out: Flat[] = [];
  for (let i = 0; i < n; i++) {
    const p = lines[(i - 1 + n) % n];
    const q = lines[i];
    if (!p || !q) return null;
    const det = p.dx * q.dz - p.dz * q.dx;
    if (Math.abs(det) < 1e-9) {
      out.push({ x: q.x, z: q.z });
      continue;
    }
    const t = ((q.x - p.x) * q.dz - (q.z - p.z) * q.dx) / det;
    out.push({ x: p.x + p.dx * t, z: p.z + p.dz * t });
  }
  for (let i = 0; i < n; i++) {
    const a = out[i] as Flat;
    const b = out[(i + 1) % n] as Flat;
    const l = lines[i];
    if (!l || (b.x - a.x) * l.dx + (b.z - a.z) * l.dz <= 0) return null;
  }
  if (Math.sign(ringArea(out)) !== Math.sign(ringArea(ring))) return null;
  for (let i = 0; i < n; i++) {
    for (let j = i + 2; j < n; j++) {
      if (i === 0 && j === n - 1) continue;
      if (
        crosses(out[i] as Flat, out[(i + 1) % n] as Flat, out[j] as Flat, out[(j + 1) % n] as Flat)
      ) {
        return null;
      }
    }
  }
  return out;
}

function crosses(a: Flat, b: Flat, c: Flat, d: Flat): boolean {
  const o = (p: Flat, q: Flat, r: Flat) => (q.x - p.x) * (r.z - p.z) - (q.z - p.z) * (r.x - p.x);
  return o(c, d, a) * o(c, d, b) < 0 && o(a, b, c) * o(a, b, d) < 0;
}

/** Скаты вальмовой крыши: кольцо между стеной и отступившим контуром, верх - плоский. */
function pushHipRoof(
  out: Buffers,
  b: Building,
  hip: { inset: Flat[]; rise: number },
  vertex: VertexInfo,
): void {
  const ring = openRing(b.rings[0] ?? []);
  const contour = ring.map((p) => new THREE.Vector2(p.x, p.z));
  const hole = hip.inset.map((p) => new THREE.Vector2(p.x, p.z));
  const all = [...contour, ...hole];
  const top = b.height + hip.rise;
  const at = (i: number) => {
    const p = all[i] as THREE.Vector2;
    return new THREE.Vector3(p.x, i < contour.length ? b.height : top, p.y);
  };
  const roofUv = (q: THREE.Vector3): [number, number] => [q.x, q.z];
  for (const face of THREE.ShapeUtils.triangulateShape(contour, [hole])) {
    const [a, c, d] = face.map(at) as [THREE.Vector3, THREE.Vector3, THREE.Vector3];
    const n = new THREE.Vector3().subVectors(c, a).cross(new THREE.Vector3().subVectors(d, a));
    if (n.lengthSq() < 1e-12) continue;
    const up = n.y >= 0;
    pushTriangle(
      out,
      up ? [a, c, d] : [a, d, c],
      up ? n.normalize() : n.negate().normalize(),
      roofUv,
      vertex,
    );
  }
  for (const face of THREE.ShapeUtils.triangulateShape(hole, [])) {
    const [a, c, d] = face.map((i) => {
      const p = hole[i] as THREE.Vector2;
      return new THREE.Vector3(p.x, top, p.y);
    }) as [THREE.Vector3, THREE.Vector3, THREE.Vector3];
    const n = new THREE.Vector3().subVectors(c, a).cross(new THREE.Vector3().subVectors(d, a));
    pushTriangle(out, n.y >= 0 ? [a, c, d] : [a, d, c], new THREE.Vector3(0, 1, 0), roofUv, vertex);
  }
}

/** Свес кровли за стену и подъём конька: 0,3 ширины дома, 1,6-4,5 м. */
const EAVES_M = 0.35;
const RIDGE_SHARE = 0.3;

function pushTriangle(
  out: Buffers,
  points: readonly THREE.Vector3[],
  normal: THREE.Vector3,
  uv: (p: THREE.Vector3) => [number, number],
  [info, colors]: VertexInfo,
): void {
  for (const q of points) {
    out.pos.push(q.x, q.y, q.z);
    out.nor.push(normal.x, normal.y, normal.z);
    out.uv.push(...uv(q));
    out.info.push(...info);
    out.colors.push(...colors);
  }
}

/** Скаты - в сетку крыш, фронтоны - в сетку стен (без окон: выше последнего этажа).
 *
 *  Скаты лежат над контуром дома с карнизом EAVES_M, а не над описанным прямоугольником:
 *  у плана с выступами и западами прямоугольник накрывал пустое место у стены, сквозь такой
 *  навес проходил фонарный столб, а под ним было видно небо (дом 1А на Харьковской,
 *  пользователь 19.10.2026: «сквозь крышу проходит столб, а сама крыша прозрачная»). Высота
 *  ската - от расстояния до конька; стена под скатом поднимается до него (фронтон и стенки
 *  западов), щели между стеной и крышей нет. */
function pushGableRoof(roofs: Buffers, walls: Buffers, b: Building, vertex: VertexInfo): void {
  const outer = b.rings[0];
  if (!outer) return;
  const r = mainAxis(outer);
  const half = r.width / 2;
  const rise = Math.min(4.5, Math.max(1.6, RIDGE_SHARE * r.width));
  const vx = -r.dz;
  const vz = r.dx;
  const across = (p: Flat) => (p.x - r.cx) * vx + (p.z - r.cz) * vz;
  const heightAt = (p: Flat) => b.height + rise * (1 - Math.abs(across(p)) / half);
  const ring = openRing(outer);
  const eaves = insetRing(ring, -EAVES_M) ?? ring;
  const roofUv = (q: THREE.Vector3): [number, number] => [q.x, q.z];
  for (const side of [1, -1]) {
    const piece = clipAcross(eaves, across, side);
    if (piece.length < 3) continue;
    const contour = piece.map((p) => new THREE.Vector2(p.x, p.z));
    for (const face of THREE.ShapeUtils.triangulateShape(contour, [])) {
      const pts = face.map((i) => {
        const p = piece[i] as Flat;
        return new THREE.Vector3(p.x, heightAt(p), p.z);
      }) as [THREE.Vector3, THREE.Vector3, THREE.Vector3];
      const n = new THREE.Vector3()
        .subVectors(pts[1], pts[0])
        .cross(new THREE.Vector3().subVectors(pts[2], pts[0]));
      if (n.lengthSq() < 1e-12) continue;
      const up = n.y >= 0;
      pushTriangle(
        roofs,
        up ? pts : [pts[0], pts[2], pts[1]],
        up ? n.normalize() : n.negate().normalize(),
        roofUv,
        vertex,
      );
    }
  }
  // Стена под скатом - до ската: на отрезке, пересекающем конёк, излом в точке конька.
  const sign = ringArea(ring) > 0 ? 1 : -1;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i] as Flat;
    const c = ring[(i + 1) % ring.length] as Flat;
    const len = Math.hypot(c.x - a.x, c.z - a.z);
    if (len < 0.05) continue;
    const outward = new THREE.Vector3(((c.z - a.z) / len) * sign, 0, (-(c.x - a.x) / len) * sign);
    const ta = across(a);
    const tc = across(c);
    const points: Flat[] = [a];
    if (ta * tc < 0) {
      const k = ta / (ta - tc);
      points.push({ x: a.x + (c.x - a.x) * k, z: a.z + (c.z - a.z) * k });
    }
    points.push(c);
    for (let j = 0; j + 1 < points.length; j++) {
      const p = points[j] as Flat;
      const q = points[j + 1] as Flat;
      const hp = heightAt(p);
      const hq = heightAt(q);
      if (hp <= b.height + 0.01 && hq <= b.height + 0.01) continue;
      const p0 = new THREE.Vector3(p.x, b.height, p.z);
      const q0 = new THREE.Vector3(q.x, b.height, q.z);
      const p1 = new THREE.Vector3(p.x, Math.max(hp, b.height), p.z);
      const q1 = new THREE.Vector3(q.x, Math.max(hq, b.height), q.z);
      // Развёртка: v выше высоты дома, поэтому шейдер не рисует на фронтоне окна.
      const uv = (v: THREE.Vector3): [number, number] => [v.x * r.dz - v.z * r.dx, v.y];
      for (const tri of [
        [p0, q0, q1],
        [p0, q1, p1],
      ] as const) {
        const n = new THREE.Vector3()
          .subVectors(tri[1], tri[0])
          .cross(new THREE.Vector3().subVectors(tri[2], tri[0]));
        if (n.lengthSq() < 1e-12) continue;
        pushTriangle(
          walls,
          n.dot(outward) >= 0 ? tri : [tri[0], tri[2], tri[1]],
          outward,
          uv,
          vertex,
        );
      }
    }
  }
}

/** Часть многоугольника по одну сторону конька (side - знак across), отсечение полуплоскостью. */
function clipAcross(ring: readonly Flat[], across: (p: Flat) => number, side: number): Flat[] {
  const out: Flat[] = [];
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i] as Flat;
    const c = ring[(i + 1) % ring.length] as Flat;
    const ta = across(a) * side;
    const tc = across(c) * side;
    if (ta >= 0) out.push(a);
    if (ta * tc < 0) {
      const k = ta / (ta - tc);
      out.push({ x: a.x + (c.x - a.x) * k, z: a.z + (c.z - a.z) * k });
    }
  }
  return out;
}

export function buildingGeometry(buildings: readonly Building[]): BuildingMeshes {
  const walls: Buffers = { pos: [], nor: [], uv: [], info: [], colors: [] };
  const roofs: Buffers = { pos: [], nor: [], uv: [], info: [], colors: [] };
  for (const b of buildings) {
    const series = seriesOf(b);
    const palette = paletteOf(b, series);
    // info: стиль, этажей, высота, разброс 0..1; colors: стена, акцент, пролёт.
    const vertex: VertexInfo = [
      [STYLE_OF[series], Math.max(1, b.floors), b.height, (b.seed % 997) / 997],
      [...linear(palette.wall), ...linear(palette.accent), bayOf(series)],
    ];
    b.rings.forEach((ring, i) => {
      if (ring.length >= 3) pushWalls(walls, ring, b.height, i > 0, vertex);
    });
    const hip = pitchedRoof(b) ? null : hipRoof(b);
    if (pitchedRoof(b)) pushGableRoof(roofs, walls, b, vertex);
    else if (hip) pushHipRoof(roofs, b, hip, vertex);
    else pushRoof(roofs, b, vertex);
  }
  return { walls: geometryOf(walls), roofs: geometryOf(roofs) };
}

export interface FacadeUniforms {
  uNight: { value: number };
  uNoise: { value: THREE.Texture };
}

/** Материал стен: рисунок окон по этажам, остекление блестит небом, ночью горят окна. */
export function facadeMaterial(uniforms: FacadeUniforms): THREE.MeshStandardMaterial {
  const m = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.85, metalness: 0 });
  m.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace(
        '#include <common>',
        '#include <common>\nattribute vec4 aInfo;\nattribute vec3 aWall;\nattribute vec4 aAccent;\n' +
          'varying vec4 vInfo;\nvarying vec3 vWall;\nvarying vec4 vAccent;\nvarying vec2 vFacade;',
      )
      .replace(
        '#include <uv_vertex>',
        '#include <uv_vertex>\nvInfo = aInfo;\nvWall = aWall;\nvAccent = aAccent;\nvFacade = uv;',
      );
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>\n${FACADE_HEAD}\n${RELIEF_NORMAL}`)
      .replace('#include <map_fragment>', FACADE_MAP)
      .replace(
        '#include <normal_fragment_maps>',
        '#include <normal_fragment_maps>\nnormal = reliefNormal(-vViewPosition, normal, facadeRelief);',
      )
      .replace('#include <roughnessmap_fragment>', 'float roughnessFactor = facadeRough;')
      .replace('#include <metalnessmap_fragment>', 'float metalnessFactor = facadeMetal;')
      .replace(
        '#include <emissivemap_fragment>',
        '#include <emissivemap_fragment>\ntotalEmissiveRadiance += facadeGlow;',
      );
  };
  m.customProgramCacheKey = () => 'green-facade';
  return m;
}

const FACADE_HEAD = /* glsl */ `
varying vec4 vInfo;
varying vec3 vWall;
varying vec4 vAccent;
varying vec2 vFacade;
uniform float uNight;
uniform sampler2D uNoise;
float facadeRough;
float facadeMetal;
float facadeRelief;
vec3 facadeGlow;

float hash12(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}
`;

/* Окно: прямоугольник в ячейке «пролёт x этаж», рама темнее стены, стекло - почти зеркало
 * с тёмно-синим тоном. Первый этаж павильона - витрина во всю ширину. Кирпич - рядами 25 x
 * 7,5 см, различимыми только вблизи, издалека стена одного тона. */
const FACADE_MAP = /* glsl */ `
{
  int style = int(vInfo.x + 0.5);
  float floors = vInfo.y;
  float height = vInfo.z;
  float tint = vInfo.w;
  float u = vFacade.x;
  float v = vFacade.y;
  float storey = floors <= 1.0 ? height : (height - 1.2) / floors;
  float plinth = floors <= 1.0 ? 0.0 : 0.9;
  float fv = (v - plinth) / storey;
  float level = floor(fv);
  float lv = fract(fv);
  float bay = vAccent.w;
  float cell = floor(u / bay);
  float lu = fract(u / bay);
  vec3 wall = vWall;
  vec3 accent = vAccent.rgb;
  float grime = texture2D(uNoise, vec2(u, v) / 37.0).r;
  wall *= 0.9 + 0.16 * grime;
  bool panel = style == 0 || style == 5;
  if (panel) {
    // Панели темнеют неравномерно; швы - по перекрытиям и стыкам панелей.
    float sw = style == 0 ? bay * 2.0 : bay;
    wall *= 0.95 + 0.07 * hash12(vec2(floor(u / sw), level) + tint * 5.0);
    vec2 aa2 = max(fwidth(vec2(u / sw, lv)), vec2(0.0001));
    float fu = fract(u / sw);
    float seamV = 1.0 - smoothstep(0.0, aa2.x * 1.5, min(fu, 1.0 - fu));
    float seamH = 1.0 - smoothstep(0.0, aa2.y * 1.5, min(lv, 1.0 - lv));
    wall *= 1.0 - 0.16 * max(seamV, seamH);
  }
  if (style == 1) {
    float row = floor(v / 0.075);
    float brick = step(0.08, fract(v / 0.075)) * step(0.04, fract(u / 0.25 + mod(row, 2.0) * 0.5));
    wall *= mix(0.8, 1.0, brick) * (0.94 + 0.12 * hash12(vec2(floor(u / 0.25), row)));
  }
  if (style == 3) {
    wall *= 0.88 + 0.12 * step(0.5, fract(u / 0.2));
  }
  // Цоколь - плитка цвета акцента, темнее стены, как синий цоколь панельных домов.
  if (style != 2 && style != 4 && floors > 1.0 && v < plinth) {
    wall = mix(accent, vec3(0.32), 0.35) * (0.7 + 0.12 * grime);
  }
  // Павильон: над витриной - полоса вывески цвета акцента.
  if (style == 2 && level < 1.0 && lv > 0.8) wall = accent * (0.85 + 0.1 * grime);
  float glass = 0.0;
  float reveal = 0.0;
  float mullion = 0.0;
  bool facade = style != 4 && v > plinth && level < floors;
  if (facade) {
    // Окно в ячейке: у панельного дома широкое окно комнаты чередуется с узким кухонным.
    vec2 size = vec2(0.46, 0.52);
    float cy = 0.52;
    if (style == 0) size = vec2(mod(cell, 2.0) < 1.0 ? 0.56 : 0.42, 0.5);
    if (style == 5) size = vec2(0.46, 0.5);
    if (style == 2) {
      size = level < 1.0 ? vec2(0.92, 0.62) : vec2(0.92, 0.42);
      cy = level < 1.0 ? 0.42 : 0.55;
    }
    if (style == 3) size = vec2(0.0);
    vec2 d = abs(vec2(lu, lv) - vec2(0.5, cy));
    float frame = step(d.x, size.x * 0.5 + 0.035) * step(d.y, size.y * 0.5 + 0.035);
    vec2 aa = max(fwidth(vec2(lu, lv)), vec2(0.0001));
    vec2 pane = 1.0 - smoothstep(size * 0.5 - aa, size * 0.5 + aa, d);
    glass = pane.x * pane.y;
    // A shallow recess and slim crossbars give windows depth without extra meshes.
    reveal = frame;
    mullion = (1.0 - smoothstep(0.006, 0.006 + aa.x, abs(lu - 0.5))) * glass;
    mullion = max(mullion, (1.0 - smoothstep(0.007, 0.007 + aa.y, abs(lv - cy - 0.12))) * glass);
    // Рамы жилых домов - белый пластик, у павильона - тёмный алюминий.
    vec3 frameColor = style == 2 ? vec3(0.17, 0.18, 0.18) : vec3(0.78, 0.78, 0.76);
    wall = mix(wall, frameColor, clamp(frame - glass + mullion, 0.0, 1.0));
    glass *= 1.0 - mullion;
  }
  // Горит примерно каждое второе окно, у каждого своя яркость и оттенок лампы; витрина
  // первого этажа ночью не светится сплошь - магазины к ночи закрыты.
  float roll = hash12(vec2(cell, level) + tint * 17.0);
  float shop = style == 2 && level < 1.0 ? 0.35 : 1.0;
  float lit = step(0.5, roll) * glass * uNight * shop * (0.35 + 0.65 * hash12(vec2(level, cell) * 1.3));
  vec3 glassColor = mix(vec3(0.09, 0.11, 0.13), vec3(0.22, 0.25, 0.29), hash12(vec2(cell * 1.7, level)));
  // Recess shadows and varied blinds stay attached to each window, at every angle.
  float blind = step(0.7, roll) * smoothstep(0.57, 0.59, lv) * (1.0 - uNight);
  glassColor = mix(glassColor, vec3(0.36, 0.34, 0.29), blind * 0.65);
  float revealShade = smoothstep(0.24, 0.32, lv) * (1.0 - smoothstep(0.71, 0.79, lv));
  glassColor *= mix(0.55, 1.0, revealShade);
  facadeRelief = -0.035 * reveal + 0.012 * mullion;
  // Парапет: верхние 40 см стены без окон и чуть темнее, как жесть отлива.
  if (v > height - 0.4 && style != 4) wall *= 0.72;
  diffuseColor.rgb *= mix(wall, glassColor, glass);
  facadeRough = mix(0.88, 0.06, glass);
  facadeMetal = style == 3 ? 0.35 * (1.0 - glass) : 0.0;
  facadeGlow = mix(vec3(1.0, 0.72, 0.42), vec3(0.95, 0.9, 0.8), fract(roll * 7.0)) * lit * 0.9;
}
`;

/** Крыша: битум, тёмный и шершавый. Отдельный материал проще, чем ветвление в фасаде. */
export function roofMaterial(
  noise: THREE.Texture,
  snow: { value: number },
): THREE.MeshStandardMaterial {
  // Двусторонняя: снизу виден карниз, а не небо сквозь скат.
  const m = new THREE.MeshStandardMaterial({
    color: 0x3a3a3c,
    roughness: 0.95,
    metalness: 0,
    side: THREE.DoubleSide,
  });
  m.onBeforeCompile = (shader) => {
    shader.uniforms.uNoise = { value: noise };
    shader.uniforms.uSnow = snow;
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec2 vRoof;')
      .replace('#include <uv_vertex>', '#include <uv_vertex>\nvRoof = uv;');
    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        '#include <common>\nvarying vec2 vRoof;\nuniform sampler2D uNoise;\nuniform float uSnow;',
      )
      .replace(
        '#include <map_fragment>',
        'diffuseColor.rgb *= 0.8 + 0.35 * texture2D(uNoise, vRoof / 13.0).r;\n' +
          // Плоская крыша под снегом белая целиком, только у парапета темнее.
          'diffuseColor.rgb = mix(diffuseColor.rgb, vec3(2.4), clamp(uSnow * 1.2, 0.0, 1.0));',
      );
  };
  m.customProgramCacheKey = () => 'green-roof';
  return m;
}
