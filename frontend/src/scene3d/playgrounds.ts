/* Оборудование детских и спортивных площадок. Чертёж даёт контур резины (part вида special в
 * surface.json) и подписи «ДЕТ.ПЛ.» и «СПОРТ ПЛ.», но не сами качели и ворота: площадка в 3D
 * стояла пустой резиной (пользователь, 19.10.2026). Каталог - типовые московские предметы с
 * габаритом и свободной зоной вокруг (у качелей - в сторону качания): комплекс с башнями и
 * горкой, качели, гнездо, карусель, балансир, качалка, песочница; на спортивной ворота,
 * турники, баскетбольная стойка, теннисный стол. Что ставить, решает площадь: набор идёт по
 * каталогу от крупного к мелкому, и предмет встаёт, только если он со своей зоной целиком
 * влез в контур, не задел деревья, опоры и зоны других предметов (пользователь, 19.10.2026:
 * «дать им размер и по тому, что влезет в площадь площадки, то и ставить»). Место - самое
 * свободное: дальше всего от края и от уже поставленного. Скамейки - спинкой к ограде,
 * рядом урна. */

import { mainAxis } from './facades';
import type { Flat } from './types';

type Ring = readonly Flat[];

export type GroundKind = 'kids' | 'sports';
export type ItemKind =
  | 'complex'
  | 'slide'
  | 'swing'
  | 'nest'
  | 'carousel'
  | 'seesaw'
  | 'rocker'
  | 'sandbox'
  | 'goal'
  | 'bars'
  | 'hoop'
  | 'table'
  | 'bench'
  | 'bin';

export interface GroundLabel {
  x: number;
  z: number;
  kind: GroundKind;
}

export interface Ground {
  rings: Ring[];
  kind: GroundKind;
  anchor: Flat;
  /** Номер части резины: подписи на одной части делят её между собой. */
  part: number;
}

export interface Item {
  kind: ItemKind;
  x: number;
  z: number;
  /** Поворот вокруг вертикали: ось x модели - вдоль, у скамейки сиденье смотрит в +z. */
  angle: number;
}

/** Занятое место: прямоугольник предмета с его свободной зоной. */
export interface Zone {
  x: number;
  z: number;
  angle: number;
  hu: number;
  hv: number;
}

/** Препятствие кругом: ствол с лункой, опора, нарисованная скамейка. */
export interface Obstacle {
  x: number;
  z: number;
  r: number;
}

interface Spec {
  /** Габарит в плане вдоль оси модели x и поперёк, м; высота - для твёрдой камеры. */
  len: number;
  wid: number;
  height: number;
  /** Свободная зона за габаритом вдоль и поперёк, м: в ней не стоит другое оборудование. */
  zoneU: number;
  zoneV: number;
  /** Габарит не ближе этого к краю контура, м. */
  edge: number;
  /** Круглый предмет: поворот не важен. */
  round?: boolean;
}

export const SPECS: Record<ItemKind, Spec> = {
  complex: { len: 7.0, wid: 5.0, height: 3.4, zoneU: 1.5, zoneV: 1.5, edge: 0.4 },
  slide: { len: 4.4, wid: 1.3, height: 2.7, zoneU: 1.5, zoneV: 1.0, edge: 0.4 },
  swing: { len: 3.4, wid: 1.9, height: 2.4, zoneU: 0.5, zoneV: 1.8, edge: 0.4 },
  nest: { len: 2.8, wid: 1.9, height: 2.3, zoneU: 0.5, zoneV: 1.6, edge: 0.4 },
  carousel: { len: 1.7, wid: 1.7, height: 1.0, zoneU: 1.5, zoneV: 1.5, edge: 0.4, round: true },
  seesaw: { len: 3.0, wid: 0.6, height: 0.9, zoneU: 1.0, zoneV: 1.0, edge: 0.4 },
  rocker: { len: 1.0, wid: 0.45, height: 0.9, zoneU: 0.8, zoneV: 0.8, edge: 0.4 },
  sandbox: { len: 2.0, wid: 2.0, height: 0.3, zoneU: 0.6, zoneV: 0.6, edge: 0.4 },
  goal: { len: 3.0, wid: 1.0, height: 2.0, zoneU: 0.3, zoneV: 0.3, edge: 0.3 },
  bars: { len: 2.6, wid: 0.6, height: 2.3, zoneU: 1.0, zoneV: 1.0, edge: 0.4 },
  hoop: { len: 1.2, wid: 1.4, height: 3.4, zoneU: 0.5, zoneV: 0.5, edge: 0.3 },
  table: { len: 2.74, wid: 1.53, height: 0.76, zoneU: 1.5, zoneV: 1.0, edge: 0.4 },
  bench: { len: 1.8, wid: 0.6, height: 0.9, zoneU: 0.1, zoneV: 0.4, edge: 0.15 },
  bin: { len: 0.45, wid: 0.45, height: 0.8, zoneU: 0.05, zoneV: 0.05, edge: 0.1, round: true },
};

