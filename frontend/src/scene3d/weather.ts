/* Погода 3D-вида: ветер, дождь, снег и листопад, у каждого сила от 0 до 1.
 *
 * Частицы не хранят положение на процессоре. Каждая - случайная точка в ящике, и шейдер
 * двигает её по формуле от времени (падение, снос ветром, покачивание), а ящик с переносом
 * на целое число сторон стоит вокруг камеры: осадки бесконечны, а кадр не тратит ни
 * миллисекунды на обновление буферов. Сила задаёт, сколько частиц из запаса рисуется.
 *
 * Погода меняет и остальную сцену (atmosphereOf): дождь и снег сгущают облака и дымку, дождь
 * мочит асфальт - он темнеет и начинает отражать небо, снег ложится на газоны, крыши и верх
 * крон, ветер качает деревья и траву и гонит облака. */

import * as THREE from 'three';

export interface WeatherSettings {
  wind: number;
  rain: number;
  snow: number;
  leaves: number;
}

export const CALM: WeatherSettings = { wind: 0.3, rain: 0, snow: 0, leaves: 0 };

/** Азимут, откуда дует ветер: в Москве чаще западный и юго-западный. */
const WIND_FROM_DEG = 250;
/** Скорость ветра при силе 1, м/с: крепкий ветер, при котором гнутся ветви. */
const WIND_MAX_MS = 12;

export interface WeatherEffect {
  /** Облачность неба с учётом осадков: дождь без туч выглядит нелепо. */
  clouds: number;
  /** Надбавка к плотности дымки: в снегопад видно на сотни метров, не на километры. */
  fog: number;
  /** Ветер в осях сцены, м/с (x - восток, z - юг). */
  windX: number;
  windZ: number;
  /** Сила качания крон для шейдера ветра. */
  sway: number;
  wet: number;
  snowCover: number;
}

export function atmosphereOf(w: WeatherSettings, clouds: number): WeatherEffect {
  const speed = w.wind * WIND_MAX_MS;
  // Ветер ДУЕТ ОТКУДА-ТО: вектор движения воздуха смотрит в противоположную сторону.
  const to = ((WIND_FROM_DEG + 180) * Math.PI) / 180;
  return {
    clouds: Math.max(clouds, w.rain * 0.95, w.snow * 0.85),
    fog: w.rain * 0.003 + w.snow * 0.006,
    windX: Math.sin(to) * speed,
    windZ: -Math.cos(to) * speed,
    sway: 0.05 + 1.15 * w.wind,
    wet: Math.min(1, w.rain * 1.4),
    snowCover: Math.min(1, w.snow * 1.25),
  };
}

/** Сколько частиц рисовать при силе intensity из запаса max: нарастание плавное с нуля. */
export function particleCount(max: number, intensity: number): number {
  return Math.round(max * Math.min(1, Math.max(0, intensity)) ** 1.3);
}

const RAIN_MAX = 30_000;
const SNOW_MAX = 24_000;
const LEAVES_MAX = 3_500;
/** Ящик осадков вокруг камеры, метры: шире поля зрения вблизи, дальше их прячет дымка. */
const BOX = new THREE.Vector3(90, 50, 90);
const LEAF_BOX = new THREE.Vector3(70, 22, 70);

interface Uniforms {
  [name: string]: THREE.IUniform;
  uCenter: { value: THREE.Vector3 };
  uBox: { value: THREE.Vector3 };
  uTime: { value: number };
  uWind: { value: THREE.Vector3 };
  uLight: { value: THREE.Color };
}

/** Перенос точки в ящик вокруг центра: частица, ушедшая за стенку, входит с другой стороны. */
const WRAP = /* glsl */ `
uniform vec3 uCenter;
uniform vec3 uBox;
uniform float uTime;
uniform vec3 uWind;
vec3 wrapBox(vec3 p) {
  return uCenter + mod(p - uCenter + uBox * 0.5, uBox) - uBox * 0.5;
}
`;

const RAIN_VERTEX = /* glsl */ `
${WRAP}
attribute vec4 aSeed;
attribute float aTail;
varying float vFade;
void main() {
  vec3 velocity = vec3(uWind.x, -8.5 - aSeed.w * 2.0, uWind.z);
  vec3 head = wrapBox(aSeed.xyz * uBox + velocity * uTime);
  vec3 p = head - normalize(velocity) * aTail * (0.45 + aSeed.w * 0.35);
  // Под землёй капли нет: там её доедает следующий оборот ящика.
  vFade = step(0.0, p.y) * (1.0 - smoothstep(0.35, 0.5, abs(head.y - uCenter.y) / uBox.y));
  gl_Position = projectionMatrix * viewMatrix * vec4(p, 1.0);
}
`;

