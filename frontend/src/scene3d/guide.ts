/* Рамка размеров посадки под прицелом: кольцо диаметра кроны на её середине, такое же кольцо
 * на земле и мачта до верха кроны. По ней видно, что подпись «высота, крона» в 3D-виде
 * совпадает с моделью: модель подогнана к этим числам (fit.ts). */

import * as THREE from 'three';

const SEGMENTS = 64;
const COLOR = 0xf2d16b;

export interface SizeGuide {
  group: THREE.Group;
  show(x: number, z: number, height: number, crown: number): void;
  hide(): void;
}

/** Середина кроны по высоте: та же, что у шара кроны при выборе прицелом (pick.ts). */
export function crownMiddle(height: number, crown: number): number {
  const r = Math.max(crown / 2, 0.3);
  return Math.max(height - r, height * 0.6);
}

export function sizeGuide(): SizeGuide {
  const material = new THREE.LineBasicMaterial({
    color: COLOR,
    transparent: true,
    opacity: 0.9,
    depthTest: false,
  });
  const circle = new THREE.BufferGeometry().setFromPoints(
    Array.from({ length: SEGMENTS }, (_, i) => {
      const t = (i / SEGMENTS) * Math.PI * 2;
      return new THREE.Vector3(Math.cos(t), 0, Math.sin(t));
    }),
  );
  const mast = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(0, 1, 0),
  ]);
  const ring = new THREE.LineLoop(circle, material);
  const ground = new THREE.LineLoop(circle, material);
  const pole = new THREE.Line(mast, material);
  const group = new THREE.Group();
  group.add(ring, ground, pole);
  group.visible = false;
  group.renderOrder = 10;
  for (const child of group.children) child.renderOrder = 10;
  return {
    group,
    show(x, z, height, crown) {
      const r = Math.max(crown / 2, 0.05);
      group.position.set(x, 0, z);
      ring.position.y = crownMiddle(height, crown);
      ring.scale.set(r, 1, r);
      ground.position.y = 0.05;
      ground.scale.set(r, 1, r);
      pole.scale.set(1, Math.max(height, 0.05), 1);
      group.visible = true;
    },
    hide() {
      group.visible = false;
    },
  };
}
