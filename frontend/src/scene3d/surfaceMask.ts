/* Покрытие каждого пикселя земли по карте покрытий прогона: газон, тротуарная плитка, асфальт
 * тротуара или проезжая часть. Контуры новых прогонов несут вид покрытия цветом (paved_kind);
 * растр старых и покрытие без материала делятся по ширине, как ниже.
 *
 * Карта покрытий знает только «грунт» и «покрытие», а всё, чего сервис не понял, оставляет
 * пустым. Пустое в 3D - газон, а не асфальт: съёмка улицы - полоса, и за её краем и в
 * неразмеченных карманах дворов на московской улице чаще трава, чем асфальт; асфальтовая
 * пустыня до горизонта выглядит стоянкой, а не улицей. Покрытие делится по ширине полосы:
 * тротуар - полоса уже TROTTOIR_M, проезжая часть и площадки шире. Ширина считается картой
 * расстояний до края покрытия: у пикселя тротуара самый дальний от края сосед в радиусе
 * окна - середина тротуара, до края от неё меньше половины его ширины. */

export const GRASS = 0;
export const PAVERS = 1;
/** Асфальт тротуара или площадки: на уровне газона. */
export const ASPHALT = 2;
/** Проезжая часть: ниже тротуара на высоту борта (контуры с paved_kind = road). */
export const ROAD = 3;
/** Пусто - сервис покрытия не знает: рисуется газоном, но бортом не обводится. */
export const EMPTY = 4;

/** Цвета контуров карты покрытий на маске (ground.ts кладёт их, classifySurface читает). */
export const SOIL_RGB = [104, 158, 104] as const;
export const ROAD_RGB = [90, 92, 100] as const;
export const ASPHALT_RGB = [122, 124, 132] as const;
export const PAVERS_RGB = [176, 142, 120] as const;
/** Покрытие без известного материала (и весь растр старых прогонов): делится по ширине. */
export const PAVED_RGB = [140, 142, 150] as const;
const PALETTE: readonly (readonly [number, readonly [number, number, number]])[] = [
  [GRASS, SOIL_RGB],
  [ROAD, ROAD_RGB],
  [ASPHALT, ASPHALT_RGB],
  [PAVERS, PAVERS_RGB],
  [-1, PAVED_RGB],
];

/** Вид покрытия по цвету пикселя: ближайший цвет палитры; -1 - покрытие без материала. */
function decode(r: number, g: number, b: number): number {
  let best = -1;
  let bestD = Infinity;
  for (const [kind, [pr, pg, pb]] of PALETTE) {
    const d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2;
    if (d < bestD) {
      bestD = d;
      best = kind;
    }
  }
  return best;
}

/** Шире этого покрытие - проезд или площадка, уже - тротуар. */
export const TROTTOIR_M = 4.6;
/** Радиус окна, в котором ищется середина полосы: больше половины ширины тротуара с запасом. */
const WINDOW_M = 3;
/** Щель уже двух таких отступов посреди покрытия - линия борта на карте покрытий, а не газон. */
const SEAM_M = 0.5;
const DIAGONAL = Math.SQRT2;

/** Грунт на карте покрытий зеленее, чем красен (как в map/paper.ts), покрытие - серое. */
export function isSoil(r: number, g: number, a: number): boolean {
  return a > 0 && g > r + 24;
}

/** Расстояние в пикселях до ближайшего пикселя вне покрытия: два прохода фаски 1 и √2.
 *  Край растра краем покрытия не считается: проезд, уходящий за маску, у её края не сужается. */
export function distanceInside(paved: Uint8Array, w: number, h: number): Float32Array {
  const d = new Float32Array(w * h);
  const far = w + h;
  for (let i = 0; i < d.length; i++) d[i] = paved[i] ? far : 0;
  const at = (x: number, y: number) =>
    x < 0 || y < 0 || x >= w || y >= h ? Infinity : (d[y * w + x] ?? 0);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      if (!d[i]) continue;
      d[i] = Math.min(
        d[i] ?? far,
        at(x - 1, y) + 1,
        at(x, y - 1) + 1,
        at(x - 1, y - 1) + DIAGONAL,
        at(x + 1, y - 1) + DIAGONAL,
      );
    }
  }
  for (let y = h - 1; y >= 0; y--) {
    for (let x = w - 1; x >= 0; x--) {
      const i = y * w + x;
      if (!d[i]) continue;
      d[i] = Math.min(
        d[i] ?? far,
        at(x + 1, y) + 1,
        at(x, y + 1) + 1,
        at(x + 1, y + 1) + DIAGONAL,
        at(x - 1, y + 1) + DIAGONAL,
      );
    }
  }
  return d;
}

/** Максимум в окне ±r по одной оси за линейное время (van Herk - Gil-Werman). Линия
 *  дополняется r нулями с обеих сторон: окно у края растра той же длины, что внутри, и не
 *  захватывает чужой блок (расстояния неотрицательны, ноль максимума не меняет). */
