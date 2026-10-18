/* Земля 3D-вида: газон, тротуарная плитка и асфальт там, где их понял сервис, а также
 * бортовой камень, ограды и опоры освещения с подосновы.
 *
 * Где грунт, а где покрытие, решает не 3D-вид: он берёт карту покрытий прогона (surface.png,
 * та же, по которой считались посадки) и поверх неё - полигоны газонов, тротуаров и проезжей
 * части с подосновы. Всё это рисуется в маску: R - газон, G - плитка, B - асфальт. Что
 * сервис не разметил, и всё за краем съёмки - газон, покрытие делится на тротуар и проезд
 * по ширине полосы (surfaceMask.ts). Шейдер земли смешивает по маске три фактуры с ровным
 * порогом. Карта покрытий приходит контурами (surface.json, areas): край проезда и газона -
 * прямая, а не лесенка клеток; у старых прогонов без контуров растр размывается на клетку. */

import * as THREE from 'three';

import { dominantAngles, keepSegments, outlines } from './contours';
import {
  absorbSmall,
  ASPHALT,
  ASPHALT_RGB,
  blurBytes,
  classifySurface,
  distanceInside,
  EMPTY,
  GRASS,
  keepLarge,
  maxFilter,
  PAVED_RGB,
  PAVERS,
  PAVERS_RGB,
  ROAD,
  ROAD_RGB,
  smoothBinary,
  SOIL_RGB,
} from './surfaceMask';
import type { Flat, Line, Ring, World } from './types';

/** Метров на пиксель маски: борт шириной 15 см маска не рисует, его ставит геометрия. */
const MASK_M_PER_PX = 0.25;
const MASK_MAX_PX = 4096;
/** Радиус сглаживания границ покрытий, м: меньше ширины тротуара, больше клетки карты. */
const SMOOTH_M = 1;
/** Окно усреднения края вдоль контура, допуск выпрямления и наибольший срез угла, м. */
const WAVE_M = 8;
const STRAIGHT_M = 0.5;
const CORNER_M = 2.5;
/** Контуры surface.json уже идут по линиям чертежа: им нужно только снять лесенку пикселей
 *  маски. Окно WAVE_M для них раздувало узкие дорожки и съезды в пятна (Харьковская,
 *  18.10.2026): усреднение по 8 м превращало угол дорожки шириной 3 м в каплю. */
export const CONTOUR_SHAPE = { window: 0, tolerance: 0.15, cap: 0.6 } as const;
/** Обрывки на стыках дорожек, которые отдаются соседнему покрытию, м². */
const SCRAP_ASPHALT_M2 = 40;
const SCRAP_PAVERS_M2 = 4;
/** Щель между газоном и проездом, которую закрывает газон, м. */
const GAP_M = 1.2;
/** Площадь, начиная с которой связный асфальт - проезжая часть (опускается, с бортом), м². */
const CARRIAGEWAY_M2 = 60;
/** Ширина асфальта, с которой он - проезд, а не тротуар, м: однополосный проезд 3,5 м. */
const DRIVE_M = 3.5;
/** Размытие маски у контуров, пикселей (softenCells берёт 0,9 от него). */
const CONTOUR_SOFTEN_PX = 1.6;
/** Земля продолжается за границу сцены, чтобы горизонт не обрывался краем плиты. */
export const GROUND_PAD_M = 3000;

/** Полигон - кольца в координатах чертежа: внешнее, затем дыры. */
export type AreaPolygon = number[][][];

/** Контуры карты покрытий: грунт и поверх него покрытие (surface.json, areas). */
export interface SurfaceAreas {
  soil: AreaPolygon[];
  paved: AreaPolygon[];
  /** Вид каждой части покрытия: road - проезжая часть, asphalt, pavers, paved - неизвестно. */
  paved_kind?: string[];
  /** Проезжая часть с запасом под край тротуара: сетка асфальта ниже уровня земли. */
  road_mesh?: AreaPolygon[];
}

/** Проезжая часть ниже тротуара и газона на высоту дорожного борта. */
export const ROAD_DROP_M = 0.15;

export interface SurfaceImage {
  img: HTMLImageElement;
  /** Угол растра с минимальными x, y чертежа, метры. */
  origin: [number, number];
  cell: number;
  width: number;
  height: number;
  areas?: SurfaceAreas | null;
}

const rgb = ([r, g, b]: readonly [number, number, number]) => `rgb(${r}, ${g}, ${b})`;
/** Цвета контуров без прозрачности: classifySurface читает вид покрытия по цвету. */
const SOIL_FILL = rgb(SOIL_RGB);
const PAVED_FILLS: Record<string, string> = {
  road: rgb(ROAD_RGB),
  asphalt: rgb(ASPHALT_RGB),
  pavers: rgb(PAVERS_RGB),
};
const PAVED_FILL = rgb(PAVED_RGB);

/** Кольца полигонов чертежа в пикселях маски: x сцены = X - начало, z сцены = -(Y - начало). */
export function areaRings(
  polygons: AreaPolygon[],
  origin: [number, number],
  minX: number,
  minZ: number,
  mpp: number,
): [number, number][][][] {
  const [ox, oy] = origin;
  return polygons.map((rings) =>
    rings.map((ring) =>
      ring.map(([x = 0, y = 0]): [number, number] => [
        (x - ox - minX) / mpp,
        (-(y - oy) - minZ) / mpp,
      ]),
    ),
  );
}

function tracePolygon(ctx: CanvasRenderingContext2D, rings: [number, number][][]): void {
  ctx.beginPath();
  for (const ring of rings) {
    ring.forEach(([x, y], i) => {
      if (i) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
    });
    ctx.closePath();
  }
}

/** Бортовой камень по краям покрытия (пользователь, 17.10.2026): кольца контуров покрытия
 *  линиями в координатах сцены, только отрезки, где edge подтверждает газон по одну сторону:
 *  шов между тротуаром и проездом бортом не обводится, линии бортов чертежа идут отдельно
 *  (world.curbs). */
/** Контуры покрытий, сглаженные для 3D: срез углов в три прохода. Контур из растра и
 *  упрощения - ломаная с изломами в 3-15° через метр-два и прямыми углами лесенки, на 3D
 *  борт по ней шёл «кривой» (пользователь, 17.10.2026). Пологий излом срезается на четверть
 *  соседних отрезков (не дальше SMOOTH_CUT_M), прямой угол - радиусным камнем не дальше
 *  SMOOTH_CORNER_M, разворот круче SMOOTH_KEEP_DEG остаётся углом. Сглаживаются и грунт, и
 *  покрытие: маска, борта и вырез земли берутся из одних контуров. */
export function smoothSurfaceAreas(areas: SurfaceAreas): SurfaceAreas {
  const rings = (polygons: AreaPolygon[]) =>
    polygons.map((polygon) => polygon.map((ring) => smoothRing(ring)));
  return {
    ...areas,
    soil: rings(areas.soil),
    paved: rings(areas.paved),
  };
}

const SMOOTH_PASSES = 3;
const SMOOTH_MIN_DEG = 2;
const SMOOTH_GENTLE_DEG = 30;
const SMOOTH_KEEP_DEG = 100;
const SMOOTH_CUT_M = 1.5;
const SMOOTH_CORNER_M = 0.75;
/** Лесенка растра: подряд не меньше трёх поворотов около прямого угла, знак чередуется,
 *  ступени короче этого. Выемка (два поворота в одну сторону подряд) лесенкой не считается. */
const STAIR_STEP_M = 2.5;
const STAIR_MIN_DEG = 60;
const STAIR_MAX_DEG = 120;

/** Поворот в вершине v между p и q: градусы со знаком (плюс - налево в координатах чертежа). */
function signedTurn(p: number[], v: number[], q: number[]): number {
  const ax = (v[0] ?? 0) - (p[0] ?? 0);
  const ay = (v[1] ?? 0) - (p[1] ?? 0);
  const bx = (q[0] ?? 0) - (v[0] ?? 0);
  const by = (q[1] ?? 0) - (v[1] ?? 0);
  return (Math.atan2(ax * by - ay * bx, ax * bx + ay * by) * 180) / Math.PI;
}

/** Лесенка клеток растра (чередующиеся повороты около прямого угла с короткими ступенями)
 *  заменяется хордой от первой её вершины до последней. */
function withoutStairs(pts: number[][]): number[][] {
  const n = pts.length;
  if (n < 5) return pts;
  const stair = pts.map((v, i) => {
    const p = pts[(i - 1 + n) % n] ?? v;
    const q = pts[(i + 1) % n] ?? v;
    const turn = signedTurn(p, v, q);
    const short = Math.hypot((q[0] ?? 0) - (v[0] ?? 0), (q[1] ?? 0) - (v[1] ?? 0)) < STAIR_STEP_M;
    return Math.abs(turn) >= STAIR_MIN_DEG && Math.abs(turn) <= STAIR_MAX_DEG && short
      ? Math.sign(turn)
      : 0;
  });
  // Ряд лесенки: подряд идущие вершины с чередующимся знаком, не меньше трёх. Снимаются все
  // его вершины, кроме первой: хорда идёт от неё до вершины за последней ступенью.
  const drop = pts.map(() => false);
  const runStart = (i: number) => {
    const s = stair[i] ?? 0;
    return s !== 0 && stair[(i - 1 + n) % n] !== -s;
  };
  for (let i = 0; i < n; i++) {
    if (!runStart(i)) continue;
    let length = 1;
    while (length < n && stair[(i + length) % n] === -(stair[(i + length - 1) % n] ?? 0)) length++;
    if (length < 3) continue;
    for (let k = 1; k < length; k++) drop[(i + k) % n] = true;
  }
  const out = pts.filter((_, i) => !drop[i]);
  return out.length < n ? out : pts;
}

