/* Здания 3D-вида: объём по контуру чертежа и высоте из scene.json, фасад рисуется шейдером.
 *
 * Стены строятся не ExtrudeGeometry: у неё развёртка стены идёт по проекции на ось x или z,
 * и на косой стене окна растягиваются. Здесь u - метры вдоль контура, v - метры от земли,
 * поэтому окно на любой стене одного размера, а этаж ровно 3 м, как у здания в чертеже.
 * Все здания сливаются в две сетки (стены и крыши): тысяча домов - два вызова отрисовки.
 *
 * Фасад процедурный: по этажности, признаку «жилое/нежилое» и материалу стен из подписей
 * (К - кирпич, М - металл) выбирается рисунок - кирпичный дом, панельный, павильон с
 * витринами, металлический ангар. Это не фотография конкретного дома: съёмка Мосгеотреста
 * фасадов не несёт, и выдавать догадку за точность нельзя. */

import * as THREE from 'three';

import type { Building, Flat, Ring } from './types';

/** Стиль фасада, номер уходит в шейдер атрибутом. */
export const STYLE = { panel: 0, brick: 1, pavilion: 2, metal: 3, porch: 4 } as const;
export type Style = (typeof STYLE)[keyof typeof STYLE];

export function styleOf(b: Building): Style {
  if (b.kind === 'porch' || b.kind === 'container' || b.kind === 'structure') return STYLE.porch;
  if (b.wall === 'metal') return STYLE.metal;
  if (b.floors <= 2) return b.use === 'residential' ? STYLE.brick : STYLE.pavilion;
  if (b.wall === 'brick') return b.floors >= 12 ? STYLE.panel : STYLE.brick;
  // Без материала: высокие дома в Москве чаще панельные, средние - кирпичные.
  return b.floors >= 9 || b.seed % 3 === 0 ? STYLE.panel : STYLE.brick;
}

function ringArea(ring: Ring): number {
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
}

/** Стены одного кольца. Нормаль наружу: у внешнего контура и у двора обход противоположный,
 *  поэтому сторона выбирается по знаку площади кольца, а не по порядку в данных. */
function pushWalls(
  out: Buffers,
  ring: Ring,
  height: number,
  hole: boolean,
  info: [number, number, number, number],
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
      out.pos.push(p.x, v, p.z);
      out.nor.push(nx, 0, nz);
      out.uv.push(u, v);
      out.info.push(...info);
    }
  }
}

function geometryOf(b: Buffers): THREE.BufferGeometry {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(b.pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(b.nor, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(b.uv, 2));
  g.setAttribute('aInfo', new THREE.Float32BufferAttribute(b.info, 4));
  g.computeBoundingSphere();
  return g;
}

/** Крыша: плоская, треугольники контура с дворами. */
function pushRoof(out: Buffers, b: Building, info: [number, number, number, number]): void {
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
    }
  }
}

export interface BuildingMeshes {
  walls: THREE.BufferGeometry;
  roofs: THREE.BufferGeometry;
}

export function buildingGeometry(buildings: readonly Building[]): BuildingMeshes {
  const walls: Buffers = { pos: [], nor: [], uv: [], info: [] };
  const roofs: Buffers = { pos: [], nor: [], uv: [], info: [] };
  for (const b of buildings) {
    const style = styleOf(b);
    // info: стиль, этажей, высота, разброс цвета 0..1.
    const info: [number, number, number, number] = [
      style,
      Math.max(1, b.floors),
      b.height,
      (b.seed % 997) / 997,
    ];
    b.rings.forEach((ring, i) => {
      if (ring.length >= 3) pushWalls(walls, ring, b.height, i > 0, info);
    });
    pushRoof(roofs, b, info);
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
        '#include <common>\nattribute vec4 aInfo;\nvarying vec4 vInfo;\nvarying vec2 vFacade;',
      )
      .replace('#include <uv_vertex>', '#include <uv_vertex>\nvInfo = aInfo;\nvFacade = uv;');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>\n${FACADE_HEAD}`)
      .replace('#include <map_fragment>', FACADE_MAP)
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
varying vec2 vFacade;
uniform float uNight;
uniform sampler2D uNoise;
float facadeRough;
float facadeMetal;
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
  float bay = style == 0 ? 3.0 : 2.8;
  float cell = floor(u / bay);
  float lu = fract(u / bay);
  vec3 wall;
  if (style == 0) wall = mix(vec3(0.72, 0.71, 0.67), vec3(0.80, 0.76, 0.66), tint);
  else if (style == 1) wall = mix(vec3(0.52, 0.28, 0.20), vec3(0.68, 0.48, 0.34), tint);
  else if (style == 2) wall = mix(vec3(0.78, 0.76, 0.72), vec3(0.64, 0.66, 0.68), tint);
  else if (style == 3) wall = mix(vec3(0.55, 0.58, 0.60), vec3(0.40, 0.45, 0.48), tint);
  else wall = vec3(0.62, 0.61, 0.58);
  float grime = texture2D(uNoise, vec2(u, v) / 37.0).r;
  wall *= 0.86 + 0.22 * grime;
  if (style == 1) {
    float row = floor(v / 0.075);
    float brick = step(0.08, fract(v / 0.075)) * step(0.04, fract(u / 0.25 + mod(row, 2.0) * 0.5));
    wall *= mix(0.78, 1.0, brick) * (0.94 + 0.12 * hash12(vec2(floor(u / 0.25), row)));
  }
  if (style == 0) {
    // Швы панелей: горизонталь на перекрытии, вертикаль через пролёт.
    float seam = (1.0 - step(0.012, abs(lv - 0.0))) + (1.0 - step(0.006, abs(fract(u / 6.0) - 0.0)));
    wall *= 1.0 - 0.18 * clamp(seam, 0.0, 1.0);
  }
  if (style == 3) {
    wall *= 0.9 + 0.1 * step(0.5, fract(u / 0.2));
  }
  float glass = 0.0;
  bool facade = style != 4 && v > plinth && level < floors;
  if (facade) {
    vec2 size = style == 2 && level < 1.0 ? vec2(0.86, 0.72) : vec2(0.5, 0.52);
    if (style == 3) size = vec2(0.0);
    vec2 d = abs(vec2(lu, lv) - vec2(0.5, 0.52));
    float frame = step(d.x, size.x * 0.5 + 0.035) * step(d.y, size.y * 0.5 + 0.035);
    glass = step(d.x, size.x * 0.5) * step(d.y, size.y * 0.5);
    wall = mix(wall, wall * 0.55 + vec3(0.05), frame - glass);
  }
  // Горит примерно каждое третье окно, у каждого своя яркость и оттенок лампы; витрина
  // первого этажа ночью не светится сплошь - магазины к ночи закрыты.
  float roll = hash12(vec2(cell, level) + tint * 17.0);
  float shop = style == 2 && level < 1.0 ? 0.35 : 1.0;
  float lit = step(0.68, roll) * glass * uNight * shop * (0.35 + 0.65 * hash12(vec2(level, cell) * 1.3));
  vec3 glassColor = mix(vec3(0.06, 0.08, 0.10), vec3(0.16, 0.19, 0.22), hash12(vec2(cell * 1.7, level)));
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
  const m = new THREE.MeshStandardMaterial({ color: 0x3a3a3c, roughness: 0.95, metalness: 0 });
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