/** Набор детской площадки по порядку: крупное раньше, со своей наименьшей площадью, м².
 *  Горка - если комплекс не встал. */
const KIDS: { kind: ItemKind; minArea: number }[] = [
  { kind: 'complex', minArea: 150 },
  { kind: 'slide', minArea: 0 },
  { kind: 'swing', minArea: 40 },
  { kind: 'carousel', minArea: 100 },
  { kind: 'seesaw', minArea: 70 },
  { kind: 'sandbox', minArea: 0 },
  { kind: 'nest', minArea: 220 },
  { kind: 'rocker', minArea: 120 },
  { kind: 'swing', minArea: 380 },
  { kind: 'rocker', minArea: 260 },
];
/** Спортивная без поля: стол, турники, стойка. */
const SPORTS: { kind: ItemKind; minArea: number }[] = [
  { kind: 'table', minArea: 60 },
  { kind: 'bars', minArea: 0 },
  { kind: 'hoop', minArea: 80 },
  { kind: 'bars', minArea: 160 },
  { kind: 'table', minArea: 240 },
];
/** Ценность предмета для выбора между расстановками: крупное и игровое дороже. */
const VALUE: Record<ItemKind, number> = {
  complex: 5,
  slide: 3,
  swing: 3,
  nest: 2,
  carousel: 2,
  seesaw: 2,
  sandbox: 2,
  rocker: 1,
  goal: 3,
  bars: 2,
  hoop: 2,
  table: 2,
  bench: 0,
  bin: 0,
};
/** Поле с воротами - на площадке не короче и не уже этого, м. */
const FIELD_LENGTH_M = 14;
const FIELD_WIDTH_M = 7;
/** Подпись площадки дальше этого от контура резины - не этой площадки, м. */
const LABEL_REACH_M = 1.0;
/** Две подписи одного вида ближе этого - одна площадка, м. */
const SAME_GROUND_M = 8.0;
/** Точек-кандидатов на площадку не больше этого: шаг сетки растёт с площадью. */
const MAX_CANDIDATES = 1500;
/** Шаг проверки стороны зоны на вхождение в контур, м. */
const SAMPLE_M = 1.0;

export function groundKind(text: string): GroundKind | null {
  const t = text.trim().toUpperCase();
  if (/^ДЕТ\W*ПЛ/.test(t)) return 'kids';
  if (/^СПОРТ\W*ПЛ/.test(t)) return 'sports';
  return null;
}

/** Площадки: контур резины и подписи на нём. Подпись каждого вида даёт свой набор. */
export function groundsOf(parts: readonly Ring[][], labels: readonly GroundLabel[]): Ground[] {
  const out: Ground[] = [];
  parts.forEach((rings, part) => {
    const own: GroundLabel[] = [];
    for (const label of labels) {
      if (distanceToArea(rings, label) > LABEL_REACH_M) continue;
      const twin = own.some(
        (o) => o.kind === label.kind && Math.hypot(o.x - label.x, o.z - label.z) < SAME_GROUND_M,
      );
      if (!twin) own.push(label);
    }
    for (const label of own) out.push({ rings: [...rings], kind: label.kind, anchor: label, part });
  });
  return out;
}