function smoothRing(ring: number[][]): number[][] {
  let pts = withoutStairs(ring.slice(0, -1).map(([x = 0, y = 0]) => [x, y]));
  for (let pass = 0; pass < SMOOTH_PASSES && pts.length > 3; pass++) {
    // Каждый следующий проход срезает вдвое короче: скругление остаётся у угла, а не
    // расползается по прямой.
    const shrink = 2 ** pass;
    const out: number[][] = [];
    for (let i = 0; i < pts.length; i++) {
      const [px = 0, py = 0] = pts[(i - 1 + pts.length) % pts.length] ?? [];
      const [vx = 0, vy = 0] = pts[i] ?? [];
      const [qx = 0, qy = 0] = pts[(i + 1) % pts.length] ?? [];
      const ax = vx - px;
      const ay = vy - py;
      const bx = qx - vx;
      const by = qy - vy;
      const la = Math.hypot(ax, ay);
      const lb = Math.hypot(bx, by);
      if (la < 1e-6 || lb < 1e-6) continue;
      const turn =
        (Math.acos(Math.max(-1, Math.min(1, (ax * bx + ay * by) / (la * lb)))) * 180) / Math.PI;
      if (turn < SMOOTH_MIN_DEG || turn > SMOOTH_KEEP_DEG) {
        out.push([vx, vy]);
        continue;
      }
      const cap = (turn > SMOOTH_GENTLE_DEG ? SMOOTH_CORNER_M : SMOOTH_CUT_M) / shrink;
      const ca = Math.min(cap, la / 4);
      const cb = Math.min(cap, lb / 4);
      out.push(
        [vx - (ax / la) * ca, vy - (ay / la) * ca],
        [vx + (bx / lb) * cb, vy + (by / lb) * cb],
      );
    }
    pts = out;
  }
  const first = pts[0];
  return first ? [...pts, [...first]] : ring;
}

/** Бортовой камень по краям покрытия (пользователь, 17.10.2026): кольца контуров покрытия
 *  линиями в координатах сцены, только отрезки, где edge подтверждает газон по одну сторону:
 *  шов между тротуаром и проездом бортом не обводится, линии бортов чертежа идут отдельно
 *  (world.curbs). */
export function areaCurbs(
  areas: SurfaceAreas,
  origin: [number, number],
  edge: (a: Flat, b: Flat) => boolean = () => true,
): Line[] {
  const [ox, oy] = origin;
  const lines: Line[] = [];
  for (const rings of areas.paved) {
    for (const ring of rings) {
      const pts = withoutHairpins(ring.map(([x = 0, y = 0]): Flat => ({ x: x - ox, z: oy - y })));
      const n = pts.length - 1; // кольцо замкнуто: последняя точка - первая
      if (n < 2) continue;
      const lengths = Array.from({ length: n }, (_, i) => dist(pts[i] as Flat, pts[i + 1] as Flat));
      const keep = Array.from({ length: n }, (_, i) => edge(pts[i] as Flat, pts[i + 1] as Flat));
      bridgeGaps(keep, lengths);
      if (keep.every(Boolean)) {
        lines.push({ points: pts });
        continue;
      }
      // Обход с отрезка без борта: бортовые отрезки по обе стороны начала кольца - одна линия.
      const start = keep.indexOf(false);
      let run: Flat[] = [];
      let runLength = 0;
      const flush = () => {
        if (run.length && runLength >= CURB_MIN_RUN_M) lines.push({ points: run });
        run = [];
        runLength = 0;
      };
      for (let k = 1; k <= n; k++) {
        const i = (start + k) % n;
        if (keep[i]) {
          if (!run.length) run.push(pts[i] as Flat);
          run.push(pts[i + 1] as Flat);
          runLength += lengths[i] ?? 0;
        } else flush();
      }
      flush();
    }
  }
  return lines;
}

/** Пропуск в ряду бортов короче этого заделывается, ряд короче CURB_MIN_RUN_M не ставится:
 *  иначе вблизи борт выходил обрывками с торцами. */
const CURB_GAP_M = 1.5;
const CURB_MIN_RUN_M = 1.0;
/** Разворот контура круче этого (угол между отрезками, градусы) - шпилька, а не поворот. */
const HAIRPIN_DEG = 150;

function dist(a: Flat, b: Flat): number {
  return Math.hypot(b.x - a.x, b.z - a.z);
}

/** Заделать короткие пропуски кольца между двумя бортовыми отрезками (по кругу). */
function bridgeGaps(keep: boolean[], lengths: number[]): void {
  const n = keep.length;
  if (keep.every(Boolean) || !keep.some(Boolean)) return;
  const start = keep.indexOf(true);
  let k = 1;
  while (k <= n) {
    const i = (start + k) % n;
    if (keep[i]) {
      k++;
      continue;
    }
    let total = 0;
    let j = 0;
    while (j < n && !keep[(i + j) % n]) {
      total += lengths[(i + j) % n] ?? 0;
      j++;
    }
    if (total < CURB_GAP_M) for (let m = 0; m < j; m++) keep[(i + m) % n] = true;
    k += j;
  }
}

/** Убрать вершины-шпильки (контур разворачивается назад): брус бортового камня на них
 *  перекручивался. Кольцо остаётся замкнутым. */
export function withoutHairpins(points: Flat[]): Flat[] {
  let pts = points.slice(0, -1);
  for (let pass = 0; pass < 3 && pts.length > 3; pass++) {
    const kept = pts.filter((v, i) => {
      const p = pts[(i - 1 + pts.length) % pts.length] as Flat;
      const q = pts[(i + 1) % pts.length] as Flat;
      const ax = v.x - p.x;
      const az = v.z - p.z;
      const bx = q.x - v.x;
      const bz = q.z - v.z;
      const la = Math.hypot(ax, az);
      const lb = Math.hypot(bx, bz);
      if (la < 0.05 || lb < 0.05) return false;
      const turn =
        (Math.acos(Math.max(-1, Math.min(1, (ax * bx + az * bz) / (la * lb)))) * 180) / Math.PI;
      return turn < HAIRPIN_DEG;
    });
    if (kept.length === pts.length) break;
    pts = kept;
  }
  const first = pts[0];
  return first ? [...pts, first] : [];
}

/** Линии борта с покрытием (плитка или асфальт) слева от хода: по самому длинному пролёту
 *  линии смотрится маска в 0,3 м по обе стороны, при покрытии справа линия разворачивается.
 *  Брус борта (ribbonBox, 'left') затеняет правую, газонную грань: на свету она шла по
 *  газону белой ниткой (пользователь, 17.10.2026). */
export function pavedOnLeft(lines: readonly Line[], mask: MaskInfo): Line[] {
  const [minX, minZ] = mask.rect;
  const kindAt = (x: number, z: number): number => {
    const col = Math.floor((x - minX) / mask.metresPerPx);
    const row = Math.floor((z - minZ) / mask.metresPerPx);
    if (col < 0 || row < 0 || col >= mask.width || row >= mask.height) return EMPTY;
    return mask.kinds[row * mask.width + col] ?? EMPTY;
  };
  const paved = (k: number) => k === PAVERS || k === ASPHALT;
  return lines.map((line) => {
    let best = 0;
    let at = -1;
    for (let i = 0; i + 1 < line.points.length; i++) {
      const d = dist(line.points[i] as Flat, line.points[i + 1] as Flat);
      if (d > best) {
        best = d;
        at = i;
      }
    }
    if (at < 0) return line;
    const p = line.points[at] as Flat;
    const q = line.points[at + 1] as Flat;
    const nx = (-(q.z - p.z) / best) * 0.3;
    const nz = ((q.x - p.x) / best) * 0.3;
    const mx = (p.x + q.x) / 2;
    const mz = (p.z + q.z) / 2;
    const left = paved(kindAt(mx + nx, mz + nz));
    const right = paved(kindAt(mx - nx, mz - nz));
    if (left || !right) return line;
    return {
      points: [...line.points].reverse(),
      ...(line.tops ? { tops: [...line.tops].reverse() } : {}),
    };
  });
}

/** Отрезок - граница двух покрытий: по одну его сторону покрытие вида a, по другую - вида b
 *  (маска после деления на газон, плитку и асфальт). Вне маски - газон. */
export function edgeBetween(
  mask: MaskInfo,
  isA: (kind: number) => boolean,
  isB: (kind: number) => boolean,
  offsetM = 0.4,
): (a: Flat, b: Flat) => boolean {
  const [minX, minZ] = mask.rect;
  const kindAt = (x: number, z: number): number => {
    const col = Math.floor((x - minX) / mask.metresPerPx);
    const row = Math.floor((z - minZ) / mask.metresPerPx);
    if (col < 0 || row < 0 || col >= mask.width || row >= mask.height) return EMPTY;
    return mask.kinds[row * mask.width + col] ?? EMPTY;
  };
  return (a, b) => {
    const dx = b.x - a.x;
    const dz = b.z - a.z;
    const len = Math.hypot(dx, dz);
    if (!len) return false;
    const nx = (-dz / len) * offsetM;
    const nz = (dx / len) * offsetM;
    const mx = (a.x + b.x) / 2;
    const mz = (a.z + b.z) / 2;
    const left = kindAt(mx + nx, mz + nz);
    const right = kindAt(mx - nx, mz - nz);
    return (isA(left) && isB(right)) || (isA(right) && isB(left));
  };
}

