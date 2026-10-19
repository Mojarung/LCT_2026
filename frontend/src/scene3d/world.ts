/* Сцена 3D-вида из артефактов прогона: scene.json, если сервис его записал, и подоснова.
 *
 * Координаты чертежа переводятся в координаты сцены: начало - в медиане посадок, x - на
 * восток, z - на юг (three.js смотрит вдоль -z, поэтому север чертежа уходит в -z). Числа
 * в десятки тысяч метров иначе съедают точность float32 на GPU: дрожат кроны и тени.
 *
 * Прогон, записанный до появления scene.json, тоже открывается: здания берутся из замкнутых
 * контуров подосновы с высотой по площади, виды - по жизненной форме. Об этом говорит флаг
 * fallback, и интерфейс обязан его показать: такая сцена грубее, чем могла бы быть. */

import type { BasemapFeature, BasemapJson, Geometry, PlanJson, Position } from '../api/artifacts';
import {
  mergePlants,
  plantsOf,
  stripPoints,
  shrubStripLines,
  type ExistingPlant,
} from '../map/existing';
import { isShrubType } from '../map/models';
import { simplifyRing } from './facades';
import { poleSites } from './poles';
import type {
  Building,
  Flat,
  FloorsSource,
  Line,
  Plant,
  Ring,
  SceneJson,
  SceneSpeciesJson,
  World,
} from './types';

/** Поле вокруг посадок, которое попадает в сцену, если scene.json не задал своё. */
export const MARGIN_M = 200;

/** Высота этажа и цоколя при запасной сборке: те же числа, что у сервиса (application/volumes.py). */
const STOREY_M = 3.0;
const PLINTH_M = 1.2;
const ONE_STOREY_M = 4.0;

/** Жизненная форма -> взрослая высота, крона через 10 лет и взрослая крона, метры. Только для
 *  прогонов без scene.json: у каталога свои числа на каждый вид. */
const LIFE_FORMS: Record<string, [number, number, number]> = {
  tree_large: [22, 6, 12],
  tree_medium: [15, 5, 8],
  tree_small: [8, 3.5, 5],
  shrub_tall: [3, 2, 3],
  shrub_medium: [1.8, 1.2, 1.8],
  shrub_low: [0.8, 0.8, 1.2],
  groundcover: [0.3, 0.6, 1],
  perennial: [0.6, 0.5, 0.6],
};

/** Устойчивое число из строки: разброс поворота и оттенка не меняется от прогона к прогону. */
export function hashOf(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function median(values: number[]): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? (sorted[mid] ?? 0) : ((sorted[mid - 1] ?? 0) + (sorted[mid] ?? 0)) / 2;
}

export interface Frame {
  origin: [number, number];
  toFlat(x: number, y: number): Flat;
}

export function frameAt(origin: [number, number]): Frame {
  const [ox, oy] = origin;
  return { origin, toFlat: (x, y) => ({ x: x - ox, z: -(y - oy) }) };
}

export function speciesFallback(
  code: string,
  lifeForm: string,
  name: string,
  crown?: number,
): SceneSpeciesJson {
  const [height, crown10, mature] = LIFE_FORMS[lifeForm] ?? LIFE_FORMS.tree_medium ?? [15, 5, 8];
  return {
    name_ru: name,
    name_lat: '',
    life_form: lifeForm,
    height_m: height,
    crown_diameter_m: crown ?? crown10,
    crown_mature_m: Math.max(mature, crown ?? 0),
    evergreen: false,
    conifer: false,
    growth: 'medium',
    genus: code.split('_')[0] ?? '',
    family: '',
  };
}

/** Площадь кольца со знаком (метры чертежа): больше нуля - против часовой. */
export function signedArea(ring: Position[]): number {
  let sum = 0;
  for (let i = 0; i < ring.length; i++) {
    const [x1, y1] = ring[i] ?? [0, 0];
    const [x2, y2] = ring[(i + 1) % ring.length] ?? [0, 0];
    sum += x1 * y2 - x2 * y1;
  }
  return sum / 2;
}

/** Этажность без подписи по площади - как у сервиса: будка, павильон, дом. */
export function floorsByArea(area: number): number {
  if (area < 150) return 1;
  if (area < 600) return 2;
  return 5;
}