interface Spot extends Flat {
  /** Расстояние до края контура, м. */
  edge: number;
}

interface Options {
  /** Уже занятое на этой части резины другими наборами. */
  taken?: Zone[];
  /** Скамейки ставить: нарисованные в съёмке уже стоят - своих не нужно. */
  benches?: boolean;
  /** Подписи других площадок той же части: каждой достаётся ближняя к ней доля резины. */
  rivals?: readonly Flat[];
}

/** Расстановка набора площадки по каталогу: что влезло, то и встало. */
export function furnish(ground: Ground, avoid: readonly Obstacle[], options: Options = {}): Item[] {
  const outer = ground.rings[0];
  if (!outer || outer.length < 3) return [];
  const taken = options.taken ?? [];
  const rivals = options.rivals ?? [];
  const axis = mainAxis([...outer]);
  const yaw = Math.atan2(-axis.dz, axis.dx);
  const step = Math.max(0.5, Math.sqrt(Math.abs(ringArea(outer)) / MAX_CANDIDATES));
  const own = (p: Flat) =>
    rivals.every(
      (r) =>
        Math.hypot(p.x - ground.anchor.x, p.z - ground.anchor.z) <=
        Math.hypot(p.x - r.x, p.z - r.z),
    );
  const spots = gridInside(ground.rings, step).filter(own);
  const area = spots.length * step * step;
  const xs = spots.map((s) => s.x);
  const zs = spots.map((s) => s.z);
  const [x0, x1, z0, z1] = [Math.min(...xs), Math.max(...xs), Math.min(...zs), Math.max(...zs)];
  // Препятствие дальше своего радиуса за контуром зону не заденет: зоны лежат в контуре.
  const near = avoid.filter(
    (o) =>
      o.x > x0 - o.r - 1 &&
      o.x < x1 + o.r + 1 &&
      o.z > z0 - o.r - 1 &&
      o.z < z1 + o.r + 1 &&
      distanceToArea(ground.rings, o) < o.r,
  );
  const items: Item[] = [];
  const place = (kind: ItemKind, spot: Flat, angle: number) => {
    items.push({ kind, x: spot.x, z: spot.z, angle });
    taken.push(zoneOf(kind, spot, angle));
  };
  const angles = (kind: ItemKind) => (SPECS[kind].round ? [yaw] : [yaw, yaw + Math.PI / 2]);
  /** Место предмета. spread - самое свободное: дальше всего от края и от поставленного;
   *  иначе плотно: у края и рядом с поставленным, чтобы в середине осталось место. */
  const best = (kind: ItemKind, zones: readonly Zone[], spread: boolean) => {
    let pick: { spot: Spot; angle: number; score: number } | null = null;
    for (const spot of spots) {
      for (const angle of angles(kind)) {
        if (!fits(ground.rings, kind, spot, angle, zones, near)) continue;
        const gaps = zones.map(
          (z) => Math.hypot(z.x - spot.x, z.z - spot.z) - Math.max(z.hu, z.hv),
        );
        const score = spread
          ? Math.min(spot.edge, ...gaps)
          : -spot.edge - 0.2 * Math.min(10, ...gaps);
        if (!pick || score > pick.score) pick = { spot, angle, score };
      }
    }
    return pick;
  };
  let field = false;
  if (ground.kind === 'sports' && axis.length >= FIELD_LENGTH_M && axis.width >= FIELD_WIDTH_M) {
    // Ворота у торцов лицом в поле: ось x ворот поперёк длины площадки.
    const along = { x: axis.dx, z: axis.dz };
    const end = axis.length / 2 - 1.0;
    for (const side of [1, -1]) {
      const p = { x: axis.cx + along.x * side * end, z: axis.cz + along.z * side * end };
      const angle = yaw + (side > 0 ? -Math.PI / 2 : Math.PI / 2);
      const spot = spots
        .filter((s) => Math.hypot(s.x - p.x, s.z - p.z) < 1.5)
        .sort((a, b) => Math.hypot(a.x - p.x, a.z - p.z) - Math.hypot(b.x - p.x, b.z - p.z))
        .find((s) => fits(ground.rings, 'goal', s, angle, taken, near));
      if (spot) {
        place('goal', spot, angle);
        field = true;
      }
    }
    if (field) {
      // Поле между воротами свободно: остальное - по краям.
      taken.push({
        x: axis.cx,
        z: axis.cz,
        angle: yaw,
        hu: axis.length / 2 - SPECS.goal.wid,
        hv: Math.min(axis.width / 2 - 2.5, 7.5),
      });
    }
  }
  const list = (ground.kind === 'kids' ? KIDS : SPORTS).filter(
    ({ kind, minArea }) => area >= minArea && !(field && kind === 'hoop'),
  );
  // Набор пробуется двумя расстановками: вольной и плотной; берётся та, где встало больше.
  const trial = (spread: boolean): Item[] => {
    const zones = [...taken];
    const got: Item[] = [];
    for (const { kind } of list) {
      if (kind === 'slide' && got.some((i) => i.kind === 'complex')) continue;
      const pick = best(kind, zones, spread);
      if (!pick) continue;
      got.push({ kind, x: pick.spot.x, z: pick.spot.z, angle: pick.angle });
      zones.push(zoneOf(kind, pick.spot, pick.angle));
    }
    return got;
  };
  const worth = (set: Item[]) => set.reduce((sum, i) => sum + VALUE[i.kind], 0);
  const spread = trial(true);
  const packed = trial(false);
  for (const item of worth(packed) > worth(spread) ? packed : spread) {
    place(item.kind, item, item.angle);
  }
  if (options.benches ?? true) {
    const center = { x: axis.cx, z: axis.cz };
    addBenches(ground, spots, area, center, { taken, near }, place);
  }
  return items;
}

