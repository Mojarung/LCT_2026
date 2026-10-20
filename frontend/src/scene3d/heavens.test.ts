import * as THREE from 'three';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { installCanvas, type InstalledCanvas } from '../test/canvas';
import type { MoonState } from './celestial';
import { Heavens, type HeavensState, moonTexture } from './heavens';

let canvas: InstalledCanvas;
beforeEach(() => {
  canvas = installCanvas();
});

/** Пиксели диска Луны: что записал moonTexture в записывающий холст. */
function moonPixels(fraction: number, waxing: boolean, size = 32) {
  const maria = new Float32Array(size * size).fill(0.5);
  const texture = moonTexture(fraction, waxing, maria, size);
  const fake = canvas.of(texture.image);
  const put = fake?.named('putImageData')[0];
  const img = put?.args[0] as { data: Uint8ClampedArray };
  const alpha = (x: number, y: number) => img.data[(y * size + x) * 4 + 3] ?? -1;
  return { texture, alpha, size };
}

function moon(over: Partial<MoonState> = {}): MoonState {
  return { elevation: 30, azimuth: 150, fraction: 1, waxing: true, ...over };
}

function state(over: Partial<HeavensState> = {}): HeavensState {
  return {
    sunDirection: new THREE.Vector3(0, 1, 0),
    sunElevation: 40,
    sunColor: new THREE.Color(1, 0.95, 0.9),
    moon: moon(),
    moonDirection: new THREE.Vector3(0, 0.5, -1).normalize(),
    night: 0,
    clouds: 0,
    ...over,
  };
}

/** Части неба по порядку отрисовки. */
function parts(h: Heavens) {
  const [dome, stars, halo, moonSprite, sun] = h.root.children as [
    THREE.Mesh,
    THREE.Points,
    THREE.Sprite,
    THREE.Sprite,
    THREE.Sprite,
  ];
  return { dome, stars, halo, moon: moonSprite, sun };
}

describe('диск Луны в фазе', () => {
  it('в полнолуние освещён весь диск, за его краем - прозрачно', () => {
    const { alpha, size } = moonPixels(1, true);
    const c = size / 2;
    expect(alpha(c, c)).toBeGreaterThan(200);
    expect(alpha(c - 10, c)).toBeGreaterThan(150);
    expect(alpha(c + 10, c)).toBeGreaterThan(150);
    expect(alpha(0, 0)).toBe(0);
  });

  it('в новолуние виден только пепельный свет - десятая доля яркости', () => {
    const { alpha, size } = moonPixels(0, true);
    const c = size / 2;
    expect(alpha(c, c)).toBeLessThan(0.11 * 255);
    expect(alpha(c, c)).toBeGreaterThan(0);
  });

  it('растущая Луна светит правым боком, убывающая - левым', () => {
    const waxing = moonPixels(0.5, true);
    const waning = moonPixels(0.5, false);
    const c = waxing.size / 2;
    expect(waxing.alpha(c + 10, c)).toBeGreaterThan(150);
    expect(waxing.alpha(c - 10, c)).toBeLessThan(40);
    expect(waning.alpha(c - 10, c)).toBeGreaterThan(150);
    expect(waning.alpha(c + 10, c)).toBeLessThan(40);
  });

  it('текстура в sRGB и размера по запросу', () => {
    const { texture } = moonPixels(0.3, true, 16);
    expect(texture.colorSpace).toBe(THREE.SRGBColorSpace);
    expect(texture.image.width).toBe(16);
  });

  it('без контекста 2D получается пустая текстура, а не падение', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    const texture = moonTexture(1, true, new Float32Array(4), 8);
    expect(texture).toBeInstanceOf(THREE.CanvasTexture);
  });
});