/** Контуры карты покрытий вместо её растра: грунт и поверх него покрытие, как в растре. */
export function drawSurfaceAreas(
  ctx: CanvasRenderingContext2D,
  areas: SurfaceAreas,
  origin: [number, number],
  minX: number,
  minZ: number,
  mpp: number,
): void {
  const soil = areaRings(areas.soil, origin, minX, minZ, mpp);
  const paved = areaRings(areas.paved, origin, minX, minZ, mpp);
  const groups = new Map<string, [number, number][][][]>();
  if (soil.length) groups.set(SOIL_FILL, soil);
  paved.forEach((rings, i) => {
    const color = PAVED_FILLS[areas.paved_kind?.[i] ?? ''] ?? PAVED_FILL;
    groups.set(color, [...(groups.get(color) ?? []), rings]);
  });
  for (const [color, polygons] of groups) {
    ctx.fillStyle = color;
    for (const rings of polygons) {
      tracePolygon(ctx, rings);
      ctx.fill('evenodd');
    }
  }
}

/** Сетка проезжей части из контура road_mesh: на ROAD_DROP_M ниже земли, в координатах сцены. */
export function roadGeometry(
  polygons: AreaPolygon[],
  origin: [number, number],
): THREE.BufferGeometry | null {
  const [ox, oy] = origin;
  const shapes = polygons
    .filter((rings) => (rings[0]?.length ?? 0) > 3)
    .map((rings) => {
      const toVec = (ring: number[][]) =>
        ring.map(([x = 0, y = 0]) => new THREE.Vector2(x - ox, y - oy));
      const shape = new THREE.Shape(toVec(rings[0] ?? []));
      shape.holes = rings.slice(1).map((ring) => new THREE.Path(toVec(ring)));
      return shape;
    });
  if (!shapes.length) return null;
  const geometry = new THREE.ShapeGeometry(shapes);
  geometry.rotateX(-Math.PI / 2);
  geometry.translate(0, -ROAD_DROP_M, 0);
  return geometry;
}

export function groundGeometry(
  bounds: [number, number, number, number],
  cuts: readonly { points: readonly Flat[]; island: boolean }[],
): THREE.BufferGeometry {
  const [minX, minZ, maxX, maxZ] = bounds;
  const half = Math.max(maxX - minX, maxZ - minZ) / 2 + GROUND_PAD_M;
  const cx = (minX + maxX) / 2;
  const cz = (minZ + maxZ) / 2;
  // Плоскость фигуры: x сцены и -z сцены (после поворота на -90° вокруг X).
  const toVec = (ring: readonly Flat[]) => ring.map((p) => new THREE.Vector2(p.x, -p.z));
  const outer = new THREE.Shape([
    new THREE.Vector2(cx - half, -(cz + half)),
    new THREE.Vector2(cx + half, -(cz + half)),
    new THREE.Vector2(cx + half, -(cz - half)),
    new THREE.Vector2(cx - half, -(cz - half)),
  ]);
  const shapes = [outer];
  for (const cut of cuts) {
    if (cut.points.length < 4) continue;
    if (cut.island) shapes.push(new THREE.Shape(toVec(cut.points)));
    else outer.holes.push(new THREE.Path(toVec(cut.points)));
  }
  const geometry = new THREE.ShapeGeometry(shapes);
  geometry.rotateX(-Math.PI / 2);
  return geometry;
}

export interface MaskInfo {
  /** Полные контуры итоговой проезжей части до отсечения борта у рамки сцены. */
  roadContours?: Line[];
  texture: THREE.DataTexture;
  /** minX, minZ и размер растра (w и h пикселей по metresPerPx) в координатах сцены. */
  rect: [number, number, number, number];
  /** Покрытие каждого пикселя (surfaceMask.ts) до размытия: по нему расставляются люди. */
  kinds: Uint8Array;
  /** Пиксель снят: карта покрытий что-то знает о нём. Остальное - газон по умолчанию, и там
   *  город вокруг (context.ts) может поставить дорогу и деревья карты. */
  known: Uint8Array;
  /** Границы покрытий в метрах сцены: проезд (под бортовой камень и вырез земли) и плитка
   *  (под поребрик у газона). */
  edges: { road: Line[]; garden: Line[] };
  /** Проезд итоговой маски (после газонов и тротуаров подосновы): 1 - асфальт. По нему же
   *  вырезана земля, поэтому машины встают только туда, где виден асфальт. */
  road: Uint8Array;
  /** Та же проезжая часть текстурой: по ней шейдер вырезает землю под опущенный асфальт. */
  cut: THREE.DataTexture;
  width: number;
  height: number;
  metresPerPx: number;
}

/** Погода на земле: мокрый асфальт темнеет и блестит, снег ложится сначала на газон. */
export interface GroundWeather {
  uWet: { value: number };
  uSnow: { value: number };
}

function ringPath(
  ctx: CanvasRenderingContext2D,
  rings: Ring[],
  toPx: (p: Flat) => [number, number],
): void {
  ctx.beginPath();
  for (const ring of rings) {
    ring.forEach((p, i) => {
      const [x, y] = toPx(p);
      if (i) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
    });
    ctx.closePath();
  }
  ctx.fill('evenodd');
}

