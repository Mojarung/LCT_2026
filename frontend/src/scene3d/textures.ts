/* Фактуры покрытий, нарисованные в коде: асфальт, тротуарная плитка, газон, бетон бортового
 * камня, решётка ограды и шум для разброса. Файлов текстур в бандле нет: стенд без интернета
 * не должен ничего качать, а 1-2 МБ фотографий на каждое покрытие утяжелили бы 3D-вид сильнее,
 * чем весь его код. Каждая фактура бесшовная: рисуется с переносом за край. */

import * as THREE from 'three';

export function rng(seed: number): () => number {
  let s = seed >>> 0 || 1;
  return () => {
    s ^= s << 13;
    s ^= s >>> 17;
    s ^= s << 5;
    return ((s >>> 0) % 1_000_000) / 1_000_000;
  };
}

/** Бесшовный шум значений: сетка period x period, билинейная интерполяция с гладким шагом. */
export function valueNoise(size: number, period: number, seed: number): Float32Array {
  const random = rng(seed);
  const lattice = new Float32Array(period * period).map(() => random());
  const out = new Float32Array(size * size);
  const at = (x: number, y: number) =>
    lattice[(((y % period) + period) % period) * period + (((x % period) + period) % period)] ?? 0;
  for (let y = 0; y < size; y++) {
    const fy = (y / size) * period;
    const y0 = Math.floor(fy);
    const ty = fy - y0;
    const sy = ty * ty * (3 - 2 * ty);
    for (let x = 0; x < size; x++) {
      const fx = (x / size) * period;
      const x0 = Math.floor(fx);
      const tx = fx - x0;
      const sx = tx * tx * (3 - 2 * tx);
      const a = at(x0, y0) + (at(x0 + 1, y0) - at(x0, y0)) * sx;
      const b = at(x0, y0 + 1) + (at(x0 + 1, y0 + 1) - at(x0, y0 + 1)) * sx;
      out[y * size + x] = a + (b - a) * sy;
    }
  }
  return out;
}

/** Фрактальный шум: сумма октав, от крупных пятен к мелкому зерну. */
export function fbm(size: number, periods: readonly number[], seed: number): Float32Array {
  const out = new Float32Array(size * size);
  let total = 0;
  periods.forEach((period, i) => {
    const weight = 1 / (i + 1);
    total += weight;
    const layer = valueNoise(size, period, seed + i * 7919);
    for (let k = 0; k < out.length; k++) out[k] = (out[k] ?? 0) + (layer[k] ?? 0) * weight;
  });
  for (let k = 0; k < out.length; k++) out[k] = (out[k] ?? 0) / total;
  return out;
}

function canvas(size: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const c = document.createElement('canvas');
  c.width = size;
  c.height = size;
  const ctx = c.getContext('2d');
  if (!ctx) throw new Error('Canvas 2D недоступен');
  return [c, ctx];
}

function texture(c: HTMLCanvasElement, srgb: boolean): THREE.CanvasTexture {
  const t = new THREE.CanvasTexture(c);
  t.wrapS = THREE.RepeatWrapping;
  t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  t.generateMipmaps = true;
  t.minFilter = THREE.LinearMipmapLinearFilter;
  t.magFilter = THREE.LinearFilter;
  t.needsUpdate = true;
  return t;
}

type Paint = (n: number, x: number, y: number) => [number, number, number];

