/* Трава на газонах: поле травинок вокруг камеры.
 *
 * Травинки разложены один раз в квадрате uSize x uSize и в шейдере переносятся со сдвигом на
 * целое число квадратов к камере: поле бесконечно, а каждая травинка стоит на своём месте
 * мира и не едет вместе с камерой. Растёт травинка только там, где маска покрытий говорит
 * «газон» (та же маска и тот же шум края, что у земли, ground.ts), и тает к краю круга,
 * дальше газон рисует фактура земли. Свет и тени - от MeshStandardMaterial, как у всей
 * сцены: тень кроны ложится и на траву. */

import * as THREE from 'three';

import type { MaskInfo } from './ground';
import { rng } from './textures';

export interface GrassOptions {
  /** Сторона квадрата раскладки, метры. */
  size: number;
  /** Травинок в квадрате. */
  count: number;
  /** Радиус, где трава видна травинками, метры. */
  radius: number;
}

export const GRASS_PRESETS: Record<'low' | 'medium' | 'high', GrassOptions | null> = {
  low: null,
  medium: { size: 40, count: 240_000, radius: 18 },
  high: { size: 44, count: 520_000, radius: 20 },
};

/** Травинка: три сегмента, сужение к кончику. x - поперёк, y - доля высоты. */
function bladeShape(): { pos: number[]; index: number[] } {
  const pos: number[] = [];
  const index: number[] = [];
  const segments = 3;
  for (let i = 0; i <= segments; i++) {
    const t = i / segments;
    const w = 0.5 * (1 - t * 0.85);
    if (i === segments) {
      pos.push(0, t, 0);
    } else {
      pos.push(-w, t, 0, w, t, 0);
    }
  }
  for (let i = 0; i < segments - 1; i++) {
    const a = i * 2;
    index.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
  }
  const last = (segments - 1) * 2;
  index.push(last, last + 1, last + 2);
  return { pos, index };
}

export function grassGeometry(opts: GrassOptions, seed = 17): THREE.InstancedBufferGeometry {
  const shape = bladeShape();
  const g = new THREE.InstancedBufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(shape.pos, 3));
  g.setIndex(shape.index);
  const random = rng(seed);
  const offsets = new Float32Array(opts.count * 2);
  const params = new Float32Array(opts.count * 4);
  for (let i = 0; i < opts.count; i++) {
    offsets[i * 2] = random() * opts.size;
    offsets[i * 2 + 1] = random() * opts.size;
    params[i * 4] = random(); // высота
    params[i * 4 + 1] = random() * Math.PI * 2; // поворот
    params[i * 4 + 2] = random(); // наклон
    params[i * 4 + 3] = random(); // оттенок
  }
  g.setAttribute('aOffset', new THREE.InstancedBufferAttribute(offsets, 2));
  g.setAttribute('aBlade', new THREE.InstancedBufferAttribute(params, 4));
  g.instanceCount = opts.count;
  // Поле всегда вокруг камеры: сфера на весь мир, чтобы его не отсекало по габариту.
  g.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1e7);
  return g;
}

export interface GrassUniforms {
  uCenter: { value: THREE.Vector2 };
  uSize: { value: number };
  uRadius: { value: number };
  uTime: { value: number };
  uMask: { value: THREE.Texture };
  uMaskRect: { value: THREE.Vector4 };
  uNoise: { value: THREE.Texture };
  uGrow: { value: number };
  uWind: { value: number };
}

const GRASS_VERTEX_HEAD = /* glsl */ `
attribute vec2 aOffset;
attribute vec4 aBlade;
uniform vec2 uCenter;
uniform float uSize;
uniform float uRadius;
uniform float uTime;
uniform sampler2D uMask;
uniform vec4 uMaskRect;
uniform sampler2D uNoise;
uniform float uGrow;
uniform float uWind;
varying vec3 vGrass;
`;

