/* Размер растения в заданный год после посадки: высота и диаметр кроны.
 *
 * Каталог знает три точки: крону через 10 лет (crown_diameter_m - по ней нарисован знак на
 * плане), взрослую высоту и взрослую крону. Посадочный материал - типовой крупномер для
 * улицы: дерево 3-4 м с кроной 1,5-2 м, куст 0,6-0,8 м. Между точками рост идёт с насыщением
 * 1 - exp(-t / tau), tau зависит от скорости роста вида. Это приближение для картинки, а не
 * лесотаксация: в 10 лет размер кроны совпадает с условным знаком плана, дальше растёт к
 * взрослому. */

import type { SceneSpeciesJson } from './types';

export interface Size {
  /** Высота до верха кроны, метры. */
  height: number;
  /** Диаметр кроны, метры. */
  crown: number;
}

/** Постоянная роста, лет: за tau вид проходит 63% пути от посадки до взрослого размера. */
const TAU: Record<string, number> = { fast: 12, medium: 18, slow: 28 };
/** Год, на который каталог даёт диаметр кроны (условный знак плана). */
export const PLAN_YEAR = 10;

const TREE_FORMS = new Set(['tree_large', 'tree_medium', 'tree_small']);

export function isTreeForm(lifeForm: string): boolean {
  return TREE_FORMS.has(lifeForm);
}

/** Посадочный материал: высота и крона в год посадки. */
export function plantingStock(species: SceneSpeciesJson): Size {
  const mature = species.height_m || 1;
  if (isTreeForm(species.life_form)) {
    const height = species.conifer ? 2.5 : species.life_form === 'tree_small' ? 3 : 4;
    return { height: Math.min(height, mature), crown: species.conifer ? 1.2 : 1.8 };
  }
  return { height: Math.min(0.7, mature), crown: Math.min(0.6, species.crown_diameter_m || 0.6) };
}

function saturation(years: number, tau: number): number {
  return 1 - Math.exp(-Math.max(0, years) / tau);
}

export function sizeAt(species: SceneSpeciesJson, years: number): Size {
  const tau = TAU[species.growth] ?? TAU.medium ?? 18;
  const stock = plantingStock(species);
  const matureHeight = Math.max(species.height_m, stock.height);
  const crownPlan = Math.max(species.crown_diameter_m, stock.crown);
  const matureCrown = Math.max(species.crown_mature_m, crownPlan);
  const height = stock.height + (matureHeight - stock.height) * saturation(years, tau);
  // До года плана крона идёт от посадочной к знаку плана по той же кривой, что и высота,
  // нормированной на год плана; после - к взрослой.
  const crown =
    years <= PLAN_YEAR
      ? stock.crown +
        (crownPlan - stock.crown) * (saturation(years, tau) / saturation(PLAN_YEAR, tau))
      : crownPlan + (matureCrown - crownPlan) * saturation(years - PLAN_YEAR, tau);
  return { height, crown };
}

/** Существующее дерево: по съёмке известна только крона, высота - по типичному отношению
 *  высоты к кроне у городских лиственных (около 2), с разбросом, чтобы ряд не был одинаковым. */
export function existingSize(radius: number, shrub: boolean, seed: number): Size {
  const crown = Math.max(radius * 2, shrub ? 0.8 : 3);
  const spread = 0.85 + ((seed % 1000) / 1000) * 0.3;
  if (shrub) return { height: Math.min(3, crown * 0.9) * spread, crown };
  const base = crown < 5.5 ? 13 : crown * 2.1;
  return { height: Math.min(26, base * spread), crown: crown * 1.25 };
}
