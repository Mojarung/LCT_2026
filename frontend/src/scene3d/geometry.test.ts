import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { buildingGeometry, STYLE, styleOf } from './buildings';
import { fenceGeometry, nearestCurbDirection, ribbonBox } from './ground';
import type { Building, Flat } from './types';

function building(ring: Flat[], extra: Partial<Building> = {}): Building {
  return {
    rings: [ring],
    height: 10,
    floors: 3,
    source: 'label',
    kind: 'building',
    wall: null,
    use: null,
    seed: 4,
    ...extra,
  };
}

const square: Flat[] = [
  { x: 0, z: 0 },
  { x: 10, z: 0 },
  { x: 10, z: 10 },
  { x: 0, z: 10 },
];

/** Каждая нормаль стены смотрит от центра здания, и лицевая сторона треугольника - наружу. */
function outward(
  geometry: THREE.BufferGeometry,
  cx: number,
  cz: number,
  inverted = false,
): boolean {
  const pos = geometry.getAttribute('position');
  const nor = geometry.getAttribute('normal');
  const a = new THREE.Vector3();
  const b = new THREE.Vector3();
  const c = new THREE.Vector3();
  for (let i = 0; i < pos.count; i += 3) {
    a.fromBufferAttribute(pos, i);
    b.fromBufferAttribute(pos, i + 1);
    c.fromBufferAttribute(pos, i + 2);
    const face = new THREE.Vector3()
      .subVectors(b, a)
      .cross(new THREE.Vector3().subVectors(c, a))
      .normalize();
    const n = new THREE.Vector3(nor.getX(i), nor.getY(i), nor.getZ(i));
    const mid = a.clone().add(b).add(c).divideScalar(3);
    const away = new THREE.Vector3(mid.x - cx, 0, mid.z - cz).dot(n);
    if (face.dot(n) < 0.99) return false;
    if (inverted ? away > 0 : away < 0) return false;
  }
  return true;
}

describe('стены зданий', () => {
  it('нормали наружу и лицом наружу при любом обходе контура', () => {
    const ccw = buildingGeometry([building(square)]);
    expect(outward(ccw.walls, 5, 5)).toBe(true);
    const cw = buildingGeometry([building([...square].reverse())]);
    expect(outward(cw.walls, 5, 5)).toBe(true);
  });

  it('стены двора смотрят во двор', () => {
    const hole: Flat[] = [
      { x: 3, z: 3 },
      { x: 7, z: 3 },
      { x: 7, z: 7 },
      { x: 3, z: 7 },
    ];
    const g = buildingGeometry([{ ...building(square), rings: [square, hole] }]);
    const pos = g.walls.getAttribute('position');
    // Первые 4 стены - внешний контур, следующие 4 - двор: 24 вершины на кольцо.
    const court = new THREE.BufferGeometry();
    const slice = (pos.array as Float32Array).slice(24 * 3);
    court.setAttribute('position', new THREE.BufferAttribute(slice, 3));
    court.setAttribute(
      'normal',
      new THREE.BufferAttribute(
        (g.walls.getAttribute('normal').array as Float32Array).slice(24 * 3),
        3,
      ),
    );
    expect(outward(court, 5, 5, true)).toBe(true);
  });

  it('развёртка фасада - метры вдоль контура и от земли, крыша на высоте здания и смотрит вверх', () => {
    const g = buildingGeometry([building(square)]);
    const uv = g.walls.getAttribute('uv');
    let maxU = 0;
    let maxV = 0;
    for (let i = 0; i < uv.count; i++) {
      maxU = Math.max(maxU, uv.getX(i));
      maxV = Math.max(maxV, uv.getY(i));
    }
    expect(maxU).toBeCloseTo(40);
    expect(maxV).toBeCloseTo(10);
    const roof = g.roofs.getAttribute('position');
    expect(roof.count).toBe(6);
    expect(roof.getY(0)).toBe(10);
    const a = new THREE.Vector3().fromBufferAttribute(roof, 0);
    const b = new THREE.Vector3().fromBufferAttribute(roof, 1);
    const c = new THREE.Vector3().fromBufferAttribute(roof, 2);
    expect(
      new THREE.Vector3().subVectors(b, a).cross(new THREE.Vector3().subVectors(c, a)).y,
    ).toBeGreaterThan(0);
  });

  it('стиль фасада по подписям: металл, павильон, панельная высотка, крыльцо', () => {
    expect(styleOf(building(square, { wall: 'metal' }))).toBe(STYLE.metal);
    expect(styleOf(building(square, { floors: 1, use: 'non_residential' }))).toBe(STYLE.pavilion);
    expect(styleOf(building(square, { floors: 16 }))).toBe(STYLE.panel);
    expect(styleOf(building(square, { kind: 'porch', height: 0.45 }))).toBe(STYLE.porch);
  });
});

describe('борт, ограда и опоры', () => {
  const line = {
    points: [
      { x: 0, z: 0 },
      { x: 10, z: 0 },
      { x: 10, z: 5 },
    ],
  };

  it('брус борта: три грани на каждый пролёт, высота 15 см', () => {
    const g = ribbonBox([line], 0.15, 0.15);
    expect(g.getAttribute('position').count).toBe(2 * 3 * 6);
    g.computeBoundingBox();
    expect(g.boundingBox?.max.y).toBeCloseTo(0.15);
  });

  it('шаг прутьев ограды не зависит от длины пролёта', () => {
    const g = fenceGeometry([line], 1, 0.5);
    const uv = g.getAttribute('uv');
    let max = 0;
    for (let i = 0; i < uv.count; i++) max = Math.max(max, uv.getX(i));
    expect(max).toBeCloseTo(30);
  });

  it('консоль фонаря смотрит на ближайший борт, дальше 25 м борта нет', () => {
    const angle = nearestCurbDirection({ x: 5, z: -3 }, [line]);
    expect(angle).not.toBeNull();
    expect(Math.cos(angle ?? 0)).toBeCloseTo(1);
    expect(nearestCurbDirection({ x: 500, z: 500 }, [line])).toBeNull();
  });
});
