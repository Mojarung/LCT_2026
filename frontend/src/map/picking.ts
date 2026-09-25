/* Видимость, выбор и порядок обхода отметок плана. */

import type { Point } from './geometry';
import type { Layers, MapItem } from './types';
import { toView } from './view';

/** Видна ли отметка: галочка слоя плюс фильтр по видам. Один источник правды для отрисовки,
 *  клика и клавиатуры: спрятанная посадка не находится под курсором и не попадается при
 *  переходе стрелками. */
export function shown(item: MapItem, layers: Layers, speciesOff: ReadonlySet<string>): boolean {
  if (item.kind !== 'placement') {
    return layers.rejections || (layers.barrier && item.barrier_m != null);
  }
  return layers.placements && !speciesOff.has(item.species_code ?? '');
}

/** Ближайшая видимая отметка под точкой: в радиусе кроны или восьми пикселей экрана. */
export function pick(
  world: Point,
  items: readonly MapItem[],
  scale: number,
  layers: Layers,
  speciesOff: ReadonlySet<string>,
): MapItem | null {
  const tolerance = 8 / scale;
  let best: MapItem | null = null;
  let bestDistance = Infinity;
  for (const item of items) {
    if (!shown(item, layers, speciesOff)) continue;
    const distance = Math.hypot(item.x - world.x, item.y - world.y);
    const reach = Math.max(item.radius, tolerance);
    if (distance <= reach && distance < bestDistance) {
      best = item;
      bestDistance = distance;
    }
  }
  return best;
}

/** Слабое место: без посадки индекс качества заметно выше. flagged - порог по размеру плана;
 *  у старых прогонов его нет, тогда - любой минус больше половины сотой промилле. */
export function isWeak(item: MapItem): boolean {
  if (item.kind !== 'placement' || !item.value) return false;
  if (typeof item.value.flagged === 'boolean') return item.value.flagged;
  return item.value.delta * 1000 <= -0.005;
}

/** Порядок обхода с клавиатуры - вдоль улицы, как читают чертёж. */
export function orderItems(items: readonly MapItem[], rot: number): MapItem[] {
  return [...items].sort((a, b) => toView({ rot }, a.x, a.y).u - toView({ rot }, b.x, b.y).u);
}
