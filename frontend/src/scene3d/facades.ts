/* Дом в 3D по типовой серии: что и где стоит на фасаде. Чистая логика без three.js.
 *
 * Съёмка Мосгеотреста фасадов не несёт: у здания есть контур, этажность из подписи и признаки
 * «жилое/нежилое», «камень/металл». Буква «К» - любой каменный дом, и кирпичный, и панельный,
 * поэтому серия выбирается по этажности и назначению, как застроены спальные районы Москвы:
 * 12 этажей и выше - панельная башня, 6-11 - панельная пластина, 4-5 - пятиэтажка, ниже -
 * кирпичный дом. Нежилое до трёх этажей - павильон с витринами.
 *
 * По серии раскладываются модули: лоджии стопками по пролётам, подъезды со стороны двора по
 * секциям, машинные помещения на крыше. Двор - сторона дома, дальняя от бортов проезда.
 * Это правдоподобная раскладка типового дома, а не съёмка конкретного фасада. */

import type { Building, Flat, Line, Ring } from './types';

export type Series = 'tower' | 'slab' | 'khrushchev' | 'brick' | 'pavilion' | 'metal' | 'porch';

/** Номер рисунка фасада в шейдере (buildings.ts). */
export const STYLE_OF: Record<Series, number> = {
  tower: 0,
  slab: 0,
  khrushchev: 5,
  brick: 1,
  pavilion: 2,
  metal: 3,
  porch: 4,
};

export function seriesOf(b: Building): Series {
  if (b.kind !== 'building') return 'porch';
  if (b.wall === 'metal') return 'metal';
  const residential = b.use !== 'non_residential';
  if (!residential) return b.floors <= 3 ? 'pavilion' : 'slab';
  if (b.floors >= 12) return 'tower';
  if (b.floors >= 6) return 'slab';
  if (b.floors >= 4) return 'khrushchev';
  return b.floors <= 1 && b.use === null ? 'pavilion' : 'brick';
}

/** Пролёт фасада, метры: по нему шейдер рисует окна, а модули встают в те же ячейки. */
export function bayOf(series: Series): number {
  return series === 'brick' ? 2.8 : 3;
}

export function storeyOf(b: Building): number {
  return b.floors <= 1 ? b.height : (b.height - 1.2) / b.floors;
}

export const PLINTH_M = 0.9;

export type Rgb = readonly [number, number, number];

export interface Palette {
  wall: Rgb;
  accent: Rgb;
}

function hex(value: string): Rgb {
  const v = Number.parseInt(value.slice(1), 16);
  return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
}

/* Цвета - sRGB, как на фото улиц пилота: белые и бежевые панели, цветные ограждения лоджий
 * и цоколь, красный и жёлтый кирпич. */
const WALLS: Record<Series, readonly string[]> = {
  tower: ['#ece9e2', '#efe8da', '#e2e1dd', '#ebe2d0', '#e6e6e1'],
  slab: ['#e6e3dc', '#ddd9d0', '#e9e1cf', '#e1ded8'],
  khrushchev: ['#d9d3c5', '#cfc9bb', '#e1dcd1', '#c9c6c0'],
  brick: ['#a65a41', '#b8704f', '#d6c196', '#c9b38a'],
  pavilion: ['#d8d6d1', '#cacdd1', '#e0dcd2'],
  metal: ['#a0a7ab', '#88939a'],
  porch: ['#bdbab3'],
};
const ACCENTS: readonly string[] = [
  '#6d8db2',
  '#b4664b',
  '#7a9a6f',
  '#c7a35d',
  '#8f949b',
  '#5f7f97',
];

export function paletteOf(b: Building, series: Series): Palette {
  const walls = WALLS[series];
  const wall = walls[b.seed % walls.length] ?? walls[0] ?? '#dddddd';
  const accent = ACCENTS[(b.seed >>> 5) % ACCENTS.length] ?? '#8f949b';
  return { wall: hex(wall), accent: hex(accent) };
}

