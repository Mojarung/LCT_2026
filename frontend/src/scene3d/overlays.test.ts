import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { boundaryOverlay, UTILITY_COLORS, utilityOverlay } from './overlays';
import type { Line } from './types';

const LINE: Line = {
  points: [
    { x: 0, z: 0 },
    { x: 10, z: 0 },
    { x: 10, z: 5 },
  ],
};

const hex = (o: THREE.Object3D): string =>
  `#${((o as THREE.Mesh).material as THREE.MeshBasicMaterial).color.getHexString()}`;

describe('рабочие слои 3D', () => {
  it('сеть - лента и тонкая линия цвета своего класса', () => {
    const group = utilityOverlay([
      { kind: 'utility.heat', lines: [LINE] },
      { kind: 'utility.unknown', lines: [LINE] },
      { kind: 'utility.gas', lines: [] },
    ]);
    expect(group.name).toBe('overlay-utilities');
    expect(group.children).toHaveLength(2);
    const [heat, other] = group.children as THREE.Group[];
    const [ribbon, thin] = heat?.children ?? [];
    expect(ribbon).toBeInstanceOf(THREE.Mesh);
    expect(thin).toBeInstanceOf(THREE.LineSegments);
    expect(hex(ribbon as THREE.Object3D)).toBe(UTILITY_COLORS['utility.heat']);
    expect(hex(other?.children[0] as THREE.Object3D)).toBe('#7a7264');
    expect(ribbon?.renderOrder).toBe(2);
    expect(thin?.renderOrder).toBe(3);
  });

  it('тонкая линия - по отрезку на каждый пролёт, над лентой', () => {
    const group = utilityOverlay([{ kind: 'utility.water', lines: [LINE] }]);
    const thin = (group.children[0] as THREE.Group).children[1] as THREE.LineSegments;
    const pos = thin.geometry.getAttribute('position');
    expect(pos.count).toBe(4);
    expect([pos.getX(2), pos.getZ(3)]).toEqual([10, 5]);
    expect(pos.getY(0)).toBeCloseTo(0.07, 5);
  });

  it('граница работ - тёмная лента, без линий пусто', () => {
    const group = boundaryOverlay([LINE]);
    expect(group.name).toBe('overlay-boundary');
    expect(hex((group.children[0] as THREE.Group).children[0] as THREE.Object3D)).toBe('#2b2620');
    expect(boundaryOverlay([]).children).toHaveLength(0);
  });
});
