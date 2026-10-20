import { beforeEach, describe, expect, it, vi } from 'vitest';

import { fakeContext, installCanvas, installImaging, type InstalledCanvas } from '../test/canvas';
import type { Palette } from './palette';
import { paintMaterial, pinToScreen, surfaceMasks, texturesFor } from './paper';
import type { SurfaceImage } from './types';

/** Палитра, у которой цвет - имя токена с приставкой: по ней видно, какой токен куда ушёл. */
const paletteOf = (prefix: string) =>
  ({ get: (token: string) => `${prefix}${token}` }) as unknown as Palette;

let canvas: InstalledCanvas;

beforeEach(() => {
  canvas = installCanvas();
  installImaging();
});

/** Узор, который вернул createPattern: плитка и её повтор. */
interface RecordedPattern {
  image: HTMLCanvasElement;
  repetition: string;
  setTransform: ReturnType<typeof vi.fn>;
}

describe('фактуры бумажной подосновы', () => {
  it('три плитки: трава, крап асфальта и штриховка здания цветами темы', () => {
    const target = fakeContext();
    const textures = texturesFor(target.ctx, paletteOf('a'), 2);
    expect(textures).not.toBeNull();
    const [grass, asphalt, hatch] = target
      .named('createPattern')
      .map((c) => ({ image: c.args[0] as HTMLCanvasElement, repetition: c.args[1] }));
    expect([grass, asphalt, hatch].map((p) => p?.repetition)).toEqual([
      'repeat',
      'repeat',
      'repeat',
    ]);
    // Плитки в пикселях устройства: 56, 64 и 9 пикселей CSS при плотности 2.
    expect([grass, asphalt, hatch].map((p) => p?.image.width)).toEqual([112, 128, 18]);
    const tile = (p: { image: HTMLCanvasElement } | undefined) => {
      const fake = p && canvas.of(p.image);
      if (!fake) throw new Error('плитку не рисовали');
      return fake;
    };
    const lawn = tile(grass);
    expect(lawn.named('scale')[0]?.args).toEqual([2, 2]);
    expect(lawn.named('fillRect')[0]?.state.fillStyle).toBe('a--c-lawn-fill');
    expect(lawn.named('stroke')[0]?.state.strokeStyle).toBe('a--c-lawn-blade');
    // 26 травинок: по штриху от основания вверх.
    expect(lawn.named('moveTo')).toHaveLength(26);
    const grain = tile(asphalt);
    expect(grain.named('fillRect')).toHaveLength(151);
    expect(grain.named('fillRect')[1]?.state.fillStyle).toBe('a--c-asphalt-speck');
    // Штриховка с перехлёстом за край плитки: три диагонали.
    expect(
      tile(hatch)
        .named('moveTo')
        .map((c) => c.args),
    ).toEqual([
      [-9, 9],
      [0, 9],
      [9, 9],
    ]);
  });

  it('те же цвета и плотность - те же фактуры; смена темы или плотности - новые', () => {
    const target = fakeContext();
    const first = texturesFor(target.ctx, paletteOf('b'), 1);
    expect(texturesFor(target.ctx, paletteOf('b'), 1)).toBe(first);
    expect(target.named('createPattern')).toHaveLength(3);
    expect(texturesFor(target.ctx, paletteOf('b'), 2)).not.toBe(first);
    expect(texturesFor(target.ctx, paletteOf('c'), 2)).not.toBe(first);
    expect(target.named('createPattern')).toHaveLength(9);
  });

  it('без контекста у плитки фактур нет', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    expect(texturesFor(fakeContext().ctx, paletteOf('d'), 1)).toBeNull();
  });

  it('узор приколот к экрану обратной матрицей холста', () => {
    const target = fakeContext();
    const fill = target.ctx.createPattern(document.createElement('canvas'), 'repeat');
    if (!fill) throw new Error('нет узора');
    expect(pinToScreen(target.ctx, fill)).toBe(fill);
    const recorded = fill as unknown as RecordedPattern;
    expect(recorded.setTransform).toHaveBeenCalledOnce();
    expect(recorded.setTransform.mock.calls[0]?.[0]).toMatchObject({ a: 1, d: 1, e: 0, f: 0 });
  });
});

