import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { lampAngle, StreetLights } from './streetlights';

describe('консоль фонаря', () => {
  it('к борту, но не над крышей дома: занятое направление сменяется обратным', () => {
    // Опора в метре от дома (дом - z < -1), борт за домом на z = -20.
    const curb = {
      points: [
        { x: -10, z: -20 },
        { x: 10, z: -20 },
      ],
    };
    const house = (p: { x: number; z: number }) => p.z < -1 && p.z > -15;
    const angle = lampAngle({ x: 0, z: 0 }, [curb], house);
    expect(Math.cos(angle)).toBeCloseTo(1, 6);
    // Без дома - прямо к борту.
    expect(Math.cos(lampAngle({ x: 0, z: 0 }, [curb], () => false))).toBeCloseTo(-1, 6);
  });
});

describe('опоры освещения в сцене', () => {
  const curb = {
    points: [
      { x: -50, z: 5 },
      { x: 50, z: 5 },
    ],
  };
  const poles = [
    { x: 0, z: 0 },
    { x: 20, z: 0 },
  ];

  it('без опор - пустой корень', () => {
    const lights = new StreetLights([], [curb]);
    expect(lights.root.name).toBe('street-lights');
    expect(lights.root.children).toHaveLength(0);
    lights.setNight(1);
    lights.dispose();
  });

  it('мачта, светильник, пятно и ореол на каждую опору, светильник над консолью к борту', () => {
    const lights = new StreetLights(poles, [curb]);
    const [mast, bulb, pool, halo] = lights.root.children as [
      THREE.InstancedMesh,
      THREE.InstancedMesh,
      THREE.InstancedMesh,
      THREE.Points,
    ];
    expect([mast.count, bulb.count, pool.count]).toEqual([2, 2, 2]);
    expect(mast.castShadow).toBe(true);
    expect(pool.renderOrder).toBe(1);
    const m = new THREE.Matrix4();
    bulb.getMatrixAt(1, m);
    const p = new THREE.Vector3().setFromMatrixPosition(m);
    // Борт на юге (+z): консоль 1,65 м к нему, светильник на 8 м.
    expect(p.x).toBeCloseTo(20, 5);
    expect(p.z).toBeCloseTo(1.65, 5);
    expect(p.y).toBeCloseTo(8, 5);
    pool.getMatrixAt(0, m);
    expect(new THREE.Vector3().setFromMatrixPosition(m).y).toBeCloseTo(0.05, 5);
    expect(halo.name).toBe('street-light-halos');
    expect(halo.geometry.getAttribute('position').count).toBe(2);
    expect(halo.visible).toBe(false);
  });

  it('ночью горят светильник, пятно и ореол, днём их нет', () => {
    const lights = new StreetLights(poles, [curb]);
    const [, bulb, pool, halo] = lights.root.children as [
      THREE.InstancedMesh,
      THREE.InstancedMesh,
      THREE.InstancedMesh,
      THREE.Points,
    ];
    lights.setNight(1);
    expect(pool.visible).toBe(true);
    expect(halo.visible).toBe(true);
    expect((halo.material as THREE.PointsMaterial).opacity).toBeCloseTo(0.8, 5);
    const color = (bulb.material as THREE.MeshBasicMaterial).color;
    expect(color.r).toBeGreaterThan(color.b);
    expect(color.r).toBeGreaterThan(2);
    const shader = pool.material as THREE.ShaderMaterial;
    expect(shader.uniforms.uNight?.value).toBe(1);
    lights.setNight(0);
    expect(pool.visible).toBe(false);
    expect(halo.visible).toBe(false);
    expect(color.r).toBeCloseTo(0.25, 5);
    lights.dispose();
  });

  it('без борта рядом консоль смотрит в +z, все стороны под крышей - к борту', () => {
    expect(lampAngle({ x: 0, z: 0 }, [], () => false)).toBe(0);
    const angle = lampAngle({ x: 0, z: 0 }, [curb], () => true);
    expect(Math.cos(angle)).toBeCloseTo(1, 6);
  });
});