function maxLine(
  src: Float32Array,
  out: Float32Array,
  n: number,
  stride: number,
  offset: number,
  r: number,
): void {
  const size = 2 * r + 1;
  const m = n + 2 * r;
  const v = (j: number) => (j < r || j >= n + r ? 0 : (src[offset + (j - r) * stride] ?? 0));
  const g = new Float32Array(m);
  const hh = new Float32Array(m);
  for (let j = 0; j < m; j++) g[j] = j % size === 0 ? v(j) : Math.max(g[j - 1] ?? 0, v(j));
  for (let j = m - 1; j >= 0; j--)
    hh[j] = j === m - 1 || (j + 1) % size === 0 ? v(j) : Math.max(hh[j + 1] ?? 0, v(j));
  for (let i = 0; i < n; i++) out[offset + i * stride] = Math.max(hh[i] ?? 0, g[i + 2 * r] ?? 0);
}

export function maxFilter(src: Float32Array, w: number, h: number, r: number): Float32Array {
  const rows = new Float32Array(src.length);
  for (let y = 0; y < h; y++) maxLine(src, rows, w, 1, y * w, r);
  const out = new Float32Array(src.length);
  for (let x = 0; x < w; x++) maxLine(rows, out, h, w, x, r);
  return out;
}

/** Линии бортов на карте покрытий - пустые клетки посреди покрытия: на 3D это зелёная нитка
 *  по асфальту. Тротуар и проезд делятся по ширине до закрытия щели (по ней тротуар узкий),
 *  а потом щель закрывается покрытием (замыкание радиуса r): у тротуара - плиткой. */
function closeSeams(
  kind: Uint8Array,
  paved: Uint8Array,
  empty: Uint8Array,
  w: number,
  h: number,
  r: number,
): void {
  const dilated = maxFilter(Float32Array.from(paved), w, h, r);
  const outside = maxFilter(
    dilated.map((v) => 1 - v),
    w,
    h,
    r,
  );
  const pavers = maxFilter(
    Float32Array.from(kind, (k) => (k === PAVERS ? 1 : 0)),
    w,
    h,
    r,
  );
  const asphalt = maxFilter(
    Float32Array.from(kind, (k) => (k === ASPHALT ? 1 : 0)),
    w,
    h,
    r,
  );
  // Щель между покрытием и газоном (линия борта у газона) - газон: иначе садовый борт не
  // видит газона по другую сторону и не встаёт.
  const covered = maxFilter(
    Float32Array.from(empty, (e) => 1 - e),
    w,
    h,
    r,
  );
  const coveredOutside = maxFilter(
    covered.map((v) => 1 - v),
    w,
    h,
    r,
  );
  for (let i = 0; i < kind.length; i++) {
    if (!empty[i]) continue;
    // Только пустая щель: газон, даже узкий (лунки деревьев), остаётся газоном. Щель отходит
    // тротуару, а не проезду: борт стоит по краю проезжей части.
    if (!outside[i]) kind[i] = pavers[i] ? PAVERS : asphalt[i] ? ASPHALT : ROAD;
    else kind[i] = coveredOutside[i] ? EMPTY : GRASS;
  }
}

/** Покрытие каждого пикселя по RGBA карты покрытий, уже положенной в масштаб маски. */
export function classifySurface(
  rgba: Uint8ClampedArray,
  w: number,
  h: number,
  metresPerPx: number,
  minAlpha = 1,
): Uint8Array {
  const kind = new Uint8Array(w * h);
  const paved = new Uint8Array(w * h);
  const unknown = new Uint8Array(w * h);
  const empty = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) {
    const a = rgba[i * 4 + 3] ?? 0;
    if (a < minAlpha) {
      empty[i] = 1;
      kind[i] = EMPTY;
      continue;
    }
    const k = decode(rgba[i * 4] ?? 0, rgba[i * 4 + 1] ?? 0, rgba[i * 4 + 2] ?? 0);
    paved[i] = k === GRASS ? 0 : 1;
    unknown[i] = k === -1 ? 1 : 0;
    kind[i] = k === -1 ? ASPHALT : k;
  }
  // Покрытие без материала делится по ширине: узкое - плитка тротуара, широкое - асфальт.
  const middle = maxFilter(
    distanceInside(unknown, w, h),
    w,
    h,
    Math.max(1, Math.round(WINDOW_M / metresPerPx)),
  );
  const half = TROTTOIR_M / 2 / metresPerPx;
  for (let i = 0; i < kind.length; i++) {
    if (unknown[i] && (middle[i] ?? 0) < half) kind[i] = PAVERS;
  }
  closeSeams(kind, paved, empty, w, h, Math.max(1, Math.round(SEAM_M / metresPerPx)));
  return kind;
}
