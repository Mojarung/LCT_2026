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
import { plantsOf } from '../map/existing';
import { isShrubType } from '../map/models';
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

/** Центр знака: у точки - она сама, у кружка опоры - середина габарита. Среднее вершин
 *  врёт: замыкающая точка контура совпадает с первой и тянет центр к ней. */
function centerOf(geometry: Geometry): Position | null {
  if (geometry.type === 'Point') return geometry.coordinates;
  const all = lines(geometry).flat();
  if (!all.length) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of all) {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }
  return [(minX + maxX) / 2, (minY + maxY) / 2];
}

interface Linework {
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

function takeFeature(feature: BasemapFeature, box: Box, frame: Frame, into: Linework): void {
  const kind = feature.properties.class;
  const geometry = feature.geometry;
  if (kind === 'pole') {
    const center = centerOf(geometry);
    if (center && inBox([center], box)) into.poles.push(frame.toFlat(center[0], center[1]));
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

function existingPlants(basemap: BasemapJson, box: Box, frame: Frame): Plant[] {
  const out: Plant[] = [];
  for (const feature of basemap.features) {
    const found = plantsOf(feature);
    if (!found) continue;
    for (const p of found) {
      if (!inBox([[p.x, p.y]], box)) continue;
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
      rings: b.rings.map((ring) => flatRing(ring, frame)),
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
function basemapBuildings(basemap: BasemapJson, box: Box, frame: Frame): Building[] {
  const out: Building[] = [];
  for (const feature of basemap.features) {
    if (feature.properties.class !== 'building') continue;
    for (const polygon of polygons(feature.geometry)) {
      const outer = polygon[0];
      if (!outer || outer.length < 4 || !inBox(outer, box)) continue;
      const area = Math.abs(signedArea(outer));
      if (area < 4) continue;
      const floors = floorsByArea(area);
      const first = outer[0] ?? [0, 0];
      out.push({
        rings: polygon.map((ring) => flatRing(ring, frame)),
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
    curbs: [],
    fences: [],
    poles: [],
    lawns: [],
    sidewalks: [],
    roads: [],
  };
  if (basemap) {
    for (const feature of basemap.features) takeFeature(feature, box, frame, linework);
    plants.push(...existingPlants(basemap, box, frame));
  }
  const buildings = scene
    ? sceneBuildings(scene, box, frame)
    : basemap
      ? basemapBuildings(basemap, box, frame)
      : [];
  const floorsBy: Record<FloorsSource, number> = { label: 0, neighbor: 0, letter: 0, assumed: 0 };
  for (const b of buildings) if (b.kind === 'building') floorsBy[b.source] += 1;
  const a = frame.toFlat(box[0], box[3]);
  const b = frame.toFlat(box[2], box[1]);
  return {
    origin,
    bounds: [a.x, a.z, b.x, b.z],
    buildings,
    plants,
    ...linework,
    floorsBy,
    fallback: !scene,
  };
}