export function heightOf(floors: number): number {
  return floors <= 1 ? ONE_STOREY_M : STOREY_M * floors + PLINTH_M;
}

type Box = [number, number, number, number];

function inBox(ring: Position[], box: Box): boolean {
  for (const [x, y] of ring) {
    if (x >= box[0] && x <= box[2] && y >= box[1] && y <= box[3]) return true;
  }
  return false;
}

function flatRing(ring: Position[], frame: Frame): Ring {
  const out = ring.map(([x, y]) => frame.toFlat(x, y));
  const first = out[0];
  const last = out[out.length - 1];
  // Замыкающая точка GeoJSON совпадает с первой: стене нулевой длины нечего делать в сетке.
  if (first && last && out.length > 1 && first.x === last.x && first.z === last.z) out.pop();
  return out;
}

function lines(geometry: Geometry): Position[][] {
  switch (geometry.type) {
    case 'LineString':
      return [geometry.coordinates];
    case 'MultiLineString':
      return geometry.coordinates;
    case 'Polygon':
      return geometry.coordinates;
    case 'MultiPolygon':
      return geometry.coordinates.flat();
    case 'GeometryCollection':
      return geometry.geometries.flatMap(lines);
    default:
      return [];
  }
}

function polygons(geometry: Geometry): Position[][][] {
  switch (geometry.type) {
    case 'Polygon':
      return [geometry.coordinates];
    case 'MultiPolygon':
      return geometry.coordinates;
    case 'GeometryCollection':
      return geometry.geometries.flatMap(polygons);
    default:
      return [];
  }
}

/** Подоснова без точных копий: тот же класс, признаки и координаты. Копии приходят из
 *  чертежа (слой вставлен дважды, xref наложен на себя) и в 3D дают двойные ограды, газоны
 *  с мерцанием и лишние мачты. Объекты хоть на миллиметр в стороне остаются: это уже не копия. */
export function distinctFeatures(features: readonly BasemapFeature[]): BasemapFeature[] {
  const seen = new Set<string>();
  const out: BasemapFeature[] = [];
  for (const feature of features) {
    const key = JSON.stringify([feature.properties, feature.geometry]);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(feature);
  }
  return out;
}

interface Linework {
  utilities: Map<string, Line[]>;
  boundary: Line[];
  treeStrips: Flat[][];
  shrubStrips: Line[];
  curbs: Line[];
  fences: Line[];
  poles: Flat[];
  lawns: Ring[][];
  sidewalks: Ring[][];
  roads: Ring[][];
}

const AREA_CLASSES: Record<string, 'lawns' | 'sidewalks' | 'roads'> = {
  lawn: 'lawns',
  sidewalk: 'sidewalks',
  road: 'roads',
};

function takeFeature(
  feature: BasemapFeature,
  box: Box,
  frame: Frame,
  into: Linework,
  poleParts: Geometry[],
): void {
  const kind = feature.properties.class;
  const geometry = feature.geometry;
  const shrubLines = shrubStripLines(feature);
  if (shrubLines.length) {
    for (const line of shrubLines) {
      // Preserve the axis as a whole: filtering individual vertices can bridge gaps.
      if (
        line.length > 1 &&
        line.some((a, i) => {
          const b = line[i + 1];
          return (
            b &&
            Math.max(a[0], b[0]) >= box[0] &&
            Math.min(a[0], b[0]) <= box[2] &&
            Math.max(a[1], b[1]) >= box[1] &&
            Math.min(a[1], b[1]) <= box[3]
          );
        })
      )
        into.shrubStrips.push({ points: line.map(([x, y]) => frame.toFlat(x, y)) });
    }
    return;
  }
  const strip = stripPoints(feature);
  if (strip) {
    const visible = strip.filter((point) => inBox([point], box));
    if (visible.length) into.treeStrips.push(visible.map(([x, y]) => frame.toFlat(x, y)));
    return;
  }
  if (kind === 'pole') {
    // Часть знака, а не опора: опоры собираются из всех частей разом (poles.ts).
    poleParts.push(geometry);
    return;
  }
  if (kind.startsWith('utility.') || kind === 'power_line_overhead' || kind === 'work_boundary') {
    const target =
      kind === 'work_boundary'
        ? into.boundary
        : (into.utilities.get(kind) ?? into.utilities.set(kind, []).get(kind) ?? []);
    for (const line of lines(geometry)) {
      if (line.length > 1 && inBox(line, box)) {
        target.push({ points: line.map(([x, y]) => frame.toFlat(x, y)) });
      }
    }
    return;
  }
  if (kind === 'curb' || kind === 'fence') {
    const target = kind === 'curb' ? into.curbs : into.fences;
    for (const line of lines(geometry)) {
      if (line.length > 1 && inBox(line, box)) {
        target.push({ points: line.map(([x, y]) => frame.toFlat(x, y)) });
      }
    }
    return;
  }
  const area = AREA_CLASSES[kind];
  if (!area) return;
  for (const polygon of polygons(geometry)) {
    const outer = polygon[0];
    if (outer && outer.length > 2 && inBox(outer, box)) {
      into[area].push(polygon.map((ring) => flatRing(ring, frame)));
    }
  }
}

