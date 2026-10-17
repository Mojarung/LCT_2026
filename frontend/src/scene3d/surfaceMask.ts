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

/** Пятно покрытия или грунта меньше этого, м², - шум растра карты покрытий, а не газон
 *  посреди проезда: в 3D вокруг него встал бы свой бортовой камень. */
export const SPECK_M2 = 8;

/** Пятна 0 или 1 меньше minPx пикселей (4-связность) перекрашиваются в окружающее. */
export function despeckle(mask: Uint8Array, w: number, h: number, minPx: number): void {
  if (minPx < 2) return;
  const seen = new Uint8Array(w * h);
  const stack: number[] = [];
  const members: number[] = [];
  for (let start = 0; start < mask.length; start++) {
    if (seen[start]) continue;
    const value = mask[start] ?? 0;
    stack.length = 0;
    members.length = 0;
    stack.push(start);
    seen[start] = 1;
    let touchesEdge = false;
    while (stack.length) {
      const i = stack.pop() ?? 0;
      members.push(i);
      const x = i % w;
      const y = (i - x) / w;
      if (x === 0 || y === 0 || x === w - 1 || y === h - 1) touchesEdge = true;
      for (const j of [
        x > 0 ? i - 1 : -1,
        x < w - 1 ? i + 1 : -1,
        y > 0 ? i - w : -1,
        y < h - 1 ? i + w : -1,
      ]) {
        if (j >= 0 && !seen[j] && mask[j] === value) {
          seen[j] = 1;
          stack.push(j);
        }
      }
    }
    // Пятно у края растра может продолжаться за ним: его не трогаем.
    if (members.length >= minPx || touchesEdge) continue;
    for (const i of members) mask[i] = value ? 0 : 1;
  }
}

/** Связные области единиц меньше minPx пикселей (4-связность) обнуляются; область у края
 *  растра остаётся - она может продолжаться за ним. */