const RAIN_FRAGMENT = /* glsl */ `
uniform vec3 uLight;
varying float vFade;
void main() {
  gl_FragColor = vec4(uLight * vec3(0.62, 0.68, 0.76), 0.32 * vFade);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
`;

const SNOW_VERTEX = /* glsl */ `
${WRAP}
attribute vec4 aSeed;
varying float vFade;
void main() {
  float t = uTime;
  vec3 drift = vec3(uWind.x * 0.9, -0.9 - aSeed.w * 0.6, uWind.z * 0.9);
  vec3 p = wrapBox(aSeed.xyz * uBox + drift * t);
  // Снежинка не падает прямо: кружится по небольшой окружности.
  float a = t * (0.8 + aSeed.w) + aSeed.x * 40.0;
  p.x += sin(a) * 0.35;
  p.z += cos(a * 1.3) * 0.35;
  vec4 mv = viewMatrix * vec4(p, 1.0);
  vFade = step(0.0, p.y) * (1.0 - smoothstep(0.35, 0.5, abs(p.y - uCenter.y) / uBox.y));
  gl_PointSize = clamp((0.035 + aSeed.w * 0.03) * 900.0 / -mv.z, 1.0, 9.0);
  gl_Position = projectionMatrix * mv;
}
`;

const SNOW_FRAGMENT = /* glsl */ `
uniform vec3 uLight;
varying float vFade;
void main() {
  float d = length(gl_PointCoord - 0.5) * 2.0;
  float a = smoothstep(1.0, 0.4, d);
  gl_FragColor = vec4(uLight * vec3(0.92, 0.94, 1.0), a * 0.9 * vFade);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
`;

const LEAF_VERTEX = /* glsl */ `
${WRAP}
attribute vec4 aSeed;
varying vec3 vColor;
varying float vFade;
varying vec2 vUv;
uniform vec3 uPalette[4];
mat3 rotation(vec3 axis, float angle) {
  float s = sin(angle);
  float c = cos(angle);
  float oc = 1.0 - c;
  return mat3(oc * axis.x * axis.x + c, oc * axis.x * axis.y + axis.z * s, oc * axis.z * axis.x - axis.y * s,
              oc * axis.x * axis.y - axis.z * s, oc * axis.y * axis.y + c, oc * axis.y * axis.z + axis.x * s,
              oc * axis.z * axis.x + axis.y * s, oc * axis.y * axis.z - axis.x * s, oc * axis.z * axis.z + c);
}
void main() {
  float t = uTime;
  vec3 drift = vec3(uWind.x, -1.1 - aSeed.w * 0.6, uWind.z);
  vec3 p = wrapBox(aSeed.xyz * uBox + drift * t);
  float sway = t * (0.9 + aSeed.w * 0.8) + aSeed.y * 30.0;
  p.x += sin(sway) * 0.8;
  p.z += cos(sway * 0.7) * 0.6;
  vec3 axis = normalize(aSeed.xyz - 0.5 + 0.001);
  vec3 leaf = rotation(axis, t * (1.5 + aSeed.w * 3.0) + aSeed.z * 6.28) * (position * (0.8 + aSeed.w * 0.6));
  vec3 world = p + leaf;
  int k = int(floor(fract(aSeed.x * 17.0 + aSeed.y * 5.0) * 4.0));
  vColor = uPalette[k] * (0.75 + 0.35 * fract(aSeed.w * 13.0));
  vUv = uv;
  vFade = step(0.0, world.y);
  gl_Position = projectionMatrix * viewMatrix * vec4(world, 1.0);
}
`;

const LEAF_FRAGMENT = /* glsl */ `
uniform vec3 uLight;
varying vec3 vColor;
varying float vFade;
varying vec2 vUv;
void main() {
  // Форма листа: заострённый овал по развёртке квадрата, остальное прозрачно.
  vec2 q = abs(vUv - 0.5) * 2.0;
  if (vFade < 0.5 || q.x + pow(q.y, 1.6) > 1.0) discard;
  gl_FragColor = vec4(vColor * uLight, 1.0);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
`;

function seeds(count: number, perVertex: number): Float32Array {
  const out = new Float32Array(count * perVertex * 4);
  let s = 12345;
  const random = () => {
    s = (s * 16807) % 2147483647;
    return s / 2147483647;
  };
  for (let i = 0; i < count; i++) {
    const seed = [random(), random(), random(), random()];
    for (let k = 0; k < perVertex; k++) out.set(seed, (i * perVertex + k) * 4);
  }
  return out;
}

function uniforms(box: THREE.Vector3): Uniforms {
  return {
    uCenter: { value: new THREE.Vector3() },
    uBox: { value: box.clone() },
    uTime: { value: 0 },
    uWind: { value: new THREE.Vector3() },
    uLight: { value: new THREE.Color(1, 1, 1) },
  };
}

