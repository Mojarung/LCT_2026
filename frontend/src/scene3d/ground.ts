/* Земля 3D-вида: газон, тротуарная плитка и асфальт там, где их понял сервис, а также
 * бортовой камень, ограды и опоры освещения с подосновы.
 *
 * Где грунт, а где покрытие, решает не 3D-вид: он берёт карту покрытий прогона (surface.png,
 * та же, по которой считались посадки) и поверх неё - полигоны газонов, тротуаров и проезжей
 * части с подосновы. Всё это рисуется в маску: R - газон, G - плитка, B - асфальт. Что
 * сервис не разметил, и всё за краем съёмки - газон, покрытие делится на тротуар и проезд
 * по ширине полосы (surfaceMask.ts). Шейдер земли смешивает по маске три фактуры с ровным
 * порогом. Карта покрытий приходит контурами (surface.json, areas): край проезда и газона -
 * прямая, а не лесенка клеток; у старых прогонов без контуров растр размывается на клетку. */

import * as THREE from 'three';

import {
  ASPHALT_RGB,
  classifySurface,
  EMPTY,
  GRASS,
  PAVED_RGB,
  PAVERS,
  PAVERS_RGB,
  ROAD,
  ROAD_RGB,
  SOIL_RGB,
} from './surfaceMask';
import type { Flat, Line, Ring, World } from './types';

/** Метров на пиксель маски: борт шириной 15 см маска не рисует, его ставит геометрия. */
const MASK_M_PER_PX = 0.25;
const MASK_MAX_PX = 4096;
/** Размытие маски у контуров, пикселей (softenCells берёт 0,9 от него). */
const CONTOUR_SOFTEN_PX = 1.6;
/** Земля продолжается за границу сцены, чтобы горизонт не обрывался краем плиты. */
export const GROUND_PAD_M = 3000;

/** Полигон - кольца в координатах чертежа: внешнее, затем дыры. */
export type AreaPolygon = number[][][];

/** Контуры карты покрытий: грунт и поверх него покрытие (surface.json, areas). */
export interface SurfaceAreas {
  soil: AreaPolygon[];
  paved: AreaPolygon[];
  /** Вид каждой части покрытия: road - проезжая часть, asphalt, pavers, paved - неизвестно. */
  paved_kind?: string[];
  /** Проезжая часть с запасом под край тротуара: сетка асфальта ниже уровня земли. */
  road_mesh?: AreaPolygon[];
}

/** Проезжая часть ниже тротуара и газона на высоту дорожного борта. */
export const ROAD_DROP_M = 0.15;

export interface SurfaceImage {
  img: HTMLImageElement;
  /** Угол растра с минимальными x, y чертежа, метры. */
  origin: [number, number];
  cell: number;
  width: number;
  height: number;
  areas?: SurfaceAreas | null;
}

const rgb = ([r, g, b]: readonly [number, number, number]) => `rgb(${r}, ${g}, ${b})`;
/** Цвета контуров без прозрачности: classifySurface читает вид покрытия по цвету. */
const SOIL_FILL = rgb(SOIL_RGB);
const PAVED_FILLS: Record<string, string> = {
  road: rgb(ROAD_RGB),
  asphalt: rgb(ASPHALT_RGB),
  pavers: rgb(PAVERS_RGB),
};
const PAVED_FILL = rgb(PAVED_RGB);

/** Кольца полигонов чертежа в пикселях маски: x сцены = X - начало, z сцены = -(Y - начало). */
export function areaRings(
  polygons: AreaPolygon[],
  origin: [number, number],
  minX: number,
  minZ: number,
  mpp: number,
): [number, number][][][] {
  const [ox, oy] = origin;
  return polygons.map((rings) =>
    rings.map((ring) =>
      ring.map(([x = 0, y = 0]): [number, number] => [
        (x - ox - minX) / mpp,
        (-(y - oy) - minZ) / mpp,
      ]),
    ),
  );
}

function tracePolygon(ctx: CanvasRenderingContext2D, rings: [number, number][][]): void {
  ctx.beginPath();
  for (const ring of rings) {
    ring.forEach(([x, y], i) => {
      if (i) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
    });
    ctx.closePath();
  }
}

/** Бортовой камень по краям покрытия (пользователь, 17.10.2026): кольца контуров покрытия
 *  линиями в координатах сцены, только отрезки, где edge подтверждает газон по одну сторону:
 *  шов между тротуаром и проездом бортом не обводится, линии бортов чертежа идут отдельно
 *  (world.curbs). */