/** Скамейки спинкой к краю площадки, сиденьем внутрь, разнесённые друг от друга; у каждой
 *  урна, если влезла. */
function addBenches(
  ground: Ground,
  spots: readonly Spot[],
  area: number,
  center: Flat,
  { taken, near }: { taken: Zone[]; near: readonly Obstacle[] },
  place: (kind: ItemKind, spot: Flat, angle: number) => void,
): void {
  const count = area < 60 ? 1 : area < 200 ? 2 : area < 450 ? 3 : 4;
  const spec = SPECS.bench;
  const rim = spots.filter(
    (s) => s.edge >= spec.wid / 2 + spec.edge && s.edge <= spec.wid / 2 + spec.edge + 0.6,
  );
  const benches: Flat[] = [];
  for (let k = 0; k < count; k++) {
    let pick: { spot: Spot; angle: number; score: number } | null = null;
    for (const spot of rim) {
      // Сиденье смотрит от ближайшей стороны внутрь: +z модели - по нормали внутрь.
      const inward = inwardNormal(ground.rings, spot);
      const angle = Math.atan2(inward.x, inward.z);
      if (!fits(ground.rings, 'bench', spot, angle, taken, near)) continue;
      // Первая - у середины длинной стороны, следующие - подальше от уже стоящих.
      const score =
        Math.min(30, ...benches.map((b) => Math.hypot(b.x - spot.x, b.z - spot.z))) -
        0.3 * Math.hypot(spot.x - center.x, spot.z - center.z);
      if (!pick || score > pick.score) pick = { spot, angle, score };
    }
    if (!pick) break;
    place('bench', pick.spot, pick.angle);
    benches.push(pick.spot);
    const c = Math.cos(pick.angle);
    const s = Math.sin(pick.angle);
    for (const side of [1, -1]) {
      const off = side * (spec.len / 2 + 0.4);
      const p = { x: pick.spot.x + off * c, z: pick.spot.z - off * s };
      const bin: Spot = { ...p, edge: edgeDistance(ground.rings, p) };
      if (fits(ground.rings, 'bin', bin, pick.angle, taken, near)) {
        place('bin', bin, pick.angle);
        break;
      }
    }
  }
}

