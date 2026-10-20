import * as THREE from 'three';
import { describe, expect, it, vi } from 'vitest';

import { fakeContext, installCanvas } from '../test/canvas';
import {
  asphalt,
  concrete,
  CURB_STONES_PER_TEXTURE,
  curbStone,
  fbm,
  fenceBars,
  grass,
  gutterShade,
  neutralLeaves,
  noiseTexture,
  pavers,
  rng,
  rubberCrumb,
  valueNoise,
} from './textures';

/** Пиксели, которые фактура положила на холст через putImageData. */
function pixels(
  t: THREE.CanvasTexture,
  canvas: ReturnType<typeof installCanvas>,
): Uint8ClampedArray {
  const fake = canvas.of(t.image);
  const call = fake?.named('putImageData')[0];
  return (call?.args[0] as ImageData).data;
}

function mean(data: Uint8ClampedArray, channel: number): number {
  let sum = 0;
  for (let i = channel; i < data.length; i += 4) sum += data[i] ?? 0;
  return sum / (data.length / 4);
}

describe('шум для фактур', () => {
  it('генератор повторяется по зерну и даёт числа 0..1', () => {
    const a = rng(5);
    const b = rng(5);
    const xs = Array.from({ length: 20 }, () => a());
    expect(xs).toEqual(Array.from({ length: 20 }, () => b()));
    for (const x of xs) {
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThan(1);
    }
  });

  it('шум и его сумма октав - в пределах 0..1 и бесшовны по краю', () => {
    const n = valueNoise(32, 4, 9);
    expect(n).toHaveLength(32 * 32);
    const f = fbm(32, [2, 4, 8], 9);
    for (const v of f) {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(1);
    }
    // Плитка повторяется: столбец 0 ближе к столбцу 31, чем к середине, в среднем.
    let edge = 0;
    let middle = 0;
    for (let y = 0; y < 32; y++) {
      edge += Math.abs((n[y * 32] ?? 0) - (n[y * 32 + 31] ?? 0));
      middle += Math.abs((n[y * 32] ?? 0) - (n[y * 32 + 16] ?? 0));
    }
    expect(edge).toBeLessThan(middle);
  });

  it('текстура шума: три канала, повтор и мип-уровни', () => {
    const t = noiseTexture();
    expect(t.image.width).toBe(256);
    expect(t.wrapS).toBe(THREE.RepeatWrapping);
    expect(t.generateMipmaps).toBe(true);
    const data = t.image.data as Uint8Array;
    expect(data[3]).toBe(255);
    expect(
      new Set(Array.from(data.subarray(0, 4000)).filter((_, i) => i % 4 === 0)).size,
    ).toBeGreaterThan(10);
  });
});

