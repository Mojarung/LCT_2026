/* Существующие насаждения с подосновы -> отметки для моделей. Съёмка даёт дерево то точкой
 * условного знака, то кружком кроны, то рядом кружков «Полосы деревьев». Карта рисует их одной
 * приглушённой моделью: точку - кроной по умолчанию, кружок - кроной его размера. Контур
 * крупнее MAX_CROWN_M - уже не одна крона, а массив насаждений: он остаётся линией подосновы. */

import type { BasemapFeature, Geometry } from '../api/artifacts';
import { type Box, measure } from './geometry';

export interface ExistingPlant {
  x: number;
  y: number;
  /** Радиус кроны, метры. */
  r: number;
  shrub: boolean;
}

/** Крона существующего дерева по умолчанию: знак съёмки размера кроны не несёт. */
const TREE_R = 2.5;
const SHRUB_R = 0.8;
/** Больше этого поперёк - массив, а не одна крона. */
const MAX_CROWN_M = 16;

export const EXISTING_CLASSES: ReadonlySet<string> = new Set(['existing_tree', 'existing_shrub']);

/** Отметки существующих насаждений объекта или null, если объект - не одиночная крона. */
export function plantsOf(feature: BasemapFeature): ExistingPlant[] | null {
  const kind = feature.properties.class;
  if (!EXISTING_CLASSES.has(kind)) return null;
  const shrub = kind === 'existing_shrub';
  const fallback = shrub ? SHRUB_R : TREE_R;
  return collect(feature.geometry, fallback, shrub);
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
