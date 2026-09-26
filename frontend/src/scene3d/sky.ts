/* Небо, солнце и воздух сцены.
 *
 * Небо - модель Preetham из примеров three.js (Sky, с облаками), солнце ставится по дню сезона
 * и часу над Москвой (solar.ts). Рассеянный свет - не константа: небо пересчитывается в карту
 * окружения (PMREM), и тени на асфальте голубеют в полдень и теплеют к вечеру сами. Тень солнца
 * одна, прямоугольник вокруг камеры: вся улица в одной карте теней дала бы по полметра на
 * пиксель. Прямоугольник сдвигается шагами в пиксель карты, иначе край тени мерцает. */

import * as THREE from 'three';
import { Sky } from 'three/addons/objects/Sky.js';

import { SEASON_DAY, type Season, sunDirection, sunPosition } from './solar';

export interface SkySettings {
  hour: number;
  season: Season;
  clouds: number;
  shadowSize: number;
  shadowExtent: number;
}

export interface SunState {
  direction: THREE.Vector3;
  elevation: number;
  color: THREE.Color;
  intensity: number;
  night: number;
}

/** Цвет солнца по высоте: у горизонта свет проходит толщу воздуха и краснеет. */
export function sunColor(elevation: number): THREE.Color {
  const t = THREE.MathUtils.clamp(elevation / 40, 0, 1);
  const warm = new THREE.Color(1.0, 0.62, 0.36);
  const noon = new THREE.Color(1.0, 0.97, 0.92);
  return warm.lerp(noon, Math.sqrt(t));
}

export class Atmosphere {
  readonly sky = new Sky();
  readonly sun = new THREE.DirectionalLight(0xffffff, 3);
  readonly hemi = new THREE.HemisphereLight(0xbfd4ff, 0x6b5a45, 0.35);
  readonly fog = new THREE.FogExp2(0xc4d0dc, 0.0011);
  readonly state: SunState = {
    direction: new THREE.Vector3(0, 1, 0),
    elevation: 45,
    color: new THREE.Color(),
    intensity: 3,
    night: 0,
  };
  private readonly pmrem: THREE.PMREMGenerator;
  private readonly envScene = new THREE.Scene();
  private envTarget: THREE.WebGLRenderTarget | null = null;
  private settings: SkySettings = {
    hour: 11,
    season: 'summer',
    clouds: 0.35,
    shadowSize: 4096,
    shadowExtent: 150,
  };

  constructor(
    private readonly renderer: THREE.WebGLRenderer,
    private readonly scene: THREE.Scene,
  ) {
    this.pmrem = new THREE.PMREMGenerator(renderer);
    this.sky.scale.setScalar(4500);
    this.sky.name = 'sky';
    const u = this.sky.material.uniforms;
    setUniform(u, 'turbidity', 4.5);
    setUniform(u, 'rayleigh', 1.6);
    setUniform(u, 'mieCoefficient', 0.004);
    setUniform(u, 'mieDirectionalG', 0.82);
    setUniform(u, 'cloudElevation', 0.55);
    setUniform(u, 'cloudDensity', 0.55);
    scene.add(this.sky);
    this.sun.castShadow = true;
    this.sun.shadow.bias = -0.00025;
    this.sun.shadow.normalBias = 0.035;
    scene.add(this.sun, this.sun.target, this.hemi);
    scene.fog = this.fog;
  }

  apply(settings: Partial<SkySettings>): void {
    const before = this.settings;
    this.settings = { ...before, ...settings };
    const s = this.settings;
    if (before.shadowSize !== s.shadowSize || !this.sun.shadow.map) {
      this.sun.shadow.mapSize.set(s.shadowSize, s.shadowSize);
      this.sun.shadow.map?.dispose();
      this.sun.shadow.map = null;
    }
    const cam = this.sun.shadow.camera;
    cam.left = -s.shadowExtent;
    cam.right = s.shadowExtent;
    cam.top = s.shadowExtent;
    cam.bottom = -s.shadowExtent;
    cam.near = 1;
    cam.far = 1200;
    cam.updateProjectionMatrix();
    this.updateSun();
  }

