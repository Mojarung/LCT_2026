/* Небо, солнце и воздух сцены.
 *
 * Небо - модель Preetham из примеров three.js (Sky, с облаками), солнце ставится по дню сезона
 * и часу над Москвой (solar.ts). Рассеянный свет - не константа: небо пересчитывается в карту
 * окружения (PMREM), и тени на асфальте голубеют в полдень и теплеют к вечеру сами. Тень солнца
 * одна, прямоугольник вокруг камеры: вся улица в одной карте теней дала бы по полметра на
 * пиксель. Прямоугольник сдвигается шагами в пиксель карты, иначе край тени мерцает.
 * Ночью направленный свет - от Луны (celestial.ts): голубоватый, по силе - по фазе, и
 * тени в полнолуние есть, как на настоящей улице. */

import * as THREE from 'three';
import { Sky } from 'three/addons/objects/Sky.js';

import { moonState, sceneTime } from './celestial';
import { Heavens } from './heavens';
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
  readonly heavens = new Heavens();
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
    setUniform(u, 'mieCoefficient', 0.0028);
    // Узкий лепесток рассеяния: ореол плотнее, диск солнца на закате читается, а не тонет в
    // белом пятне на полнеба.
    setUniform(u, 'mieDirectionalG', 0.94);
    setUniform(u, 'cloudElevation', 0.55);
    setUniform(u, 'cloudDensity', 0.55);
    scene.add(this.sky);
    this.sun.castShadow = true;
    this.sun.shadow.bias = -0.00025;
    this.sun.shadow.normalBias = 0.035;
    scene.add(this.sun, this.sun.target, this.hemi, this.heavens.root);
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
    const moon = moonState(sceneTime(SEASON_DAY[s.season], s.hour));
    const [mx, my, mz] = sunDirection(moon);
    const moonDir = new THREE.Vector3(mx, my, mz).normalize();
    const cloudDim = 1 - s.clouds * 0.55;
    this.state.elevation = elevation;
    if (elevation > 0) {
      this.state.direction.copy(dir);
      this.state.color.copy(sunColor(elevation));
      this.state.intensity = (1.2 + 4.3 * THREE.MathUtils.smoothstep(elevation, 0, 35)) * cloudDim;
    } else {
      // Солнце под горизонтом: светит Луна, если она над ним, иначе - слабый свет неба сверху.
      const moonUp = THREE.MathUtils.smoothstep(moon.elevation, 0, 12);
      this.state.direction.copy(
        moon.elevation > 0 ? moonDir : new THREE.Vector3(0.2, 1, 0.1).normalize(),
      );
      this.state.color.set(0x9fb2d6);
      this.state.intensity = (0.03 + 0.32 * moon.fraction * moonUp) * cloudDim;
    }
    this.heavens.update({
      sunDirection: dir,
      sunElevation: elevation,
      sunColor: sunColor(Math.max(elevation, 0)),
      moon,
      moonDirection: moonDir,
      night: this.state.night,
      clouds: s.clouds,
    });
    this.sun.color.copy(this.state.color);
    this.sun.intensity = this.state.intensity;
    this.hemi.intensity = 0.14 + 0.16 * day;
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
    const centre = this.sky.position.clone();
    this.sky.position.set(0, 0, 0);
    this.envScene.add(this.sky);
    const target = this.pmrem.fromScene(this.envScene, 0, 1, 5000);
    this.scene.add(this.sky);
    this.sky.position.copy(centre);
    setUniform(u, 'showSunDisc', 1);
    this.envTarget?.dispose();
    this.envTarget = target;
    this.scene.environment = target.texture;
    this.scene.environmentIntensity =
      0.12 + 0.16 * THREE.MathUtils.smoothstep(this.state.elevation, -4, 20);
  }

  /** Небо и светила вокруг камеры: коробка неба конечна, и в стороне от начала сцены
   *  светила вышли бы за её стенку. */
  center(camera: THREE.Camera): void {
    this.sky.position.copy(camera.position);
    this.heavens.follow(camera);
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
    this.heavens.dispose();
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
