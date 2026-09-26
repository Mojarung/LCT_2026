/* Земля 3D-вида: газон, тротуарная плитка и асфальт там, где их понял сервис, а также
 * бортовой камень, ограды и опоры освещения с подосновы.
 *
 * Где грунт, а где покрытие, решает не 3D-вид: он берёт карту покрытий прогона (surface.png,
 * та же, по которой считались посадки) и поверх неё - полигоны газонов, тротуаров и проезжей
 * части с подосновы. Всё это рисуется в маску: R - газон, G - плитка, B - асфальт. Что
 * сервис не разметил, и всё за краем съёмки - газон, покрытие делится на тротуар и проезд
 * по ширине полосы (surfaceMask.ts). Шейдер земли смешивает по маске три фактуры, а шум
 * сбивает ступеньку растра на границе газона. */

import * as THREE from 'three';

import { ASPHALT, classifySurface, GRASS, PAVERS } from './surfaceMask';
import type { Flat, Line, Ring, World } from './types';

/** Метров на пиксель маски: борт шириной 15 см маска не рисует, его ставит геометрия. */
const MASK_M_PER_PX = 0.25;
const MASK_MAX_PX = 4096;
/** Земля продолжается за границу сцены, чтобы горизонт не обрывался краем плиты. */
export const GROUND_PAD_M = 3000;

export interface SurfaceImage {
  img: HTMLImageElement;
  /** Угол растра с минимальными x, y чертежа, метры. */
  origin: [number, number];
  cell: number;
  width: number;
  height: number;
}

export interface MaskInfo {
  texture: THREE.CanvasTexture;
  /** minX, minZ, sizeX, sizeZ в координатах сцены. */
  rect: [number, number, number, number];
}

function ringPath(
  ctx: CanvasRenderingContext2D,
  rings: Ring[],
  toPx: (p: Flat) => [number, number],
): void {
  ctx.beginPath();
  for (const ring of rings) {
    ring.forEach((p, i) => {
      const [x, y] = toPx(p);
      if (i) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
    });
    ctx.closePath();
  }
  ctx.fill('evenodd');
}

