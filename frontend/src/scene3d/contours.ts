/* Контуры покрытий по маске земли: граница асфальта и плитки в метрах сцены. Чистая логика.
 *
 * Бортовой камень в подоснове распознан не везде (на Кустанайской - 10 линий на улицу), а
 * граница проезда в карте покрытий есть всегда. Маска - растр с размытой границей; изолиния
 * на половине яркости (marching squares с линейной интерполяцией по ребру клетки) даёт
 * гладкую линию, по которой 3D-вид ставит бортовой камень и обрезает плоскость земли:
 * камень и вырез под проезд совпадают, щелей нет. Ломаная упрощается и сглаживается. */

import type { Flat, Line } from './types';

export interface Grid {
  /** Яркость 0..255 построчно, width x height. */
  values: Uint8Array;
  width: number;
  height: number;
}

type Pt = [number, number];

/* Для каждого из 16 случаев - пары рёбер клетки, которые пересекает изолиния. Рёбра: 0 -
 * верх (a-b), 1 - право (b-c), 2 - низ (d-c), 3 - лево (a-d). Седловые случаи 5 и 10 - две
 * пары. Угол «внутри» - яркость не ниже порога. */
const CASES: readonly (readonly [number, number])[][] = [
  [],
  [[3, 0]],
  [[0, 1]],
  [[3, 1]],
  [[1, 2]],
  [
    [3, 0],
    [1, 2],
  ],
  [[0, 2]],
  [[3, 2]],
  [[2, 3]],
  [[2, 0]],
  [
    [0, 1],
    [2, 3],
  ],
  [[2, 1]],
  [[1, 3]],
  [[1, 0]],
  [[0, 3]],
  [],
];

/** Отрезки изолинии в пикселях маски, шаг клетки - step пикселей. */
export function isoSegments(grid: Grid, threshold: number, step: number): [Pt, Pt][] {
  const { values, width: w, height: h } = grid;
  const at = (x: number, y: number) => values[y * w + x] ?? 0;
  const out: [Pt, Pt][] = [];
  for (let y = 0; y + step < h; y += step) {
    for (let x = 0; x + step < w; x += step) {
      const a = at(x, y);
      const b = at(x + step, y);
      const c = at(x + step, y + step);
      const d = at(x, y + step);
      const index =
        (a >= threshold ? 1 : 0) |
        (b >= threshold ? 2 : 0) |
        (c >= threshold ? 4 : 0) |
        (d >= threshold ? 8 : 0);
      const pairs = CASES[index];
      if (!pairs?.length) continue;
      const lerp = (v0: number, v1: number) => (v1 === v0 ? 0.5 : (threshold - v0) / (v1 - v0));
      const edge = (e: number): Pt => {
        switch (e) {
          case 0:
            return [x + lerp(a, b) * step, y];
          case 1:
            return [x + step, y + lerp(b, c) * step];
          case 2:
            return [x + lerp(d, c) * step, y + step];
          default:
            return [x, y + lerp(a, d) * step];
        }
      };
      for (const [e0, e1] of pairs) out.push([edge(e0), edge(e1)]);
    }
  }
  return out;
}

/** Отрезки - в ломаные: соседние отрезки делят точку на общем ребре клетки. */
export function chain(segments: readonly [Pt, Pt][]): Pt[][] {
  const key = (p: Pt) => `${p[0].toFixed(3)},${p[1].toFixed(3)}`;
  const ends = new Map<string, number[]>();
  segments.forEach(([p, q], i) => {
    for (const k of [key(p), key(q)]) {
      const list = ends.get(k);
      if (list) list.push(i);
      else ends.set(k, [i]);
    }
  });
  const used = new Uint8Array(segments.length);
  const lines: Pt[][] = [];
  const extend = (line: Pt[], forward: boolean) => {
    for (;;) {
      const tip = forward ? line[line.length - 1] : line[0];
      if (!tip) return;
      const next = (ends.get(key(tip)) ?? []).find((i) => !used[i]);
      if (next === undefined) return;
      used[next] = 1;
      const seg = segments[next];
      if (!seg) return;
      const [p, q] = seg;
      const other = key(p) === key(tip) ? q : p;
      if (forward) line.push(other);
      else line.unshift(other);
    }
  };
  segments.forEach(([p, q], i) => {
    if (used[i]) return;
    used[i] = 1;
    const line: Pt[] = [p, q];
    extend(line, true);
    extend(line, false);
    lines.push(line);
  });
  return lines;
}