  private updateSun(): void {
    const s = this.settings;
    const pos = sunPosition(SEASON_DAY[s.season], s.hour);
    const [x, y, z] = sunDirection(pos);
    const dir = new THREE.Vector3(x, y, z).normalize();
    const u = this.sky.material.uniforms;
    setVector(u, 'sunPosition', dir);
    setUniform(u, 'cloudCoverage', s.clouds);
    const elevation = pos.elevation;
    const day = THREE.MathUtils.smoothstep(elevation, -6, 6);
    // Ночь - по гражданским сумеркам: солнце ниже 6 градусов под горизонтом.
    this.state.night = 1 - THREE.MathUtils.smoothstep(elevation, -8, 2);
    this.state.direction.copy(elevation > 0 ? dir : new THREE.Vector3(0.3, 0.6, 0.2).normalize());
    this.state.elevation = elevation;
    this.state.color.copy(elevation > 0 ? sunColor(elevation) : new THREE.Color(0.55, 0.62, 0.85));
    const cloudDim = 1 - s.clouds * 0.55;
    this.state.intensity =
      elevation > 0 ? (1.2 + 4.3 * THREE.MathUtils.smoothstep(elevation, 0, 35)) * cloudDim : 0.08;
    this.sun.color.copy(this.state.color);
    this.sun.intensity = this.state.intensity;
    this.hemi.intensity = 0.08 + 0.22 * day;
    this.hemi.color.set(day > 0.5 ? 0xc8dcff : 0x6f7fa8);
    const haze = new THREE.Color(0.74, 0.8, 0.87).lerp(
      new THREE.Color(0.95, 0.72, 0.52),
      1 - THREE.MathUtils.smoothstep(elevation, 2, 22),
    );
    haze.lerp(new THREE.Color(0.05, 0.07, 0.12), this.state.night);
    haze.lerp(new THREE.Color(0.78, 0.8, 0.82), s.clouds * 0.4 * day);
    this.fog.color.copy(haze);
    this.fog.density = 0.0006 + s.clouds * 0.0005;
    this.renderer.toneMappingExposure = 0.42 + 0.2 * day;
    this.environment();
  }

  /** Карта окружения из неба: рассеянный свет и отражения в стёклах. */
  private environment(): void {
    // Без диска солнца: он уже есть направленным светом с тенью, и в карте окружения светил
    // бы второй раз - сквозь стены и кроны, стирая все тени сцены.
    const u = this.sky.material.uniforms;
    setUniform(u, 'showSunDisc', 0);
    this.envScene.add(this.sky);
    const target = this.pmrem.fromScene(this.envScene, 0, 1, 5000);
    this.scene.add(this.sky);
    setUniform(u, 'showSunDisc', 1);
    this.envTarget?.dispose();
    this.envTarget = target;
    this.scene.environment = target.texture;
    this.scene.environmentIntensity =
      0.12 + 0.16 * THREE.MathUtils.smoothstep(this.state.elevation, -4, 20);
  }

  /** Тень вокруг точки, куда смотрит камера, с шагом в пиксель карты теней. */
  follow(focus: THREE.Vector3, time: number): void {
    const extent = this.settings.shadowExtent;
    const texel = (extent * 2) / this.settings.shadowSize;
    const light = this.sun;
    const dir = this.state.direction;
    // Ось тени: в системе света сдвигаем фокус на целое число пикселей.
    const basis = new THREE.Matrix4().lookAt(
      new THREE.Vector3(),
      dir.clone().negate(),
      new THREE.Vector3(0, 1, 0),
    );
    const inverse = basis.clone().invert();
    const local = focus.clone().applyMatrix4(inverse);
    local.x = Math.round(local.x / texel) * texel;
    local.y = Math.round(local.y / texel) * texel;
    const snapped = local.applyMatrix4(basis);
    light.target.position.copy(snapped);
    light.position.copy(snapped).addScaledVector(dir, 600);
    light.target.updateMatrixWorld();
    const u = this.sky.material.uniforms;
    setUniform(u, 'time', time);
  }

  dispose(): void {
    this.envTarget?.dispose();
    this.pmrem.dispose();
    this.sky.geometry.dispose();
    this.sky.material.dispose();
    this.sun.shadow.map?.dispose();
  }
}

type Uniforms = Record<string, THREE.IUniform>;

function setUniform(u: Uniforms, name: string, value: number): void {
  const uniform = u[name];
  if (uniform) uniform.value = value;
}

function setVector(u: Uniforms, name: string, value: THREE.Vector3): void {
  const uniform = u[name];
  if (uniform) (uniform.value as THREE.Vector3).copy(value);
}
