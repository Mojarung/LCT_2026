/* Солнце, Луна и звёзды на небе 3D-вида.
 *
 * Небо Preetham рисует солнце точкой в пиксель и ничего не знает о Луне и ночи. Поэтому
 * поверх него: диск солнца с ореолом, Луна с фазой на дату сцены (celestial.ts), звёзды и
 * ночной купол - тёмная синева в зените и рыжая засветка города у горизонта, как над
 * Москвой. Всё держится на сфере вокруг камеры, внутри коробки неба: сколько ни лети,
 * светила остаются на бесконечности. Размеры дисков увеличены против настоящих (0,5
 * градуса): иначе Луну на снимке не разглядеть. */

import * as THREE from 'three';

import type { MoonState } from './celestial';
import { fbm } from './textures';

/** Радиус сферы светил: внутри коробки неба (половина её стороны - 2250 м). */
const RADIUS = 2000;
/** Видимый угловой радиус, градусы: ореол солнца и диск Луны. */
const SUN_GLOW_DEG = 4.5;
const MOON_DEG = 1.3;
const STARS = 2600;

function sphereScale(deg: number): number {
  return 2 * RADIUS * Math.tan((deg * Math.PI) / 180);
}

/** Ореол солнца: яркое ядро и мягкий спад, прозрачный край. */
function glowTexture(): THREE.CanvasTexture {
  const size = 256;
  const c = document.createElement('canvas');
  c.width = size;
  c.height = size;
  const ctx = c.getContext('2d');
  if (ctx) {
    const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    // Ядро - диск солнца, дальше быстрый спад: широкий ореол уже рисует рассеяние самого неба.
    g.addColorStop(0, 'rgba(255,255,255,1)');
    g.addColorStop(0.1, 'rgba(255,255,248,1)');
    g.addColorStop(0.16, 'rgba(255,240,215,0.35)');
    g.addColorStop(0.4, 'rgba(255,220,180,0.06)');
    g.addColorStop(1, 'rgba(255,210,170,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/** Диск Луны в фазе: освещённая часть по углу между Солнцем и нами, моря пятнами, тёмная
 *  сторона - едва заметный пепельный свет. */
export function moonTexture(
  fraction: number,
  waxing: boolean,
  maria: Float32Array,
  size = 256,
): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = size;
  c.height = size;
  const ctx = c.getContext('2d');
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  if (!ctx) return t;
  const img = ctx.createImageData(size, size);
  // Направление на Солнце в системе диска: полнолуние - на нас (z), новолуние - от нас.
  const phase = Math.acos(2 * fraction - 1);
  const lx = Math.sin(phase) * (waxing ? 1 : -1);
  const lz = Math.cos(phase);
  const r = size / 2 - 2;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const nx = (x - size / 2) / r;
      const ny = (y - size / 2) / r;
      const rr = nx * nx + ny * ny;
      const i = (y * size + x) * 4;
      if (rr > 1) continue;
      const nz = Math.sqrt(1 - rr);
      const lit = Math.max(0, nx * lx + nz * lz);
      const light = Math.min(1, lit * 1.6);
      const m = maria[Math.floor((y * size + x) % maria.length)] ?? 0.5;
      // Моря темнее материков, край диска чуть темнее середины.
      const albedo = (0.62 + 0.38 * Math.max(0, Math.min(1, (m - 0.38) * 3))) * (0.82 + 0.18 * nz);
      const edge = Math.min(1, (1 - Math.sqrt(rr)) * r * 0.5);
      img.data[i] = 236 * albedo;
      img.data[i + 1] = 232 * albedo;
      img.data[i + 2] = 218 * albedo;
      img.data[i + 3] = 255 * edge * (0.1 + 0.9 * light);
    }
  }
  ctx.putImageData(img, 0, 0);
  return t;
}

const DOME_VERTEX = /* glsl */ `
varying vec3 vDir;
void main() {
  vDir = normalize(position);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const DOME_FRAGMENT = /* glsl */ `
