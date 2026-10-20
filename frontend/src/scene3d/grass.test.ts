import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import type { MaskInfo } from './ground';
import {
  GRASS_PRESETS,
  GrassField,
  grassGeometry,
  grassMaterial,
  type GrassUniforms,
} from './grass';

const OPTS = { size: 10, count: 50, radius: 5 };

function mask(withGrass: boolean): MaskInfo {
  const tex = new THREE.DataTexture(new Uint8Array(4), 1, 1);
  return {
    texture: tex,
    grass: withGrass ? new THREE.DataTexture(new Uint8Array(4), 1, 1) : undefined,
    rect: [-5, -6, 20, 30],
    kinds: new Uint8Array(1),
    known: new Uint8Array(1),
    edges: { road: [], garden: [] },
    road: new Uint8Array(1),
    cut: new THREE.DataTexture(new Uint8Array(1), 1, 1),
    width: 1,
    height: 1,
    metresPerPx: 1,
  };
}

const SHADER_STUB = {
  vertexShader:
    '#include <common>\n#include <beginnormal_vertex>\n#include <begin_vertex>\nvoid main(){}',
  fragmentShader: '#include <common>\n#include <normal_fragment_begin>\n#include <map_fragment>',
  uniforms: {} as Record<string, THREE.IUniform>,
};

describe('травинки', () => {
  it('пресеты: на слабой графике травы нет, на сильной больше травинок', () => {
    expect(GRASS_PRESETS.low).toBeNull();
    expect(GRASS_PRESETS.high?.count).toBeGreaterThan(GRASS_PRESETS.medium?.count ?? 0);
  });

  it('травинка - 7 вершин и 5 треугольников, раскладка внутри квадрата', () => {
    const g = grassGeometry(OPTS);
    expect(g.getAttribute('position').count).toBe(7);
    expect(g.getIndex()?.count).toBe(15);
    expect(g.instanceCount).toBe(50);
    const offsets = g.getAttribute('aOffset');
    for (let i = 0; i < offsets.count; i++) {
      expect(offsets.getX(i)).toBeGreaterThanOrEqual(0);
      expect(offsets.getY(i)).toBeLessThan(10);
    }
    expect(g.getAttribute('aBlade').itemSize).toBe(4);
  });

  it('раскладка повторяется по зерну и меняется с ним', () => {
    const a = grassGeometry(OPTS, 3).getAttribute('aOffset').array;
    const b = grassGeometry(OPTS, 3).getAttribute('aOffset').array;
    const c = grassGeometry(OPTS, 4).getAttribute('aOffset').array;
    expect(Array.from(a)).toEqual(Array.from(b));
    expect(Array.from(a)).not.toEqual(Array.from(c));
  });

  it('шейдер получает униформы и код травинок вместо стандартных вставок', () => {
    const uniforms = { uTime: { value: 2 } } as unknown as GrassUniforms;
    const m = grassMaterial(uniforms);
    const shader = { ...SHADER_STUB, uniforms: {} as Record<string, THREE.IUniform> };
    m.onBeforeCompile(
      shader as unknown as THREE.WebGLProgramParametersWithUniforms,
      undefined as never,
    );
    expect(shader.uniforms.uTime).toBe(uniforms.uTime);
    expect(shader.vertexShader).toContain('attribute vec2 aOffset;');
    expect(shader.vertexShader).toContain('vec3 objectNormal = vec3(0.0, 1.0, 0.0);');
    expect(shader.vertexShader).not.toContain('#include <begin_vertex>');
    expect(shader.fragmentShader).toContain('varying vec3 vGrass;');
    expect(shader.fragmentShader).toContain('grassTip');
    expect(m.customProgramCacheKey()).toBe('green-grass');
    expect(m.side).toBe(THREE.DoubleSide);
  });
});

describe('поле травы', () => {
  it('берёт газон без покрытий, если он есть, и прямоугольник маски', () => {
    const noise = new THREE.Texture();
    const withGrass = mask(true);
    const field = new GrassField(withGrass, noise, OPTS);
    expect(field.uniforms.uMask.value).toBe(withGrass.grass);
    expect(field.uniforms.uMaskRect.value.toArray()).toEqual([-5, -6, 20, 30]);
    expect(field.mesh.frustumCulled).toBe(false);
    const plain = mask(false);
    expect(new GrassField(plain, noise, OPTS).uniforms.uMask.value).toBe(plain.texture);
  });

  it('идёт за камерой и гаснет выше 25 м', () => {
    const field = new GrassField(mask(false), new THREE.Texture(), OPTS);
    const camera = new THREE.PerspectiveCamera();
    camera.position.set(3, 1.7, -4);
    field.update(camera, 7);
    expect(field.uniforms.uCenter.value.toArray()).toEqual([3, -4]);
    expect(field.uniforms.uTime.value).toBe(7);
    expect(field.mesh.visible).toBe(true);
    camera.position.y = 30;
    field.update(camera, 8);
    expect(field.mesh.visible).toBe(false);
    field.dispose();
  });
});
