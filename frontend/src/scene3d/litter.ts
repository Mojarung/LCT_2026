/* Опавшие листья осенью. Под кронами листья лежат ковром, на открытом месте - реже
 * (пользователь, 19.10.2026, фото двора в октябре: «посмотри, сколько листвы, может, раскидать
 * для осени»). Плотность - карта по кронам деревьев и кустов сцены, лист - яйцевидная
 * пластинка 5-11 см с черешком, своего цвета, размера и поворота, в два слоя, в шейдере
 * земли, резины площадок и земли лунок; вдали узор растворяется в средний цвет, а не рябит.
 * На проезде листьев мало: их сметают машины. */

import * as THREE from 'three';

import type { Plant } from './types';

export interface LitterUniforms {
  /** 0 - листьев нет, 1 - осень. */
  uLitter: { value: number };
  uLitterMap: { value: THREE.Texture };
  /** Прямоугольник карты в метрах сцены: x0, z0, ширина, высота. */
  uLitterRect: { value: THREE.Vector4 };
}

/** Метров на пиксель карты плотности. */
export const LITTER_M_PER_PX = 1.0;
const MAX_PX = 4096;
/** Опад тянется за край кроны ветром на долю радиуса. */
const SPREAD = 1.8;

export function litterUniforms(): LitterUniforms {
  const empty = new THREE.DataTexture(new Uint8Array([0]), 1, 1, THREE.RedFormat);
  empty.needsUpdate = true;
  return {
    uLitter: { value: 0 },
    uLitterMap: { value: empty },
    uLitterRect: { value: new THREE.Vector4(0, 0, 1, 1) },
  };
}

/** Радиус кроны для опада: у существующих - с подосновы, у посадок - средний взрослеющий. */
export function crownRadius(plant: Pick<Plant, 'type' | 'existingRadius'>): number {
  if (plant.existingRadius) return plant.existingRadius;
  if (/hedge/.test(plant.type)) return 0.8;
  if (/shrub/.test(plant.type)) return 1.2;
  return 3.0;
}

/** Карта плотности опада: под кроной 1, к краю опада 0; кроны складываются до 1. */
export function litterDensity(
  plants: readonly Pick<Plant, 'x' | 'z' | 'type' | 'existingRadius'>[],
  rect: readonly [number, number, number, number],
  metresPerPx = LITTER_M_PER_PX,
): { data: Uint8Array; width: number; height: number; metresPerPx: number } {
  const [x0, z0, w, h] = rect;
  const m = Math.max(metresPerPx, w / MAX_PX, h / MAX_PX);
  const width = Math.max(1, Math.ceil(w / m));
  const height = Math.max(1, Math.ceil(h / m));
  const acc = new Float32Array(width * height);
  for (const plant of plants) {
    const r = crownRadius(plant) * SPREAD;
    const cx = (plant.x - x0) / m;
    const cz = (plant.z - z0) / m;
    const rp = r / m;
    const i0 = Math.max(0, Math.floor(cx - rp));
    const i1 = Math.min(width - 1, Math.ceil(cx + rp));
    const j0 = Math.max(0, Math.floor(cz - rp));
    const j1 = Math.min(height - 1, Math.ceil(cz + rp));
    for (let j = j0; j <= j1; j++) {
      for (let i = i0; i <= i1; i++) {
        const d = Math.hypot(i + 0.5 - cx, j + 0.5 - cz) / rp;
        if (d >= 1) continue;
        // Под кроной ковёр, к краю опада - на нет.
        const t = Math.min(1, (1 - d) / (1 - 0.7 / SPREAD));
        acc[j * width + i] = (acc[j * width + i] ?? 0) + t * t * (3 - 2 * t);
      }
    }
  }
  const data = new Uint8Array(width * height);
  for (let k = 0; k < data.length; k++) data[k] = Math.round(Math.min(1, acc[k] ?? 0) * 255);
  return { data, width, height, metresPerPx: m };
}