uniform float uNight;
varying vec3 vDir;
void main() {
  float h = clamp(vDir.y, -0.2, 1.0);
  vec3 zenith = vec3(0.006, 0.01, 0.03);
  vec3 horizon = vec3(0.06, 0.055, 0.075);
  vec3 glow = vec3(0.16, 0.09, 0.05);
  vec3 col = mix(horizon, zenith, smoothstep(0.0, 0.5, h));
  col += glow * exp(-max(h, 0.0) * 14.0);
  gl_FragColor = vec4(col, uNight * 0.92);
}
`;

export interface HeavensState {
  sunDirection: THREE.Vector3;
  sunElevation: number;
  sunColor: THREE.Color;
  moon: MoonState;
  moonDirection: THREE.Vector3;
  night: number;
  clouds: number;
}

export class Heavens {
  readonly root = new THREE.Group();
  private readonly sun: THREE.Sprite;
  private readonly moon: THREE.Sprite;
  private readonly moonHalo: THREE.Sprite;
  private readonly stars: THREE.Points;
  private readonly dome: THREE.Mesh;
  private readonly domeNight = { value: 0 };
  // Моря Луны: гладкий шум в несколько октав, а не клетки одной решётки.
  private readonly maria = fbm(256, [3, 6, 12, 24], 4242);
  private moonKey = '';

  constructor() {
    this.root.name = 'heavens';
    const glow = glowTexture();
    this.sun = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: glow,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        fog: false,
      }),
    );
    this.sun.scale.setScalar(sphereScale(SUN_GLOW_DEG));
    this.moonHalo = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: glow,
        color: 0x9fb4d8,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        fog: false,
      }),
    );
    this.moonHalo.scale.setScalar(sphereScale(MOON_DEG * 5));
    this.moon = new THREE.Sprite(
      new THREE.SpriteMaterial({ transparent: true, depthWrite: false, fog: false }),
    );
    this.moon.scale.setScalar(sphereScale(MOON_DEG));
    this.stars = this.starField();
    this.dome = new THREE.Mesh(
      new THREE.SphereGeometry(RADIUS * 1.05, 32, 16),
      new THREE.ShaderMaterial({
        uniforms: { uNight: this.domeNight },
        vertexShader: DOME_VERTEX,
        fragmentShader: DOME_FRAGMENT,
        side: THREE.BackSide,
        transparent: true,
        depthWrite: false,
      }),
    );
    // Порядок поверх неба: купол, звёзды, ореол Луны, Луна, солнце.
    [this.dome, this.stars, this.moonHalo, this.moon, this.sun].forEach((o, i) => {
      o.renderOrder = -10 + i;
      o.frustumCulled = false;
      this.root.add(o);
    });
  }

  private starField(): THREE.Points {
    const pos = new Float32Array(STARS * 3);
    const col = new Float32Array(STARS * 3);
    let seed = 7;
    const random = () => {
      seed = (seed * 16807) % 2147483647;
      return seed / 2147483647;
    };
    for (let i = 0; i < STARS; i++) {
      // Равномерно по верхней полусфере с запасом под горизонт.
      const y = random() * 1.05 - 0.05;
      const a = random() * Math.PI * 2;
      const r = Math.sqrt(1 - y * y);
      pos.set(
        [Math.cos(a) * r * RADIUS * 0.98, y * RADIUS * 0.98, Math.sin(a) * r * RADIUS * 0.98],
        i * 3,
      );
      const b = 0.35 + random() ** 3 * 0.9;
      const warm = random();
      col.set([b * (0.85 + warm * 0.2), b * 0.92, b * (1.05 - warm * 0.2)], i * 3);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
    return new THREE.Points(
      g,
      new THREE.PointsMaterial({
        size: 1.8,
        sizeAttenuation: false,
        vertexColors: true,
        transparent: true,
        depthWrite: false,
        fog: false,
      }),
    );
  }

  update(s: HeavensState): void {
    this.sun.position.copy(s.sunDirection).multiplyScalar(RADIUS);
    const sunMaterial = this.sun.material;
    sunMaterial.color.copy(s.sunColor);
    sunMaterial.opacity =
      0.8 * THREE.MathUtils.smoothstep(s.sunElevation, -2.5, 2) * (1 - s.clouds * 0.55);
    this.sun.visible = sunMaterial.opacity > 0.01;

    this.moon.position.copy(s.moonDirection).multiplyScalar(RADIUS * 0.99);
    this.moonHalo.position.copy(this.moon.position);
    const up = THREE.MathUtils.smoothstep(s.moon.elevation, -1.5, 1.5);
    // Днём Луна бледная, как на настоящем небе; ночью - в полную силу.
    this.moon.material.opacity = up * (0.35 + 0.65 * s.night) * (1 - s.clouds * 0.5);
    this.moonHalo.material.opacity = up * s.night * s.moon.fraction * 0.35 * (1 - s.clouds * 0.6);
    this.moon.visible = this.moon.material.opacity > 0.01;
    this.moonHalo.visible = this.moonHalo.material.opacity > 0.01;
    const key = `${s.moon.fraction.toFixed(2)}:${String(s.moon.waxing)}`;
    if (key !== this.moonKey) {
      this.moonKey = key;
      this.moon.material.map?.dispose();
      this.moon.material.map = moonTexture(s.moon.fraction, s.moon.waxing, this.maria);
      this.moon.material.needsUpdate = true;
    }

    const starMaterial = this.stars.material as THREE.PointsMaterial;
    starMaterial.opacity = s.night ** 2 * (1 - s.clouds * 0.85);
    this.stars.visible = starMaterial.opacity > 0.01;
    this.domeNight.value = s.night;
    this.dome.visible = s.night > 0.01;
  }

  /** Сфера светил едет за камерой: они на бесконечности. */
  follow(camera: THREE.Camera): void {
    this.root.position.copy(camera.position);
  }

  dispose(): void {
    this.sun.material.map?.dispose();
    this.sun.material.dispose();
    this.moonHalo.material.dispose();
    this.moon.material.map?.dispose();
    this.moon.material.dispose();
    this.stars.geometry.dispose();
    (this.stars.material as THREE.Material).dispose();
    this.dome.geometry.dispose();
    (this.dome.material as THREE.Material).dispose();
  }
}
