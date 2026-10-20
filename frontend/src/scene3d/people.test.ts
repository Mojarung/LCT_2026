import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { cellPoint, type MaskGrid, People, type Person } from './people';

const CROWD: Person[] = [
  { x: 1, z: 2, heading: 0, span: 6, seed: 0.1 },
  { x: 5, z: -3, heading: Math.PI / 2, span: 0, seed: 0.9 },
  { x: -4, z: 7, heading: 1, span: 3, seed: 0.5 },
  { x: 0, z: 0, heading: 2, span: 0, seed: 0.3 },
];

function stub() {
  return {
    uniforms: {} as Record<string, THREE.IUniform>,
    vertexShader: '#include <common>\n#include <begin_vertex>',
    fragmentShader: '#include <common>\n#include <map_fragment>',
  };
}

const compile = (m: THREE.Material, shader: ReturnType<typeof stub>) => {
  m.onBeforeCompile(
    shader as unknown as THREE.WebGLProgramParametersWithUniforms,
    {} as THREE.WebGLRenderer,
  );
};

describe('люди на улице', () => {
  it('по экземпляру на человека, в своей точке, сначала никого не видно', () => {
    const people = new People(CROWD);
    expect(people.root.name).toBe('people');
    const mesh = people.root.children[0] as THREE.InstancedMesh;
    expect(mesh.count).toBe(0);
    expect(mesh.castShadow).toBe(true);
    const m = new THREE.Matrix4();
    mesh.getMatrixAt(1, m);
    const p = new THREE.Vector3();
    const q = new THREE.Quaternion();
    const s = new THREE.Vector3();
    m.decompose(p, q, s);
    expect([p.x, p.y, p.z]).toEqual([5, 0, -3]);
    expect(s.x).toBeCloseTo(0.92 + 0.9 * 0.16, 5);
    const walk = mesh.geometry.getAttribute('aWalk');
    expect(walk.getX(0)).toBe(6);
    expect(walk.getX(1)).toBe(0);
    expect(walk.getZ(2)).toBeCloseTo(0.5, 6);
    expect(mesh.geometry.getAttribute('aTop').count).toBe(4);
  });

  it('густота - доля от расставленных, в пределах 0..1', () => {
    const people = new People(CROWD);
    const mesh = people.root.children[0] as THREE.InstancedMesh;
    people.setDensity(0.5);
    expect(mesh.count).toBe(2);
    people.setDensity(3);
    expect(mesh.count).toBe(4);
    people.setDensity(-1);
    expect(mesh.count).toBe(0);
  });

  it('шаг в шейдере: время сцены, одежда по экземпляру, тень с той же походкой', () => {
    const people = new People(CROWD);
    const mesh = people.root.children[0] as THREE.InstancedMesh;
    const shader = stub();
    compile(mesh.material as THREE.Material, shader);
    people.update(12.5);
    expect(shader.uniforms.uTime?.value).toBe(12.5);
    expect(shader.vertexShader).toContain('attribute vec3 aTop;');
    expect(shader.vertexShader).toContain('vCloth = aTint > 1.5 ? aBottom');
    expect(shader.fragmentShader).toContain('diffuseColor.rgb *= vCloth;');
    expect((mesh.material as THREE.Material).customProgramCacheKey()).toBe('green-people');
    const depth = mesh.customDepthMaterial as THREE.MeshDepthMaterial;
    const shadow = stub();
    compile(depth, shadow);
    expect(shadow.uniforms.uTime).toBe(shader.uniforms.uTime);
    expect(shadow.vertexShader).toContain('uniform float uTime;');
    expect(depth.customProgramCacheKey()).toBe('green-people-depth');
    people.dispose();
  });

  it('дети: свой корень, меньше рост, медленнее шаг; пустая улица - один пустой экземпляр', () => {
    const kids = new People(CROWD, true);
    const adults = new People(CROWD);
    expect(kids.root.name).toBe('children');
    const kid = kids.root.children[0] as THREE.InstancedMesh;
    const adult = adults.root.children[0] as THREE.InstancedMesh;
    expect(kid.geometry.getAttribute('aWalk').getY(0)).toBeLessThan(
      adult.geometry.getAttribute('aWalk').getY(0),
    );
    kid.geometry.computeBoundingBox();
    adult.geometry.computeBoundingBox();
    expect(kid.geometry.boundingBox?.max.y ?? 0).toBeLessThan(
      adult.geometry.boundingBox?.max.y ?? 0,
    );
    const none = new People([]);
    const mesh = none.root.children[0] as THREE.InstancedMesh;
    none.setDensity(1);
    expect(mesh.count).toBe(0);
  });
});

describe('пиксель маски людей', () => {
  it('центр пикселя в координатах сцены', () => {
    const grid: MaskGrid = {
      kinds: new Uint8Array(16),
      width: 4,
      height: 4,
      rect: [10, 20, 4, 4],
      metresPerPx: 0.5,
    };
    expect(cellPoint(grid, 5)).toEqual({ x: 10.75, z: 20.75 });
  });
});