function segDistance(p: Pt, a: Pt, b: Pt): number {
  const vx = b[0] - a[0];
  const vy = b[1] - a[1];
  const len2 = vx * vx + vy * vy;
  const t = len2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / len2)) : 0;
  return Math.hypot(a[0] + vx * t - p[0], a[1] + vy * t - p[1]);
}

/** Дуглас-Пекер для открытой ломаной. */
export function simplify(line: readonly Pt[], tolerance: number): Pt[] {
  if (line.length < 3) return [...line];
  const keep = new Uint8Array(line.length);
  keep[0] = 1;
  keep[line.length - 1] = 1;
  const stack: [number, number][] = [[0, line.length - 1]];
  while (stack.length) {
    const [from, to] = stack.pop() ?? [0, 0];
    const a = line[from];
    const b = line[to];
    if (!a || !b) continue;
    let index = -1;
    let max = tolerance;
    for (let i = from + 1; i < to; i++) {
      const p = line[i];
      if (!p) continue;
      const d = segDistance(p, a, b);
      if (d > max) {
        max = d;
        index = i;
      }
    }
    if (index < 0) continue;
    keep[index] = 1;
    stack.push([from, index], [index, to]);
  }
  return line.filter((_, i) => keep[i]);
}

/** Сглаживание Чайкина: углы растра скругляются, концы ломаной остаются на месте. */
export function chaikin(line: readonly Pt[], iterations = 2): Pt[] {
  let out = [...line];
  for (let k = 0; k < iterations && out.length > 2; k++) {
    const next: Pt[] = [out[0] ?? [0, 0]];
    for (let i = 0; i + 1 < out.length; i++) {
      const [ax, ay] = out[i] ?? [0, 0];
      const [bx, by] = out[i + 1] ?? [0, 0];
      next.push([ax * 0.75 + bx * 0.25, ay * 0.75 + by * 0.25]);
      next.push([ax * 0.25 + bx * 0.75, ay * 0.25 + by * 0.75]);
    }
    next.push(out[out.length - 1] ?? [0, 0]);
    out = next;
  }
  return out;
}

/** Контуры маски в метрах сцены: rect - угол и размер маски, mpp - метров на пиксель. */
export function contours(
  grid: Grid,
  rect: readonly [number, number, number, number],
  metresPerPx: number,
  { threshold = 128, step = 2, minLength = 1.5 } = {},
): Line[] {
  const lines = chain(isoSegments(grid, threshold, step));
  const out: Line[] = [];
  for (const raw of lines) {
    const metres = raw.map(([x, y]): Pt => [
      rect[0] + (x + 0.5) * metresPerPx,
      rect[1] + (y + 0.5) * metresPerPx,
    ]);
    let length = 0;
    for (let i = 1; i < metres.length; i++) {
      const a = metres[i - 1] ?? [0, 0];
      const b = metres[i] ?? [0, 0];
      length += Math.hypot(b[0] - a[0], b[1] - a[1]);
    }
    if (length < minLength) continue;
    const smooth = chaikin(simplify(metres, metresPerPx * 0.35));
    out.push({ points: smooth.map(([x, z]): Flat => ({ x, z })) });
  }
  return out;
}

/** Скругление углов замкнутого контура: срез угла - четверть стороны, но не больше cap
 *  метров. Длинные прямые остаются прямыми, повороты дороги - дугами, мелкие изломы
 *  растра - сглаживаются. */