describe('фактуры покрытий', () => {
  it('асфальт тёмный, газон зелёный, плитка светлее асфальта', () => {
    const canvas = installCanvas();
    const a = asphalt();
    const g = grass();
    const p = pavers();
    const ad = pixels(a, canvas);
    const gd = pixels(g, canvas);
    const pd = pixels(p, canvas);
    expect(mean(ad, 0)).toBeLessThan(110);
    expect(mean(gd, 1)).toBeGreaterThan(mean(gd, 0));
    expect(mean(gd, 1)).toBeGreaterThan(mean(gd, 2));
    expect(mean(pd, 0)).toBeGreaterThan(mean(ad, 0));
    expect(ad[3]).toBe(255);
    for (const t of [a, g, p]) {
      expect(t.colorSpace).toBe(THREE.SRGBColorSpace);
      expect(t.wrapS).toBe(THREE.RepeatWrapping);
      expect(t.minFilter).toBe(THREE.LinearMipmapLinearFilter);
    }
  });

  it('у плитки тёмные швы по краю плиток', () => {
    const canvas = installCanvas();
    const d = pixels(pavers(), canvas);
    // Пиксель (0, 50) - на шве первой строки, (50, 50) - посреди плитки.
    expect(d[(50 * 1024 + 0) * 4 + 1]).toBe(72);
    expect(d[(50 * 1024 + 50) * 4 + 1]).toBeGreaterThan(110);
  });

  it('резиновая крошка бурая, бетон светло-серый', () => {
    const canvas = installCanvas();
    const rubber = pixels(rubberCrumb(), canvas);
    const stone = pixels(concrete(), canvas);
    expect(mean(rubber, 0)).toBeGreaterThan(mean(rubber, 1) + 20);
    expect(mean(stone, 0)).toBeGreaterThan(140);
    expect(Math.abs(mean(stone, 0) - mean(stone, 1))).toBeLessThan(3);
  });

  it('бортовой камень: четыре камня с тёмным швом между ними', () => {
    const canvas = installCanvas();
    const d = pixels(curbStone(), canvas);
    const stone = 512 / CURB_STONES_PER_TEXTURE;
    let joint = 0;
    let body = 0;
    for (let y = 0; y < 512; y++) {
      joint += d[(y * 512 + stone + 1) * 4] ?? 0;
      body += d[(y * 512 + stone + 60) * 4] ?? 0;
    }
    expect(joint / 512).toBeLessThan(body / 512 - 50);
  });

  it('лоток у борта - градиент без повтора и без цветового пространства', () => {
    const canvas = installCanvas();
    const t = gutterShade();
    expect(t.wrapS).toBe(THREE.ClampToEdgeWrapping);
    expect(t.colorSpace).toBe(THREE.NoColorSpace);
    const fake = canvas.of(t.image);
    expect(fake?.named('fillRect')[0]?.state.fillStyle).toMatchObject({ kind: 'linear' });
  });

  it('решётка ограды: прутья через 32 px и две перекладины', () => {
    const canvas = installCanvas();
    const t = fenceBars();
    const rects = canvas.of(t.image)?.named('fillRect') ?? [];
    expect(rects).toHaveLength(8 + 2);
    expect(rects[1]?.args).toEqual([44, 0, 7, 256]);
    expect(t.wrapT).toBe(THREE.ClampToEdgeWrapping);
    expect(t.wrapS).toBe(THREE.RepeatWrapping);
  });
});

describe('серая листва', () => {
  it('без картинки или с пустой картинкой - исходная текстура', async () => {
    const empty = new THREE.Texture();
    expect(await neutralLeaves(empty)).toBe(empty);
    const broken = new THREE.Texture({
      complete: false,
      naturalWidth: 0,
      decode: () => Promise.reject(new Error('нет')),
    } as unknown as HTMLImageElement);
    expect(await neutralLeaves(broken)).toBe(broken);
  });

  it('цвет снимается, прозрачность та же, средняя яркость листа ведётся к 205', async () => {
    const fake = fakeContext({ width: 2, height: 1 });
    const data = new Uint8ClampedArray([0, 100, 0, 255, 255, 0, 0, 0]);
    Object.assign(fake.ctx, { getImageData: () => ({ width: 2, height: 1, data }) });
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(() => fake.ctx);
    const source = new THREE.Texture({
      complete: true,
      naturalWidth: 2,
      naturalHeight: 1,
    } as unknown as HTMLImageElement);
    const out = await neutralLeaves(source);
    expect(out).not.toBe(source);
    expect(out).toBeInstanceOf(THREE.CanvasTexture);
    expect(out.colorSpace).toBe(THREE.SRGBColorSpace);
    expect(fake.named('putImageData')).toHaveLength(1);
    // Непрозрачный зелёный пиксель: яркость 59 -> 205, красный и синий не выше зелёного.
    expect(data[1]).toBeGreaterThan(150);
    expect(data[0]).toBeLessThanOrEqual(data[1] ?? 0);
    expect(data[3]).toBe(255);
    expect(data[7]).toBe(0);
  });
});
