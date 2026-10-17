/* Покрытие каждого пикселя земли по карте покрытий прогона: газон, тротуарная плитка или
 * асфальт проезда.
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
export const ASPHALT = 2;

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
  for (let i = 0; i < kind.length; i++) {
    // Только пустая щель: газон, даже узкий (лунки деревьев), остаётся газоном.
    if (empty[i] && !outside[i]) kind[i] = pavers[i] ? PAVERS : ASPHALT;
  }
}

/** Покрытие каждого пикселя по RGBA карты покрытий, уже положенной в масштаб маски. */
export function classifySurface(
  rgba: Uint8ClampedArray,
  w: number,
  h: number,
  metresPerPx: number,
): Uint8Array {
  const kind = new Uint8Array(w * h);
  const paved = new Uint8Array(w * h);
  const empty = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) {
    const a = rgba[i * 4 + 3] ?? 0;
    const soil = isSoil(rgba[i * 4] ?? 0, rgba[i * 4 + 1] ?? 0, a);
    paved[i] = a > 0 && !soil ? 1 : 0;
    empty[i] = a > 0 ? 0 : 1;
    kind[i] = paved[i] ? ASPHALT : GRASS;
  }
  const middle = maxFilter(
    distanceInside(paved, w, h),
    w,
    h,
    Math.max(1, Math.round(WINDOW_M / metresPerPx)),
  );
  const half = TROTTOIR_M / 2 / metresPerPx;
  for (let i = 0; i < kind.length; i++) {
    if (paved[i] && (middle[i] ?? 0) < half) kind[i] = PAVERS;
  }
  closeSeams(kind, paved, empty, w, h, Math.max(1, Math.round(SEAM_M / metresPerPx)));
  return kind;
}