function segDistance(p: Flat, a: Flat, b: Flat): number {
  const vx = b.x - a.x;
  const vz = b.z - a.z;
  const len2 = vx * vx + vz * vz;
  const t = len2 > 0 ? Math.max(0, Math.min(1, ((p.x - a.x) * vx + (p.z - a.z) * vz) / len2)) : 0;
  return Math.hypot(a.x + vx * t - p.x, a.z + vz * t - p.z);
}

/** Контур без дрожания: Дуглас-Пекер с допуском в сантиметры. На длинном доме съёмка даёт
 *  ломаную из коротких кусков, и стена шла бы изломами, а окна - косыми рядами. */
export function simplifyRing(ring: Ring, tolerance = 0.25): Ring {
  if (ring.length <= 4) return ring;
  const keep = new Uint8Array(ring.length);
  // Опорные точки - две самые дальние друг от друга: кольцо делится на две ломаные.
  let far = 0;
  let best = -1;
  const first = ring[0];
  if (!first) return ring;
  ring.forEach((p, i) => {
    const d = Math.hypot(p.x - first.x, p.z - first.z);
    if (d > best) {
      best = d;
      far = i;
    }
  });
  keep[0] = 1;
  keep[far] = 1;
  const stack: [number, number][] = [
    [0, far],
    [far, ring.length],
  ];
  while (stack.length) {
    const [from, to] = stack.pop() ?? [0, 0];
    const a = ring[from];
    const b = ring[to % ring.length];
    if (!a || !b || to - from < 2) continue;
    let index = -1;
    let max = tolerance;
    for (let i = from + 1; i < to; i++) {
      const p = ring[i];
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
  const out = ring.filter((_, i) => keep[i]);
  return out.length >= 3 ? out : ring;
}

export function ringArea(ring: Ring): number {
  let sum = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i];
    const b = ring[(i + 1) % ring.length];
    if (a && b) sum += a.x * b.z - b.x * a.z;
  }
  return sum / 2;
}

/** Стена кольца: начало, касательная, нормаль наружу и u - метры вдоль контура от его
 *  начала, как у развёртки стен в buildings.ts. */
export interface Wall {
  a: Flat;
  b: Flat;
  length: number;
  tx: number;
  tz: number;
  nx: number;
  nz: number;
  u0: number;
}

export function wallsOf(ring: Ring, hole: boolean): Wall[] {
  const outward = ringArea(ring) > 0 !== hole ? 1 : -1;
  const out: Wall[] = [];
  let along = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i];
    const b = ring[(i + 1) % ring.length];
    if (!a || !b) continue;
    const dx = b.x - a.x;
    const dz = b.z - a.z;
    const length = Math.hypot(dx, dz);
    if (length < 0.05) continue;
    out.push({
      a,
      b,
      length,
      tx: dx / length,
      tz: dz / length,
      nx: (dz / length) * outward,
      nz: (-dx / length) * outward,
      u0: along,
    });
    along += length;
  }
  return out;
}

/** Главная ось дома: прямоугольник наименьшей площади вокруг контура, по направлениям его
 *  сторон. По оси дом делится на секции. */
export interface Axis {
  cx: number;
  cz: number;
  dx: number;
  dz: number;
  length: number;
  width: number;
}

export function mainAxis(ring: Ring): Axis {
  let best: Axis = { cx: 0, cz: 0, dx: 1, dz: 0, length: 0, width: 0 };
  let bestArea = Number.POSITIVE_INFINITY;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i];
    const b = ring[(i + 1) % ring.length];
    if (!a || !b) continue;
    const len = Math.hypot(b.x - a.x, b.z - a.z);
    if (len < 0.5) continue;
    const dx = (b.x - a.x) / len;
    const dz = (b.z - a.z) / len;
    let minU = Infinity;
    let maxU = -Infinity;
    let minV = Infinity;
    let maxV = -Infinity;
    for (const p of ring) {
      const u = p.x * dx + p.z * dz;
      const v = -p.x * dz + p.z * dx;
      minU = Math.min(minU, u);
      maxU = Math.max(maxU, u);
      minV = Math.min(minV, v);
      maxV = Math.max(maxV, v);
    }
    const area = (maxU - minU) * (maxV - minV);
    if (area >= bestArea) continue;
    bestArea = area;
    const cu = (minU + maxU) / 2;
    const cv = (minV + maxV) / 2;
    const long = maxU - minU >= maxV - minV;
    best = {
      cx: cu * dx - cv * dz,
      cz: cu * dz + cv * dx,
      dx: long ? dx : -dz,
      dz: long ? dz : dx,
      length: Math.max(maxU - minU, maxV - minV),
      width: Math.min(maxU - minU, maxV - minV),
    };
  }
  return best;
}

