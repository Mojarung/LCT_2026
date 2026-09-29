/* Бумажная подоснова, как на слайдах презентации: газон с травяными штрихами, асфальт с
 * крапом, здания со штриховкой и тенью. Фактуры живут в экранных пикселях: трава не растёт
 * при приближении и не поворачивается вместе с видом вдоль улицы, как не поворачивается
 * бумага под чертежом.
 *
 * Где газон и где асфальт, берётся из карты покрытий сервиса: это то самое понимание участка,
 * по которому он решает, где сажать. Чертёж сам заливок почти не несёт - газон и тротуар там
 * линии и подписи, - поэтому раскраска и проверка разбора здесь одно и то же. */

import type { Palette } from './palette';
import type { SurfaceImage } from './types';

export interface Textures {
  grass: CanvasPattern;
  asphalt: CanvasPattern;
  hatch: CanvasPattern;
}

let made: { key: string; dpr: number; textures: Textures } | null = null;

/** Фактуры под текущую тему. Пересоздаются, только когда поменялись цвета или плотность
 *  пикселей: палитра карты сбрасывается при смене темы, ключ - сами цвета. */
export function texturesFor(
  ctx: CanvasRenderingContext2D,
  palette: Palette,
  dpr: number,
): Textures | null {
  const colors = [
    '--c-lawn-fill',
    '--c-lawn-blade',
    '--c-asphalt',
    '--c-asphalt-speck',
    '--c-building-hatch',
  ].map((token) => palette.get(token));
  const key = colors.join('|');
  if (made?.key === key && made.dpr === dpr) return made.textures;
  const [lawn = '', blade = '', asphalt = '', speck = '', hatch = ''] = colors;
  const grass = pattern(ctx, 56, dpr, (t, size) => {
    t.fillStyle = lawn;
    t.fillRect(0, 0, size, size);
    t.strokeStyle = blade;
    t.lineWidth = 1;
    t.lineCap = 'round';
    const rand = random(7);
    t.beginPath();
    for (let i = 0; i < 26; i++) {
      const x = rand() * size;
      const y = rand() * size;
      const len = 3 + rand() * 4;
      const lean = (rand() - 0.5) * 2.4;
      t.moveTo(x, y);
      t.lineTo(x + lean, y - len);
    }
    t.stroke();
  });
  const grain = pattern(ctx, 64, dpr, (t, size) => {
    t.fillStyle = asphalt;
    t.fillRect(0, 0, size, size);
    t.fillStyle = speck;
    const rand = random(11);
    for (let i = 0; i < 150; i++) {
      const d = rand() < 0.2 ? 1.4 : 0.9;
      t.fillRect(rand() * size, rand() * size, d, d);
    }
  });
  const lines = pattern(ctx, 9, dpr, (t, size) => {
    t.strokeStyle = hatch;
    t.lineWidth = 1;
    t.beginPath();
    // Диагональ с перехлёстом за край плитки: иначе на стыках плиток штрих рвётся.
    for (const shift of [-size, 0, size]) {
      t.moveTo(shift, size);
      t.lineTo(shift + size, 0);
    }
    t.stroke();
  });
  if (!grass || !grain || !lines) return null;
  made = { key, dpr, textures: { grass, asphalt: grain, hatch: lines } };
  return made.textures;
}

function pattern(
  ctx: CanvasRenderingContext2D,
  size: number,
  dpr: number,
  draw: (t: CanvasRenderingContext2D, size: number) => void,
): CanvasPattern | null {
  const tile = document.createElement('canvas');
  tile.width = Math.round(size * dpr);
  tile.height = tile.width;
  const t = tile.getContext('2d');
  if (!t) return null;
  t.scale(dpr, dpr);
  draw(t, size);
  return ctx.createPattern(tile, 'repeat');
}

/** Узор в экранных пикселях при любой текущей матрице: обратная матрица отменяет мировую. */
export function pinToScreen(ctx: CanvasRenderingContext2D, fill: CanvasPattern): CanvasPattern {
  fill.setTransform(ctx.getTransform().inverse());
  return fill;
}

let scratch: HTMLCanvasElement | null = null;

/** Залить фактурой (в инженерном стиле - плоским цветом) всё, где маска покрытия
 *  непрозрачна. Маска кладётся мировой матрицей во вспомогательный холст, фактура заливает её
 *  по source-in в экранных пикселях, готовый слой ложится на подоснову. place - та же мировая
 *  матрица, что у подосновы. */
export function paintMaterial(
  ctx: CanvasRenderingContext2D,
  mask: CanvasImageSource,
  surface: SurfaceImage,
  fill: CanvasPattern | string,
  place: (target: CanvasRenderingContext2D) => void,
): void {
  const { width, height } = ctx.canvas;
  scratch ??= document.createElement('canvas');
  if (scratch.width !== width || scratch.height !== height) {
    scratch.width = width;
    scratch.height = height;
  }
  const s = scratch.getContext('2d');
  if (!s) return;
  s.setTransform(1, 0, 0, 1, 0, 0);
  s.globalCompositeOperation = 'source-over';
  s.clearRect(0, 0, width, height);
  place(s);
  s.imageSmoothingEnabled = true;
  s.drawImage(mask, surface.x, surface.y, surface.w, surface.h);
  s.setTransform(1, 0, 0, 1, 0, 0);
  s.globalCompositeOperation = 'source-in';
  if (typeof fill !== 'string') fill.setTransform(new DOMMatrix());
  s.fillStyle = fill;
  s.fillRect(0, 0, width, height);
  s.globalCompositeOperation = 'source-over';
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.drawImage(scratch, 0, 0);
  ctx.restore();
}

/** Маски грунта и твёрдого из растра карты покрытий. Цвета растра - SURFACE_COLORS сервиса:
 *  грунт зеленоватый, твёрдое серое; отличаются они зелёным каналом, это переживает любое
 *  сжатие PNG и премультипликацию альфы. Растр длиннее MASK_SIDE сторон уменьшается: маска -
 *  это только «где», для неё хватает и половины клеток. */
const MASK_SIDE = 2048;

export function surfaceMasks(
  img: CanvasImageSource & { naturalWidth: number; naturalHeight: number },
): { soil: HTMLCanvasElement; paved: HTMLCanvasElement } | null {
  const k = Math.min(1, MASK_SIDE / Math.max(img.naturalWidth, img.naturalHeight, 1));
  const width = Math.max(1, Math.round(img.naturalWidth * k));
  const height = Math.max(1, Math.round(img.naturalHeight * k));
  const source = document.createElement('canvas');
  source.width = width;
  source.height = height;
  const ctx = source.getContext('2d', { willReadFrequently: true });
  if (!ctx) return null;
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(img, 0, 0, width, height);
  const pixels = ctx.getImageData(0, 0, width, height).data;
  const soil = new ImageData(width, height);
  const paved = new ImageData(width, height);
  for (let i = 0; i < pixels.length; i += 4) {
    if ((pixels[i + 3] ?? 0) === 0) continue;
    const red = pixels[i] ?? 0;
    const green = pixels[i + 1] ?? 0;
    const target = green > red + 24 ? soil.data : paved.data;
    target[i + 3] = 255;
  }
  const toCanvas = (data: ImageData) => {
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    canvas.getContext('2d')?.putImageData(data, 0, 0);
    return canvas;
  };
  return { soil: toCanvas(soil), paved: toCanvas(paved) };
}

function random(state: number): () => number {
  let a = state;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