describe('заливка покрытия по маске', () => {
  const surface: SurfaceImage = {
    img: document.createElement('canvas'),
    x: 10,
    y: 20,
    w: 30,
    h: 40,
    soil: null,
    paved: null,
  };

  it('маска кладётся мировой матрицей, цвет заливает её по source-in, слой ложится на подоснову', () => {
    const base = document.createElement('canvas');
    base.width = 300;
    base.height = 200;
    const ctx = base.getContext('2d');
    if (!ctx) throw new Error('нет контекста');
    const mask = document.createElement('canvas');
    const place = vi.fn((target: CanvasRenderingContext2D) => {
      target.setTransform(2, 0, 0, -2, 5, 7);
    });
    paintMaterial(ctx, mask, surface, '#00ff00', place);
    expect(place).toHaveBeenCalledOnce();
    const scratch = canvas.contexts.at(-1);
    if (!scratch) throw new Error('нет вспомогательного холста');
    const drawn = scratch.named('drawImage')[0];
    expect(drawn?.args).toEqual([mask, 10, 20, 30, 40]);
    const fill = scratch.named('fillRect')[0];
    expect(fill?.args).toEqual([0, 0, 300, 200]);
    expect(fill?.state).toMatchObject({
      fillStyle: '#00ff00',
      globalCompositeOperation: 'source-in',
    });
    const onBase = canvas.of(base)?.named('drawImage')[0];
    expect(onBase?.args.slice(1)).toEqual([0, 0]);
    expect(onBase?.args[0]).toBeInstanceOf(HTMLCanvasElement);
    expect((onBase?.args[0] as HTMLCanvasElement).width).toBe(300);
  });

  it('фактура перед заливкой сбрасывает свою матрицу: узор в пикселях вспомогательного холста', () => {
    const ctx = document.createElement('canvas').getContext('2d');
    if (!ctx) throw new Error('нет контекста');
    const pattern = ctx.createPattern(document.createElement('canvas'), 'repeat');
    if (!pattern) throw new Error('нет узора');
    paintMaterial(ctx, document.createElement('canvas'), surface, pattern, vi.fn());
    expect((pattern as unknown as RecordedPattern).setTransform).toHaveBeenCalledOnce();
  });
});

describe('маски грунта и покрытия из растра карты покрытий', () => {
  /** Растр 3 x 1: зелёный грунт, серый асфальт и прозрачная клетка. */
  const PIXELS = [
    [90, 160, 80, 255],
    [128, 128, 128, 255],
    [0, 0, 0, 0],
  ];

  it('зелёный канал выше красного на 24 - грунт, остальное непрозрачное - покрытие', () => {
    canvas = installCanvas({ pixels: () => new Uint8ClampedArray(PIXELS.flat()) });
    const img = Object.assign(document.createElement('canvas'), { width: 3, height: 1 });
    const masks = surfaceMasks(Object.assign(img, { naturalWidth: 3, naturalHeight: 1 }));
    if (!masks) throw new Error('масок нет');
    const alpha = (mask: HTMLCanvasElement) => {
      const put = canvas.of(mask)?.named('putImageData')[0]?.args[0] as ImageData | undefined;
      return put ? [...put.data].filter((_, i) => i % 4 === 3) : [];
    };
    expect(alpha(masks.soil)).toEqual([255, 0, 0]);
    expect(alpha(masks.paved)).toEqual([0, 255, 0]);
    expect([masks.soil.width, masks.soil.height]).toEqual([3, 1]);
  });

  it('растр длиннее 2048 клеток уменьшается до 2048 по длинной стороне', () => {
    const img = Object.assign(document.createElement('canvas'), {
      naturalWidth: 4096,
      naturalHeight: 1000,
    });
    const masks = surfaceMasks(img);
    expect([masks?.paved.width, masks?.paved.height]).toEqual([2048, 500]);
    const source = canvas.contexts[0];
    expect(source?.named('drawImage')[0]?.args).toEqual([img, 0, 0, 2048, 500]);
  });

  it('без контекста холста масок нет', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    const img = Object.assign(document.createElement('canvas'), {
      naturalWidth: 1,
      naturalHeight: 1,
    });
    expect(surfaceMasks(img)).toBeNull();
  });
});