export function insideRing(p: Flat, ring: Ring): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[i];
    const b = ring[j];
    if (!a || !b) continue;
    if (a.z > p.z !== b.z > p.z && p.x < ((b.x - a.x) * (p.z - a.z)) / (b.z - a.z) + a.x) {
      inside = !inside;
    }
  }
  return inside;
}

/** Модуль на фасаде или крыше: точка на стене, угол поворота (модуль смотрит +z наружу),
 *  размеры. Высота y - низ модуля. */
export interface Module {
  x: number;
  z: number;
  y: number;
  angle: number;
  width: number;
  height: number;
  depth: number;
  accent: Rgb;
}

export interface Loggia extends Module {
  glazed: boolean;
}

export interface FacadePlan {
  loggias: Loggia[];
  entrances: Module[];
  roofBoxes: Module[];
}

const SECTION_M: Partial<Record<Series, number>> = { slab: 26, khrushchev: 15, brick: 16 };
const LOGGIA_DEPTH_M = 1.15;

function distanceToCurbs(p: Flat, curbs: readonly Line[]): number {
  let best = Number.POSITIVE_INFINITY;
  for (const line of curbs) {
    for (let i = 0; i + 1 < line.points.length; i++) {
      const a = line.points[i];
      const b = line.points[i + 1];
      if (a && b) best = Math.min(best, segDistance(p, a, b));
    }
  }
  return best;
}

/** Сторона двора: +1 или -1 поперёк оси. Двор дальше от бортов, чем улица. */
export function yardSide(axis: Axis, curbs: readonly Line[], seed: number): 1 | -1 {
  const px = -axis.dz;
  const pz = axis.dx;
  const reach = axis.width / 2 + 10;
  const plus = distanceToCurbs({ x: axis.cx + px * reach, z: axis.cz + pz * reach }, curbs);
  const minus = distanceToCurbs({ x: axis.cx - px * reach, z: axis.cz - pz * reach }, curbs);
  if (!Number.isFinite(plus) && !Number.isFinite(minus)) return seed % 2 ? 1 : -1;
  return plus >= minus ? 1 : -1;
}

/** Ближняя стена по лучу из точки внутри дома: на ней и встанет подъезд секции. */
function hitWall(
  walls: readonly Wall[],
  from: Flat,
  dx: number,
  dz: number,
): [Wall, number] | null {
  let best: [Wall, number] | null = null;
  let bestT = Number.POSITIVE_INFINITY;
  for (const w of walls) {
    // Луч from + t*d против отрезка a + s*(b-a).
    const ex = w.b.x - w.a.x;
    const ez = w.b.z - w.a.z;
    const den = dx * ez - dz * ex;
    if (Math.abs(den) < 1e-9) continue;
    const ax = w.a.x - from.x;
    const az = w.a.z - from.z;
    const t = (ax * ez - az * ex) / den;
    const s = (ax * dz - az * dx) / den;
    if (t <= 0 || s < 0 || s > 1 || t >= bestT) continue;
    bestT = t;
    best = [w, s * w.length];
  }
  return best;
}

function angleOf(w: Wall): number {
  return Math.atan2(w.nx, w.nz);
}

function onWall(w: Wall, u: number, y: number): { x: number; z: number; y: number } {
  return { x: w.a.x + w.tx * u, z: w.a.z + w.tz * u, y };
}

