import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { carGeometry, carGroup, paintOf } from './cars';
import type { CarSpot } from './parking';

const box = (g: THREE.BufferGeometry): THREE.Box3 => {
  g.computeBoundingBox();
  return g.boundingBox ?? new THREE.Box3();
};

describe('машины: кузов', () => {
  it('у каждой вершины есть нормаль, цвет и доля цвета экземпляра', () => {
    const g = carGeometry(0);
    const count = g.getAttribute('position').count;
    expect(count).toBeGreaterThan(100);
    expect(g.getAttribute('normal').count).toBe(count);
    expect(g.getAttribute('color').count).toBe(count);
    expect(g.getAttribute('aAccent').count).toBe(count);
    expect(g.boundingSphere).not.toBeNull();
  });

  it('цвет экземпляра идёт только на кузов, стёкла и колёса своего цвета', () => {
    const accent = carGeometry(1).getAttribute('aAccent');
    const values = new Set<number>();
    for (let i = 0; i < accent.count; i++) values.add(accent.getX(i));
    expect([...values].sort()).toEqual([0, 1]);
  });

  it('стоит на земле, вдоль +x, шириной с машину, у кроссовера крыша выше', () => {
    const sedan = box(carGeometry(0));
    const crossover = box(carGeometry(2));
    expect(sedan.min.y).toBeCloseTo(0, 5);
    expect(sedan.max.x - sedan.min.x).toBeGreaterThan(4.6);
    expect(sedan.max.z - sedan.min.z).toBeCloseTo(1.8, 2);
    expect(crossover.max.y).toBeGreaterThan(sedan.max.y);
  });

  it('номер кузова берётся по кругу', () => {
    expect(carGeometry(3).getAttribute('position').count).toBe(
      carGeometry(0).getAttribute('position').count,
    );
  });
});

describe('машины: цвет', () => {
  it('по зерну, из палитры, больше всего белых', () => {
    const counts = new Map<string, number>();
    for (let seed = 0; seed < 800; seed++) {
      const c = paintOf(seed);
      counts.set(c, (counts.get(c) ?? 0) + 1);
    }
    expect(counts.size).toBe(8);
    const top = [...counts.entries()].sort((a, b) => b[1] - a[1])[0];
    expect(top?.[0]).toBe('#e9e9e6');
    expect(paintOf(0)).toBe(paintOf(0));
  });
});

describe('машины: сцена', () => {
  it('без мест - пустая группа', () => {
    const group = carGroup([]);
    expect(group.name).toBe('cars');
    expect(group.children).toHaveLength(0);
  });

  it('сетка экземпляров на каждый кузов, машина стоит в своей точке на высоте y', () => {
    const spots: CarSpot[] = [
      { x: 1, z: 2, angle: 0, seed: 0 },
      { x: 5, z: 6, angle: Math.PI / 2, seed: 3 },
      { x: 9, z: 9, angle: 0, seed: 1 },
    ];
    const group = carGroup(spots, -0.15);
    const meshes = group.children as THREE.InstancedMesh[];
    expect(meshes.map((m) => m.name)).toEqual(['cars-0', 'cars-1']);
    expect(meshes[0]?.count).toBe(2);
    expect(meshes[1]?.count).toBe(1);
    const m = new THREE.Matrix4();
    meshes[0]?.getMatrixAt(1, m);
    const p = new THREE.Vector3().setFromMatrixPosition(m);
    expect(p.x).toBe(5);
    expect(p.y).toBeCloseTo(-0.15, 5);
    expect(p.z).toBe(6);
    expect(meshes[0]?.castShadow).toBe(true);
    expect(meshes[0]?.instanceColor).not.toBeNull();
  });

  it('часть машин развёрнута на 180 градусов по биту зерна', () => {
    const group = carGroup([
      { x: 0, z: 0, angle: 0, seed: 0 },
      { x: 0, z: 0, angle: 0, seed: 3 << 7 },
    ]);
    const mesh = group.children[0] as THREE.InstancedMesh;
    const m = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const s = new THREE.Vector3();
    const t = new THREE.Vector3();
    mesh.getMatrixAt(0, m);
    m.decompose(t, q, s);
    expect(q.angleTo(new THREE.Quaternion())).toBeCloseTo(0, 5);
    mesh.getMatrixAt(1, m);
    m.decompose(t, q, s);
    expect(q.angleTo(new THREE.Quaternion())).toBeCloseTo(Math.PI, 5);
  });
});