function fromNoise(size: number, noise: Float32Array, paint: Paint): HTMLCanvasElement {
  const [c, ctx] = canvas(size);
  const img = ctx.createImageData(size, size);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const i = y * size + x;
      const [r, g, b] = paint(noise[i] ?? 0, x, y);
      img.data[i * 4] = r;
      img.data[i * 4 + 1] = g;
      img.data[i * 4 + 2] = b;
      img.data[i * 4 + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  return c;
}

/** Асфальт: тёмная основа, светлый щебень зерном, пятна износа. Плитка текстуры - 4 м. */
export function asphalt(): THREE.CanvasTexture {
  const size = 1024;
  const macro = fbm(size, [4, 8, 16], 11);
  const grain = valueNoise(size, 512, 23);
  const random = rng(37);
  const c = fromNoise(size, macro, (n, x, y) => {
    const g = grain[y * size + x] ?? 0;
    const speck = random() > 0.985 ? 38 : random() > 0.93 ? 14 : 0;
    const v = 56 + n * 9 + g * 16 + speck;
    return [v + 2, v + 1, v - 1];
  });
  return texture(c, true);
}

/** Тротуарная плитка 30 x 30 см вразбежку, как на московских тротуарах, с тёмными швами.
 *  Плитка текстуры - 3 м, 10 x 10 плиток. */
export function pavers(): THREE.CanvasTexture {
  const size = 1024;
  const tiles = 10;
  const step = size / tiles;
  const noise = fbm(size, [8, 32, 128], 51);
  const random = rng(71);
  const tone = Array.from({ length: tiles * tiles * 2 }, () => random());
  const c = fromNoise(size, noise, (n, x, y) => {
    const row = Math.floor(y / step);
    const shift = row % 2 ? step / 2 : 0;
    const col = Math.floor((x + shift) / step) % tiles;
    const lx = (x + shift) % step;
    const ly = y % step;
    const seam = Math.min(lx, ly, step - lx, step - ly) < 2.2;
    const t = tone[row * tiles + col] ?? 0.5;
    const v = seam ? 72 : 128 + t * 26 + n * 30;
    return [v + 2, v, v - 4];
  });
  return texture(c, true);
}

/** Газон: несколько зелёных в шуме, мелкий штрих травинок и редкие пятна земли. Плитка - 6 м. */
export function grass(): THREE.CanvasTexture {
  const size = 1024;
  const macro = fbm(size, [3, 6, 12], 91);
  const fine = valueNoise(size, 256, 97);
  const blade = valueNoise(size, 700, 101);
  const c = fromNoise(size, macro, (n, x, y) => {
    const f = fine[y * size + x] ?? 0;
    const b = blade[y * size + x] ?? 0;
    const dirt = Math.max(0, n - 0.72) * 3.5;
    const r = 56 + n * 12 + b * 16 + dirt * 45;
    const g = 68 + n * 12 + f * 16 + b * 18 + dirt * 10;
    const bl = 38 + n * 6 + b * 8 + dirt * 12;
    return [r, g, bl];
  });
  return texture(c, true);
}

/** Неспецифичная листва условной изгороди: рисунок не задаёт породу или число кустов. */
export function hedgeLeaves(): THREE.CanvasTexture {
  const [c, ctx] = canvas(256);
  const random = rng(239);
  ctx.fillStyle = '#334426';
  ctx.fillRect(0, 0, 256, 256);
  for (let i = 0; i < 2400; i++) {
    const shade = random();
    ctx.fillStyle = `rgb(${42 + shade * 38},${62 + shade * 48},${26 + shade * 25})`;
    ctx.beginPath();
    ctx.ellipse(
      random() * 256,
      random() * 256,
      2 + random() * 4,
      1 + random() * 2,
      random() * Math.PI,
      0,
      Math.PI * 2,
    );
    ctx.fill();
  }
  return texture(c, true);
}

/** Бетон бортового камня и цоколей: светло-серый с кавернами. */
export function concrete(): THREE.CanvasTexture {
  const size = 512;
  const noise = fbm(size, [4, 16, 64, 128], 131);
  const random = rng(137);
  const c = fromNoise(size, noise, (n) => {
    const pit = random() > 0.992 ? -30 : 0;
    const v = 150 + n * 40 + pit;
    return [v, v - 1, v - 4];
  });
  return texture(c, true);
}

/** Решётка ограды: стойки через 12 см, две перекладины, прозрачность между прутьями. */
export function fenceBars(): THREE.CanvasTexture {
  const [c, ctx] = canvas(256);
  ctx.clearRect(0, 0, 256, 256);
  ctx.fillStyle = '#ffffff';
  for (let x = 0; x < 256; x += 32) ctx.fillRect(x + 12, 0, 7, 256);
  ctx.fillRect(0, 10, 256, 10);
  ctx.fillRect(0, 226, 256, 12);
  const t = texture(c, true);
  t.wrapT = THREE.ClampToEdgeWrapping;
  return t;
}

/** Шум для разброса в шейдерах: R - крупные пятна, G - средние, B - мелкие. */
export function noiseTexture(): THREE.DataTexture {
  const size = 256;
  const a = fbm(size, [4, 8], 211);
  const b = fbm(size, [16, 32], 223);
  const c = valueNoise(size, 128, 227);
  const data = new Uint8Array(size * size * 4);
  for (let i = 0; i < size * size; i++) {
    data[i * 4] = Math.round((a[i] ?? 0) * 255);
    data[i * 4 + 1] = Math.round((b[i] ?? 0) * 255);
    data[i * 4 + 2] = Math.round((c[i] ?? 0) * 255);
    data[i * 4 + 3] = 255;
  }
  const t = new THREE.DataTexture(data, size, size, THREE.RGBAFormat);
  t.wrapS = THREE.RepeatWrapping;
  t.wrapT = THREE.RepeatWrapping;
  t.magFilter = THREE.LinearFilter;
  t.minFilter = THREE.LinearMipmapLinearFilter;
  t.generateMipmaps = true;
  t.needsUpdate = true;
  return t;
}

/** Серая листва из цветной: яркость без цвета, альфа как была. Цвет задаёт экземпляр - вид,
 *  сезон и разброс, - поэтому одна текстура годится и для липы, и для цветущей сирени. */
export async function neutralLeaves(source: THREE.Texture): Promise<THREE.Texture> {
  const image = source.image as HTMLImageElement | undefined;
  if (!image) return source;
  if (!image.complete || !image.naturalWidth) await image.decode().catch(() => undefined);
  if (!image.naturalWidth) return source;
  const c = document.createElement('canvas');
  c.width = image.naturalWidth;
  c.height = image.naturalHeight;
  const ctx = c.getContext('2d');
  if (!ctx) return source;
  ctx.drawImage(image, 0, 0);
  const img = ctx.getImageData(0, 0, c.width, c.height);
  const d = img.data;
  let sum = 0;
  let count = 0;
  for (let i = 0; i < d.length; i += 4) {
    if ((d[i + 3] ?? 0) < 128) continue;
    sum += 0.3 * (d[i] ?? 0) + 0.59 * (d[i + 1] ?? 0) + 0.11 * (d[i + 2] ?? 0);
    count++;
  }
  const mean = count ? sum / count : 128;
  const gain = 205 / Math.max(mean, 1);
  for (let i = 0; i < d.length; i += 4) {
    const lum = 0.3 * (d[i] ?? 0) + 0.59 * (d[i + 1] ?? 0) + 0.11 * (d[i + 2] ?? 0);
    const v = Math.min(255, lum * gain);
    d[i] = v;
    d[i + 1] = v;
    d[i + 2] = v;
  }
  ctx.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  t.needsUpdate = true;
  return t;
}
