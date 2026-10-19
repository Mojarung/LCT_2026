/* Данные 3D-вида. scene.json пишет src/green/infrastructure/reports/artifacts.py (_scene):
 * здания с этажностью по подписям чертежа, посадки точками и параметры видов для объёма
 * кроны. При правке там правится и здесь. Координаты - метры чертежа, Y на север. */

import type { Position } from '../api/artifacts';

export type FloorsSource = 'label' | 'neighbor' | 'letter' | 'assumed';
export type VolumeKind = 'building' | 'porch' | 'container' | 'structure';

export interface BuildingJson {
  /** Первое кольцо - внешний контур против часовой, остальные - дворы по часовой. */
  rings: Position[][];
  height_m: number;
  floors: number | null;
  floors_source: FloorsSource;
  kind: VolumeKind;
  wall: 'brick' | 'metal' | 'mixed' | null;
  use: 'residential' | 'non_residential' | null;
  labels: string[];
}

export interface ScenePlantJson {
  id: string;
  /** Номер посадки, как в plan.json; нет у прогонов, записанных до 29.09.2026. */
  number?: number;
  x: number;
  y: number;
  type: string;
  code: string;
  structure: string | null;
}

export interface SceneSpeciesJson {
  name_ru: string;
  name_lat: string;
  life_form: string;
  height_m: number;
  crown_diameter_m: number;
  crown_mature_m: number;
  evergreen: boolean;
  conifer: boolean;
  growth: string;
  genus: string;
  family: string;
}

export interface SceneJson {
  version: number;
  extent: [number, number, number, number];
  counts: Record<string, number>;
  buildings: BuildingJson[];
  plants: ScenePlantJson[];
  species: Record<string, SceneSpeciesJson>;
}

/** Точка сцены: x - на восток, z - на юг (три.js смотрит вдоль -z), метры от начала сцены. */
export interface Flat {
  x: number;
  z: number;
}

export type Ring = Flat[];

export interface Building {
  rings: Ring[];
  height: number;
  floors: number;
  source: FloorsSource;
  kind: VolumeKind;
  wall: BuildingJson['wall'];
  use: BuildingJson['use'];
  /** Устойчивое к порядку число для разброса цвета фасада. */
  seed: number;
}

export interface Plant {
  id: string;
  /** Номер посадки в плане; у существующих насаждений и старых прогонов нет. */
  number?: number;
  x: number;
  z: number;
  /** tree | shrub | hedge | existing_tree | existing_shrub */
  type: string;
  code: string;
  name: string;
  species: SceneSpeciesJson;
  existing: boolean;
  /** Радиус кроны с подосновы у существующих: знак съёмки не несёт высоты. */
  existingRadius?: number;
  /** Крона ряда «полосы деревьев» съёмки: рисуется, но в счёт стволов не идёт. */
  strip?: boolean;
  seed: number;
}

export interface Line {
  points: Flat[];
  /** Отметка верха бруса в каждой точке (борт с понижением); без неё верх ровный. */
  tops?: number[];
}

/** Всё, что видно в 3D, в координатах сцены. */
export interface World {
  /** Условные знаки полос: не модели деревьев и не места подтверждённых стволов. */
  treeStrips?: Flat[][];
  /** Recognised shrub-strip axes; dimensions of the 3D band are illustrative. */
  shrubStrips?: Line[];
  /** Начало сцены в координатах чертежа. */
  origin: [number, number];
  /** Прямоугольник сцены: minX, minZ, maxX, maxZ. */
  bounds: [number, number, number, number];
  buildings: Building[];
  plants: Plant[];
  curbs: Line[];
  /** Подземные сети и воздушные линии подосновы по классу (utility.*), для рабочего слоя. */
  utilities?: { kind: string; lines: Line[] }[];
  /** Граница работ. */
  boundary?: Line[];
  fences: Line[];
  /** Ограды - оси из выгрузки (basemap.fence_axes): склейка и снятие двойных не нужны. */
  fenceAxes?: boolean;
  poles: Flat[];
  lawns: Ring[][];
  sidewalks: Ring[][];
  roads: Ring[][];
  /** Скамейки, нарисованные в съёмке (МАФ 1,9 x 0,6 м): центр и угол, ось x модели вдоль. */
  benches?: { x: number; z: number; angle: number }[];
  /** Подписи площадок съёмки («ДЕТ.ПЛ.», «СПОРТ ПЛ.») в координатах сцены. */
  groundLabels?: { x: number; z: number; kind: 'kids' | 'sports' }[];
  /** Цветники плана (GREEN_FLOWERBED): земля с многолетниками. */
  flowerbeds?: Ring[][];
  /** Навесы: замкнутый пунктир на слое зданий в стороне от стен (canopies.ts). */
  canopies?: Ring[];
  /** Откуда взята этажность: число зданий по каждому источнику. */
  floorsBy: Record<FloorsSource, number>;
  /** scene.json не нашёлся: здания только замкнутые, по площади, виды - по жизненной форме. */
  fallback: boolean;
}