/** Ближе этого две опоры в 3D - одна мачта, м. */
const POLE_MERGE_M = 1.2;

/** Шаг крон ряда полосы, м: знаки полосы стоят по 1-2 м и числа стволов не несут. */
const STRIP_STEP_M = 4.5;

/** Полоса деревьев съёмки - рядом крон по её знакам с шагом взрослой кроны. Знаками-кольцами
 *  на земле в 3D она читалась как непонятные круги. В счёт деревьев ряд не идёт (strip). */
function stripCrowns(strips: readonly Flat[][]): Plant[] {
  const out: Plant[] = [];
  for (const strip of strips) {
    let last: Flat | null = null;
    for (const p of strip) {
      if (last && Math.hypot(p.x - last.x, p.z - last.z) < STRIP_STEP_M) continue;
      last = p;
      const seed = hashOf(`strip:${p.x.toFixed(2)}:${p.z.toFixed(2)}`);
      const radius = 2 + (seed % 1000) / 1000;
      out.push({
        id: `strip-${String(out.length)}`,
        x: p.x,
        z: p.z,
        type: 'existing_tree',
        code: 'existing_tree',
        name: 'Полоса деревьев (знак съёмки)',
        species: speciesFallback('existing_tree', 'tree_large', '', radius * 2),
        existing: true,
        existingRadius: radius,
        strip: true,
        seed,
      });
    }
  }
  return out;
}

/** Шаг кустов в ряду кустарниковой полосы, м: кроны около 0,9 м смыкаются в живую изгородь. */
export const STRIP_SHRUB_STEP_M = 0.7;

/** Кустарниковая полоса съёмки - ряд кустов по её оси. Брусом с фактурой листвы она читалась
 *  плоской стенкой (пользователь, 19.10.2026: «кусты еще 2д»). Кусты - условные, в счёт
 *  насаждений не идут (strip), как кроны полосы деревьев. */
function stripShrubs(
  strips: readonly Line[],
  bounds: readonly [number, number, number, number],
): Plant[] {
  const [minX, minZ, maxX, maxZ] = bounds;
  const out: Plant[] = [];
  for (const strip of strips) {
    let carry = 0;
    for (let i = 0; i + 1 < strip.points.length; i++) {
      const a = strip.points[i] as Flat;
      const b = strip.points[i + 1] as Flat;
      const len = Math.hypot(b.x - a.x, b.z - a.z);
      if (len < 1e-9) continue;
      let u = carry;
      for (; u <= len; u += STRIP_SHRUB_STEP_M) {
        const x = a.x + ((b.x - a.x) * u) / len;
        const z = a.z + ((b.z - a.z) * u) / len;
        if (x < minX || x > maxX || z < minZ || z > maxZ) continue;
        const seed = hashOf(`hedge:${x.toFixed(2)}:${z.toFixed(2)}`);
        const radius = 0.42 + ((seed % 1000) / 1000) * 0.12;
        out.push({
          id: `hedge-${String(out.length)}`,
          x,
          z,
          type: 'existing_shrub',
          code: 'existing_shrub',
          name: 'Кустарниковая полоса (знак съёмки)',
          species: speciesFallback('existing_shrub', 'shrub_tall', '', radius * 2),
          existing: true,
          existingRadius: radius,
          strip: true,
          seed,
        });
      }
      carry = u - len;
    }
  }
  return out;
}

