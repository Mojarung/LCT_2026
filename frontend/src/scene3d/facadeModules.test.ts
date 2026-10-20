import * as THREE from 'three';
import { describe, expect, it, vi } from 'vitest';

import {
  disposeGroup,
  entranceGeometry,
  facadeModules,
  glassMaterial,
  loggiaGeometry,
  loggiaGlassGeometry,
  moduleMaterial,
  roofBoxGeometry,
} from './facadeModules';
import { facadePlan } from './facades';
import type { Building, Flat, Line } from './types';

function building(ring: Flat[], extra: Partial<Building> = {}): Building {
  return {
    rings: [ring],
    height: 28.2,
    floors: 9,
    source: 'label',
    kind: 'building',
    wall: 'brick',
    use: 'residential',
    seed: 6,
    ...extra,
  };
}

/** Девятиэтажка 60 x 12 м вдоль улицы, борт - в 15 м к югу. */
const SLAB = building([
  { x: 0, z: 0 },
  { x: 60, z: 0 },
  { x: 60, z: 12 },
  { x: 0, z: 12 },
]);
const CURB: Line = {
  points: [
    { x: -20, z: 27 },
    { x: 80, z: 27 },
  ],
};

const bbox = (g: THREE.BufferGeometry): THREE.Box3 => {
  g.computeBoundingBox();
  return g.boundingBox ?? new THREE.Box3();
};

describe('модули фасада: сетки', () => {
  it('лоджия в долях модуля; у остеклённой рамы, у открытой - перила', () => {
    const glazed = loggiaGeometry(true);
    const open = loggiaGeometry(false);
    for (const g of [glazed, open]) {
      const box = bbox(g);
      expect([box.min.x, box.max.x, box.min.y, box.max.y]).toEqual([-0.5, 0.5, 0, 1]);
      expect(g.getAttribute('color').count).toBe(g.getAttribute('position').count);
    }
    expect(glazed.getAttribute('position').count).toBeGreaterThan(
      open.getAttribute('position').count,
    );
    // Ограждение - цвета дома: у него единица в aAccent.
    const accent = open.getAttribute('aAccent');
    let tinted = 0;
    for (let i = 0; i < accent.count; i++) tinted += accent.getX(i);
    expect(tinted).toBeGreaterThan(0);
    expect(tinted).toBeLessThan(accent.count);
    const glass = bbox(loggiaGlassGeometry());
    expect(glass.max.z - glass.min.z).toBeLessThan(0.01);
  });

  it('подъезд в метрах: крыльцо, козырёк на 2,6-2,86 м; короб на крыше - в долях', () => {
    const entrance = bbox(entranceGeometry());
    expect(entrance.max.y).toBeCloseTo(2.86, 5);
    expect(entrance.max.x).toBeCloseTo(1.45, 5);
    const roof = bbox(roofBoxGeometry());
    expect(roof.max.y).toBeCloseTo(1.04, 5);
    expect(roof.min.z).toBeCloseTo(-0.52, 5);
  });

  it('материал модулей: цвет вершин и цвет экземпляра по aAccent; стекло отражает небо', () => {
    const m = moduleMaterial({ roughness: 0.3 });
    expect(m.vertexColors).toBe(true);
    expect(m.roughness).toBe(0.3);
    const shader = {
      uniforms: {},
      vertexShader: '#include <common>\n#include <color_vertex>',
      fragmentShader: '',
    };
    m.onBeforeCompile(
      shader as unknown as THREE.WebGLProgramParametersWithUniforms,
      {} as THREE.WebGLRenderer,
    );
    expect(shader.vertexShader).toContain('attribute float aAccent;');
    expect(shader.vertexShader).toContain(
      'mix( vColor.rgb, vColor.rgb * instanceColor.rgb, aAccent )',
    );
    expect(m.customProgramCacheKey()).toBe('green-facade-module');
    const glass = glassMaterial();
    expect(glass.roughness).toBe(0.1);
    expect(glass.envMapIntensity).toBeCloseTo(1.1, 6);
  });
});

describe('модули фасада: улица', () => {
  it('по сетке экземпляров на каждый вид модуля, число экземпляров - по плану фасада', () => {
    const plan = facadePlan(SLAB, [CURB]);
    const group = facadeModules([SLAB], [CURB]);
    expect(group.name).toBe('facade-modules');
    const byName = new Map(group.children.map((c) => [c.name, c]));
    const glazed = plan.loggias.filter((l) => l.glazed).length;
    const open = plan.loggias.length - glazed;
    if (glazed) {
      expect((byName.get('loggias-glazed') as THREE.InstancedMesh).count).toBe(glazed);
      expect((byName.get('loggia-glass') as THREE.InstancedMesh).count).toBe(glazed);
    }
    if (open) expect((byName.get('loggias-open') as THREE.InstancedMesh).count).toBe(open);
    expect(plan.loggias.length).toBeGreaterThan(0);
    const entrances = byName.get('entrances') as THREE.InstancedMesh | undefined;
    expect(entrances?.count ?? 0).toBe(plan.entrances.length);
    const roofs = byName.get('roof-boxes') as THREE.InstancedMesh | undefined;
    expect(roofs?.count ?? 0).toBe(plan.roofBoxes.length);
    expect(byName.get('parapets')).toBeInstanceOf(THREE.Mesh);
    const first = plan.loggias[0];
    const mesh = byName.get(
      first?.glazed ? 'loggias-glazed' : 'loggias-open',
    ) as THREE.InstancedMesh;
    const m = new THREE.Matrix4();
    mesh.getMatrixAt(0, m);
    const p = new THREE.Vector3().setFromMatrixPosition(m);
    const sameKind = plan.loggias.filter((l) => l.glazed === first?.glazed)[0];
    expect(p.x).toBeCloseTo(sameKind?.x ?? NaN, 4);
    expect(p.z).toBeCloseTo(sameKind?.z ?? NaN, 4);
    expect(mesh.instanceColor).not.toBeNull();
    expect(mesh.castShadow).toBe(true);
  });

  it('без парапетов по запросу; без домов - пустая группа', () => {
    const group = facadeModules([SLAB], [CURB], { parapets: false });
    expect(group.children.some((c) => c.name === 'parapets')).toBe(false);
    expect(facadeModules([], []).children).toHaveLength(0);
  });

  it('освобождение: сетки, экземпляры и общий материал - по одному разу', () => {
    const group = facadeModules([SLAB], [CURB]);
    group.add(new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial()));
    const materials = new Set<THREE.Material>();
    group.traverse((o) => {
      if (o instanceof THREE.Mesh || o instanceof THREE.LineSegments)
        materials.add(o.material as THREE.Material);
    });
    const spies = [...materials].map((m) => vi.spyOn(m, 'dispose'));
    disposeGroup(group);
    for (const spy of spies) expect(spy).toHaveBeenCalledTimes(1);
  });
});