export function roundCorners(loop: readonly Pt[], cap: number, iterations = 3): Pt[] {
  let out = loop.slice(0, -1);
  for (let k = 0; k < iterations && out.length > 2; k++) {
    const next: Pt[] = [];
    for (let i = 0; i < out.length; i++) {
      const [ax, ay] = out[i] ?? [0, 0];
      const [bx, by] = out[(i + 1) % out.length] ?? [0, 0];
      const len = Math.hypot(bx - ax, by - ay);
      const t = len > 0 ? Math.min(0.25, cap / len) : 0.25;
      next.push([ax + (bx - ax) * t, ay + (by - ay) * t]);
      next.push([ax + (bx - ax) * (1 - t), ay + (by - ay) * (1 - t)]);
    }
    out = next;
  }
  const first = out[0];
  return first ? [...out, first] : out;
}

function ringLength(loop: readonly Pt[]): number {
  let s = 0;
  for (let i = 0; i + 1 < loop.length; i++) {
    const [ax, ay] = loop[i] ?? [0, 0];
    const [bx, by] = loop[i + 1] ?? [0, 0];
    s += Math.hypot(bx - ax, by - ay);
  }
  return s;
}

function ringArea(loop: readonly Pt[]): number {
  let s = 0;
  for (let i = 0; i + 1 < loop.length; i++) {
    const [ax, ay] = loop[i] ?? [0, 0];
    const [bx, by] = loop[i + 1] ?? [0, 0];
    s += ax * by - bx * ay;
  }
  return Math.abs(s) / 2;
}

/** Замкнутый контур - точками через равный шаг по длине (последняя точка = первой). */
export function resample(loop: readonly Pt[], spacing: number): Pt[] {
  const out: Pt[] = [];
  let carry = 0;
  for (let i = 0; i + 1 < loop.length; i++) {
    const [ax, ay] = loop[i] ?? [0, 0];
    const [bx, by] = loop[i + 1] ?? [0, 0];
    const len = Math.hypot(bx - ax, by - ay);
    let t = carry;
    while (t < len) {
      out.push([ax + ((bx - ax) * t) / len, ay + ((by - ay) * t) / len]);
      t += spacing;
    }
    carry = t - len;
  }
  const first = out[0];
  return first ? [...out, first] : out;
}

/** Скользящее среднее по замкнутому контуру: окно 2r+1 точек, проходов passes. */
export function averageLoop(loop: readonly Pt[], r: number, passes = 2): Pt[] {
  let pts = loop.slice(0, -1);
  const n = pts.length;
  if (n < 3 || r < 1) return [...loop];
  for (let k = 0; k < passes; k++) {
    const next: Pt[] = [];
    for (let i = 0; i < n; i++) {
      let sx = 0;
      let sy = 0;
      for (let j = -r; j <= r; j++) {
        const [x, y] = pts[(((i + j) % n) + n) % n] ?? [0, 0];
        sx += x;
        sy += y;
      }
      next.push([sx / (2 * r + 1), sy / (2 * r + 1)]);
    }
    pts = next;
  }
  const first = pts[0];
  return first ? [...pts, first] : pts;
}

/** Ровные замкнутые контуры областей маски, как их чертит проектировщик: изолиния по маске
 *  с полем нулей вокруг (каждый контур замкнут), усреднение вдоль контура окном window
 *  метров снимает волну клеток карты, Дуглас-Пекер с малым допуском оставляет прямые
 *  отрезки, углы скругляются срезом до cap метров. Контуры площадью меньше minArea м² и
 *  уже minWidth метров в среднем (2 x площадь / периметр) отбрасываются: щель в проезде
 *  давала второй бортовой камень посреди асфальта. Выпрямлять сразу Дугласом-Пекером нельзя: его вершины ложатся на гребни
 *  волны, и после скругления край снова волнистый. */