function hash(a: number, b: number, c: number): number {
  let h = Math.imul(a ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(b + 0x632be5ab, 0xc2b2ae35);
  h = Math.imul(h ^ (h >>> 13) ^ c, 0x27d4eb2f);
  return ((h ^ (h >>> 15)) >>> 0) / 4294967296;
}

/** Раскладка модулей одного дома. */
export function facadePlan(b: Building, curbs: readonly Line[]): FacadePlan {
  const plan: FacadePlan = { loggias: [], entrances: [], roofBoxes: [] };
  const series = seriesOf(b);
  const outer = b.rings[0];
  if (!outer || outer.length < 3 || b.floors < 2) return plan;
  const palette = paletteOf(b, series);
  const walls = wallsOf(outer, false);
  const axis = mainAxis(outer);
  const residential = series === 'tower' || series === 'slab' || series === 'khrushchev';
  const storey = storeyOf(b);
  const sectionLength = SECTION_M[series];
  const sections =
    series === 'tower' || !sectionLength ? 1 : Math.max(1, Math.round(axis.length / sectionLength));
  const centers: Flat[] = [];
  for (let i = 0; i < sections; i++) {
    const k = ((i + 0.5) / sections - 0.5) * axis.length;
    centers.push({ x: axis.cx + axis.dx * k, z: axis.cz + axis.dz * k });
  }

  // Подъезды - со двора, по одному на секцию; у кирпичного дома тоже.
  const doorBays: { wall: Wall; u: number }[] = [];
  if (residential || series === 'brick') {
    const side = yardSide(axis, curbs, b.seed);
    const dx = -axis.dz * side;
    const dz = axis.dx * side;
    for (const c of centers) {
      if (!insideRing(c, outer)) continue;
      const hit = hitWall(walls, c, dx, dz);
      if (!hit) continue;
      const [wall, u] = hit;
      if (wall.length < 4 || u < 1.6 || u > wall.length - 1.6) continue;
      doorBays.push({ wall, u });
      plan.entrances.push({
        ...onWall(wall, u, 0),
        angle: angleOf(wall),
        width: 2.6,
        height: 2.9,
        depth: 1.5,
        accent: palette.accent,
      });
    }
  }

  // Лоджии стопками в одних и тех же пролётах снизу доверху; у пятиэтажки - открытые
  // балконы. Рядом с подъездом - лестница, лоджий нет.
  if (residential) {
    const bay = bayOf(series);
    const pattern = b.seed % 3;
    const stack = (index: number) =>
      pattern === 0
        ? index % 3 === 1
        : pattern === 1
          ? index % 4 === 1 || index % 4 === 2
          : index % 2 === 1;
    const width = series === 'khrushchev' ? 2.6 : 2.7;
    for (const wall of walls) {
      if (wall.length < 6) continue;
      const first = Math.ceil(wall.u0 / bay);
      const last = Math.floor((wall.u0 + wall.length) / bay);
      for (let index = first; index < last; index++) {
        if (!stack(index)) continue;
        const u = (index + 0.5) * bay - wall.u0;
        if (u - width / 2 < 0.35 || u + width / 2 > wall.length - 0.35) continue;
        if (doorBays.some((d) => d.wall === wall && Math.abs(d.u - u) < bay * 1.5)) continue;
        for (let level = 1; level < b.floors; level++) {
          const glazed = series !== 'khrushchev' && hash(b.seed, index, level) < 0.72;
          plan.loggias.push({
            ...onWall(wall, u, PLINTH_M + level * storey),
            angle: angleOf(wall),
            width,
            height: storey,
            depth: series === 'khrushchev' ? 0.9 : LOGGIA_DEPTH_M,
            accent: palette.accent,
            glazed,
          });
        }
      }
    }
  }

  // Машинное помещение лифта и выход на крышу - над каждой секцией многоэтажки.
  if (series === 'tower' || series === 'slab') {
    for (const c of centers) {
      if (!insideRing(c, outer)) continue;
      plan.roofBoxes.push({
        x: c.x,
        z: c.z,
        y: b.height,
        angle: Math.atan2(axis.dx, axis.dz),
        width: Math.min(6, axis.width * 0.45),
        height: 2.6,
        depth: 4,
        accent: palette.wall,
      });
    }
  }
  return plan;
}