describe('небесная сфера', () => {
  it('купол, звёзды, ореол Луны, Луна и солнце рисуются по порядку поверх неба', () => {
    const h = new Heavens();
    expect(h.root.name).toBe('heavens');
    const { dome, stars, halo, moon: m, sun } = parts(h);
    expect([dome, stars, halo, m, sun].map((o) => o.renderOrder)).toEqual([-10, -9, -8, -7, -6]);
    expect(h.root.children.every((o) => !o.frustumCulled)).toBe(true);
    expect(dome.material).toBeInstanceOf(THREE.ShaderMaterial);
    expect((dome.material as THREE.ShaderMaterial).side).toBe(THREE.BackSide);
    // Ореол солнца - радиальный градиент на холсте 256 x 256.
    const glow = canvas.contexts[0];
    expect(glow?.named('createRadialGradient')).toHaveLength(1);
    expect(glow?.named('fillRect')[0]?.args).toEqual([0, 0, 256, 256]);
  });

  it('2600 звёзд на сфере радиусом 1960 м, почти все - над горизонтом', () => {
    const { stars } = parts(new Heavens());
    const pos = stars.geometry.getAttribute('position');
    const col = stars.geometry.getAttribute('color');
    expect(pos.count).toBe(2600);
    expect(col.count).toBe(2600);
    let below = 0;
    for (let i = 0; i < pos.count; i++) {
      const r = Math.hypot(pos.getX(i), pos.getY(i), pos.getZ(i));
      expect(r).toBeCloseTo(1960, 3);
      expect(pos.getY(i)).toBeGreaterThanOrEqual(-0.05 * 1960 - 1e-6);
      if (pos.getY(i) < 0) below++;
      expect(col.getY(i)).toBeGreaterThan(0.3);
    }
    expect(below / pos.count).toBeLessThan(0.07);
  });

  it('днём солнце горит, звёзд и ночного купола нет', () => {
    const h = new Heavens();
    const dir = new THREE.Vector3(0.3, 0.8, 0.5).normalize();
    h.update(state({ sunDirection: dir, sunElevation: 40 }));
    const { sun, stars, dome } = parts(h);
    expect(sun.visible).toBe(true);
    expect(sun.material.opacity).toBeCloseTo(0.8);
    expect(sun.position.distanceTo(dir.clone().multiplyScalar(2000))).toBeLessThan(1e-6);
    expect(sun.material.color.getHex()).toBe(new THREE.Color(1, 0.95, 0.9).getHex());
    expect(stars.visible).toBe(false);
    expect(dome.visible).toBe(false);
    expect((dome.material as THREE.ShaderMaterial).uniforms.uNight?.value).toBe(0);
  });

  it('облака гасят солнце: в сплошной облачности ореол слабее вдвое', () => {
    const h = new Heavens();
    h.update(state({ clouds: 1 }));
    expect(parts(h).sun.material.opacity).toBeCloseTo(0.8 * 0.45);
  });

  it('ночью солнца нет, в полнолуние Луна в полную силу с ореолом, звёзды и купол видны', () => {
    const h = new Heavens();
    h.update(state({ sunElevation: -20, night: 1, moon: moon({ fraction: 1 }) }));
    const { sun, moon: m, halo, stars, dome } = parts(h);
    expect(sun.visible).toBe(false);
    expect(m.visible).toBe(true);
    expect(m.material.opacity).toBeCloseTo(1);
    expect(halo.visible).toBe(true);
    expect(halo.material.opacity).toBeCloseTo(0.35);
    expect(halo.position.equals(m.position)).toBe(true);
    expect(m.position.length()).toBeCloseTo(1980);
    expect(stars.visible).toBe(true);
    expect((stars.material as THREE.PointsMaterial).opacity).toBeCloseTo(1);
    expect(dome.visible).toBe(true);
    expect((dome.material as THREE.ShaderMaterial).uniforms.uNight?.value).toBe(1);
  });

  it('днём Луна бледная и без ореола, в облачную ночь звёзд почти не видно', () => {
    const day = new Heavens();
    day.update(state({ night: 0 }));
    expect(parts(day).moon.material.opacity).toBeCloseTo(0.35);
    expect(parts(day).halo.visible).toBe(false);

    const cloudy = new Heavens();
    cloudy.update(state({ sunElevation: -20, night: 1, clouds: 1 }));
    const starMaterial = parts(cloudy).stars.material as THREE.PointsMaterial;
    expect(starMaterial.opacity).toBeCloseTo(0.15);
    expect(parts(cloudy).moon.material.opacity).toBeCloseTo(0.5);
  });

  it('Луна под горизонтом не видна', () => {
    const h = new Heavens();
    h.update(state({ night: 1, moon: moon({ elevation: -10 }) }));
    expect(parts(h).moon.visible).toBe(false);
    expect(parts(h).halo.visible).toBe(false);
  });

  it('текстура Луны перерисовывается только при смене фазы', () => {
    const h = new Heavens();
    h.update(state({ moon: moon({ fraction: 0.5 }) }));
    const first = parts(h).moon.material.map;
    expect(first).toBeInstanceOf(THREE.CanvasTexture);
    const dispose = vi.spyOn(first as THREE.Texture, 'dispose');
    h.update(state({ moon: moon({ fraction: 0.501 }) }));
    expect(parts(h).moon.material.map).toBe(first);
    h.update(state({ moon: moon({ fraction: 0.5, waxing: false }) }));
    expect(parts(h).moon.material.map).not.toBe(first);
    expect(dispose).toHaveBeenCalledOnce();
  });

  it('сфера светил едет за камерой', () => {
    const h = new Heavens();
    const camera = new THREE.PerspectiveCamera();
    camera.position.set(120, 35, -40);
    h.follow(camera);
    expect(h.root.position.toArray()).toEqual([120, 35, -40]);
  });

  it('dispose освобождает геометрии, материалы и текстуры', () => {
    const h = new Heavens();
    h.update(state());
    const { stars, dome, moon: m } = parts(h);
    const spies = [
      vi.spyOn(stars.geometry, 'dispose'),
      vi.spyOn(dome.geometry, 'dispose'),
      vi.spyOn(m.material, 'dispose'),
      vi.spyOn(m.material.map as THREE.Texture, 'dispose'),
    ];
    h.dispose();
    for (const spy of spies) expect(spy).toHaveBeenCalled();
  });
});