export function outlines(
  grid: Grid,
  rect: readonly [number, number, number, number],
  metresPerPx: number,
  {
    window = 3,
    tolerance = 0.12,
    cap = 1,
    minArea = 4,
    minWidth = 0,
    step = 2,
    angles = [] as readonly number[],
  } = {},
): Line[] {
  const pad = step;
  const w = grid.width + pad * 2;
  const h = grid.height + pad * 2;
  const values = new Uint8Array(w * h);
  for (let y = 0; y < grid.height; y++) {
    values.set(grid.values.subarray(y * grid.width, (y + 1) * grid.width), (y + pad) * w + pad);
  }
  const spacing = 0.5;
  const out: Line[] = [];
  for (const raw of chain(isoSegments({ values, width: w, height: h }, 128, step))) {
    const metres = raw.map(([x, y]): Pt => [
      rect[0] + (x - pad + 0.5) * metresPerPx,
      rect[1] + (y - pad + 0.5) * metresPerPx,
    ]);
    if (metres.length < 4) continue;
    const area = ringArea(metres);
    if (area < minArea || 2 * area < minWidth * ringLength(metres)) continue;
    // Окно не больше шестой части периметра: маленький островок газона длинным окном съёжился бы.
    const span = Math.min(window, ringLength(metres) / 6);
    const even = averageLoop(resample(metres, spacing), Math.round(span / 2 / spacing));
    const simple = simplify(even, tolerance);
    if (simple.length < 4) continue;
    // Стороны - параллельно стенам и бортам участка, если направление близко.
    const straight = angles.length ? snapToAngles(simple, angles) : simple;
    const smooth = roundCorners(straight, cap, 2);
    out.push({ points: smooth.map(([x, z]): Flat => ({ x, z })) });
  }
  return out;
}

/** Ломаные из отрезков, которые прошли проверку keep: остальные отрезки - разрывы. */
export function keepSegments(lines: readonly Line[], keep: (a: Flat, b: Flat) => boolean): Line[] {
  const out: Line[] = [];
  for (const line of lines) {
    let run: Flat[] = [];
    for (let i = 0; i + 1 < line.points.length; i++) {
      const a = line.points[i];
      const b = line.points[i + 1];
      if (!a || !b) continue;
      if (keep(a, b)) {
        if (!run.length) run.push(a);
        run.push(b);
      } else if (run.length) {
        out.push({ points: run });
        run = [];
      }
    }
    if (run.length > 1) out.push({ points: run });
  }
  return out;
}

/** Главные направления участка по линиям чертежа (стены, борта, ограды): гистограмма углов
 *  отрезков по модулю 90° с весом длины, шаг 1°. Возвращает до двух пиков в радианах: второй -
 *  если он не слабее четверти первого и отстоит от него хотя бы на 10°. */
export function dominantAngles(lines: readonly Line[]): number[] {
  const bins = new Float64Array(90);
  const samples: [number, number][] = [];
  for (const line of lines) {
    for (let i = 0; i + 1 < line.points.length; i++) {
      const a = line.points[i];
      const b = line.points[i + 1];
      if (!a || !b) continue;
      const len = Math.hypot(b.x - a.x, b.z - a.z);
      if (len < 2) continue;
      const deg = ((Math.atan2(b.z - a.z, b.x - a.x) * 180) / Math.PI + 360) % 90;
      const k = Math.floor(deg) % 90;
      bins[k] = (bins[k] ?? 0) + len;
      samples.push([deg, len]);
    }
  }
  // Сглаживание гистограммы по кругу: соседние градусы - одно направление.
  const smooth = Array.from({ length: 90 }, (_, k) => {
    let s = 0;
    for (let d = -2; d <= 2; d++) s += bins[(k + d + 90) % 90] ?? 0;
    return s;
  });
  const peak = (skipNear: number | null) => {
    let best = -1;
    let bestValue = 0;
    smooth.forEach((v, k) => {
      if (skipNear !== null) {
        const d = Math.min(Math.abs(k - skipNear), 90 - Math.abs(k - skipNear));
        if (d < 10) return;
      }
      if (v > bestValue) {
        bestValue = v;
        best = k;
      }
    });
    return [best, bestValue] as const;
  };
  // Точный угол пика - средний по отрезкам в 3° от него, с весом длины.
  const refine = (k: number) => {
    let sum = 0;
    let weight = 0;
    for (const [deg, len] of samples) {
      const d = ((deg - (k + 0.5) + 135) % 90) - 45;
      if (Math.abs(d) > 3) continue;
      sum += d * len;
      weight += len;
    }
    return ((k + 0.5 + (weight ? sum / weight : 0)) * Math.PI) / 180;
  };
  const [first, firstValue] = peak(null);
  if (first < 0 || !firstValue) return [];
  const out = [refine(first)];
  const [second, secondValue] = peak(first);
  if (second >= 0 && secondValue >= firstValue / 4) out.push(refine(second));
  return out;
}