export function areaCurbs(
  areas: SurfaceAreas,
  origin: [number, number],
  edge: (a: Flat, b: Flat) => boolean = () => true,
): Line[] {
  const [ox, oy] = origin;
  const lines: Line[] = [];
  for (const rings of areas.paved) {
    for (const ring of rings) {
      const pts = ring.map(([x = 0, y = 0]): Flat => ({ x: x - ox, z: oy - y }));
      const n = pts.length - 1; // кольцо замкнуто: последняя точка - первая
      if (n < 2) continue;
      const keep = Array.from({ length: n }, (_, i) => edge(pts[i] as Flat, pts[i + 1] as Flat));
      if (keep.every(Boolean)) {
        lines.push({ points: pts });
        continue;
      }
      // Обход с отрезка без борта: бортовые отрезки по обе стороны начала кольца - одна линия.
      const start = keep.indexOf(false);
      let run: Flat[] = [];
      for (let k = 1; k <= n; k++) {
        const i = (start + k) % n;
        if (keep[i]) {
          if (!run.length) run.push(pts[i] as Flat);
          run.push(pts[i + 1] as Flat);
        } else if (run.length) {
          lines.push({ points: run });
          run = [];
        }
      }
      if (run.length) lines.push({ points: run });
    }
  }
  return lines;
}

/** Отрезок - граница двух покрытий: по одну его сторону покрытие вида a, по другую - вида b
 *  (маска после деления на газон, плитку и асфальт). Вне маски - газон. */
export function edgeBetween(
  mask: MaskInfo,
  isA: (kind: number) => boolean,
  isB: (kind: number) => boolean,
  offsetM = 0.4,
): (a: Flat, b: Flat) => boolean {
  const [minX, minZ] = mask.rect;
  const kindAt = (x: number, z: number): number => {
    const col = Math.floor((x - minX) / mask.metresPerPx);
    const row = Math.floor((z - minZ) / mask.metresPerPx);
    if (col < 0 || row < 0 || col >= mask.width || row >= mask.height) return EMPTY;
    return mask.kinds[row * mask.width + col] ?? EMPTY;
  };
  return (a, b) => {
    const dx = b.x - a.x;
    const dz = b.z - a.z;
    const len = Math.hypot(dx, dz);
    if (!len) return false;
    const nx = (-dz / len) * offsetM;
    const nz = (dx / len) * offsetM;
    const mx = (a.x + b.x) / 2;
    const mz = (a.z + b.z) / 2;
    const left = kindAt(mx + nx, mz + nz);
    const right = kindAt(mx - nx, mz - nz);
    return (isA(left) && isB(right)) || (isA(right) && isB(left));
  };
}

/** Контуры карты покрытий вместо её растра: грунт и поверх него покрытие, как в растре. */
export function drawSurfaceAreas(
  ctx: CanvasRenderingContext2D,
  areas: SurfaceAreas,
  origin: [number, number],
  minX: number,
  minZ: number,
  mpp: number,
): void {
  const soil = areaRings(areas.soil, origin, minX, minZ, mpp);
  const paved = areaRings(areas.paved, origin, minX, minZ, mpp);
  const groups = new Map<string, [number, number][][][]>();
  if (soil.length) groups.set(SOIL_FILL, soil);
  paved.forEach((rings, i) => {
    const color = PAVED_FILLS[areas.paved_kind?.[i] ?? ''] ?? PAVED_FILL;
    groups.set(color, [...(groups.get(color) ?? []), rings]);
  });
  for (const [color, polygons] of groups) {
    ctx.fillStyle = color;
    for (const rings of polygons) {
      tracePolygon(ctx, rings);
      ctx.fill('evenodd');
    }
  }
}

/** Сетка проезжей части из контура road_mesh: на ROAD_DROP_M ниже земли, в координатах сцены. */
export function roadGeometry(
  polygons: AreaPolygon[],
  origin: [number, number],
): THREE.BufferGeometry | null {
  const [ox, oy] = origin;
  const shapes = polygons
    .filter((rings) => (rings[0]?.length ?? 0) > 3)
    .map((rings) => {
      const toVec = (ring: number[][]) =>
        ring.map(([x = 0, y = 0]) => new THREE.Vector2(x - ox, y - oy));
      const shape = new THREE.Shape(toVec(rings[0] ?? []));
      shape.holes = rings.slice(1).map((ring) => new THREE.Path(toVec(ring)));
      return shape;
    });
  if (!shapes.length) return null;
  const geometry = new THREE.ShapeGeometry(shapes);
  geometry.rotateX(-Math.PI / 2);
  geometry.translate(0, -ROAD_DROP_M, 0);
  return geometry;
}