function existingPlants(features: readonly BasemapFeature[], box: Box, frame: Frame): Plant[] {
  const marks: ExistingPlant[] = [];
  for (const feature of features) {
    const found = plantsOf(feature);
    if (found) marks.push(...found.filter((p) => inBox([[p.x, p.y]], box)));
  }
  const out: Plant[] = [];
  for (const p of mergePlants(marks)) {
    const code = p.shrub ? 'existing_shrub' : 'existing_tree';
    const seed = hashOf(`${p.x.toFixed(2)}:${p.y.toFixed(2)}`);
    const crown = p.r * 2;
    out.push({
      id: `existing-${out.length}`,
      ...frame.toFlat(p.x, p.y),
      type: code,
      code,
      name: p.shrub ? 'Существующий кустарник' : 'Существующее дерево',
      species: speciesFallback(code, p.shrub ? 'shrub_tall' : 'tree_large', '', crown),
      existing: true,
      existingRadius: p.r,
      seed,
    });
  }
  return out;
}

function sceneBuildings(scene: SceneJson, box: Box, frame: Frame): Building[] {
  const out: Building[] = [];
  for (const b of scene.buildings) {
    const outer = b.rings[0];
    if (!outer || outer.length < 3 || !inBox(outer, box) || b.height_m <= 0) continue;
    const first = outer[0] ?? [0, 0];
    out.push({
      // Контур без дрожания съёмки: стена дома идёт ровно, а не изломами.
      rings: b.rings.map((ring) => simplifyRing(flatRing(ring, frame))),
      height: b.height_m,
      floors: b.floors ?? Math.max(1, Math.round(b.height_m / STOREY_M)),
      source: b.floors_source,
      kind: b.kind,
      wall: b.wall,
      use: b.use,
      seed: hashOf(`${first[0].toFixed(1)}:${first[1].toFixed(1)}`),
    });
  }
  return out;
}

/** Здания без scene.json: только замкнутые контуры подосновы, этажность по площади. */
function basemapBuildings(features: readonly BasemapFeature[], box: Box, frame: Frame): Building[] {
  const out: Building[] = [];
  for (const feature of features) {
    if (feature.properties.class !== 'building') continue;
    for (const polygon of polygons(feature.geometry)) {
      const outer = polygon[0];
      if (!outer || outer.length < 4 || !inBox(outer, box)) continue;
      const area = Math.abs(signedArea(outer));
      if (area < 4) continue;
      const floors = floorsByArea(area);
      const first = outer[0] ?? [0, 0];
      out.push({
        rings: polygon.map((ring) => simplifyRing(flatRing(ring, frame))),
        height: heightOf(floors),
        floors,
        source: 'assumed',
        kind: 'building',
        wall: null,
        use: null,
        seed: hashOf(`${first[0].toFixed(1)}:${first[1].toFixed(1)}`),
      });
    }
  }
  return out;
}

interface PlantPoint {
  id: string;
  number?: number;
  x: number;
  y: number;
  type: string;
  code: string;
  species: SceneSpeciesJson;
}

function planPoints(scene: SceneJson | null, plan: PlanJson | null): PlantPoint[] {
  if (scene) {
    return scene.plants.map((p) => ({
      ...p,
      species:
        scene.species[p.code] ??
        speciesFallback(p.code, isShrubType(p.type) ? 'shrub_medium' : 'tree_medium', p.code),
    }));
  }
  return (plan?.placements ?? []).map((p) => {
    const code = p.species?.code ?? (isShrubType(p.planting_type) ? 'shrub' : 'tree');
    const lifeForm =
      p.species?.life_form ?? (isShrubType(p.planting_type) ? 'shrub_medium' : 'tree_medium');
    return {
      id: p.id,
      number: p.number,
      x: p.x,
      y: p.y,
      type: p.planting_type,
      code,
      species: speciesFallback(
        code,
        lifeForm,
        p.species?.name_ru ?? code,
        p.species?.crown_diameter_m,
      ),
    };
  });
}

