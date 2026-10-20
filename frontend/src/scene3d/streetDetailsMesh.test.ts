import * as THREE from 'three';
import { beforeEach, describe, expect, it } from 'vitest';

import { installCanvas, type InstalledCanvas } from '../test/canvas';
import type { Spot } from './streetDetails';
import { type StreetDetailInput, streetDetails } from './streetDetailsMesh';

let canvas: InstalledCanvas;
beforeEach(() => {
  canvas = installCanvas();
});

/** Земля: проезд (z > 4) на 0,15 м ниже тротуара. */
const levelAt = (_x: number, z: number) => (z > 4 ? -0.15 : 0);

function input(extra: Partial<StreetDetailInput> = {}): StreetDetailInput {
  return { grates: [], mulch: [], manholes: [], benches: [], bins: [], levelAt, ...extra };
}

function mesh(group: THREE.Group, name: string): THREE.InstancedMesh {
  const found = group.getObjectByName(name);
  if (!(found instanceof THREE.InstancedMesh)) throw new Error(`нет ${name}`);
  return found as THREE.InstancedMesh;
}

function at(m: THREE.InstancedMesh, i: number) {
  const matrix = new THREE.Matrix4();
  m.getMatrixAt(i, matrix);
  const p = new THREE.Vector3();
  const q = new THREE.Quaternion();
  const s = new THREE.Vector3();
  matrix.decompose(p, q, s);
  return { p, angle: new THREE.Euler().setFromQuaternion(q, 'YXZ').y };
}

describe('мелочи улицы', () => {
  it('без входных точек группа пустая', () => {
    const g = streetDetails(input());
    expect(g.name).toBe('street-details');
    expect(g.children).toHaveLength(0);
    expect(canvas.contexts).toHaveLength(0);
  });

  it('решётки и мульча лежат над землёй своей точки и условные', () => {
    const g = streetDetails(
      input({
        grates: [
          { x: 1, z: 2 },
          { x: 3, z: 8 },
        ],
        mulch: [{ x: -4, z: -1 }],
      }),
    );
    const grates = mesh(g, 'tree-grates');
    expect(grates.count).toBe(2);
    expect(at(grates, 0).p.y).toBeCloseTo(0.01);
    expect(at(grates, 1).p.y).toBeCloseTo(-0.14);
    expect(at(grates, 1).p.x).toBeCloseTo(3);
    expect(grates.userData.extra).toBe(true);
    const material = grates.material as THREE.MeshStandardMaterial;
    expect(material.map).toBeInstanceOf(THREE.CanvasTexture);
    expect(material.metalness).toBeCloseTo(0.35);
    expect(material.polygonOffset).toBe(true);

    const mulch = mesh(g, 'tree-mulch');
    expect(mulch.count).toBe(1);
    expect(at(mulch, 0).p.y).toBeCloseTo(0.012);
    const mulchMaterial = mulch.material as THREE.MeshStandardMaterial;
    expect(mulchMaterial.map).toBeNull();
    expect(mulchMaterial.metalness).toBe(0);
    expect(mulchMaterial.color.getHex()).toBe(0x4a3628);
    // Круг мульчи лежит в плоскости земли.
    mulch.geometry.computeBoundingBox();
    const box = mulch.geometry.boundingBox;
    expect(box?.max.y).toBeCloseTo(0);
    expect(box?.max.x).toBeCloseTo(0.75);
  });

  it('решётка рисует 32 щели-луча, люк - кольца и рифление', () => {
    streetDetails(input({ grates: [{ x: 0, z: 0 }], manholes: [{ x: 0, z: 6, angle: 0.3 }] }));
    expect(canvas.contexts).toHaveLength(2);
    const [grate, manhole] = canvas.contexts;
    expect(grate?.named('stroke')).toHaveLength(32 + 0);
    expect(grate?.named('strokeRect')).toHaveLength(1);
    expect(manhole?.named('strokeRect')).toHaveLength(0);
    // Рифление: по линии на каждые 16 пикселей от 30 до 226, затем два кольца.
    const ribs = Math.ceil((256 - 60) / 16);
    expect(manhole?.named('stroke')).toHaveLength(ribs + 2);
  });

  it('люки условные, пока не нарисованы в съёмке, и повёрнуты по точке', () => {
    const spots: Spot[] = [{ x: 2, z: 6, angle: 0.5 }];
    const drawn = mesh(streetDetails(input({ manholes: spots, manholesDrawn: true })), 'manholes');
    expect(drawn.userData.extra).toBeUndefined();
    const shown = mesh(streetDetails(input({ manholes: spots })), 'manholes');
    expect(shown.userData.extra).toBe(true);
    const { p, angle } = at(shown, 0);
    expect(p.y).toBeCloseTo(-0.15 + 0.008);
    expect(angle).toBeCloseTo(0.5);
  });

  it('скамейки со спинкой и без делятся на две пары экземпляров', () => {
    const g = streetDetails(
      input({
        benches: [
          { x: 0, z: 0, angle: 0 },
          { x: 5, z: 0, angle: Math.PI / 2, back: true },
          { x: 9, z: 1, angle: 0, back: false },
        ],
      }),
    );
    const back = mesh(g, 'benches');
    const flat = mesh(g, 'benches-flat');
    expect(back.count).toBe(2);
    expect(flat.count).toBe(1);
    expect(mesh(g, 'bench-legs').count).toBe(2);
    expect(mesh(g, 'bench-flat-legs').count).toBe(1);
    for (const m of [back, flat]) {
      expect(m.castShadow).toBe(true);
      expect(m.userData.extra).toBe(true);
    }
    // Спинка поднимает скамейку выше лавки без неё.
    back.geometry.computeBoundingBox();
    flat.geometry.computeBoundingBox();
    expect(back.geometry.boundingBox?.max.y ?? 0).toBeGreaterThan(0.75);
    expect(flat.geometry.boundingBox?.max.y ?? 0).toBeLessThan(0.5);
    expect(at(back, 1).angle).toBeCloseTo(Math.PI / 2);
  });

  it('нарисованные скамейки не условные, урны условные всегда', () => {
    const g = streetDetails(
      input({
        benches: [{ x: 0, z: 0, angle: 0 }],
        bins: [{ x: 1, z: 6, angle: 0 }],
        benchesDrawn: true,
      }),
    );
    expect(mesh(g, 'benches').userData.extra).toBe(false);
    expect(mesh(g, 'bench-legs').userData.extra).toBe(false);
    const bins = mesh(g, 'bins');
    expect(bins.userData.extra).toBe(true);
    expect(bins.castShadow).toBe(true);
    bins.geometry.computeBoundingBox();
    // Урна стоит на земле: низ на нуле, высота 0,72 м.
    expect(bins.geometry.boundingBox?.min.y).toBeCloseTo(0);
    expect(bins.geometry.boundingBox?.max.y).toBeCloseTo(0.72);
    expect(at(bins, 0).p.y).toBeCloseTo(-0.15);
  });
});