/** Покрытие каждого пикселя -> каналы маски: R - газон, G - плитка, B - асфальт. */
function surfaceToMask(ctx: CanvasRenderingContext2D, w: number, h: number, mpp: number): void {
  const img = ctx.getImageData(0, 0, w, h);
  const d = img.data;
  const kind = classifySurface(d, w, h, mpp);
  for (let i = 0; i < kind.length; i++) {
    const k = kind[i];
    d[i * 4] = k === GRASS ? 255 : 0;
    d[i * 4 + 1] = k === PAVERS ? 255 : 0;
    d[i * 4 + 2] = k === ASPHALT ? 255 : 0;
    d[i * 4 + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
}

/** Размыть растр карты покрытий на размер клетки: ступенька в метр читается сверху как
 *  пиксельная лесенка, а настоящая граница газона плавная. Полигоны подосновы рисуются
 *  после, чётко. */
function softenCells(c: HTMLCanvasElement, ctx: CanvasRenderingContext2D, cellPx: number): void {
  if (cellPx < 1.5) return;
  const copy = document.createElement('canvas');
  copy.width = c.width;
  copy.height = c.height;
  copy.getContext('2d')?.drawImage(c, 0, 0);
  ctx.save();
  ctx.filter = `blur(${(cellPx * 0.6).toFixed(1)}px)`;
  ctx.drawImage(copy, 0, 0);
  ctx.restore();
}

export function buildMask(world: World, surface: SurfaceImage | null): MaskInfo {
  const [minX, minZ, maxX, maxZ] = world.bounds;
  const sizeX = Math.max(1, maxX - minX);
  const sizeZ = Math.max(1, maxZ - minZ);
  const mpp = Math.max(MASK_M_PER_PX, Math.max(sizeX, sizeZ) / MASK_MAX_PX);
  const w = Math.ceil(sizeX / mpp);
  const h = Math.ceil(sizeZ / mpp);
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('Canvas 2D недоступен');
  // Карта покрытий полупрозрачная: рисуется на прозрачный холст, иначе её цвет смешается с
  // фоном и грунт перестанет отличаться от покрытия. Пустое после разбора - газон.
  ctx.clearRect(0, 0, w, h);
  if (surface) {
    // Строка 0 растра - минимальный Y чертежа, то есть наибольший z сцены: рисуем с
    // отражением по вертикали, от нижнего края вверх.
    const [ox, oy] = world.origin;
    const left = (surface.origin[0] - ox - minX) / mpp;
    const bottom = (-(surface.origin[1] - oy) - minZ) / mpp;
    ctx.save();
    ctx.imageSmoothingEnabled = false;
    ctx.translate(left, bottom);
    ctx.scale(
      (surface.cell / mpp) * (surface.width / surface.img.naturalWidth),
      -(surface.cell / mpp) * (surface.height / surface.img.naturalHeight),
    );
    ctx.drawImage(surface.img, 0, 0);
    ctx.restore();
  }
  surfaceToMask(ctx, w, h, mpp);
  if (surface) softenCells(c, ctx, surface.cell / mpp);
  const toPx = (p: Flat): [number, number] => [(p.x - minX) / mpp, (p.z - minZ) / mpp];
  ctx.fillStyle = '#0000ff';
  for (const rings of world.roads) ringPath(ctx, rings, toPx);
  ctx.fillStyle = '#00ff00';
  for (const rings of world.sidewalks) ringPath(ctx, rings, toPx);
  ctx.fillStyle = '#ff0000';
  for (const rings of world.lawns) ringPath(ctx, rings, toPx);
  const texture = new THREE.CanvasTexture(c);
  texture.flipY = false;
  texture.colorSpace = THREE.NoColorSpace;
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.minFilter = THREE.LinearMipmapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.needsUpdate = true;
  return { texture, rect: [minX, minZ, sizeX, sizeZ] };
}

export interface GroundTextures {
  grass: THREE.Texture;
  asphalt: THREE.Texture;
  pavers: THREE.Texture;
  noise: THREE.Texture;
}

/** Земля: один лист на всю сцену и поле вокруг, фактура по маске в шейдере. */
export function groundMesh(world: World, mask: MaskInfo, tex: GroundTextures): THREE.Mesh {
  const [minX, minZ, maxX, maxZ] = world.bounds;
  const cx = (minX + maxX) / 2;
  const cz = (minZ + maxZ) / 2;
  const size = Math.max(maxX - minX, maxZ - minZ) + GROUND_PAD_M * 2;
  const geometry = new THREE.PlaneGeometry(size, size, 1, 1);
  geometry.rotateX(-Math.PI / 2);
  geometry.translate(cx, 0, cz);
  const material = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    roughness: 0.92,
    metalness: 0,
  });
  const uniforms = {
    uMask: { value: mask.texture },
    uMaskRect: { value: new THREE.Vector4(...mask.rect) },
    uGrass: { value: tex.grass },
    uAsphalt: { value: tex.asphalt },
    uPavers: { value: tex.pavers },
    uNoise: { value: tex.noise },
  };
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vGroundPos;')
      .replace(
        '#include <worldpos_vertex>',
        '#include <worldpos_vertex>\nvGroundPos = (modelMatrix * vec4(transformed, 1.0)).xyz;',
      );
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>\n${GROUND_FRAGMENT_HEAD}`)
      .replace('#include <map_fragment>', GROUND_MAP)
      .replace('#include <roughnessmap_fragment>', GROUND_ROUGHNESS);
  };
  material.customProgramCacheKey = () => 'green-ground';
  const mesh = new THREE.Mesh(geometry, material);
  mesh.receiveShadow = true;
  mesh.name = 'ground';
  return mesh;
}

const GROUND_FRAGMENT_HEAD = /* glsl */ `
varying vec3 vGroundPos;
uniform sampler2D uMask;
uniform vec4 uMaskRect;
uniform sampler2D uGrass;
uniform sampler2D uAsphalt;
uniform sampler2D uPavers;
uniform sampler2D uNoise;
vec3 groundWeights;
float groundBreakup;

// Два масштаба одной фактуры со сдвигом: повтор плитки на газоне не читается глазом.
vec3 antiTile(sampler2D tex, vec2 p, float scale) {
  vec3 a = texture2D(tex, p / scale).rgb;
  vec3 b = texture2D(tex, p / (scale * 3.7) + vec2(0.37, 0.71)).rgb;
  float n = texture2D(uNoise, p / 90.0).r;
  return mix(a, b, smoothstep(0.35, 0.65, n) * 0.45);
}
`;

const GROUND_MAP = /* glsl */ `
{
  vec2 p = vGroundPos.xz;
  vec2 muv = (p - uMaskRect.xy) / uMaskRect.zw;
  vec3 m = texture2D(uMask, clamp(muv, 0.0, 1.0)).rgb;
  // За границей сцены данных нет: газон квартала, край уходит в дымку.
  float outside = step(0.0, muv.x) * step(muv.x, 1.0) * step(0.0, muv.y) * step(muv.y, 1.0);
  vec4 nz = texture2D(uNoise, p / 23.0);
  float edge = (nz.g - 0.5) * 0.5 + (texture2D(uNoise, p / 3.1).b - 0.5) * 0.35;
  float lawn = smoothstep(0.42, 0.58, m.r + edge);
  float paver = smoothstep(0.45, 0.55, m.g + edge * 0.3) * (1.0 - lawn);
  lawn = mix(1.0, lawn, outside);
  paver *= outside;
  float asph = clamp(1.0 - lawn - paver, 0.0, 1.0);
  groundWeights = vec3(lawn, paver, asph);
  // Крупные пятна - шумом в десятки метров, а не фактурой: повтор плитки фактуры сверху
  // читается рядами, пятна шума - нет.
  float macro = texture2D(uNoise, p / 173.0).r * 0.6 + texture2D(uNoise, p / 47.0).g * 0.4;
  vec3 g = antiTile(uGrass, p, 6.0);
  g *= mix(vec3(1.12, 1.0, 0.72), vec3(0.84, 0.97, 0.9), macro) * (0.8 + 0.26 * macro);
  // Дальнее поле за краем съёмки глуше: оно фон, а не газон участка.
  g = mix(g * vec3(0.86, 0.84, 0.8), g, outside);
  vec3 pv = texture2D(uPavers, p / 3.0).rgb * (0.9 + 0.16 * macro);
  vec3 a = antiTile(uAsphalt, p, 4.0) * (0.84 + 0.3 * macro);
  vec3 col = g * lawn + pv * paver + a * asph;
  diffuseColor.rgb *= col;
}
`;

const GROUND_ROUGHNESS = /* glsl */ `
float roughnessFactor = roughness * (groundWeights.x * 1.0 + groundWeights.y * 0.82 + groundWeights.z * 0.9);
`;

/** Бортовой камень: брус 15 x 15 см вдоль каждой линии борта. */
export const CURB_W = 0.15;
export const CURB_H = 0.15;

/** Сетка бруса вдоль ломаной: верх и две боковые грани, без дна. */
export function ribbonBox(
  lines: readonly Line[],
  width: number,
  height: number,
  lift = 0,
): THREE.BufferGeometry {
  const pos: number[] = [];
  const nor: number[] = [];
  const uv: number[] = [];
  const quad = (
    a: number[],
    b: number[],
    c: number[],
    d: number[],
    n: number[],
    u0: number,
    u1: number,
  ) => {
    pos.push(...a, ...b, ...c, ...a, ...c, ...d);
    for (let i = 0; i < 6; i++) nor.push(...n);
    uv.push(u0, 0, u1, 0, u1, 1, u0, 0, u1, 1, u0, 1);
  };
  for (const line of lines) {
    let along = 0;
    for (let i = 0; i + 1 < line.points.length; i++) {
      const p = line.points[i];
      const q = line.points[i + 1];
      if (!p || !q) continue;
      const dx = q.x - p.x;
      const dz = q.z - p.z;
      const len = Math.hypot(dx, dz);
      if (len < 0.01) continue;
      const nx = -dz / len;
      const nz = dx / len;
      const hw = width / 2;
      const y0 = lift;
      const y1 = lift + height;
      const l = [p.x + nx * hw, p.z + nz * hw, q.x + nx * hw, q.z + nz * hw];
      const r = [p.x - nx * hw, p.z - nz * hw, q.x - nx * hw, q.z - nz * hw];
      const u0 = along;
      const u1 = along + len;
      along = u1;
      // Верх, левая и правая грани.
      quad(
        [l[0] ?? 0, y1, l[1] ?? 0],
        [r[0] ?? 0, y1, r[1] ?? 0],
        [r[2] ?? 0, y1, r[3] ?? 0],
        [l[2] ?? 0, y1, l[3] ?? 0],
        [0, 1, 0],
        u0,
        u1,
      );
      quad(
        [l[0] ?? 0, y0, l[1] ?? 0],
        [l[0] ?? 0, y1, l[1] ?? 0],
        [l[2] ?? 0, y1, l[3] ?? 0],
        [l[2] ?? 0, y0, l[3] ?? 0],
        [nx, 0, nz],
        u0,
        u1,
      );
      quad(
        [r[2] ?? 0, y0, r[3] ?? 0],
        [r[2] ?? 0, y1, r[3] ?? 0],
        [r[0] ?? 0, y1, r[1] ?? 0],
        [r[0] ?? 0, y0, r[1] ?? 0],
        [-nx, 0, -nz],
        u1,
        u0,
      );
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.computeBoundingSphere();
  return g;
}

/** Ограда: вертикальная лента высотой height, решётка - прозрачностью текстуры. u - метры
 *  вдоль ограды, чтобы шаг прутьев не зависел от длины пролёта. */
export function fenceGeometry(
  lines: readonly Line[],
  height: number,
  barStepM: number,
): THREE.BufferGeometry {
  const pos: number[] = [];
  const nor: number[] = [];
  const uv: number[] = [];
  for (const line of lines) {
    let along = 0;
    for (let i = 0; i + 1 < line.points.length; i++) {
      const p = line.points[i];
      const q = line.points[i + 1];
      if (!p || !q) continue;
      const len = Math.hypot(q.x - p.x, q.z - p.z);
      if (len < 0.01) continue;
      const nx = -(q.z - p.z) / len;
      const nz = (q.x - p.x) / len;
      const u0 = along / barStepM;
      const u1 = (along + len) / barStepM;
      along += len;
      pos.push(
        p.x,
        0,
        p.z,
        q.x,
        0,
        q.z,
        q.x,
        height,
        q.z,
        p.x,
        0,
        p.z,
        q.x,
        height,
        q.z,
        p.x,
        height,
        p.z,
      );
      for (let k = 0; k < 6; k++) nor.push(nx, 0, nz);
      uv.push(u0, 0, u1, 0, u1, 1, u0, 0, u1, 1, u0, 1);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.computeBoundingSphere();
  return g;
}

/** Направление от опоры к ближайшему борту: консоль фонаря смотрит на проезжую часть. */
export function nearestCurbDirection(pole: Flat, curbs: readonly Line[], maxM = 25): number | null {
  let best = maxM;
  let angle: number | null = null;
  for (const line of curbs) {
    for (let i = 0; i + 1 < line.points.length; i++) {
      const a = line.points[i];
      const b = line.points[i + 1];
      if (!a || !b) continue;
      const vx = b.x - a.x;
      const vz = b.z - a.z;
      const len2 = vx * vx + vz * vz;
      const t =
        len2 > 0 ? Math.max(0, Math.min(1, ((pole.x - a.x) * vx + (pole.z - a.z) * vz) / len2)) : 0;
      const qx = a.x + vx * t;
      const qz = a.z + vz * t;
      const d = Math.hypot(qx - pole.x, qz - pole.z);
      if (d < best && d > 0.05) {
        best = d;
        angle = Math.atan2(qx - pole.x, qz - pole.z);
      }
    }
  }
  return angle;
}

/** Опора освещения: ствол 8 м, консоль 1,6 м и светильник. Модель смотрит консолью в +z. */
export function streetLightGeometry(): THREE.BufferGeometry {
  const parts: THREE.BufferGeometry[] = [];
  const mast = new THREE.CylinderGeometry(0.07, 0.12, 8, 10, 1);
  mast.translate(0, 4, 0);
  parts.push(mast);
  const base = new THREE.CylinderGeometry(0.18, 0.2, 0.6, 10, 1);
  base.translate(0, 0.3, 0);
  parts.push(base);
  const arm = new THREE.CylinderGeometry(0.035, 0.045, 1.7, 6, 1);
  arm.rotateX(Math.PI / 2 - 0.18);
  arm.translate(0, 7.95, 0.8);
  parts.push(arm);
  const head = new THREE.BoxGeometry(0.28, 0.12, 0.62);
  head.translate(0, 8.05, 1.65);
  parts.push(head);
  return mergeSimple(parts);
}

/** Слияние без индексов: у опоры пять частей, тянуть ради этого BufferGeometryUtils незачем. */
export function mergeSimple(parts: THREE.BufferGeometry[]): THREE.BufferGeometry {
  const pos: number[] = [];
  const nor: number[] = [];
  for (const part of parts) {
    const g = part.index ? part.toNonIndexed() : part;
    const p = g.getAttribute('position');
    const n = g.getAttribute('normal');
    for (let i = 0; i < p.count; i++) {
      pos.push(p.getX(i), p.getY(i), p.getZ(i));
      nor.push(n.getX(i), n.getY(i), n.getZ(i));
    }
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  out.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  out.computeBoundingSphere();
  return out;
}