/** Осенняя палитра листопада: жёлтый липы, оранжевый клёна, красный рябины, бурый дуба. */
const LEAF_PALETTE = ['#d8b43a', '#d0701e', '#b8392a', '#8a5a26'].map((hex) =>
  new THREE.Color(hex).convertSRGBToLinear(),
);

export class Weather {
  readonly root = new THREE.Group();
  private readonly rain: THREE.LineSegments;
  private readonly snow: THREE.Points;
  private readonly leaves: THREE.Mesh;
  private readonly rainU = uniforms(BOX);
  private readonly snowU = uniforms(BOX);
  private readonly leafU = uniforms(LEAF_BOX);
  private readonly leafGeometry: THREE.InstancedBufferGeometry;

  constructor() {
    this.root.name = 'weather';
    const rain = new THREE.BufferGeometry();
    rain.setAttribute(
      'position',
      new THREE.Float32BufferAttribute(new Float32Array(RAIN_MAX * 2 * 3), 3),
    );
    rain.setAttribute('aSeed', new THREE.Float32BufferAttribute(seeds(RAIN_MAX, 2), 4));
    const tail = new Float32Array(RAIN_MAX * 2);
    for (let i = 0; i < RAIN_MAX; i++) tail[i * 2 + 1] = 1;
    rain.setAttribute('aTail', new THREE.Float32BufferAttribute(tail, 1));
    this.rain = new THREE.LineSegments(
      rain,
      new THREE.ShaderMaterial({
        uniforms: this.rainU,
        vertexShader: RAIN_VERTEX,
        fragmentShader: RAIN_FRAGMENT,
        transparent: true,
        depthWrite: false,
      }),
    );
    const snow = new THREE.BufferGeometry();
    snow.setAttribute(
      'position',
      new THREE.Float32BufferAttribute(new Float32Array(SNOW_MAX * 3), 3),
    );
    snow.setAttribute('aSeed', new THREE.Float32BufferAttribute(seeds(SNOW_MAX, 1), 4));
    this.snow = new THREE.Points(
      snow,
      new THREE.ShaderMaterial({
        uniforms: this.snowU,
        vertexShader: SNOW_VERTEX,
        fragmentShader: SNOW_FRAGMENT,
        transparent: true,
        depthWrite: false,
      }),
    );
    this.leafGeometry = new THREE.InstancedBufferGeometry();
    this.leafGeometry.copy(
      new THREE.PlaneGeometry(0.07, 0.05) as unknown as THREE.InstancedBufferGeometry,
    );
    this.leafGeometry.setAttribute(
      'aSeed',
      new THREE.InstancedBufferAttribute(seeds(LEAVES_MAX, 1), 4),
    );
    this.leafGeometry.instanceCount = 0;
    this.leaves = new THREE.Mesh(
      this.leafGeometry,
      new THREE.ShaderMaterial({
        uniforms: { ...this.leafU, uPalette: { value: LEAF_PALETTE } },
        vertexShader: LEAF_VERTEX,
        fragmentShader: LEAF_FRAGMENT,
        side: THREE.DoubleSide,
      }),
    );
    for (const o of [this.rain, this.snow, this.leaves]) {
      o.frustumCulled = false;
      o.visible = false;
      this.root.add(o);
    }
  }

  apply(w: WeatherSettings, effect: WeatherEffect): void {
    const rain = particleCount(RAIN_MAX, w.rain);
    const snow = particleCount(SNOW_MAX, w.snow);
    const leaves = particleCount(LEAVES_MAX, w.leaves);
    this.rain.geometry.setDrawRange(0, rain * 2);
    this.snow.geometry.setDrawRange(0, snow);
    this.leafGeometry.instanceCount = leaves;
    this.rain.visible = rain > 0;
    this.snow.visible = snow > 0;
    this.leaves.visible = leaves > 0;
    for (const u of [this.rainU, this.snowU, this.leafU])
      u.uWind.value.set(effect.windX, 0, effect.windZ);
  }

  /** Ящики осадков за камерой; свет частиц - по яркости сцены, ночью капли не светятся. */
  update(camera: THREE.Camera, time: number, light: THREE.Color): void {
    for (const u of [this.rainU, this.snowU, this.leafU]) {
      u.uCenter.value.copy(camera.position);
      u.uTime.value = time;
      u.uLight.value.copy(light);
    }
    // Листья летят у земли, где кроны, а не на высоте облёта.
    this.leafU.uCenter.value.y = Math.min(camera.position.y, LEAF_BOX.y * 0.5);
  }

  dispose(): void {
    for (const o of [this.rain, this.snow, this.leaves]) {
      o.geometry.dispose();
      (o.material as THREE.Material).dispose();
    }
  }
}
