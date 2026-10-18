/* Опоры освещения: мачта с консолью к ближайшему борту, ночью - горящий светильник и пятно
 * тёплого света на земле. Точечный свет на каждую из сотен опор уронил бы кадр, поэтому пятно
 * - плоский диск с мягким краем, сложенный с землёй: издалека и с высоты глаз его не
 * отличить от света фонаря, а стоит он одну отрисовку на все опоры. */

import * as THREE from 'three';

import { nearestCurbDirection, streetLightGeometry } from './ground';
import type { Flat, Line } from './types';

/** Где светильник относительно опоры: консоль смотрит в +z модели (ground.ts). */
const HEAD = new THREE.Vector3(0, 8.06, 1.65);
/** Радиус пятна света на земле, метры: фонарь на 8 м освещает полосу около 15-20 м. */
const POOL_M = 10;
/** Ореол светильника, метры: издалека горящий фонарь виден светлой точкой, а не тёмной
 *  коробкой (пользователь, 18.10.2026: «чтобы все лампы светились ночью»). */
const HALO_M = 9;

const POOL_FRAGMENT = /* glsl */ `
uniform float uNight;
varying vec2 vUv;
void main() {
  float d = length(vUv - 0.5) * 2.0;
  float a = pow(max(1.0 - d, 0.0), 2.2);
  gl_FragColor = vec4(vec3(1.0, 0.72, 0.42) * a * uNight * 0.8, 1.0);
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
  private halo: THREE.Points | null = null;

  constructor(poles: readonly Flat[], curbs: readonly Line[]) {
    this.root.name = 'street-lights';
    if (!poles.length) return;
    const mast = new THREE.InstancedMesh(
      streetLightGeometry(),
      new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.8, metalness: 0.1 }),
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
    this.halo = haloPoints(poles, curbs);
    this.root.add(this.halo);
  }

  /** Ночью светильник горит и под ним пятно света, днём - серое стекло и ничего. */
  setNight(night: number): void {
    this.night.value = night;
    this.bulbMaterial.color.setRGB(0.25 + 2.2 * night, 0.25 + 1.7 * night, 0.25 + 1.1 * night);
    const pool = this.meshes[2];
    if (pool) pool.visible = night > 0.02;
    if (this.halo) {
      this.halo.visible = night > 0.02;
      (this.halo.material as THREE.PointsMaterial).opacity = 0.8 * night;
    }
  }

  dispose(): void {
    if (this.halo) {
      this.halo.geometry.dispose();
      const material = this.halo.material as THREE.PointsMaterial;
      material.map?.dispose();
      material.dispose();
    }
    for (const mesh of this.meshes) {
      mesh.geometry.dispose();
      (mesh.material as THREE.Material).dispose();
      mesh.dispose();
    }
  }
}

/** Ореолы светильников одним облаком точек: точка всегда смотрит в камеру и сложена со сценой,
 *  поэтому сотни фонарей стоят одну отрисовку. */
function haloPoints(poles: readonly Flat[], curbs: readonly Line[]): THREE.Points {
  const positions = new Float32Array(poles.length * 3);
  const head = new THREE.Vector3();
  const up = new THREE.Vector3(0, 1, 0);
  poles.forEach((p, i) => {
    const angle = nearestCurbDirection(p, curbs) ?? 0;
    head.copy(HEAD).applyAxisAngle(up, angle);
    positions.set([p.x + head.x, head.y - 0.15, p.z + head.z], i * 3);
  });
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  const material = new THREE.PointsMaterial({
    size: HALO_M,
    sizeAttenuation: true,
    map: haloTexture(),
    color: new THREE.Color(1.0, 0.82, 0.55),
    transparent: true,
    opacity: 0,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    fog: false,
    // Ореол ярче тон-маппинга ночной сцены: иначе фонарь гаснет вместе с экспозицией.
    toneMapped: false,
  });
  const points = new THREE.Points(geometry, material);
  points.name = 'street-light-halos';
  points.frustumCulled = false;
  points.visible = false;
  return points;
}

/** Мягкое пятно ореола: яркая середина, плавный спад к краю. */
function haloTexture(): THREE.Texture {
  const size = 64;
  const data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const d = Math.hypot(x + 0.5 - size / 2, y + 0.5 - size / 2) / (size / 2);
      const a = Math.pow(Math.max(1 - d, 0), 2.4);
      const i = (y * size + x) * 4;
      data.set([255, 255, 255, Math.round(255 * a)], i);
    }
  }
  const texture = new THREE.DataTexture(data, size, size);
  texture.needsUpdate = true;
  return texture;
}
