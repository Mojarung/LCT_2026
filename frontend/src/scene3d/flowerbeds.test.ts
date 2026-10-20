import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { flowerbedGroup, insideRings, scatterInRings } from './flowerbeds';
import type { Ring } from './types';

const square = (x0: number, z0: number, size: number): Ring => [
  { x: x0, z: z0 },
  { x: x0 + size, z: z0 },
  { x: x0 + size, z: z0 + size },
  { x: x0, z: z0 + size },
];

describe('цветник: россыпь растений по контуру', () => {
  it('кладёт растения только внутри контура и не в дыре, с плотностью на квадратный метр', () => {
    const bed = [square(0, 0, 4), square(1, 1, 2)]; // 16 м² минус дыра 4 м²
    const points = scatterInRings(bed, 10, 10_000, 3);
    expect(points.length).toBeGreaterThan(100);
    expect(points.length).toBeLessThan(140);
    expect(points.every((p) => insideRings(bed, p))).toBe(true);
    expect(points.some((p) => p.x > 1 && p.x < 3 && p.z > 1 && p.z < 3)).toBe(false);
  });

  it('ограничивает число растений', () => {
    expect(scatterInRings([square(0, 0, 100)], 25, 500, 3)).toHaveLength(500);
  });
});

describe('цветник в сцене', () => {
  it('без контуров клумбы нет', () => {
    expect(flowerbedGroup([])).toBeNull();
  });

  it('земля, кустики листвы и цветки внутри клумбы, цветки выше листвы', () => {
    const group = flowerbedGroup([[square(0, 0, 4)]]);
    expect(group?.name).toBe('flowerbeds');
    const [soil, leaves, flowers] = (group?.children ?? []) as [
      THREE.Mesh,
      THREE.InstancedMesh,
      THREE.InstancedMesh,
    ];
    expect((soil.material as THREE.MeshStandardMaterial).color.getHex()).toBe(0x3b2a1e);
    expect(soil.receiveShadow).toBe(true);
    expect(leaves.count).toBeGreaterThan(0);
    expect(flowers.count).toBeGreaterThan(leaves.count);
    const m = new THREE.Matrix4();
    const p = new THREE.Vector3();
    let leafTop = 0;
    for (let i = 0; i < leaves.count; i++) {
      leaves.getMatrixAt(i, m);
      p.setFromMatrixPosition(m);
      expect(insideRings([square(0, 0, 4)], { x: p.x, z: p.z })).toBe(true);
      leafTop = Math.max(leafTop, p.y);
    }
    flowers.getMatrixAt(0, m);
    expect(new THREE.Vector3().setFromMatrixPosition(m).y).toBeGreaterThanOrEqual(0.16);
    expect(leafTop).toBeLessThanOrEqual(0.12);
    expect(flowers.instanceColor).not.toBeNull();
  });

  it('раскладка повторяется по зерну', () => {
    const a = flowerbedGroup([[square(0, 0, 3)]], 5)?.children[1] as THREE.InstancedMesh;
    const b = flowerbedGroup([[square(0, 0, 3)]], 5)?.children[1] as THREE.InstancedMesh;
    expect(Array.from(a.instanceMatrix.array)).toEqual(Array.from(b.instanceMatrix.array));
  });
});