function extentOf(scene: SceneJson | null, points: PlantPoint[], basemap: BasemapJson | null): Box {
  if (scene && scene.extent[2] > scene.extent[0]) return scene.extent;
  if (points.length) {
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    return [
      Math.min(...xs) - MARGIN_M,
      Math.min(...ys) - MARGIN_M,
      Math.max(...xs) + MARGIN_M,
      Math.max(...ys) + MARGIN_M,
    ];
  }
  return basemap?.bbox ?? [0, 0, 0, 0];
}

export interface WorldInput {
  scene: SceneJson | null;
  plan: PlanJson | null;
  basemap: BasemapJson | null;
}

export function buildWorld({ scene, plan, basemap }: WorldInput): World {
  const points = planPoints(scene, plan);
  const box = extentOf(scene, points, basemap);
  const origin: [number, number] = points.length
    ? [median(points.map((p) => p.x)), median(points.map((p) => p.y))]
    : [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
  const frame = frameAt(origin);
  const plants: Plant[] = points.map((p) => ({
    id: p.id,
    number: p.number,
    ...frame.toFlat(p.x, p.y),
    type: p.type,
    code: p.code,
    name: p.species.name_ru || p.code,
    species: p.species,
    existing: false,
    seed: hashOf(p.id),
  }));
  const linework: Linework = {
    utilities: new Map(),
    boundary: [],
    treeStrips: [],
    shrubStrips: [],
    curbs: [],
    fences: [],
    poles: [],
    lawns: [],
    sidewalks: [],
    roads: [],
  };
  const features = basemap ? distinctFeatures(basemap.features) : [];
  const poleParts: Geometry[] = [];
  for (const feature of features) takeFeature(feature, box, frame, linework, poleParts);
  for (const [x, y] of poleSites(poleParts)) {
    if (!inBox([[x, y]], box)) continue;
    const site = frame.toFlat(x, y);
    // Опора и её подкос или повторный знак съёмки в метре друг от друга - одна мачта в 3D:
    // соседние опоры освещения стоят минимум в десятке метров.
    if (linework.poles.some((q) => Math.hypot(q.x - site.x, q.z - site.z) < POLE_MERGE_M)) continue;
    linework.poles.push(site);
  }
  // Оси оград от сервиса - одна линия на ограду вместо двух линий знака и штрихов.
  const axes = basemap?.fence_axes;
  if (axes?.length) {
    linework.fences = axes
      .filter((line) => line.length > 1 && inBox(line, box))
      .map((line) => ({ points: line.map(([x, y]) => frame.toFlat(x, y)) }));
  }
  plants.push(...existingPlants(features, box, frame));
  plants.push(...stripCrowns(linework.treeStrips));
  const buildings = scene
    ? sceneBuildings(scene, box, frame)
    : basemapBuildings(features, box, frame);
  const floorsBy: Record<FloorsSource, number> = { label: 0, neighbor: 0, letter: 0, assumed: 0 };
  for (const b of buildings) if (b.kind === 'building') floorsBy[b.source] += 1;
  const a = frame.toFlat(box[0], box[3]);
  const b = frame.toFlat(box[2], box[1]);
  plants.push(...stripShrubs(linework.shrubStrips, [a.x, a.z, b.x, b.z]));
  const flowerbeds = (plan?.lawns ?? [])
    .filter((lawn) => lawn.kind === 'flowerbed')
    .flatMap((lawn) => polygons(lawn.geometry))
    .filter((polygon) => (polygon[0]?.length ?? 0) > 3)
    .map((polygon) => polygon.map((ring) => flatRing(ring, frame)));
  return {
    origin,
    bounds: [a.x, a.z, b.x, b.z],
    flowerbeds,
    fenceAxes: !!axes?.length,
    buildings,
    plants,
    ...linework,
    utilities: [...linework.utilities].map(([kind, list]) => ({ kind, lines: list })),
    floorsBy,
    fallback: !scene,
  };
}