/** Стороны замкнутого контура длиной от minSide, отклонённые от главного направления (или
 *  перпендикуляра к нему) не больше tolDeg, поворачиваются вокруг середины параллельно ему;
 *  вершины - пересечения соседних сторон, а если стороны почти параллельны или пересечение
 *  ушло дальше 3 м - прежняя вершина. Поворот, сдвигающий конец стороны дальше maxShift,
 *  не делается: выравнивание, а не перекройка участка. Так край газона встаёт параллельно стене и борту. */
export function snapToAngles(
  loop: readonly Pt[],
  angles: readonly number[],
  { minSide = 4, tolDeg = 15, maxShift = 0.6 } = {},
): Pt[] {
  const pts = loop.slice(0, -1);
  const n = pts.length;
  if (n < 3 || !angles.length) return [...loop];
  const tol = (tolDeg * Math.PI) / 180;
  const dirs: [number, number][] = [];
  const mids: Pt[] = [];
  for (let i = 0; i < n; i++) {
    const [ax, ay] = pts[i] ?? [0, 0];
    const [bx, by] = pts[(i + 1) % n] ?? [0, 0];
    const len = Math.hypot(bx - ax, by - ay) || 1;
    let dx = (bx - ax) / len;
    let dy = (by - ay) / len;
    if (len >= minSide) {
      const own = Math.atan2(dy, dx);
      for (const base of angles) {
        for (let q = 0; q < 4; q++) {
          const target = base + (q * Math.PI) / 2;
          const diff = Math.atan2(Math.sin(own - target), Math.cos(own - target));
          // Концы стороны при повороте вокруг середины сдвигаются на len/2 * sin(diff): длинная
          // сторона, повёрнутая на 10°, наползала на соседнюю дорожку.
          if (Math.abs(diff) <= tol && (len / 2) * Math.abs(Math.sin(diff)) <= maxShift) {
            dx = Math.cos(target);
            dy = Math.sin(target);
          }
        }
      }
    }
    dirs.push([dx, dy]);
    mids.push([(ax + bx) / 2, (ay + by) / 2]);
  }
  const out: Pt[] = [];
  for (let i = 0; i < n; i++) {
    const prev = (i - 1 + n) % n;
    const [d1x, d1y] = dirs[prev] ?? [1, 0];
    const [d2x, d2y] = dirs[i] ?? [1, 0];
    const [p1x, p1y] = mids[prev] ?? [0, 0];
    const [p2x, p2y] = mids[i] ?? [0, 0];
    const original = pts[i] ?? [0, 0];
    const cross = d1x * d2y - d1y * d2x;
    if (Math.abs(cross) < Math.sin((5 * Math.PI) / 180)) {
      out.push(original);
      continue;
    }
    const t = ((p2x - p1x) * d2y - (p2y - p1y) * d2x) / cross;
    const hit: Pt = [p1x + d1x * t, p1y + d1y * t];
    out.push(
      Math.hypot(hit[0] - original[0], hit[1] - original[1]) > 2 * maxShift ? original : hit,
    );
  }
  const first = out[0];
  return first ? [...out, first] : out;
}
