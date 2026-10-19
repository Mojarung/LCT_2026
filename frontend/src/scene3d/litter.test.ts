import { describe, expect, it } from 'vitest';

import { crownRadius, litterDensity, litterTexture } from './litter';

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