export function keepLarge(mask: Uint8Array, w: number, h: number, minPx: number): void {
  const seen = new Uint8Array(w * h);
  const stack: number[] = [];
  const members: number[] = [];
  for (let start = 0; start < mask.length; start++) {
    if (seen[start] || !mask[start]) continue;
    stack.length = 0;
    members.length = 0;
    stack.push(start);
    seen[start] = 1;
    let edge = false;
    while (stack.length) {
      const i = stack.pop() ?? 0;
      members.push(i);
      const x = i % w;
      const y = (i - x) / w;
      if (x === 0 || y === 0 || x === w - 1 || y === h - 1) edge = true;
      for (const j of [
        x > 0 ? i - 1 : -1,
        x < w - 1 ? i + 1 : -1,
        y > 0 ? i - w : -1,
        y < h - 1 ? i + w : -1,
      ]) {
        if (j >= 0 && !seen[j] && mask[j]) {
          seen[j] = 1;
          stack.push(j);
        }
      }
    }
    if (!edge && members.length < minPx) for (const i of members) mask[i] = 0;
  }
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
  // Растр старых прогонов шумит отдельными клетками: пятна покрытия и дыры в нём меньше
  // SPECK_M2 убираются. Контуры (minAlpha > 1) уже чистые.
  if (minAlpha <= 1) {
    const before = paved.slice();
    despeckle(paved, w, h, Math.round(SPECK_M2 / (metresPerPx * metresPerPx)));
    for (let i = 0; i < w * h; i++) {
      if (before[i] === paved[i] || empty[i]) continue;
      kind[i] = paved[i] ? ASPHALT : GRASS;
      unknown[i] = paved[i] ?? 0;
    }
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

/** Скользящее среднее по строкам (step 1) или столбцам (step w) с краем «как есть». */
function boxPass(
  src: Float32Array,
  dst: Float32Array,
  w: number,
  h: number,
  r: number,
  rows: boolean,
): void {
  const lines = rows ? h : w;
  const len = rows ? w : h;
  const stride = rows ? 1 : w;
  const span = 2 * r + 1;
  for (let line = 0; line < lines; line++) {
    const base = rows ? line * w : line;
    const at = (k: number) => src[base + Math.min(len - 1, Math.max(0, k)) * stride] ?? 0;
    let sum = 0;
    for (let k = -r; k <= r; k++) sum += at(k);
    for (let k = 0; k < len; k++) {
      dst[base + k * stride] = sum / span;
      sum += at(k + r + 1) - at(k - r);
    }
  }
}

/** Граница двоичной маски (0 или 255) плавной кривой: два прохода размытия окном
 *  радиуса r и порог на половине. Выступы и впадины уже r сглаживаются, лесенка растра
 *  исчезает, площадь больших областей почти не меняется. */
export function smoothBinary(values: Uint8Array, w: number, h: number, r: number): Uint8Array {
  if (r < 1) return values.slice();
  const a = Float32Array.from(values);
  const b = new Float32Array(a.length);
  for (let pass = 0; pass < 2; pass++) {
    boxPass(a, b, w, h, r, true);
    boxPass(b, a, w, h, r, false);
  }
  const out = new Uint8Array(values.length);
  for (let i = 0; i < out.length; i++) out[i] = (a[i] ?? 0) >= 127.5 ? 255 : 0;
  return out;
}

/** Размытие байтовой маски окном радиуса r (два прохода), без порога: ступенька растра
 *  становится плавным переходом, и порог 0,5 в шейдере идёт по линии контура, а не по краю
 *  пикселя. Заливка холста в Chrome бывает без сглаживания края. */
export function blurBytes(values: Uint8Array, w: number, h: number, r: number): Uint8Array {
  if (r < 1) return values.slice();
  const a = Float32Array.from(values);
  const b = new Float32Array(a.length);
  for (let pass = 0; pass < 2; pass++) {
    boxPass(a, b, w, h, r, true);
    boxPass(b, a, w, h, r, false);
  }
  return Uint8Array.from(a, (v) => Math.round(v));
}

/** Мелкие пятна одного покрытия на стыке других: связная область метки target меньше maxPx
 *  пикселей (4-связность) получает ту метку соседей, с которой у неё самая длинная общая
 *  граница. Метки из keep не отдаются и не принимают: пятно, касающееся проезда, остаётся -
 *  это край проезда, а не обрывок. Возвращает новый массив меток. */
export function absorbSmall(
  labels: Uint8Array,
  w: number,
  h: number,
  target: number,
  maxPx: number,
  keep: readonly number[] = [],
): Uint8Array {
  const out = labels.slice();
  const seen = new Uint8Array(labels.length);
  const stack: number[] = [];
  for (let start = 0; start < labels.length; start++) {
    if (seen[start] || out[start] !== target) continue;
    const members: number[] = [];
    const border = new Map<number, number>();
    let pinned = false;
    seen[start] = 1;
    stack.push(start);
    while (stack.length) {
      const i = stack.pop() ?? 0;
      members.push(i);
      const x = i % w;
      const y = (i - x) / w;
      const near = [
        x > 0 ? i - 1 : -1,
        x < w - 1 ? i + 1 : -1,
        y > 0 ? i - w : -1,
        y < h - 1 ? i + w : -1,
      ];
      for (const j of near) {
        if (j < 0) {
          pinned = true;
          continue;
        }
        const l = out[j] ?? 0;
        if (l === target) {
          if (!seen[j]) {
            seen[j] = 1;
            stack.push(j);
          }
        } else if (keep.includes(l)) {
          pinned = true;
        } else {
          border.set(l, (border.get(l) ?? 0) + 1);
        }
      }
    }
    if (pinned || members.length >= maxPx || !border.size) continue;
    let best = -1;
    let most = 0;
    for (const [l, n] of border) {
      if (n > most) {
        most = n;
        best = l;
      }
    }
    for (const i of members) out[i] = best;
  }
  return out;
}
