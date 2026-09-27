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

/** Радиус попадания в ствол, CSS-пиксели: уверенный клик мышью и касание пальцем. */
export const TRUNK_PICK_PX = 10;
/** Больше стольких посадок список выбора не показывает: ближайшие стволы идут первыми. */
export const MAX_CANDIDATES = 8;

/** Видимые отметки, чей ствол (центр) не дальше TRUNK_PICK_PX экрана от точки, ближайшие
 *  первыми. Кроны на плане перекрываются, стволы - нет: выбор по стволу берёт ту посадку,
 *  в которую целились, а не ту, чья крона легла сверху. */
export function candidatesAt(
  world: Point,
  items: readonly MapItem[],
  scale: number,
  layers: Layers,
  speciesOff: ReadonlySet<string>,
): MapItem[] {
  const reach = TRUNK_PICK_PX / scale;
  const found: { item: MapItem; distance: number }[] = [];
  for (const item of items) {
    if (!shown(item, layers, speciesOff)) continue;
    const distance = Math.hypot(item.x - world.x, item.y - world.y);
    if (distance <= reach) found.push({ item, distance });
  }
  found.sort((a, b) => a.distance - b.distance);
  return found.slice(0, MAX_CANDIDATES).map((entry) => entry.item);
}

/** Выбор под точкой: ближайший ствол; если стволов рядом нет - крона, накрывшая точку, чей
 *  ствол ближе. Так на крупном плане по-прежнему можно щёлкнуть в любое место большой кроны. */
export function pick(
  world: Point,
  items: readonly MapItem[],
  scale: number,
  layers: Layers,
  speciesOff: ReadonlySet<string>,
): MapItem | null {
  const [trunk] = candidatesAt(world, items, scale, layers, speciesOff);
  if (trunk) return trunk;
  let best: MapItem | null = null;
  let bestDistance = Infinity;
  for (const item of items) {
    if (!shown(item, layers, speciesOff)) continue;
    const distance = Math.hypot(item.x - world.x, item.y - world.y);
    if (distance <= item.radius && distance < bestDistance) {
      best = item;
      bestDistance = distance;
    }
  }
  return best;
}

/** Кого тащить в режиме правки: выбранную, если её ствол среди попавших под курсор, иначе
 *  ближайший ствол. Посадку, выбранную из списка спорного клика, можно сразу тянуть, даже
 *  если рядом ствол соседки чуть ближе. */
export function preferSelected(
  candidates: readonly MapItem[],
  selected: MapItem | null,
): MapItem | null {
  if (selected && candidates.includes(selected)) return selected;
  return candidates[0] ?? null;
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
