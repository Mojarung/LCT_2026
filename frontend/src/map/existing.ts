/* Существующие насаждения с подосновы -> отметки для моделей. Съёмка даёт дерево то точкой
 * условного знака, то кружком кроны, то рядом кружков «Полосы деревьев». Карта рисует их одной
 * приглушённой моделью: точку - кроной по умолчанию, кружок - кроной его размера. Контур
 * крупнее MAX_CROWN_M - уже не одна крона, а массив насаждений: он остаётся линией подосновы. */

import type { BasemapFeature, Geometry, Position } from '../api/artifacts';
import { type Box, measure } from './geometry';

export interface ExistingPlant {
  x: number;
  y: number;
  /** Радиус кроны, метры. */
  r: number;
  shrub: boolean;
  /** Дерево со знаком хвойного в съёмке: в инженерном стиле - зелёное кольцо. Ключа нет у
   *  лиственных и у деревьев без знака (кружок кроны, полоса деревьев). */
  conifer?: true;
}

/** Крона существующего дерева по умолчанию: знак съёмки размера кроны не несёт. */
const TREE_R = 2.5;
const SHRUB_R = 0.8;
/** Больше этого поперёк - массив, а не одна крона. */
const MAX_CROWN_M = 16;

export const EXISTING_CLASSES: ReadonlySet<string> = new Set(['existing_tree', 'existing_shrub']);

/** Старые артефакты не сохраняли TREE_STRIP. Их MultiPoint нельзя выдавать за стволы.
 * Явное individual в новых данных позволяет отличить настоящую группу отдельных растений. */
export function stripPoints(feature: BasemapFeature): Position[] | null {
  if (!EXISTING_CLASSES.has(feature.properties.class)) return null;
  const kind = feature.properties.vegetation_kind;
  if (kind === 'individual') return null;
  if (feature.geometry.type === 'MultiPoint') return feature.geometry.coordinates;
  if (kind === 'strip' && feature.geometry.type === 'Point') return [feature.geometry.coordinates];
  if (kind === 'strip') {
    const box: Box = [Infinity, Infinity, -Infinity, -Infinity];
    measure(feature.geometry, box);
    if (Number.isFinite(box[0])) return [[(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]];
  }
  return null;
}

/** Only a recognised linear shrub symbol has an axis. Legacy dots remain ambiguous. */
export function shrubStripLines(feature: BasemapFeature): Position[][] {
  if (
    feature.properties.class !== 'existing_shrub' ||
    feature.properties.vegetation_kind !== 'shrub_strip'
  )
    return [];
  if (feature.geometry.type === 'LineString') return [feature.geometry.coordinates];
  if (feature.geometry.type === 'MultiLineString') return feature.geometry.coordinates;
  return [];
}

/** Illustrative width and height, not dimensions measured from the survey. */
export const SHRUB_STRIP_WIDTH_M = 0.8;
export const SHRUB_STRIP_HEIGHT_M = 0.8;

/** Метки ближе друг к другу - одно растение (как MERGE_M в application/stock.py). */
export const MERGE_M = 1;

/** Склеить отметки одного растения. Съёмка рисует одно дерево несколькими объектами: знаком,
 *  кружком кроны, копией блока. Каждый объект даёт отметку, и в 3D-виде в одной точке встают
 *  два-три ствола разных пород. Одиночная связь при MERGE_M, как на сервере: центр компоненты,
 *  крона - наибольшая из склеенных. Деревья и кусты склеиваются раздельно. */
export function mergePlants(plants: readonly ExistingPlant[]): ExistingPlant[] {
  const parent = plants.map((_, i) => i);
  const root = (i: number): number => {
    let r = i;
    while ((parent[r] ?? r) !== r) r = parent[r] ?? r;
    parent[i] = r;
    return r;
  };
  const cell = (v: number) => Math.floor(v / MERGE_M);
  const grid = new Map<string, number[]>();
  plants.forEach((p, i) => {
    const cx = cell(p.x);
    const cy = cell(p.y);
    for (let dx = -1; dx <= 1; dx++)
      for (let dy = -1; dy <= 1; dy++)
        for (const j of grid.get(`${cx + dx}:${cy + dy}`) ?? []) {
          const q = plants[j];
          if (q && q.shrub === p.shrub && Math.hypot(q.x - p.x, q.y - p.y) <= MERGE_M)
            parent[root(i)] = root(j);
        }
    const key = `${cx}:${cy}`;
    const list = grid.get(key);
    if (list) list.push(i);
    else grid.set(key, [i]);
  });
  const groups = new Map<number, ExistingPlant[]>();
  plants.forEach((p, i) => {
    const r = root(i);
    const list = groups.get(r);
    if (list) list.push(p);
    else groups.set(r, [p]);
  });
  return [...groups.values()].map((group) => {
    const merged: ExistingPlant = {
      x: group.reduce((s, p) => s + p.x, 0) / group.length,
      y: group.reduce((s, p) => s + p.y, 0) / group.length,
      r: Math.max(...group.map((p) => p.r)),
      shrub: group.some((p) => p.shrub),
    };
    if (group.some((p) => p.conifer)) merged.conifer = true;
    return merged;
  });
}

/** Отметки существующих насаждений объекта или null, если объект - не одиночная крона. */
export function plantsOf(feature: BasemapFeature): ExistingPlant[] | null {
  const kind = feature.properties.class;
  if (
    !EXISTING_CLASSES.has(kind) ||
    feature.properties.vegetation_kind === 'strip' ||
    feature.properties.vegetation_kind === 'shrub_strip' ||
    stripPoints(feature)
  )
    return null;
  const shrub = kind === 'existing_shrub';
  const fallback = shrub ? SHRUB_R : TREE_R;
  const plants = collect(feature.geometry, fallback, shrub);
  if (plants && !shrub && feature.properties.conifer === true) {
    for (const plant of plants) plant.conifer = true;
  }
  return plants;
}

function collect(geometry: Geometry, fallback: number, shrub: boolean): ExistingPlant[] | null {
  switch (geometry.type) {
    case 'Point': {
      const [x, y] = geometry.coordinates;
      return [{ x, y, r: fallback, shrub }];
    }
    case 'MultiPoint':
      return geometry.coordinates.map(([x, y]) => ({ x, y, r: fallback, shrub }));
    case 'GeometryCollection': {
      const plants: ExistingPlant[] = [];
      for (const part of geometry.geometries) {
        const found = collect(part, fallback, shrub);
        if (!found) return null;
        plants.push(...found);
      }
      return plants;
    }
    case 'MultiPolygon': {
      const plants: ExistingPlant[] = [];
      for (const coordinates of geometry.coordinates) {
        const found = collect({ type: 'Polygon', coordinates }, fallback, shrub);
        if (!found) return null;
        plants.push(...found);
      }
      return plants;
    }
    default: {
      // Кружок кроны: линия или полигон. Центр и радиус - по габариту.
      const box: Box = [Infinity, Infinity, -Infinity, -Infinity];
      measure(geometry, box);
      if (!Number.isFinite(box[0])) return [];
      const span = Math.max(box[2] - box[0], box[3] - box[1]);
      if (span > MAX_CROWN_M) return null;
      return [
        {
          x: (box[0] + box[2]) / 2,
          y: (box[1] + box[3]) / 2,
          r: Math.max(span / 2, shrub ? 0.4 : 1),
          shrub,
        },
      ];
    }
  }
}