/** Нормаль внутрь контура у точки: к точке от ближайшей точки края. */
function inwardNormal(rings: readonly Ring[], p: Flat): Flat {
  let best = Infinity;
  let foot: Flat = p;
  for (const ring of rings) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const a = ring[j] as Flat;
      const b = ring[i] as Flat;
      const q = closest(p, a, b);
      const d = Math.hypot(p.x - q.x, p.z - q.z);
      if (d < best) {
        best = d;
        foot = q;
      }
    }
  }
  const len = Math.hypot(p.x - foot.x, p.z - foot.z) || 1;
  return { x: (p.x - foot.x) / len, z: (p.z - foot.z) / len };
}

function zoneOf(kind: ItemKind, p: Flat, angle: number): Zone {
  const spec = SPECS[kind];
  return {
    x: p.x,
    z: p.z,
    angle,
    hu: spec.len / 2 + spec.zoneU,
    hv: spec.wid / 2 + spec.zoneV,
  };
}

/** Предмет встаёт: зона целиком в контуре, габарит с запасом от края, зона не задевает чужие
 *  зоны и препятствия. */
function fits(
  rings: readonly Ring[],
  kind: ItemKind,
  spot: Spot,
  angle: number,
  taken: readonly Zone[],
  avoid: readonly Obstacle[],
): boolean {
  const spec = SPECS[kind];
  const zone = zoneOf(kind, spot, angle);
  const body = { hu: spec.len / 2 + spec.edge, hv: spec.wid / 2 + spec.edge };
  const reach = Math.max(Math.hypot(zone.hu, zone.hv), Math.hypot(body.hu, body.hv));
  if (spot.edge < Math.min(body.hu, body.hv)) return false;
  for (const other of taken) if (rectsOverlap(zone, other)) return false;
  for (const o of avoid) if (circleInRect(o, zone)) return false;
  // Круг вокруг точки целиком в контуре - прямоугольник тоже.
  if (spot.edge >= reach) return true;
  for (const half of [zone, { ...zone, ...body }]) {
    for (const q of rectSamples(spot, angle, half.hu, half.hv)) {
      if (distanceToArea(rings, q) > 0) return false;
    }
  }
  for (const q of rectSamples(spot, angle, spec.len / 2, spec.wid / 2)) {
    if (edgeDistance(rings, q) < spec.edge) return false;
  }
  return true;
}

/** Точки по периметру прямоугольника не реже SAMPLE_M: вогнутый угол контура не проскочит. */
function rectSamples(c: Flat, angle: number, hu: number, hv: number): Flat[] {
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  const at = (u: number, v: number): Flat => ({
    x: c.x + u * cos + v * sin,
    z: c.z - u * sin + v * cos,
  });
  const out: Flat[] = [];
  const nu = Math.max(1, Math.ceil((2 * hu) / SAMPLE_M));
  const nv = Math.max(1, Math.ceil((2 * hv) / SAMPLE_M));
  for (let i = 0; i <= nu; i++) {
    const u = -hu + (2 * hu * i) / nu;
    out.push(at(u, -hv), at(u, hv));
  }
  for (let i = 1; i < nv; i++) {
    const v = -hv + (2 * hv * i) / nv;
    out.push(at(-hu, v), at(hu, v));
  }
  return out;
}

function corners(z: Zone): Flat[] {
  const cos = Math.cos(z.angle);
  const sin = Math.sin(z.angle);
  return (
    [
      [-z.hu, -z.hv],
      [z.hu, -z.hv],
      [z.hu, z.hv],
      [-z.hu, z.hv],
    ] as const
  ).map(([u, v]) => ({ x: z.x + u * cos + v * sin, z: z.z - u * sin + v * cos }));
}

