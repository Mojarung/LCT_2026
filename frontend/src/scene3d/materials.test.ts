import * as THREE from 'three';
import { describe, expect, it, vi } from 'vitest';

import { loadGroundMaterials } from './materials';

describe('материалы земли', () => {
  it('девять текстур с повтором и анизотропией, цвет - в sRGB, нормали и ARM - без пространства', async () => {
    vi.spyOn(THREE.TextureLoader.prototype, 'loadAsync').mockImplementation(() =>
      Promise.resolve(new THREE.Texture<HTMLImageElement>()),
    );
    const m = await loadGroundMaterials(8);
    expect(m.textures).toHaveLength(9);
    expect(m.grass.wrapS).toBe(THREE.RepeatWrapping);
    expect(m.paversArmMap.wrapT).toBe(THREE.RepeatWrapping);
    expect(m.asphalt.anisotropy).toBe(8);
    expect(m.pavers.colorSpace).toBe(THREE.SRGBColorSpace);
    expect(m.grassNormalMap.colorSpace).toBe(THREE.NoColorSpace);
    expect(m.asphaltArmMap.colorSpace).toBe(THREE.NoColorSpace);
  });

  it('если хоть одна не загрузилась - остальные освобождаются и выходит понятная ошибка', async () => {
    const loaded: THREE.Texture[] = [];
    let n = 0;
    vi.spyOn(THREE.TextureLoader.prototype, 'loadAsync').mockImplementation(() => {
      n += 1;
      if (n === 4) return Promise.reject(new Error('404'));
      const t = new THREE.Texture<HTMLImageElement>();
      loaded.push(t);
      return Promise.resolve(t);
    });
    const disposed = vi.fn();
    const spy = vi.spyOn(THREE.Texture.prototype, 'dispose').mockImplementation(disposed);
    await expect(loadGroundMaterials(1)).rejects.toThrow('Не удалось загрузить материалы 3D');
    expect(loaded).toHaveLength(8);
    expect(spy).toHaveBeenCalledTimes(8);
  });
});