/** Покрытие каждого пикселя -> каналы маски: R - газон, G - плитка, B - асфальт. */
function surfaceToMask(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  mpp: number,
  minAlpha: number,
): Uint8Array {
  const img = ctx.getImageData(0, 0, w, h);
  const d = img.data;
  const kind = classifySurface(d, w, h, mpp, minAlpha);
  // Проезд - проезжая часть и широкий асфальт (дворовые проезды от DRIVE_M): в жизни у них
  // тоже бортовой камень на 15 см. Узкий асфальт - тротуар, вровень с плиткой.
  const asphalt = Uint8Array.from(kind, (k) => (k === ASPHALT ? 1 : 0));
  const middle = maxFilter(
    distanceInside(asphalt, w, h),
    w,
    h,
    Math.max(1, Math.round(DRIVE_M / mpp)),
  );
  const halfDrive = DRIVE_M / 2 / mpp;
  for (let i = 0; i < kind.length; i++) {
    const k = kind[i];
    const drive = k === ROAD || (k === ASPHALT && (middle[i] ?? 0) >= halfDrive);
    // R - газон (и пустое), G - плитка, B - проезд: его землю шейдер вырезает, под ней лежит
    // плоскость проезда ниже на высоту борта. Асфальт тротуара - где нет ни одного канала.
    d[i * 4] = k === GRASS || k === EMPTY ? 255 : 0;
    d[i * 4 + 1] = k === PAVERS ? 255 : 0;
    d[i * 4 + 2] = drive ? 255 : 0;
    d[i * 4 + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  return kind;
}

/** Размыть растр карты покрытий на размер клетки: ступенька в метр читается сверху как
 *  пиксельная лесенка, а у размытой на клетку лесенки порог 0,5 идёт почти прямой. Полигоны
 *  подосновы рисуются после, чётко. */
function softenCells(c: HTMLCanvasElement, ctx: CanvasRenderingContext2D, cellPx: number): void {
  if (cellPx < 1.5) return;
  const copy = document.createElement('canvas');
  copy.width = c.width;
  copy.height = c.height;
  copy.getContext('2d')?.drawImage(c, 0, 0);
  ctx.save();
  ctx.filter = `blur(${(cellPx * 0.9).toFixed(1)}px)`;
  ctx.drawImage(copy, 0, 0);
  ctx.restore();
}

/** Заливка замкнутых контуров (чёт-нечет: дворы внутри проезда остаются дырами) в растр
 *  маски; край сглаживается размытием на пиксель (blurBytes). */
/** Пятна асфальта меньше SCRAP_ASPHALT_M2 и плитки меньше SCRAP_PAVERS_M2 на стыке дорожек
 *  отдаются соседнему покрытию с самой длинной общей границей (absorbSmall): обрывки асфальта
 *  между полосами плитки читались «месивом» и в 3D, и на фото. Пятна у проезда не трогаются.
 *  Меняет каналы маски и покрытия пикселей на месте. */
function absorbScraps(
  rgba: Uint8ClampedArray,
  kinds: Uint8Array,
  road: Uint8Array,
  w: number,
  h: number,
  mpp: number,
): void {
  const LAWN = 0;
  const TILE = 1;
  const WALK = 2;
  const DRIVE = 3;
  const labels = new Uint8Array(w * h);
  for (let i = 0; i < labels.length; i++) {
    labels[i] = road[i]
      ? DRIVE
      : (rgba[i * 4] ?? 0) >= 128
        ? LAWN
        : (rgba[i * 4 + 1] ?? 0) >= 128
          ? TILE
          : WALK;
  }
  const px2 = mpp * mpp;
  const walk = absorbSmall(labels, w, h, WALK, Math.round(SCRAP_ASPHALT_M2 / px2), [DRIVE]);
  const tidy = absorbSmall(walk, w, h, TILE, Math.round(SCRAP_PAVERS_M2 / px2), [DRIVE]);
  for (let i = 0; i < tidy.length; i++) {
    const l = tidy[i];
    if (l === labels[i]) continue;
    rgba[i * 4] = l === LAWN ? 255 : 0;
    rgba[i * 4 + 1] = l === TILE ? 255 : 0;
    kinds[i] = l === LAWN ? GRASS : l === TILE ? PAVERS : ASPHALT;
  }
}

function fillLoops(
  loops: readonly Line[],
  w: number,
  h: number,
  minX: number,
  minZ: number,
  mpp: number,
): Uint8Array {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('Canvas 2D недоступен');
  ctx.fillStyle = '#ffffff';
  ctx.beginPath();
  for (const loop of loops) {
    loop.points.forEach((p, i) => {
      const x = (p.x - minX) / mpp;
      const y = (p.z - minZ) / mpp;
      if (i) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
    });
    ctx.closePath();
  }
  ctx.fill('evenodd');
  const data = ctx.getImageData(0, 0, w, h).data;
  const out = new Uint8Array(w * h);
  for (let i = 0; i < out.length; i++) out[i] = data[i * 4] ?? 0;
  return blurBytes(out, w, h, 1);
}

export function buildMask(world: World, surface: SurfaceImage | null): MaskInfo {
  const [minX, minZ, maxX, maxZ] = world.bounds;
  const sizeX = Math.max(1, maxX - minX);
  const sizeZ = Math.max(1, maxZ - minZ);
  const mpp = Math.max(MASK_M_PER_PX, Math.max(sizeX, sizeZ) / MASK_MAX_PX);
  const w = Math.ceil(sizeX / mpp);
  const h = Math.ceil(sizeZ / mpp);
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('Canvas 2D недоступен');
  // Карта покрытий полупрозрачная: рисуется на прозрачный холст, иначе её цвет смешается с
  // фоном и грунт перестанет отличаться от покрытия. Пустое после разбора - газон.
  ctx.clearRect(0, 0, w, h);
  // Контуры карты покрытий (surface.json, areas) - прямые края без лесенки клеток; растр - для
  // прогонов, сделанных до них.
  const areas = surface?.areas;
  if (surface && areas) {
    drawSurfaceAreas(ctx, areas, world.origin, minX, minZ, mpp);
  } else if (surface) {
    // Строка 0 растра - минимальный Y чертежа, то есть наибольший z сцены: рисуем с
    // отражением по вертикали, от нижнего края вверх.
    const [ox, oy] = world.origin;
    const left = (surface.origin[0] - ox - minX) / mpp;
    const bottom = (-(surface.origin[1] - oy) - minZ) / mpp;
    ctx.save();
    ctx.imageSmoothingEnabled = false;
    ctx.translate(left, bottom);
    ctx.scale(
      (surface.cell / mpp) * (surface.width / surface.img.naturalWidth),
      -(surface.cell / mpp) * (surface.height / surface.img.naturalHeight),
    );
    ctx.drawImage(surface.img, 0, 0);
    ctx.restore();
  }
  const known = new Uint8Array(w * h);
  const alpha = ctx.getImageData(0, 0, w, h).data;
  for (let i = 0; i < known.length; i++) known[i] = (alpha[i * 4 + 3] ?? 0) > 0 ? 1 : 0;
  // Контур залит непрозрачно, его край - доля покрытия пикселя: покрытием считается пиксель,
  // покрытый наполовину. С порогом «любой непустой» асфальт вылезал за край на пиксель маски
  // (до 0,4 м) - за бортовой камень. Растр старых прогонов полупрозрачный: порог - непустой.
  const kinds = surfaceToMask(ctx, w, h, mpp, areas ? 128 : 1);
  // Край контура на пикселе маски (у большой сцены до 0,4 м) - лесенка; лёгкое размытие
  // выравнивает порог шейдера. У растра без контуров - размытие на клетку.
  if (surface) softenCells(c, ctx, areas ? CONTOUR_SOFTEN_PX : surface.cell / mpp);
  const toPx = (p: Flat): [number, number] => [(p.x - minX) / mpp, (p.z - minZ) / mpp];
  ctx.fillStyle = '#0000ff';
  for (const rings of world.roads) ringPath(ctx, rings, toPx);
  ctx.fillStyle = '#00ff00';
  for (const rings of world.sidewalks) ringPath(ctx, rings, toPx);
  ctx.fillStyle = '#ff0000';
  for (const rings of world.lawns) ringPath(ctx, rings, toPx);
  const image = ctx.getImageData(0, 0, w, h);
  const final = image.data;
  // Карта покрытий - клетки по 0,5 м: граница газона и асфальта шла лесенкой и волной.
  // Каждый канал сглаживается окном SMOOTH_M и пишется обратно - шейдер, бортовой камень и
  // поребрик берут одну и ту же плавную границу.
  // Контуры surface.json уже прямые - их не размываем, иначе пропадут узкие полосы.
  const smoothPx = areas ? 0 : Math.round(SMOOTH_M / mpp);
  // Выпрямление краёв: усреднение вдоль контура окном WAVE_M гасит волны карты покрытий
  // (пятна по 5-10 м), Дуглас-Пекер с допуском STRAIGHT_M оставляет прямые стороны, повороты
  // скругляются дугой до CORNER_M. Окно 3 м волну такой длины не брало: край газона и дорожки
  // в 3D и на фото шёл «пятнами».
  // Главные направления участка - по стенам домов, бортам и оградам чертежа.
  const angles = dominantAngles([
    ...world.buildings.flatMap((b) =>
      b.rings.map((ring) => ({ points: [...ring, ...ring.slice(0, 1)] })),
    ),
    ...world.curbs,
    ...world.fences,
  ]);
  const shape = areas
    ? { ...CONTOUR_SHAPE, angles }
    : { window: WAVE_M, tolerance: STRAIGHT_M, cap: CORNER_M, angles };
  for (let offset = 0; offset < 3; offset++) {
    const plane = new Uint8Array(w * h);
    for (let i = 0; i < plane.length; i++) plane[i] = (final[i * 4 + offset] ?? 0) >= 128 ? 255 : 0;
    const smooth = smoothBinary(plane, w, h, smoothPx);
    for (let i = 0; i < plane.length; i++) final[i * 4 + offset] = smooth[i] ?? 0;
  }
  // Растр покрывает w x h пикселей по mpp метров - чуть больше сцены. Маска в шейдере
  // растягивается на этот прямоугольник: при размере сцены вместо него она съезжала к краю
  // участка на пиксель, и вырез под проезд расходился с бортовым камнем.
  const rect: [number, number, number, number] = [minX, minZ, w * mpp, h * mpp];
  // Опускается и обрамляется бортом проезд от CARRIAGEWAY_M2: пятна асфальта меньше остаются
  // вровень с тротуаром - с бортом по кругу они выглядели ямами.
  const road = new Uint8Array(w * h);
  for (let i = 0; i < road.length; i++) road[i] = (final[i * 4 + 2] ?? 0) >= 128 ? 1 : 0;
  keepLarge(road, w, h, Math.round(CARRIAGEWAY_M2 / (mpp * mpp)));
  // Края проезда и газона - ровными линиями, как на исполнительной съёмке: контур маски
  // выпрямляется в отрезки со скруглёнными углами и заливается заново. По этим же линиям
  // стоят бортовой камень и поребрик, режется плоскость земли.
  const toBytes = (pick: (i: number) => boolean) => {
    const out = new Uint8Array(w * h);
    for (let i = 0; i < out.length; i++) out[i] = pick(i) ? 255 : 0;
    return out;
  };
  const roadLoops = outlines(
    { values: toBytes((i) => road[i] === 1), width: w, height: h },
    rect,
    mpp,
    { ...shape, minWidth: 1.5 },
  );
  const roadFill = fillLoops(roadLoops, w, h, minX, minZ, mpp);
  // Газон и плитка выпрямляются без вычета проезда, а проезд потом перекрывает их: край
  // газона у дороги совпадает с бортом, без полоски асфальта между ними.
  // Щель уже GAP_M между газоном и проездом, не плитка, - газон до борта: на карте покрытий
  // это клетки асфальта на стыке, в жизни за бортовым камнем сразу дёрн.
  const gapPx = Math.max(1, Math.round(GAP_M / mpp));
  const red = new Float32Array(w * h);
  for (let i = 0; i < red.length; i++) red[i] = final[i * 4] ?? 0;
  const nearLawn = maxFilter(red, w, h, gapPx);
  const nearRoad = maxFilter(Float32Array.from(road), w, h, gapPx);
  const isLawn = (i: number) =>
    (final[i * 4] ?? 0) >= 128 ||
    (road[i] === 0 &&
      (final[i * 4 + 1] ?? 0) < 128 &&
      (nearLawn[i] ?? 0) >= 128 &&
      (nearRoad[i] ?? 0) > 0);
  const lawnLoops = outlines({ values: toBytes(isLawn), width: w, height: h }, rect, mpp, {
    ...shape,
    minWidth: 0.6,
  });
  const lawnFill = fillLoops(lawnLoops, w, h, minX, minZ, mpp);
  const paverFill = fillLoops(
    outlines(
      { values: toBytes((i) => (final[i * 4 + 1] ?? 0) >= 128), width: w, height: h },
      rect,
      mpp,
      { ...shape, minWidth: 0.6 },
    ),
    w,
    h,
    minX,
    minZ,
    mpp,
  );
  for (let i = 0; i < road.length; i++) {
    const r = roadFill[i] ?? 0;
    const g = Math.min(lawnFill[i] ?? 0, 255 - r);
    const pv = Math.min(paverFill[i] ?? 0, 255 - r, 255 - g);
    final[i * 4] = g;
    final[i * 4 + 1] = pv;
    final[i * 4 + 2] = r;
    road[i] = r >= 128 ? 1 : 0;
    // Покрытие пикселя - по итоговой маске, с газонами, тротуарами и проезжей частью
    // подосновы поверх карты покрытий: по нему растёт трава и ходят люди.
    if (road[i]) kinds[i] = ASPHALT;
    else if (g >= 128) kinds[i] = GRASS;
    else if (pv >= 128) kinds[i] = PAVERS;
  }
  absorbScraps(final, kinds, road, w, h, mpp);
  const cut = new THREE.DataTexture(roadFill, w, h, THREE.RedFormat, THREE.UnsignedByteType);
  cut.magFilter = THREE.LinearFilter;
  cut.minFilter = THREE.LinearFilter;
  cut.generateMipmaps = false;
  // Строки однобайтовой текстуры не выровнены по 4 байта: без этого вырез съезжал от маски.
  cut.unpackAlignment = 1;
  cut.needsUpdate = true;
  // По краю сцены контур замкнут рамкой - там борта нет, проезд продолжается дальше.
  const border = mpp * 3;
  const onBorder = (p: Flat) =>
    p.x - minX < border || maxX - p.x < border || p.z - minZ < border || maxZ - p.z < border;
  const inside = (a: Flat, b: Flat) => !(onBorder(a) && onBorder(b));
  const roadAt = (x: number, z: number) => {
    const px = Math.floor((x - minX) / mpp);
    const py = Math.floor((z - minZ) / mpp);
    if (px < 0 || py < 0 || px >= w || py >= h) return false;
    return (roadFill[py * w + px] ?? 0) >= 128;
  };
  const lawnAt = (x: number, z: number) => {
    const px = Math.floor((x - minX) / mpp);
    const py = Math.floor((z - minZ) / mpp);
    if (px < 0 || py < 0 || px >= w || py >= h) return false;
    return kinds[py * w + px] === GRASS;
  };
  const edges = {
    road: keepSegments(roadLoops, inside),
    // Поребрик - по краю газона, кроме стыка с проездом: там уже стоит бортовой камень.
    garden: keepSegments(lawnLoops, (a, b) => {
      if (!inside(a, b)) return false;
      const len = Math.hypot(b.x - a.x, b.z - a.z) || 1;
      const nx = (-(b.z - a.z) / len) * 0.5;
      const nz = ((b.x - a.x) / len) * 0.5;
      const mx = (a.x + b.x) / 2;
      const mz = (a.z + b.z) / 2;
      if (roadAt(mx + nx, mz + nz) || roadAt(mx - nx, mz - nz)) return false;
      // Поребрик - только между газоном и не газоном: пятно, отданное газону, его не держит.
      return lawnAt(mx + nx, mz + nz) !== lawnAt(mx - nx, mz - nz);
    }),
  };
  // Маска - прямо из массива: через холст полупрозрачная карта покрытий умножалась на
  // альфу, значения на краю портились, и газон у борта шёл зубцами.
  for (let i = 0; i < road.length; i++) final[i * 4 + 3] = 255;
  const texture = new THREE.DataTexture(
    new Uint8Array(final.buffer, final.byteOffset, final.byteLength),
    w,
    h,
    THREE.RGBAFormat,
    THREE.UnsignedByteType,
  );
  // Без мип-уровней: на косом взгляде уменьшенная маска размывала край газона, и между газоном
  // и бортом проступала волнистая полоса асфальта.
  texture.generateMipmaps = false;
  texture.flipY = false;
  texture.colorSpace = THREE.NoColorSpace;
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.needsUpdate = true;
  return {
    texture,
    rect,
    kinds,
    known,
    edges,
    roadContours: roadLoops,
    road,
    cut,
    width: w,
    height: h,
    metresPerPx: mpp,
  };
}

export interface GroundTextures {
  grass: THREE.Texture;
  asphalt: THREE.Texture;
  pavers: THREE.Texture;
  noise: THREE.Texture;
  grassNormalMap?: THREE.Texture;
  asphaltNormalMap?: THREE.Texture;
  paversNormalMap?: THREE.Texture;
  grassArmMap?: THREE.Texture;
  asphaltArmMap?: THREE.Texture;
  paversArmMap?: THREE.Texture;
}

/** Земля: один лист на всю сцену и поле вокруг, фактура по маске в шейдере. */

/** Клетка сетки земли, м. Лист в километры одним треугольником интерполировал координату
 *  фрагмента с ошибкой в десятки сантиметров: край газона у борта шёл волнами. */
const GROUND_CELL_M = 40;
const segmentsFor = (size: number) => Math.max(1, Math.min(256, Math.ceil(size / GROUND_CELL_M)));

/** Земля: 'ground' - газон и плитка на всю сцену с вырезом под проезд, 'road' - асфальт
 *  проезда на ROAD_DROP_M ниже, под вырезом, только в пределах маски. */
export function groundMesh(
  world: World,
  mask: MaskInfo,
  tex: GroundTextures,
  weather: GroundWeather,
  options: {
    geometry?: THREE.BufferGeometry;
    cutRoad?: boolean;
    name?: string;
    /** Плоскость проезда под вырезом: на ROAD_DROP_M ниже, только асфальт. */
    road?: boolean;
  } = {},
): THREE.Mesh {
  const [minX, minZ, maxX, maxZ] = world.bounds;
  const cx = (minX + maxX) / 2;
  const cz = (minZ + maxZ) / 2;
  const size = Math.max(maxX - minX, maxZ - minZ) + GROUND_PAD_M * 2;
  let geometry = options.geometry;
  if (!geometry && options.road) {
    const [rx, rz, rw, rh] = mask.rect;
    geometry = new THREE.PlaneGeometry(rw, rh, segmentsFor(rw), segmentsFor(rh));
    geometry.rotateX(-Math.PI / 2);
    geometry.translate(rx + rw / 2, -ROAD_DROP_M, rz + rh / 2);
  } else if (!geometry) {
    geometry = new THREE.PlaneGeometry(size, size, segmentsFor(size), segmentsFor(size));
    geometry.rotateX(-Math.PI / 2);
    geometry.translate(cx, 0, cz);
  }
  const material = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    roughness: 0.92,
    metalness: 0,
  });
  const uniforms = {
    uMask: { value: mask.texture },
    uMaskRect: { value: new THREE.Vector4(...mask.rect) },
    uGrass: { value: tex.grass },
    uAsphalt: { value: tex.asphalt },
    uPavers: { value: tex.pavers },
    uNoise: { value: tex.noise },
    uPbr: {
      value: new THREE.Vector3(
        Number(!!tex.grassNormalMap && !!tex.grassArmMap),
        Number(!!tex.paversNormalMap && !!tex.paversArmMap),
        Number(!!tex.asphaltNormalMap && !!tex.asphaltArmMap),
      ),
    },
    uGrassNormal: { value: tex.grassNormalMap ?? tex.noise },
    uAsphaltNormal: { value: tex.asphaltNormalMap ?? tex.noise },
    uPaversNormal: { value: tex.paversNormalMap ?? tex.noise },
    uGrassArm: { value: tex.grassArmMap ?? tex.noise },
    uAsphaltArm: { value: tex.asphaltArmMap ?? tex.noise },
    uPaversArm: { value: tex.paversArmMap ?? tex.noise },
    uRoad: { value: options.road ? 1 : 0 },
    uCut: { value: mask.cut },
    // Земля на уровне тротуара вырезает проезжую часть: там видна плоскость проезда ниже.
    uCutRoad: { value: options.cutRoad ? 1 : 0 },
    ...weather,
  };
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vGroundPos;')
      .replace(
        '#include <worldpos_vertex>',
        '#include <worldpos_vertex>\nvGroundPos = (modelMatrix * vec4(transformed, 1.0)).xyz;',
      );
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>\n${GROUND_FRAGMENT_HEAD}`)
      .replace('#include <map_fragment>', GROUND_MAP)
      .replace('#include <roughnessmap_fragment>', GROUND_ROUGHNESS)
      .replace('#include <normal_fragment_maps>', GROUND_NORMAL);
  };
  material.customProgramCacheKey = () => 'green-ground';
  const mesh = new THREE.Mesh(geometry, material);
  mesh.receiveShadow = true;
  mesh.name = options.name ?? (options.road ? 'road-surface' : 'ground');
  return mesh;
}

const GROUND_FRAGMENT_HEAD = /* glsl */ `
varying vec3 vGroundPos;
uniform sampler2D uMask;
uniform vec4 uMaskRect;
uniform sampler2D uGrass;
uniform sampler2D uAsphalt;
uniform sampler2D uPavers;
uniform sampler2D uNoise;
uniform vec3 uPbr;
uniform sampler2D uGrassNormal;
uniform sampler2D uAsphaltNormal;
uniform sampler2D uPaversNormal;
uniform sampler2D uGrassArm;
uniform sampler2D uAsphaltArm;
uniform sampler2D uPaversArm;
uniform float uWet;
uniform float uSnow;
uniform float uRoad;
uniform sampler2D uCut;
uniform float uCutRoad;
vec3 groundWeights;
float groundSnow;
float groundWet;
vec3 groundArm;

float groundHash(vec2 c) {
  vec3 p3 = fract(vec3(c.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}

// Тротуар - гранитные плиты 60 x 30 см со смещением рядов, как на улицах «Моей улицы»:
// у каждой плиты свой оттенок, шов темнее; вдали швы растворяются, а не рябят.
vec3 paverTile(vec2 p) {
  vec2 t = p / vec2(0.6, 0.3);
  float row = floor(t.y);
  t.x += mod(row, 2.0) * 0.5;
  vec2 cell = floor(t);
  vec2 f = fract(t);
  float h = groundHash(cell + 17.0);
  vec3 base = mix(vec3(0.56, 0.56, 0.545), vec3(0.67, 0.665, 0.64), h);
  base *= 0.9 + 0.14 * texture2D(uNoise, p * 1.9).b;
  vec2 aa = fwidth(t);
  vec2 inner = smoothstep(vec2(0.0), aa * 1.5 + vec2(0.012, 0.024), f)
    * smoothstep(vec2(0.0), aa * 1.5 + vec2(0.012, 0.024), 1.0 - f);
  float fade = clamp(1.0 - max(aa.x, aa.y) * 2.5, 0.0, 1.0);
  return base * mix(1.0, mix(0.58, 1.0, inner.x * inner.y), fade);
}

// Smoothly blend hashed texture offsets: patches no longer repeat in a visible grid.
vec3 antiTile(sampler2D tex, vec2 p, float scale) {
  float n = texture2D(uNoise, p / 90.0).r * 8.0;
  float cell = floor(n);
  vec2 a = sin(vec2(3.0, 7.0) * (cell + 1.0)) * 17.0;
  vec2 b = sin(vec2(3.0, 7.0) * (cell + 2.0)) * 17.0;
  return mix(texture2D(tex, p / scale + a).rgb,
             texture2D(tex, p / scale + b).rgb, smoothstep(0.2, 0.8, fract(n)));
}
`;

export const GROUND_MAP = /* glsl */ `
{
  vec2 p = vGroundPos.xz;
  vec2 muv = (p - uMaskRect.xy) / uMaskRect.zw;
  // Нулевой мип-уровень: при косом взгляде мипмапы размывают узкий проезд, и вырез земли
  // разошёлся бы с бортовым камнем и машинами.
  vec3 m = textureLod(uMask, clamp(muv, 0.0, 1.0), 0.0).rgb;
  // За границей сцены данных нет: газон квартала, край уходит в дымку.
  float outside = step(0.0, muv.x) * step(muv.x, 1.0) * step(0.0, muv.y) * step(muv.y, 1.0);
  vec4 nz = texture2D(uNoise, p / 23.0);
  // Проезд - своя плоскость ниже на высоту борта, здесь под ним вырез (mask.cut). Порог выше
  // середины: вырез чуть уже проезда, край земли уходит под бортовой камень, щели нет.
  if (uCutRoad > 0.5 && outside > 0.5 && textureLod(uCut, clamp(muv, 0.0, 1.0), 0.0).r > 0.6) discard;
  // Граница газона, плитки и асфальта - порог маски без шума: шум делал край «обгрызенным»
  // (пользователь, 17.10.2026). Лесенку клеток растра снимает размытие маски (softenCells).
  // Exclude the lowered road channel before normalising sidewalk/soil shares.
  vec3 share = vec3(m.r, m.g, max(1.0 - m.r - m.g - m.b, 0.0));
  share /= max(share.r + share.g + share.b, 1e-3);
  float lawn = smoothstep(0.45, 0.55, share.r);
  float paver = smoothstep(0.45, 0.55, share.g) * (1.0 - lawn);
  lawn = mix(1.0, lawn, outside);
  paver *= outside;
  if (uRoad > 0.5) {
    lawn = 0.0;
    paver = 0.0;
  }
  float asph = clamp(1.0 - lawn - paver, 0.0, 1.0);
  groundWeights = vec3(lawn, paver, asph);
  // Крупные пятна - шумом в десятки метров, а не фактурой: повтор плитки фактуры сверху
  // читается рядами, пятна шума - нет.
  float macro = texture2D(uNoise, p / 173.0).r * 0.6 + texture2D(uNoise, p / 47.0).g * 0.4;
  vec3 g = antiTile(uGrass, p, 2.0);
  // Keep the scanned fine structure, with a living summer turf palette.
  float turfLuma = dot(g, vec3(0.2126, 0.7152, 0.0722));
  g = mix(g, turfLuma * vec3(0.55, 1.08, 0.28), 0.78);
  g *= mix(vec3(1.06, 0.96, 0.8), vec3(0.8, 1.03, 0.88), macro) * 0.65;
  // Дальнее поле за краем съёмки глуше: оно фон, а не газон участка.
  g = mix(g * vec3(0.86, 0.84, 0.8), g, outside);
  vec3 pv = paverTile(p) * (0.95 + 0.07 * macro);
  vec3 a = antiTile(uAsphalt, p, 3.0) * (0.74 + 0.26 * macro);
  vec3 col = g * lawn + pv * paver + a * asph;
  // Мокрое покрытие темнее, газон темнеет меньше; лужи - пятнами шума.
  float puddle = smoothstep(0.55, 0.7, texture2D(uNoise, p / 9.0).g) * (1.0 - lawn);
  col *= 1.0 - uWet * (0.3 * (1.0 - lawn) + 0.15 * lawn + 0.2 * puddle);
  // Снег ложится сначала на газон, на проезды - позже и пятнами: их чистят и греют машины.
  float cover = uSnow * (lawn * 1.25 + (1.0 - lawn) * 0.6) + (nz.b - 0.5) * 0.5 * uSnow;
  groundSnow = clamp(cover, 0.0, 1.0);
  col = mix(col, vec3(0.9, 0.92, 0.96), groundSnow);
  groundWet = uWet * (1.0 - groundSnow) * (0.6 + 0.4 * puddle);
  groundArm = antiTile(uGrassArm, p, 2.0) * lawn
    + vec3(1.0, 0.82, 0.0) * paver
    + antiTile(uAsphaltArm, p, 3.0) * asph;
  groundArm = mix(vec3(1.0, 0.92, 0.0), groundArm, dot(groundWeights, uPbr));
  col *= mix(groundArm.r, 1.0, 0.35 + groundSnow * 0.65);
  diffuseColor.rgb *= col;
}
`;

const GROUND_ROUGHNESS = /* glsl */ `
float roughnessFactor = clamp(groundArm.g, 0.45, 1.0);
roughnessFactor = mix(roughnessFactor, 0.12, groundWet * (1.0 - groundWeights.x) * 0.9);
roughnessFactor = mix(roughnessFactor, 0.75, groundSnow);
`;

// The scanned texture coordinates are world X/Z; transform their tangent normal to view space.
const GROUND_NORMAL = /* glsl */ `
vec2 groundP = vGroundPos.xz;
vec3 scannedNormal = (antiTile(uGrassNormal, groundP, 2.0) * groundWeights.x
  + vec3(0.5, 0.5, 1.0) * groundWeights.y
  + antiTile(uAsphaltNormal, groundP, 3.0) * groundWeights.z) * 2.0 - 1.0;
scannedNormal = mix(vec3(0.0, 0.0, 1.0), scannedNormal, dot(groundWeights, uPbr));
scannedNormal.xy *= mix(1.0, 0.35, groundWeights.x) * (1.0 - groundSnow * 0.95) * (1.0 - groundWet * 0.85);
normal = normalize(mat3(viewMatrix) * vec3(scannedNormal.x, scannedNormal.z, scannedNormal.y));
`;

/** Бортовой камень: брус 15 x 15 см вдоль каждой линии борта - дорожный, у проезжей части. */
export const CURB_W = 0.15;
export const CURB_H = 0.15;
/** Верх дорожного борта вровень с тротуаром. */
export const CURB_ABOVE_WALK_M = 0;
/** Садовый борт между тротуаром и газоном (БР 100.20.8 по ГОСТ 6665): 8 см шириной, над
 *  газоном выступает на несколько сантиметров. */
export const GARDEN_CURB_W = 0.08;
export const GARDEN_CURB_H = 0.06;

/** Сетка бруса вдоль ломаной: верх и две боковые грани без дна. Пролёты стыкуются срезом
 *  угла (без щели и нахлёста на изломе, срез не длиннее ширины бруса), открытая ломаная
 *  закрыта торцами, замкнутое кольцо - стыком конца с началом: изнутри брус не виден. */
export function ribbonBox(
  lines: readonly Line[],
  width: number,
  height: number,
  lift = 0,
  bevel = 0,
  bevelSides: 'both' | 'left' = 'both',
): THREE.BufferGeometry {
  const pos: number[] = [];
  const nor: number[] = [];
  const uv: number[] = [];
  const shade: number[] = [];
  const quad = (
    a: number[],
    b: number[],
    c: number[],
    d: number[],
    n: number[],
    u0: number,
    u1: number,
    dark = 0,
  ) => {
    pos.push(...a, ...b, ...c, ...a, ...c, ...d);
    for (let i = 0; i < 6; i++) {
      nor.push(...n);
      shade.push(dark);
    }
    uv.push(u0, 0, u1, 0, u1, 1, u0, 0, u1, 1, u0, 1);
  };
  const hw = width / 2;
  const y0 = lift;
  const y1 = lift + height;
  // Фаска по верхним рёбрам: на ребре ловится блик, как у тёсаного камня, а не у бруса.
  const b = Math.min(Math.max(bevel, 0), hw * 0.8, height * 0.8);
  const inset = (hw - b) / hw;
  // Фаска только слева (у дорожного борта - со стороны проезда): справа грань до верха и
  // верх до самого ребра, иначе на газоне светилась тонкая полоска фаски.
  const rightBevel = bevelSides === 'both';
  const insetR = rightBevel ? inset : 1;
  // Правая грань при фаске слева - газонная: затеняется (aShade), будто засыпана землёй.
  const rightShade = rightBevel ? 0 : 1;
  const sq = Math.SQRT1_2;
  for (const line of lines) {
    const pts: Flat[] = [];
    const tops: number[] = [];
    line.points.forEach((p, k) => {
      const last = pts.at(-1);
      if (!last || Math.hypot(p.x - last.x, p.z - last.z) >= 0.01) {
        pts.push(p);
        tops.push(line.tops?.[k] ?? y1);
      }
    });
    const first = pts[0];
    const end = pts.at(-1);
    const closed =
      pts.length > 3 && !!first && !!end && Math.hypot(first.x - end.x, first.z - end.z) < 0.01;
    if (closed) {
      pts.pop();
      tops.pop();
    }
    const n = pts.length;
    // Верх и начало фаски в точке: борт с понижением на съезде.
    const topAt = (k: number) => tops[k % n] ?? y1;
    const bevelAt = (k: number) => topAt(k) - b;
    const segments = closed ? n : n - 1;
    if (segments < 1) continue;
    // Нормаль каждого пролёта.
    const normals: [number, number][] = [];
    for (let s = 0; s < segments; s++) {
      const p = pts[s] as Flat;
      const q = pts[(s + 1) % n] as Flat;
      const len = Math.hypot(q.x - p.x, q.z - p.z);
      normals.push([-(q.z - p.z) / len, (q.x - p.x) / len]);
    }
    // Смещение вершины влево: среднее нормалей соседних пролётов, длиной до стыка граней.
    const offset = (k: number): [number, number] => {
      const after = closed ? k % segments : Math.min(k, segments - 1);
      const before = closed ? (k - 1 + segments) % segments : Math.max(k - 1, 0);
      const [ax, az] = normals[before] ?? [0, 0];
      const [bx, bz] = normals[after] ?? [0, 0];
      let mx = ax + bx;
      let mz = az + bz;
      const ml = Math.hypot(mx, mz);
      if (ml < 1e-6) return [bx * hw, bz * hw];
      mx /= ml;
      mz /= ml;
      const scale = Math.min(hw / Math.max(mx * bx + mz * bz, 1e-6), width);
      return [mx * scale, mz * scale];
    };
    let along = 0;
    for (let s = 0; s < segments; s++) {
      const p = pts[s] as Flat;
      const q = pts[(s + 1) % n] as Flat;
      const [ox0, oz0] = offset(s);
      const [ox1, oz1] = offset(s + 1);
      const [nx, nz] = normals[s] ?? [0, 0];
      const len = Math.hypot(q.x - p.x, q.z - p.z);
      const u0 = along;
      const u1 = along + len;
      along = u1;
      const l0 = [p.x + ox0, p.z + oz0];
      const r0 = [p.x - ox0, p.z - oz0];
      const l1 = [q.x + ox1, q.z + oz1];
      const r1 = [q.x - ox1, q.z - oz1];
      const li0 = [p.x + ox0 * inset, p.z + oz0 * inset];
      const ri0 = [p.x - ox0 * insetR, p.z - oz0 * insetR];
      const li1 = [q.x + ox1 * inset, q.z + oz1 * inset];
      const ri1 = [q.x - ox1 * insetR, q.z - oz1 * insetR];
      const t0 = topAt(s);
      const t1 = topAt(s + 1);
      const b0 = bevelAt(s);
      const b1 = bevelAt(s + 1);
      const rb0 = rightBevel ? b0 : t0;
      const rb1 = rightBevel ? b1 : t1;
      // Верх, фаски, левая и правая грани.
      quad(
        [li0[0] ?? 0, t0, li0[1] ?? 0],
        [ri0[0] ?? 0, t0, ri0[1] ?? 0],
        [ri1[0] ?? 0, t1, ri1[1] ?? 0],
        [li1[0] ?? 0, t1, li1[1] ?? 0],
        [0, 1, 0],
        u0,
        u1,
      );
      if (b > 0) {
        quad(
          [l0[0] ?? 0, b0, l0[1] ?? 0],
          [li0[0] ?? 0, t0, li0[1] ?? 0],
          [li1[0] ?? 0, t1, li1[1] ?? 0],
          [l1[0] ?? 0, b1, l1[1] ?? 0],
          [nx * sq, sq, nz * sq],
          u0,
          u1,
        );
        if (rightBevel)
          quad(
            [ri1[0] ?? 0, t1, ri1[1] ?? 0],
            [ri0[0] ?? 0, t0, ri0[1] ?? 0],
            [r0[0] ?? 0, b0, r0[1] ?? 0],
            [r1[0] ?? 0, b1, r1[1] ?? 0],
            [-nx * sq, sq, -nz * sq],
            u1,
            u0,
          );
      }
      quad(
        [l0[0] ?? 0, y0, l0[1] ?? 0],
        [l0[0] ?? 0, b0, l0[1] ?? 0],
        [l1[0] ?? 0, b1, l1[1] ?? 0],
        [l1[0] ?? 0, y0, l1[1] ?? 0],
        [nx, 0, nz],
        u0,
        u1,
      );
      quad(
        [r1[0] ?? 0, y0, r1[1] ?? 0],
        [r1[0] ?? 0, rb1, r1[1] ?? 0],
        [r0[0] ?? 0, rb0, r0[1] ?? 0],
        [r0[0] ?? 0, y0, r0[1] ?? 0],
        [-nx, 0, -nz],
        u1,
        u0,
        rightShade,
      );
    }
    if (closed) continue;
    // Торцы открытой ломаной.
    for (const [k, sign] of [
      [0, -1],
      [n - 1, 1],
    ] as const) {
      const p = pts[k] as Flat;
      const [ox, oz] = offset(k);
      const [nx, nz] = normals[sign < 0 ? 0 : segments - 1] ?? [0, 0];
      const dir = [nz * sign, -nx * sign];
      const a = [p.x + ox, p.z + oz];
      const c = [p.x - ox, p.z - oz];
      const ai = [p.x + ox * inset, p.z + oz * inset];
      const ci = [p.x - ox * insetR, p.z - oz * insetR];
      const [first, second, firstIn, secondIn] = sign < 0 ? [a, c, ai, ci] : [c, a, ci, ai];
      const nrm = [dir[0] ?? 0, 0, dir[1] ?? 0];
      const tk = topAt(k);
      const bk = bevelAt(k);
      // Угол без фаски (справа при bevelSides 'left') доходит до верха.
      const rk = rightBevel ? bk : tk;
      const [bFirst, bSecond] = sign < 0 ? [bk, rk] : [rk, bk];
      quad(
        [first[0] ?? 0, y0, first[1] ?? 0],
        [first[0] ?? 0, bFirst, first[1] ?? 0],
        [second[0] ?? 0, bSecond, second[1] ?? 0],
        [second[0] ?? 0, y0, second[1] ?? 0],
        nrm,
        0,
        width,
      );
      if (b > 0)
        quad(
          [first[0] ?? 0, bFirst, first[1] ?? 0],
          [firstIn[0] ?? 0, tk, firstIn[1] ?? 0],
          [secondIn[0] ?? 0, tk, secondIn[1] ?? 0],
          [second[0] ?? 0, bSecond, second[1] ?? 0],
          nrm,
          0,
          width,
        );
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setAttribute('aShade', new THREE.Float32BufferAttribute(shade, 1));
  g.computeBoundingSphere();
  return g;
}

/** Ограда: вертикальная лента высотой height, решётка - прозрачностью текстуры. u - метры
 *  вдоль ограды, чтобы шаг прутьев не зависел от длины пролёта. */
export function fenceGeometry(
  lines: readonly Line[],
  height: number,
  barStepM: number,
): THREE.BufferGeometry {
  const pos: number[] = [];
  const nor: number[] = [];
  const uv: number[] = [];
  for (const line of lines) {
    let along = 0;
    for (let i = 0; i + 1 < line.points.length; i++) {
      const p = line.points[i];
      const q = line.points[i + 1];
      if (!p || !q) continue;
      const len = Math.hypot(q.x - p.x, q.z - p.z);
      if (len < 0.01) continue;
      const nx = -(q.z - p.z) / len;
      const nz = (q.x - p.x) / len;
      const u0 = along / barStepM;
      const u1 = (along + len) / barStepM;
      along += len;
      pos.push(
        p.x,
        0,
        p.z,
        q.x,
        0,
        q.z,
        q.x,
        height,
        q.z,
        p.x,
        0,
        p.z,
        q.x,
        height,
        q.z,
        p.x,
        height,
        p.z,
      );
      for (let k = 0; k < 6; k++) nor.push(nx, 0, nz);
      uv.push(u0, 0, u1, 0, u1, 1, u0, 0, u1, 1, u0, 1);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.computeBoundingSphere();
  return g;
}

/** Точки прутьев решётки вдоль оград с шагом step, м. */
export function fenceBarSpots(lines: readonly Line[], step: number): Flat[] {
  const out: Flat[] = [];
  for (const line of lines) {
    let carry = step / 2;
    for (let i = 0; i + 1 < line.points.length; i++) {
      const a = line.points[i];
      const b = line.points[i + 1];
      if (!a || !b) continue;
      const len = Math.hypot(b.x - a.x, b.z - a.z);
      let u = carry;
      for (; u < len; u += step) {
        out.push({ x: a.x + ((b.x - a.x) * u) / len, z: a.z + ((b.z - a.z) * u) / len });
      }
      carry = u - len;
    }
  }
  return out;
}

/** Каркас ограды: столбы через 2,5 м и на концах, верхнее и нижнее перила. */
/** Ближе этого два столба ограды не встают, м. */
const POST_GAP_M = 1.2;

export function fenceFrame(lines: readonly Line[]): THREE.BufferGeometry {
  const rails = [ribbonBox(lines, 0.04, 0.05, 0.95), ribbonBox(lines, 0.04, 0.04, 0.08)];
  const pos: number[] = [];
  const nor: number[] = [];
  const post = new THREE.BoxGeometry(0.06, 1.1, 0.06).toNonIndexed();
  post.translate(0, 0.55, 0);
  const pp = post.getAttribute('position');
  const pn = post.getAttribute('normal');
  // Столб не ставится ближе POST_GAP_M к уже стоящему: на стыке двух кусков ограды и у конца
  // пролёта, где шаг 2,5 м не кратен длине, вставали два столба рядом.
  const placed = new Map<string, Flat[]>();
  const cellOf = (x: number, z: number) =>
    `${Math.floor(x / POST_GAP_M)},${Math.floor(z / POST_GAP_M)}`;
  const crowded = (x: number, z: number) => {
    const cx = Math.floor(x / POST_GAP_M);
    const cz = Math.floor(z / POST_GAP_M);
    for (let dx = -1; dx <= 1; dx++) {
      for (let dz = -1; dz <= 1; dz++) {
        const near = placed.get(`${cx + dx},${cz + dz}`) ?? [];
        if (near.some((q) => Math.hypot(q.x - x, q.z - z) < POST_GAP_M)) return true;
      }
    }
    return false;
  };
  const addPost = (x: number, z: number) => {
    if (crowded(x, z)) return;
    const key = cellOf(x, z);
    placed.set(key, [...(placed.get(key) ?? []), { x, z }]);
    for (let i = 0; i < pp.count; i++) {
      pos.push(pp.getX(i) + x, pp.getY(i), pp.getZ(i) + z);
      nor.push(pn.getX(i), pn.getY(i), pn.getZ(i));
    }
  };
  // Концы ограды - первыми: на них столб нужен обязательно, промежуточный рядом уступает.
  for (const line of lines) {
    const start = line.points[0];
    const end = line.points[line.points.length - 1];
    if (start) addPost(start.x, start.z);
    if (end) addPost(end.x, end.z);
  }
  for (const line of lines) {
    let carry = 0;
    for (let i = 0; i + 1 < line.points.length; i++) {
      const a = line.points[i];
      const b = line.points[i + 1];
      if (!a || !b) continue;
      const len = Math.hypot(b.x - a.x, b.z - a.z);
      for (let u = carry; u < len; u += 2.5)
        addPost(a.x + ((b.x - a.x) * u) / len, a.z + ((b.z - a.z) * u) / len);
      carry = (carry - len) % 2.5;
      if (carry < 0) carry += 2.5;
    }
  }
  for (const rail of rails) {
    const rp = rail.getAttribute('position');
    const rn = rail.getAttribute('normal');
    for (let i = 0; i < rp.count; i++) {
      pos.push(rp.getX(i), rp.getY(i), rp.getZ(i));
      nor.push(rn.getX(i), rn.getY(i), rn.getZ(i));
    }
    rail.dispose();
  }
  post.dispose();
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  g.computeBoundingSphere();
  return g;
}

/** Направление от опоры к ближайшему борту: консоль фонаря смотрит на проезжую часть. */
export function nearestCurbDirection(pole: Flat, curbs: readonly Line[], maxM = 25): number | null {
  let best = maxM;
  let angle: number | null = null;
  for (const line of curbs) {
    for (let i = 0; i + 1 < line.points.length; i++) {
      const a = line.points[i];
      const b = line.points[i + 1];
      if (!a || !b) continue;
      const vx = b.x - a.x;
      const vz = b.z - a.z;
      const len2 = vx * vx + vz * vz;
      const t =
        len2 > 0 ? Math.max(0, Math.min(1, ((pole.x - a.x) * vx + (pole.z - a.z) * vz) / len2)) : 0;
      const qx = a.x + vx * t;
      const qz = a.z + vz * t;
      const d = Math.hypot(qx - pole.x, qz - pole.z);
      if (d < best && d > 0.05) {
        best = d;
        angle = Math.atan2(qx - pole.x, qz - pole.z);
      }
    }
  }
  return angle;
}

/** Опора освещения, как на улицах пилота: конический железобетонный ствол 8,4 м, стальной
 *  кронштейн с подъёмом и консольный светильник. Модель смотрит консолью в +z; бетон и сталь
 *  различаются цветом вершин. */
export function streetLightGeometry(): THREE.BufferGeometry {
  // Цвета вершин линейные: 0,2 - светло-серый бетон на солнце, а не белая мачта.
  const concrete: [number, number, number] = [0.2, 0.2, 0.19];
  const steel: [number, number, number] = [0.07, 0.075, 0.08];
  const parts: [THREE.BufferGeometry, [number, number, number]][] = [];
  // Ствол уходит на 20 см под землю: опора на опущенном проезде не висит.
  const shaft = new THREE.CylinderGeometry(0.085, 0.16, 8.6, 8, 1);
  shaft.translate(0, 4.1, 0);
  parts.push([shaft, concrete]);
  const collar = new THREE.CylinderGeometry(0.1, 0.1, 0.25, 8, 1);
  collar.translate(0, 8.25, 0);
  parts.push([collar, steel]);
  // Кронштейн: короткая стойка вверх и наклонная трубка к светильнику.
  const riser = new THREE.CylinderGeometry(0.035, 0.04, 0.5, 6, 1);
  riser.translate(0, 8.6, 0);
  parts.push([riser, steel]);
  const arm = new THREE.CylinderGeometry(0.03, 0.035, 1.75, 6, 1);
  arm.rotateX(Math.PI / 2 - 0.2);
  arm.translate(0, 8.5, 0.82);
  parts.push([arm, steel]);
  const head = new THREE.BoxGeometry(0.3, 0.13, 0.66);
  head.translate(0, 8.12, 1.65);
  parts.push([head, steel]);
  const pos: number[] = [];
  const nor: number[] = [];
  const col: number[] = [];
  for (const [part, color] of parts) {
    const g = part.index ? part.toNonIndexed() : part;
    const pp = g.getAttribute('position');
    const nn = g.getAttribute('normal');
    for (let i = 0; i < pp.count; i++) {
      pos.push(pp.getX(i), pp.getY(i), pp.getZ(i));
      nor.push(nn.getX(i), nn.getY(i), nn.getZ(i));
      col.push(...color);
    }
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  out.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  out.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  out.computeBoundingSphere();
  return out;
}

/** Дорога или дорожка карты города для маски земли. */
export interface PaintedRoads {
  width: number;
  paved: 'asphalt' | 'pavers';
  lines: readonly Line[];
}

/** Дороги и дорожки OpenStreetMap там, где съёмки нет, вписываются в маску земли: плоская
 *  серая лента поверх газона читалась заплаткой без фактуры, а в маске дорожка получает
 *  плитку, проезд - асфальт, как всё остальное. Снятое съёмкой карта не перекрывает. */
export function paintContextRoads(mask: MaskInfo, roads: readonly PaintedRoads[]): void {
  const { width: w, height: h, metresPerPx: mpp } = mask;
  const [minX, minZ] = mask.rect;
  const data = mask.texture.image.data as Uint8Array;
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  if (!ctx) return;
  let changed = false;
  for (const paved of ['asphalt', 'pavers'] as const) {
    const group = roads.filter((r) => r.paved === paved);
    if (!group.length) continue;
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = '#ffffff';
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    for (const road of group) {
      ctx.lineWidth = road.width / mpp;
      ctx.beginPath();
      for (const line of road.lines) {
        line.points.forEach((p, i) => {
          const x = (p.x - minX) / mpp;
          const y = (p.z - minZ) / mpp;
          if (i) ctx.lineTo(x, y);
          else ctx.moveTo(x, y);
        });
      }
      ctx.stroke();
    }
    const img = ctx.getImageData(0, 0, w, h).data;
    const raw = new Uint8Array(w * h);
    for (let i = 0; i < raw.length; i++) raw[i] = img[i * 4] ?? 0;
    const paint = blurBytes(raw, w, h, 1);
    for (let i = 0; i < paint.length; i++) {
      const v = paint[i] ?? 0;
      if (!v || mask.known[i] || mask.road[i]) continue;
      changed = true;
      data[i * 4] = Math.min(data[i * 4] ?? 0, 255 - v);
      data[i * 4 + 1] =
        paved === 'pavers'
          ? Math.max(data[i * 4 + 1] ?? 0, v)
          : Math.min(data[i * 4 + 1] ?? 0, 255 - v);
      if (v >= 128) mask.kinds[i] = paved === 'pavers' ? PAVERS : ASPHALT;
    }
  }
  if (changed) mask.texture.needsUpdate = true;
}