/* Край газона считается так же, как в шейдере земли: маска R плюс шум, порог 0,5. */
const GRASS_BEGIN = /* glsl */ `
vec2 local = mod(aOffset - uCenter + uSize * 0.5, uSize) - uSize * 0.5;
vec2 world = uCenter + local;
vec2 muv = (world - uMaskRect.xy) / uMaskRect.zw;
float inside = step(0.0, muv.x) * step(muv.x, 1.0) * step(0.0, muv.y) * step(muv.y, 1.0);
float m = texture2D(uMask, clamp(muv, 0.0, 1.0)).r;
float edge = (texture2D(uNoise, world / 23.0).g - 0.5) * 0.5 + (texture2D(uNoise, world / 3.1).b - 0.5) * 0.35;
float lawn = smoothstep(0.5, 0.62, m + edge) * inside;
float dist = length(local);
float fade = 1.0 - smoothstep(uRadius * 0.6, uRadius, dist);
float patchy = texture2D(uNoise, world / 7.0).r;
float h = mix(0.045, 0.14, aBlade.x * aBlade.x) * (0.75 + 0.5 * patchy) * uGrow * lawn * fade;
float c = cos(aBlade.y);
float s = sin(aBlade.y);
float width = 0.006 + 0.007 * aBlade.w;
float t = position.y;
float gust = sin(uTime * 1.7 + dot(world, vec2(0.21, 0.13))) * 0.5 + sin(uTime * 3.1 + world.x * 0.7) * 0.2;
float bend = 0.35 + aBlade.z * 0.85 + gust * (0.1 + 0.9 * uWind);
vec3 blade = vec3(position.x * width, t * h, bend * t * t * h);
vec3 transformed = vec3(world.x + blade.x * c - blade.z * s, blade.y, world.y + blade.x * s + blade.z * c);
vGrass = vec3(t, aBlade.w, patchy);
`;

export function grassMaterial(uniforms: GrassUniforms): THREE.MeshStandardMaterial {
  const m = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    roughness: 0.85,
    metalness: 0,
    side: THREE.DoubleSide,
    envMapIntensity: 0.5,
  });
  m.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', `#include <common>\n${GRASS_VERTEX_HEAD}`)
      // Нормаль травинки - почти вверх: газон освещается ровно, без мерцания граней.
      .replace('#include <beginnormal_vertex>', 'vec3 objectNormal = vec3(0.0, 1.0, 0.0);')
      .replace('#include <begin_vertex>', GRASS_BEGIN);
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vGrass;')
      .replace(
        '#include <normal_fragment_begin>',
        '#include <normal_fragment_begin>\nnormal = normalize(mat3(viewMatrix) * vec3(0.0, 1.0, 0.0));',
      )
      .replace(
        '#include <map_fragment>',
        `vec3 grassBase = mix(vec3(0.045, 0.075, 0.02), vec3(0.07, 0.1, 0.03), vGrass.y);
vec3 grassTip = mix(vec3(0.085, 0.15, 0.035), vec3(0.13, 0.18, 0.055), vGrass.z);
diffuseColor.rgb *= mix(grassBase, grassTip, vGrass.x);`,
      );
  };
  m.customProgramCacheKey = () => 'green-grass';
  return m;
}

export class GrassField {
  readonly mesh: THREE.Mesh;
  readonly uniforms: GrassUniforms;

  constructor(mask: MaskInfo, noise: THREE.Texture, opts: GrassOptions) {
    this.uniforms = {
      uCenter: { value: new THREE.Vector2() },
      uSize: { value: opts.size },
      uRadius: { value: opts.radius },
      uTime: { value: 0 },
      uMask: { value: mask.texture },
      uMaskRect: { value: new THREE.Vector4(...mask.rect) },
      uNoise: { value: noise },
      uGrow: { value: 1 },
      uWind: { value: 0.35 },
    };
    this.mesh = new THREE.Mesh(grassGeometry(opts), grassMaterial(this.uniforms));
    this.mesh.frustumCulled = false;
    this.mesh.receiveShadow = true;
    this.mesh.name = 'grass';
  }

  /** Поле за камерой; выше 25 м травинок не разглядеть - поле выключается. */
  update(camera: THREE.Camera, time: number): void {
    const p = camera.position;
    this.uniforms.uCenter.value.set(p.x, p.z);
    this.uniforms.uTime.value = time;
    this.mesh.visible = p.y < 25;
  }

  dispose(): void {
    this.mesh.geometry.dispose();
    (this.mesh.material as THREE.Material).dispose();
  }
}