export interface MaskInfo {
  texture: THREE.CanvasTexture;
  /** minX, minZ, sizeX, sizeZ в координатах сцены. */
  rect: [number, number, number, number];
  /** Покрытие каждого пикселя (surfaceMask.ts) до размытия: по нему расставляются люди. */
  kinds: Uint8Array;
  width: number;
  height: number;
  metresPerPx: number;
}

/** Погода на земле: мокрый асфальт темнеет и блестит, снег ложится сначала на газон. */
export interface GroundWeather {
  uWet: { value: number };
  uSnow: { value: number };
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
function surfaceToMask(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  mpp: number,
  minAlpha: number,
): Uint8Array {
  const img = ctx.getImageData(0, 0, w, h);
  const d = img.data;
  const kind = classifySurface(d, w, h, mpp, minAlpha);
  for (let i = 0; i < kind.length; i++) {
    const k = kind[i];
    // R - газон (и пустое), G - плитка, B - проезжая часть: её землю шейдер вырезает, под ней
    // лежит сетка проезда ниже на высоту борта. Асфальт тротуара - где нет ни одного канала.
    d[i * 4] = k === GRASS || k === EMPTY ? 255 : 0;
    d[i * 4 + 1] = k === PAVERS ? 255 : 0;
    d[i * 4 + 2] = k === ROAD ? 255 : 0;
    d[i * 4 + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  return kind;
}

/** Размыть растр карты покрытий на размер клетки: ступенька в метр читается сверху как
 *  пиксельная лесенка, а у размытой на клетку лесенки порог 0,5 идёт почти прямой. Полигоны
 *  подосновы рисуются после, чётко. */
function softenCells(c: HTMLCanvasElement, ctx: CanvasRenderingContext2D, cellPx: number): void {
  if (cellPx < 1.5) return;
  const copy = document.createElement('canvas');
  copy.width = c.width;
  copy.height = c.height;
  copy.getContext('2d')?.drawImage(c, 0, 0);
  ctx.save();
  ctx.filter = `blur(${(cellPx * 0.9).toFixed(1)}px)`;
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
  // Контуры карты покрытий (surface.json, areas) - прямые края без лесенки клеток; растр - для
  // прогонов, сделанных до них.
  const areas = surface?.areas;
  if (surface && areas) {
    drawSurfaceAreas(ctx, areas, world.origin, minX, minZ, mpp);
  } else if (surface) {
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
  // Контур залит непрозрачно, его край - доля покрытия пикселя: покрытием считается пиксель,
  // покрытый наполовину. С порогом «любой непустой» асфальт вылезал за край на пиксель маски
  // (до 0,4 м) - за бортовой камень. Растр старых прогонов полупрозрачный: порог - непустой.
  const kinds = surfaceToMask(ctx, w, h, mpp, areas ? 128 : 1);
  // Край контура на пикселе маски (у большой сцены до 0,4 м) - лесенка; лёгкое размытие
  // выравнивает порог шейдера. У растра без контуров - размытие на клетку.
  if (surface) softenCells(c, ctx, areas ? CONTOUR_SOFTEN_PX : surface.cell / mpp);
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
  return {
    texture,
    rect: [minX, minZ, sizeX, sizeZ],
    kinds,
    width: w,
    height: h,
    metresPerPx: mpp,
  };
}

export interface GroundTextures {
  grass: THREE.Texture;
  asphalt: THREE.Texture;
  pavers: THREE.Texture;
  noise: THREE.Texture;
  grassNormalMap?: THREE.Texture;
  asphaltNormalMap?: THREE.Texture;
  paversNormalMap?: THREE.Texture;
  grassArmMap?: THREE.Texture;
  asphaltArmMap?: THREE.Texture;
  paversArmMap?: THREE.Texture;
}

/** Земля: один лист на всю сцену и поле вокруг, фактура по маске в шейдере. */
export function groundMesh(
  world: World,
  mask: MaskInfo,
  tex: GroundTextures,
  weather: GroundWeather,
  options: { geometry?: THREE.BufferGeometry; cutRoad?: boolean; name?: string } = {},
): THREE.Mesh {
  const [minX, minZ, maxX, maxZ] = world.bounds;
  const cx = (minX + maxX) / 2;
  const cz = (minZ + maxZ) / 2;
  const size = Math.max(maxX - minX, maxZ - minZ) + GROUND_PAD_M * 2;
  let geometry = options.geometry;
  if (!geometry) {
    geometry = new THREE.PlaneGeometry(size, size, 1, 1);
    geometry.rotateX(-Math.PI / 2);
    geometry.translate(cx, 0, cz);
  }
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
    uPbr: {
      value: new THREE.Vector3(
        Number(!!tex.grassNormalMap && !!tex.grassArmMap),
        Number(!!tex.paversNormalMap && !!tex.paversArmMap),
        Number(!!tex.asphaltNormalMap && !!tex.asphaltArmMap),
      ),
    },
    uGrassNormal: { value: tex.grassNormalMap ?? tex.noise },
    uAsphaltNormal: { value: tex.asphaltNormalMap ?? tex.noise },
    uPaversNormal: { value: tex.paversNormalMap ?? tex.noise },
    uGrassArm: { value: tex.grassArmMap ?? tex.noise },
    uAsphaltArm: { value: tex.asphaltArmMap ?? tex.noise },
    uPaversArm: { value: tex.paversArmMap ?? tex.noise },
    // Земля на уровне тротуара вырезает проезжую часть: там видна сетка проезда ниже.
    uCutRoad: { value: options.cutRoad ? 1 : 0 },
    ...weather,
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
      .replace('#include <roughnessmap_fragment>', GROUND_ROUGHNESS)
      .replace('#include <normal_fragment_maps>', GROUND_NORMAL);
  };
  material.customProgramCacheKey = () => 'green-ground';
  const mesh = new THREE.Mesh(geometry, material);
  mesh.receiveShadow = true;
  mesh.name = options.name ?? 'ground';
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
uniform vec3 uPbr;
uniform sampler2D uGrassNormal;
uniform sampler2D uAsphaltNormal;
uniform sampler2D uPaversNormal;
uniform sampler2D uGrassArm;
uniform sampler2D uAsphaltArm;
uniform sampler2D uPaversArm;
uniform float uWet;
uniform float uSnow;
uniform float uCutRoad;
vec3 groundWeights;
float groundSnow;
float groundWet;
vec3 groundArm;

// Smoothly blend hashed texture offsets: patches no longer repeat in a visible grid.
vec3 antiTile(sampler2D tex, vec2 p, float scale) {
  float n = texture2D(uNoise, p / 90.0).r * 8.0;
  float cell = floor(n);
  vec2 a = sin(vec2(3.0, 7.0) * (cell + 1.0)) * 17.0;
  vec2 b = sin(vec2(3.0, 7.0) * (cell + 2.0)) * 17.0;
  return mix(texture2D(tex, p / scale + a).rgb,
             texture2D(tex, p / scale + b).rgb, smoothstep(0.2, 0.8, fract(n)));
}
`;

export const GROUND_MAP = /* glsl */ `
{
  vec2 p = vGroundPos.xz;
  vec2 muv = (p - uMaskRect.xy) / uMaskRect.zw;
  vec3 m = texture2D(uMask, clamp(muv, 0.0, 1.0)).rgb;
  // За границей сцены данных нет: газон квартала, край уходит в дымку.
  float outside = step(0.0, muv.x) * step(muv.x, 1.0) * step(0.0, muv.y) * step(muv.y, 1.0);
  // Порог выше середины: вырез чуть уже проезда, край земли уходит под борт, а не открывает
  // щель между бортом и тротуаром.
  if (uCutRoad > 0.5 && outside > 0.5 && m.b > 0.7) discard;
  vec4 nz = texture2D(uNoise, p / 23.0);
  // Граница газона, плитки и асфальта - порог маски без шума: шум делал край «обгрызенным»
  // (пользователь, 17.10.2026). Лесенку клеток растра снимает размытие маски (softenCells).
  float lawn = smoothstep(0.45, 0.55, m.r);
  float paver = smoothstep(0.45, 0.55, m.g) * (1.0 - lawn);
  lawn = mix(1.0, lawn, outside);
  paver *= outside;
  float asph = clamp(1.0 - lawn - paver, 0.0, 1.0);
  groundWeights = vec3(lawn, paver, asph);
  // Крупные пятна - шумом в десятки метров, а не фактурой: повтор плитки фактуры сверху
  // читается рядами, пятна шума - нет.
  float macro = texture2D(uNoise, p / 173.0).r * 0.6 + texture2D(uNoise, p / 47.0).g * 0.4;
  vec3 g = antiTile(uGrass, p, 2.0);
  // Keep the scanned fine structure, with a living summer turf palette.
  float turfLuma = dot(g, vec3(0.2126, 0.7152, 0.0722));
  g = mix(g, turfLuma * vec3(0.55, 1.08, 0.28), 0.78);
  g *= mix(vec3(1.06, 0.96, 0.8), vec3(0.8, 1.03, 0.88), macro) * 0.65;
  // Дальнее поле за краем съёмки глуше: оно фон, а не газон участка.
  g = mix(g * vec3(0.86, 0.84, 0.8), g, outside);
  vec3 pv = texture2D(uPavers, p / 2.1).rgb * (0.9 + 0.16 * macro);
  vec3 a = antiTile(uAsphalt, p, 3.0) * (0.84 + 0.3 * macro);
  vec3 col = g * lawn + pv * paver + a * asph;
  // Мокрое покрытие темнее, газон темнеет меньше; лужи - пятнами шума.
  float puddle = smoothstep(0.55, 0.7, texture2D(uNoise, p / 9.0).g) * (1.0 - lawn);
  col *= 1.0 - uWet * (0.3 * (1.0 - lawn) + 0.15 * lawn + 0.2 * puddle);
  // Снег ложится сначала на газон, на проезды - позже и пятнами: их чистят и греют машины.
  float cover = uSnow * (lawn * 1.25 + (1.0 - lawn) * 0.6) + (nz.b - 0.5) * 0.5 * uSnow;
  groundSnow = clamp(cover, 0.0, 1.0);
  col = mix(col, vec3(0.9, 0.92, 0.96), groundSnow);
  groundWet = uWet * (1.0 - groundSnow) * (0.6 + 0.4 * puddle);
  groundArm = antiTile(uGrassArm, p, 2.0) * lawn
    + texture2D(uPaversArm, p / 2.1).rgb * paver
    + antiTile(uAsphaltArm, p, 3.0) * asph;
  groundArm = mix(vec3(1.0, 0.92, 0.0), groundArm, dot(groundWeights, uPbr));
  col *= mix(groundArm.r, 1.0, 0.35 + groundSnow * 0.65);
  diffuseColor.rgb *= col;
}
`;

const GROUND_ROUGHNESS = /* glsl */ `
float roughnessFactor = clamp(groundArm.g, 0.45, 1.0);
roughnessFactor = mix(roughnessFactor, 0.12, groundWet * (1.0 - groundWeights.x) * 0.9);
roughnessFactor = mix(roughnessFactor, 0.75, groundSnow);
`;

// The scanned texture coordinates are world X/Z; transform their tangent normal to view space.
const GROUND_NORMAL = /* glsl */ `
vec2 groundP = vGroundPos.xz;
vec3 scannedNormal = (antiTile(uGrassNormal, groundP, 2.0) * groundWeights.x
  + texture2D(uPaversNormal, groundP / 2.1).rgb * groundWeights.y
  + antiTile(uAsphaltNormal, groundP, 3.0) * groundWeights.z) * 2.0 - 1.0;
scannedNormal = mix(vec3(0.0, 0.0, 1.0), scannedNormal, dot(groundWeights, uPbr));
scannedNormal.xy *= mix(1.0, 0.35, groundWeights.x) * (1.0 - groundSnow * 0.95) * (1.0 - groundWet * 0.85);
normal = normalize(mat3(viewMatrix) * vec3(scannedNormal.x, scannedNormal.z, scannedNormal.y));
`;

/** Бортовой камень: брус 15 x 15 см вдоль каждой линии борта - дорожный, у проезжей части. */
export const CURB_W = 0.15;
export const CURB_H = 0.15;
/** Садовый борт между тротуаром и газоном (БР 100.20.8 по ГОСТ 6665): 8 см шириной, над
 *  газоном выступает на несколько сантиметров. */
/** Верх дорожного борта над тротуаром: борт обычно чуть выше плитки. */
export const CURB_ABOVE_WALK_M = 0.02;
export const GARDEN_CURB_W = 0.08;
export const GARDEN_CURB_H = 0.06;

/** Сетка бруса вдоль ломаной: верх и две боковые грани без дна. Пролёты стыкуются срезом
 *  угла (без щели и нахлёста на изломе, срез не длиннее ширины бруса), открытая ломаная
 *  закрыта торцами, замкнутое кольцо - стыком конца с началом: изнутри брус не виден. */
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
  const hw = width / 2;
  const y0 = lift;
  const y1 = lift + height;
  for (const line of lines) {
    const pts: Flat[] = [];
    for (const p of line.points) {
      const last = pts.at(-1);
      if (!last || Math.hypot(p.x - last.x, p.z - last.z) >= 0.01) pts.push(p);
    }
    const first = pts[0];
    const end = pts.at(-1);
    const closed =
      pts.length > 3 && !!first && !!end && Math.hypot(first.x - end.x, first.z - end.z) < 0.01;
    if (closed) pts.pop();
    const n = pts.length;
    const segments = closed ? n : n - 1;
    if (segments < 1) continue;
    // Нормаль каждого пролёта.
    const normals: [number, number][] = [];
    for (let s = 0; s < segments; s++) {
      const p = pts[s] as Flat;
      const q = pts[(s + 1) % n] as Flat;
      const len = Math.hypot(q.x - p.x, q.z - p.z);
      normals.push([-(q.z - p.z) / len, (q.x - p.x) / len]);
    }
    // Смещение вершины влево: среднее нормалей соседних пролётов, длиной до стыка граней.
    const offset = (k: number): [number, number] => {
      const after = closed ? k % segments : Math.min(k, segments - 1);
      const before = closed ? (k - 1 + segments) % segments : Math.max(k - 1, 0);
      const [ax, az] = normals[before] ?? [0, 0];
      const [bx, bz] = normals[after] ?? [0, 0];
      let mx = ax + bx;
      let mz = az + bz;
      const ml = Math.hypot(mx, mz);
      if (ml < 1e-6) return [bx * hw, bz * hw];
      mx /= ml;
      mz /= ml;
      const scale = Math.min(hw / Math.max(mx * bx + mz * bz, 1e-6), width);
      return [mx * scale, mz * scale];
    };
    let along = 0;
    for (let s = 0; s < segments; s++) {
      const p = pts[s] as Flat;
      const q = pts[(s + 1) % n] as Flat;
      const [ox0, oz0] = offset(s);
      const [ox1, oz1] = offset(s + 1);
      const [nx, nz] = normals[s] ?? [0, 0];
      const len = Math.hypot(q.x - p.x, q.z - p.z);
      const u0 = along;
      const u1 = along + len;
      along = u1;
      const l0 = [p.x + ox0, p.z + oz0];
      const r0 = [p.x - ox0, p.z - oz0];
      const l1 = [q.x + ox1, q.z + oz1];
      const r1 = [q.x - ox1, q.z - oz1];
      // Верх, левая и правая грани.
      quad(
        [l0[0] ?? 0, y1, l0[1] ?? 0],
        [r0[0] ?? 0, y1, r0[1] ?? 0],
        [r1[0] ?? 0, y1, r1[1] ?? 0],
        [l1[0] ?? 0, y1, l1[1] ?? 0],
        [0, 1, 0],
        u0,
        u1,
      );
      quad(
        [l0[0] ?? 0, y0, l0[1] ?? 0],
        [l0[0] ?? 0, y1, l0[1] ?? 0],
        [l1[0] ?? 0, y1, l1[1] ?? 0],
        [l1[0] ?? 0, y0, l1[1] ?? 0],
        [nx, 0, nz],
        u0,
        u1,
      );
      quad(
        [r1[0] ?? 0, y0, r1[1] ?? 0],
        [r1[0] ?? 0, y1, r1[1] ?? 0],
        [r0[0] ?? 0, y1, r0[1] ?? 0],
        [r0[0] ?? 0, y0, r0[1] ?? 0],
        [-nx, 0, -nz],
        u1,
        u0,
      );
    }
    if (closed) continue;
    // Торцы открытой ломаной.
    for (const [k, sign] of [
      [0, -1],
      [n - 1, 1],
    ] as const) {
      const p = pts[k] as Flat;
      const [ox, oz] = offset(k);
      const [nx, nz] = normals[sign < 0 ? 0 : segments - 1] ?? [0, 0];
      const dir = [nz * sign, -nx * sign];
      const a = [p.x + ox, p.z + oz];
      const b = [p.x - ox, p.z - oz];
      const [first, second] = sign < 0 ? [a, b] : [b, a];
      quad(
        [first[0] ?? 0, y0, first[1] ?? 0],
        [first[0] ?? 0, y1, first[1] ?? 0],
        [second[0] ?? 0, y1, second[1] ?? 0],
        [second[0] ?? 0, y0, second[1] ?? 0],
        [dir[0] ?? 0, 0, dir[1] ?? 0],
        0,
        width,
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
