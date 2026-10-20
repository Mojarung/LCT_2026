import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { atmosphereOf, CALM, Weather } from './weather';

function parts(w: Weather) {
  const [rain, snow, leaves] = w.root.children as [THREE.LineSegments, THREE.Points, THREE.Mesh];
  const u = (o: THREE.Object3D) => ((o as THREE.Mesh).material as THREE.ShaderMaterial).uniforms;
  return { rain, snow, leaves, u };
}

describe('осадки в сцене', () => {
  it('три облака частиц: капли отрезками, снег точками, листья плоскостями, сначала скрыты', () => {
    const w = new Weather();
    const { rain, snow, leaves } = parts(w);
    expect(w.root.name).toBe('weather');
    expect(rain).toBeInstanceOf(THREE.LineSegments);
    expect(snow).toBeInstanceOf(THREE.Points);
    expect(leaves).toBeInstanceOf(THREE.Mesh);
    expect(rain.geometry.getAttribute('position').count).toBe(60_000);
    // У капли две вершины: голова и хвост.
    const tail = rain.geometry.getAttribute('aTail');
    expect([tail.getX(0), tail.getX(1)]).toEqual([0, 1]);
    const seed = rain.geometry.getAttribute('aSeed');
    expect(seed.getX(0)).toBe(seed.getX(1));
    expect(snow.geometry.getAttribute('position').count).toBe(24_000);
    expect((leaves.geometry as THREE.InstancedBufferGeometry).instanceCount).toBe(0);
    for (const o of [rain, snow, leaves]) {
      expect(o.visible).toBe(false);
      expect(o.frustumCulled).toBe(false);
    }
  });

  it('сила осадков задаёт число частиц, ветер - во все шейдеры', () => {
    const w = new Weather();
    const { rain, snow, leaves, u } = parts(w);
    const settings = { wind: 1, rain: 1, snow: 0, leaves: 0.5 };
    const effect = atmosphereOf(settings, 0);
    w.apply(settings, effect);
    expect(rain.visible).toBe(true);
    expect(rain.geometry.drawRange.count).toBe(60_000);
    expect(snow.visible).toBe(false);
    expect(leaves.visible).toBe(true);
    expect((leaves.geometry as THREE.InstancedBufferGeometry).instanceCount).toBe(
      Math.round(3500 * 0.5 ** 1.3),
    );
    const wind = u(snow).uWind?.value as THREE.Vector3;
    expect(wind.x).toBeCloseTo(effect.windX, 5);
    expect(wind.z).toBeCloseTo(effect.windZ, 5);
    expect((u(leaves).uPalette?.value as THREE.Color[]).length).toBe(4);
    w.apply(CALM, atmosphereOf(CALM, 0));
    expect(rain.visible).toBe(false);
    expect(leaves.visible).toBe(false);
  });

  it('ящики идут за камерой, листья - у земли, свет частиц - по сцене', () => {
    const w = new Weather();
    const { rain, leaves, u } = parts(w);
    const camera = new THREE.PerspectiveCamera();
    camera.position.set(5, 60, -7);
    w.update(camera, 3, new THREE.Color(0.2, 0.3, 0.4));
    expect((u(rain).uCenter?.value as THREE.Vector3).toArray()).toEqual([5, 60, -7]);
    expect((u(leaves).uCenter?.value as THREE.Vector3).y).toBe(11);
    expect(u(rain).uTime?.value).toBe(3);
    expect((u(rain).uLight?.value as THREE.Color).g).toBeCloseTo(0.3, 5);
    camera.position.y = 2;
    w.update(camera, 4, new THREE.Color());
    expect((u(leaves).uCenter?.value as THREE.Vector3).y).toBe(2);
    w.dispose();
  });
});
