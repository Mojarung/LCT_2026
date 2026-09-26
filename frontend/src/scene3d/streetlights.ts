/* Опоры освещения: мачта с консолью к ближайшему борту, ночью - горящий светильник и пятно
 * тёплого света на земле. Точечный свет на каждую из сотен опор уронил бы кадр, поэтому пятно
 * - плоский диск с мягким краем, сложенный с землёй: издалека и с высоты глаз его не
 * отличить от света фонаря, а стоит он одну отрисовку на все опоры. */

import * as THREE from 'three';

import { nearestCurbDirection, streetLightGeometry } from './ground';
import type { Flat, Line } from './types';

/** Где светильник относительно опоры: консоль смотрит в +z модели (ground.ts). */
const HEAD = new THREE.Vector3(0, 8.0, 1.65);
/** Радиус пятна света на земле, метры: фонарь на 8 м освещает полосу около 15-20 м. */
const POOL_M = 9;

const POOL_FRAGMENT = /* glsl */ `
uniform float uNight;
varying vec2 vUv;
void main() {
  float d = length(vUv - 0.5) * 2.0;
  float a = pow(max(1.0 - d, 0.0), 2.2);
  gl_FragColor = vec4(vec3(1.0, 0.72, 0.42) * a * uNight * 0.55, 1.0);
}
`;

const POOL_VERTEX = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * instanceMatrix * vec4(position, 1.0);
}
`;

export class StreetLights {
  readonly root = new THREE.Group();
  private readonly night = { value: 0 };
  private readonly bulbMaterial = new THREE.MeshBasicMaterial({ color: 0x333333, fog: false });
  private readonly meshes: THREE.InstancedMesh[] = [];

  constructor(poles: readonly Flat[], curbs: readonly Line[]) {
    this.root.name = 'street-lights';
    if (!poles.length) return;
    const mast = new THREE.InstancedMesh(
      streetLightGeometry(),
      new THREE.MeshStandardMaterial({ color: 0x5b6166, roughness: 0.45, metalness: 0.7 }),
      poles.length,
    );
    mast.castShadow = true;
    const bulb = new THREE.InstancedMesh(
      new THREE.BoxGeometry(0.22, 0.05, 0.5),
      this.bulbMaterial,
      poles.length,
    );
    const pool = new THREE.InstancedMesh(
      new THREE.PlaneGeometry(POOL_M * 2, POOL_M * 2).rotateX(-Math.PI / 2),
      new THREE.ShaderMaterial({
        uniforms: { uNight: this.night },
        vertexShader: POOL_VERTEX,
        fragmentShader: POOL_FRAGMENT,
        blending: THREE.AdditiveBlending,
        transparent: true,
        depthWrite: false,
        polygonOffset: true,
        polygonOffsetFactor: -4,
        polygonOffsetUnits: -4,
      }),
      poles.length,
    );
    const m = new THREE.Matrix4();
    const head = new THREE.Vector3();
    poles.forEach((p, i) => {
      const angle = nearestCurbDirection(p, curbs) ?? 0;
      m.makeRotationY(angle).setPosition(p.x, 0, p.z);
      mast.setMatrixAt(i, m);
      head.copy(HEAD).applyAxisAngle(new THREE.Vector3(0, 1, 0), angle);
      m.makeRotationY(angle).setPosition(p.x + head.x, head.y - 0.06, p.z + head.z);
      bulb.setMatrixAt(i, m);
      m.makeTranslation(p.x + head.x, 0.05, p.z + head.z);
      pool.setMatrixAt(i, m);
    });
    for (const mesh of [mast, bulb, pool]) {
      mesh.frustumCulled = false;
      this.meshes.push(mesh);
      this.root.add(mesh);
    }
    pool.renderOrder = 1;
  }

  /** Ночью светильник горит и под ним пятно света, днём - серое стекло и ничего. */
  setNight(night: number): void {
    this.night.value = night;
    this.bulbMaterial.color.setRGB(0.25 + 2.2 * night, 0.25 + 1.7 * night, 0.25 + 1.1 * night);
    const pool = this.meshes[2];
    if (pool) pool.visible = night > 0.02;
  }

  dispose(): void {
    for (const mesh of this.meshes) {
      mesh.geometry.dispose();
      (mesh.material as THREE.Material).dispose();
      mesh.dispose();
    }
  }
}
