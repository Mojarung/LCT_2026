import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { crownRadius, litterDensity, litterTexture, litterUniforms, withLitter } from './litter';

const tree = { x: 10, z: 10, type: 'existing_tree', existingRadius: 4 };

describe('карта осеннего опада', () => {
  it('под кроной ковёр, к краю опада на нет, вдали пусто', () => {
    const { data, width } = litterDensity([tree], [0, 0, 40, 40]);
    const at = (x: number, z: number) => data[Math.floor(z) * width + Math.floor(x)] ?? -1;
    expect(at(10, 10)).toBe(255);
    expect(at(13, 10)).toBeGreaterThan(at(15, 10));
    expect(at(15, 10)).toBeGreaterThan(0);
    expect(at(30, 30)).toBe(0);
  });

  it('кроны складываются, но не больше единицы', () => {
    const { data, width } = litterDensity([tree, { ...tree, x: 11 }], [0, 0, 40, 40]);
    expect(Math.max(...data)).toBe(255);
    expect(data[10 * width + 15]).toBeGreaterThan(
      litterDensity([tree], [0, 0, 40, 40]).data[10 * width + 15] ?? 0,
    );
  });

  it('радиус кроны: у съёмки - с подосновы, у посадок - по виду', () => {
    expect(crownRadius(tree)).toBe(4);
    expect(crownRadius({ type: 'tree' })).toBeGreaterThan(crownRadius({ type: 'shrub' }));
  });

  it('текстура покрывает прямоугольник сцены', () => {
    const { texture, rect } = litterTexture([tree], [-5, -5, 50, 30]);
    expect(rect.x).toBe(-5);
    expect(rect.z).toBeGreaterThanOrEqual(50);
    expect(texture.image.width * texture.image.height).toBeGreaterThan(0);
  });
});

describe('опад на чужом материале', () => {
  it('шейдер берёт униформы опада, мировые координаты и кладёт листья поверх карты', () => {
    const material = new THREE.MeshStandardMaterial();
    const uniforms = litterUniforms();
    withLitter(material, uniforms, 0.4);
    const shader = {
      uniforms: {} as Record<string, THREE.IUniform>,
      vertexShader: '#include <common>\n#include <worldpos_vertex>',
      fragmentShader: '#include <common>\n#include <map_fragment>',
    };
    material.onBeforeCompile(
      shader as unknown as THREE.WebGLProgramParametersWithUniforms,
      {} as THREE.WebGLRenderer,
    );
    expect(shader.uniforms.uLitterMap).toBe(uniforms.uLitterMap);
    expect(shader.vertexShader).toContain('varying vec3 vLitterPos;');
    expect(shader.vertexShader).toContain('vLitterPos = (modelMatrix');
    expect(shader.fragmentShader).toContain(
      'applyLitter(diffuseColor.rgb, vLitterPos.xz, 1.0, 0.40)',
    );
    expect(material.customProgramCacheKey()).toBe('litter-0.4');
    const plain = new THREE.MeshStandardMaterial();
    withLitter(plain, uniforms);
    expect(plain.customProgramCacheKey()).toBe('litter-0');
  });

  it('кусты и изгородь роняют опад с меньшего круга, чем дерево', () => {
    expect(crownRadius({ type: 'hedge' })).toBe(0.8);
    expect(crownRadius({ type: 'shrub' })).toBe(1.2);
    expect(crownRadius({ type: 'tree' })).toBeGreaterThan(1.2);
  });
});