/** Пересечение повёрнутых прямоугольников по разделяющим осям. */
export function rectsOverlap(a: Zone, b: Zone): boolean {
  const ca = corners(a);
  const cb = corners(b);
  for (const angle of [a.angle, b.angle]) {
    for (const axis of [
      { x: Math.cos(angle), z: -Math.sin(angle) },
      { x: Math.sin(angle), z: Math.cos(angle) },
    ]) {
      const pa = ca.map((p) => p.x * axis.x + p.z * axis.z);
      const pb = cb.map((p) => p.x * axis.x + p.z * axis.z);
      if (Math.max(...pa) <= Math.min(...pb) || Math.max(...pb) <= Math.min(...pa)) return false;
    }
  }
  return true;
}

function circleInRect(o: Obstacle, z: Zone): boolean {
  const dx = o.x - z.x;
  const dz = o.z - z.z;
  const cos = Math.cos(z.angle);
  const sin = Math.sin(z.angle);
  const u = dx * cos - dz * sin;
  const v = dx * sin + dz * cos;
  const cu = Math.max(-z.hu, Math.min(z.hu, u));
  const cv = Math.max(-z.hv, Math.min(z.hv, v));
  return Math.hypot(u - cu, v - cv) < o.r;
}

function gridInside(rings: readonly Ring[], step: number): Spot[] {
  const outer = rings[0] ?? [];
  const xs = outer.map((p) => p.x);
  const zs = outer.map((p) => p.z);
  const out: Spot[] = [];
  for (let x = Math.min(...xs) + step / 2; x <= Math.max(...xs); x += step) {
    for (let z = Math.min(...zs) + step / 2; z <= Math.max(...zs); z += step) {
      if (distanceToArea(rings, { x, z }) > 0) continue;
      out.push({ x, z, edge: edgeDistance(rings, { x, z }) });
    }
  }
  return out;
}

function edgeDistance(rings: readonly Ring[], p: Flat): number {
  let edge = Infinity;
  for (const ring of rings) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const q = closest(p, ring[j] as Flat, ring[i] as Flat);
      edge = Math.min(edge, Math.hypot(p.x - q.x, p.z - q.z));
    }
  }
  return edge;
}

function closest(p: Flat, a: Flat, b: Flat): Flat {
  const vx = b.x - a.x;
  const vz = b.z - a.z;
  const len2 = vx * vx + vz * vz;
  const t = len2 > 0 ? Math.max(0, Math.min(1, ((p.x - a.x) * vx + (p.z - a.z) * vz) / len2)) : 0;
  return { x: a.x + vx * t, z: a.z + vz * t };
}

function ringArea(ring: Ring): number {
  let s = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[j] as Flat;
    const b = ring[i] as Flat;
    s += a.x * b.z - b.x * a.z;
  }
  return s / 2;
}

/** Контур предмета в плане для твёрдой камеры: прямоугольник и высота. */
export function itemFootprint(item: Item): { ring: Flat[]; height: number } {
  const spec = SPECS[item.kind];
  const ring = corners({
    x: item.x,
    z: item.z,
    angle: item.angle,
    hu: spec.len / 2,
    hv: spec.wid / 2,
  });
  return { ring, height: spec.height };
}

/** Расстояние от точки до многоугольника с дырами: 0 внутри. */
export function distanceToArea(rings: readonly Ring[], p: Flat): number {
  let inside = false;
  let best = Infinity;
  for (const ring of rings) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const a = ring[i] as Flat;
      const b = ring[j] as Flat;
      if (a.z > p.z !== b.z > p.z && p.x < ((b.x - a.x) * (p.z - a.z)) / (b.z - a.z) + a.x) {
        inside = !inside;
      }
      const q = closest(p, a, b);
      best = Math.min(best, Math.hypot(p.x - q.x, p.z - q.z));
    }
  }
  return inside ? 0 : best;
}

export { playgroundGroup } from './playgroundModels';