/** Карта опада текстурой; строки - по z, как у маски земли. */
export function litterTexture(
  plants: readonly Pick<Plant, 'x' | 'z' | 'type' | 'existingRadius'>[],
  rect: readonly [number, number, number, number],
): { texture: THREE.DataTexture; rect: THREE.Vector4 } {
  const { data, width, height, metresPerPx } = litterDensity(plants, rect);
  const texture = new THREE.DataTexture(data, width, height, THREE.RedFormat);
  texture.magFilter = THREE.LinearFilter;
  texture.minFilter = THREE.LinearFilter;
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.needsUpdate = true;
  return {
    texture,
    rect: new THREE.Vector4(rect[0], rect[1], width * metresPerPx, height * metresPerPx),
  };
}

/** Объявления и функции опада для фрагментного шейдера. */
export const LITTER_HEAD = /* glsl */ `
uniform float uLitter;
uniform sampler2D uLitterMap;
uniform vec4 uLitterRect;

float litterHash(vec2 c) {
  vec3 p3 = fract(vec3(c.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}

float litterNoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(litterHash(i), litterHash(i + vec2(1.0, 0.0)), f.x),
             mix(litterHash(i + vec2(0.0, 1.0)), litterHash(i + vec2(1.0, 1.0)), f.x), f.y);
}

// Жёлтый липы и берёзы, золотой и рыжий клёна, бурый подсохший, бледная изнанка, редкий зелёный.
vec3 litterLeafColor(float h) {
  vec3 c = mix(vec3(0.88, 0.70, 0.18), vec3(0.80, 0.55, 0.13), smoothstep(0.2, 0.45, h));
  c = mix(c, vec3(0.66, 0.36, 0.11), smoothstep(0.5, 0.65, h));
  c = mix(c, vec3(0.36, 0.23, 0.12), step(0.72, h));
  c = mix(c, vec3(0.70, 0.60, 0.42), step(0.86, h));
  c = mix(c, vec3(0.58, 0.60, 0.24), step(0.95, h));
  // Палитра задана в sRGB, как на фото; шейдер считает свет в линейном пространстве.
  return pow(c, vec3(2.2));
}

// Лист в ячейке 7,5 см: яйцевидная пластинка с острым кончиком и черешком, свой угол, размер,
// цвет; верхний лист - с наибольшим весом. Ячейка без листа - с вероятностью 1 - density.
// Возвращает цвет и вес листа, в w - ещё и тень от листьев рядом (тёмная кайма).
vec4 litterLayer(vec2 t, float density, float salt, inout float shade) {
  vec2 cell = floor(t);
  vec4 top = vec4(0.0);
  for (int i = -1; i <= 1; i++) {
    for (int j = -1; j <= 1; j++) {
      vec2 c = cell + vec2(float(i), float(j));
      if (litterHash(c + salt) > density) continue;
      vec2 o = vec2(litterHash(c + 3.1 + salt), litterHash(c + 7.7 + salt));
      float a = litterHash(c + 13.3 + salt) * 6.2832;
      float size = 0.75 + 0.5 * litterHash(c + 31.7 + salt);
      vec2 d = (t - (c + o)) / size;
      d = vec2(cos(a) * d.x + sin(a) * d.y, -sin(a) * d.x + cos(a) * d.y);
      // Полуширина пластинки вдоль её оси: шире у основания, к кончику сходится.
      float x = d.x / 0.85;
      float hw = 0.5 * sqrt(max(0.0, 1.0 - x * x)) * (1.0 - 0.38 * x);
      float edge = hw - abs(d.y);
      float w = smoothstep(-0.02, 0.04, edge) * step(abs(x), 1.0);
      // Черешок за основанием.
      w = max(w, (1.0 - smoothstep(0.012, 0.03, abs(d.y))) * step(-1.25, x) * step(x, -0.95));
      shade = max(shade, smoothstep(-0.12, 0.0, edge) * step(abs(x), 1.15) * 0.5);
      if (w > top.a) {
        vec3 leaf = litterLeafColor(litterHash(c + 21.9 + salt));
        leaf *= 0.72 + 0.4 * litterHash(c + 5.5 + salt);
        // Середина светлее края, жилка темнее: лист чуть выгнут.
        leaf *= 0.86 + 0.2 * smoothstep(0.0, 0.25, edge);
        leaf *= 1.0 - 0.2 * (1.0 - smoothstep(0.0, 0.035, abs(d.y))) * step(abs(x), 0.9);
        top = vec4(leaf, w);
      }
    }
  }
  return top;
}

// Два слоя листьев: второй мельче и сдвинут, при густом опаде ковёр сплошной.
vec4 litterLeaves(vec2 p, float density, inout float shade) {
  vec4 a = litterLayer(p / 0.075, density, 0.0, shade);
  vec4 b = litterLayer(p / 0.058 + 0.5, clamp((density - 0.35) * 1.6, 0.0, 1.0), 57.0, shade);
  return a.a >= b.a ? a : b;
}

// Опад поверх цвета земли: amount - доля опада для этого покрытия (проезд - мало),
// boost - добавка плотности (земля лунки под деревом).
vec3 applyLitter(vec3 col, vec2 p, float amount, float boost) {
  if (uLitter <= 0.0) return col;
  vec2 uv = (p - uLitterRect.xy) / uLitterRect.zw;
  float inMap = step(0.0, uv.x) * step(uv.x, 1.0) * step(0.0, uv.y) * step(uv.y, 1.0);
  float under = texture2D(uLitterMap, clamp(uv, 0.0, 1.0)).r * inMap;
  // Ветер сбивает листья в пятна и полосы: шум в метры и в десятки метров.
  float drift = 0.55 + 0.6 * litterNoise(p / 3.7) + 0.25 * litterNoise(p / 17.0);
  float density = clamp(uLitter * amount * ((0.2 + 0.8 * under) * drift + boost), 0.0, 1.0);
  vec2 fw = fwidth(p / 0.075);
  float detail = 1.0 - smoothstep(0.3, 0.8, max(fw.x, fw.y));
  // Вдали узор растворяется в средний цвет опада с долей, как у листьев вблизи.
  // Сверху пятно опада не должно читаться рыжим кругом: цвет приглушён, доля не больше 0,8.
  float cover = clamp(density * 0.55 + max(density - 0.35, 0.0) * 0.4, 0.0, 0.8);
  vec3 far = mix(col, pow(vec3(0.64, 0.5, 0.25), vec3(2.2)), cover);
  if (detail <= 0.0) return far;
  float shade = 0.0;
  vec4 leaf = litterLeaves(p, density, shade);
  // Земля у края листа в его тени: листья лежат, а не нарисованы.
  vec3 near = mix(col * (1.0 - 0.35 * shade), leaf.rgb, leaf.a);
  return mix(far, near, detail);
}
`;

const LITTER_POSITION = /* glsl */ `
#ifdef USE_INSTANCING
vLitterPos = (modelMatrix * instanceMatrix * vec4(transformed, 1.0)).xyz;
#else
vLitterPos = (modelMatrix * vec4(transformed, 1.0)).xyz;
#endif
`;

/** Опад на материал вне шейдера земли (резина площадок, земля лунок): мировые координаты
 *  из вершинного шейдера, листья поверх карты материала. */
export function withLitter(
  material: THREE.MeshStandardMaterial,
  uniforms: LitterUniforms,
  boost = 0,
): void {
  const key = `litter-${String(boost)}`;
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vLitterPos;')
      .replace('#include <worldpos_vertex>', `#include <worldpos_vertex>\n${LITTER_POSITION}`);
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>\nvarying vec3 vLitterPos;\n${LITTER_HEAD}`)
      .replace(
        '#include <map_fragment>',
        `#include <map_fragment>\ndiffuseColor.rgb = applyLitter(diffuseColor.rgb, vLitterPos.xz, 1.0, ${boost.toFixed(2)});`,
      );
  };
  material.customProgramCacheKey = () => key;
}
