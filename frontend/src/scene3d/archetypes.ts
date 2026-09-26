/* Архетипы крон для 3D-вида: какой процедурной моделью ez-tree рисуется вид.
 *
 * Модель на каждый из 55 видов генерировать незачем: у видов одной формы одинаковый рисунок
 * ветвления, а отличает их на снимке размер, пропорция кроны и цвет листвы. Поэтому вид
 * получает архетип по форме кроны из базы моделей карты (map/models.ts) с уточнением по роду:
 * берёза и тополь узнаются по силуэту, ель, сосна и туя - по ярусам хвои. Размер и цвет
 * задаются экземпляру, модель общая. */

import { modelOf } from '../map/models';
import type { Season } from './solar';
import type { Plant } from './types';

export type Archetype =
  | 'broadleaf'
  | 'oak'
  | 'ash'
  | 'birch'
  | 'poplar'
  | 'small'
  | 'weeping'
  | 'spruce'
  | 'pine'
  | 'dwarf_conifer'
  | 'thuja'
  | 'shrub'
  | 'shrub_dense'
  | 'creeper';

export const CONIFERS: ReadonlySet<Archetype> = new Set([
  'spruce',
  'pine',
  'dwarf_conifer',
  'thuja',
  'creeper',
]);
export const SHRUBS: ReadonlySet<Archetype> = new Set(['shrub', 'shrub_dense', 'creeper']);

/** Существующее дерево вида не несёт: разброс по породам, которые чаще всего растут на
 *  московских улицах (липа, клён, берёза, тополь, ясень), чтобы старый ряд не был клоном. */
const EXISTING_TREES: readonly Archetype[] = [
  'broadleaf',
  'broadleaf',
  'ash',
  'birch',
  'poplar',
  'oak',
];
const EXISTING_SHRUBS: readonly Archetype[] = ['shrub', 'shrub_dense'];

function byGenus(genus: string, treeForm: boolean): Archetype | null {
  switch (genus) {
    case 'betula':
      return 'birch';
    case 'populus':
      return 'poplar';
    case 'quercus':
      return 'oak';
    case 'fraxinus':
      return 'ash';
    case 'picea':
    case 'abies':
    case 'pseudotsuga':
    case 'larix':
      return treeForm ? 'spruce' : 'dwarf_conifer';
    case 'pinus':
      return treeForm ? 'pine' : 'dwarf_conifer';
    case 'thuja':
      return 'thuja';
    default:
      return null;
  }
}

export function archetypeOf(plant: Plant): Archetype {
  if (plant.existing) {
    const pool = plant.type === 'existing_shrub' ? EXISTING_SHRUBS : EXISTING_TREES;
    return pool[plant.seed % pool.length] ?? 'broadleaf';
  }
  const species = plant.species;
  const treeForm = species.life_form.startsWith('tree');
  const genus = (species.genus || plant.code.split('_')[0] || '').toLowerCase();
  const form = modelOf(plant.code, plant.type).form;
  if (form === 'creeper') return 'creeper';
  if (form === 'shrub') return plant.seed % 3 === 0 ? 'shrub_dense' : 'shrub';
  const known = byGenus(genus, treeForm && form !== 'dwarf_conifer');
  if (known) return known;
  switch (form) {
    case 'rounded':
      return 'small';
    case 'columnar':
      return 'poplar';
    case 'weeping':
      return 'weeping';
    case 'conifer':
      return 'spruce';
    case 'dwarf_conifer':
      return 'dwarf_conifer';
    default:
      return species.life_form === 'tree_small' ? 'small' : 'broadleaf';
  }
}

/** Цвет листвы в сезон. Тон базы моделей подобран под бумажную карту и светлее живой листвы:
 *  в 3D он темнеет и насыщается, иначе крона выглядит выгоревшей на солнце. */
export type { Season };

/** Зимой лиственные деревья и кустарники стоят голыми, хвоя остаётся. */
export function leafless(archetype: Archetype, season: Season): boolean {
  return season === 'winter' && !CONIFERS.has(archetype);
}

/** Осенняя окраска по роду: клёны краснеют, липы и берёзы желтеют, дуб буреет. */
const AUTUMN: Record<string, string> = {
  acer: '#c8541f',
  betula: '#d8b43a',
  tilia: '#d2a92f',
  populus: '#cfb23c',
  ulmus: '#c9a23a',
  fraxinus: '#b8a23c',
  quercus: '#9c6428',
  larix: '#d7a336',
  sorbus: '#b8392a',
  crataegus: '#b0442c',
  prunus: '#a8352e',
  malus: '#c07a2c',
  cotoneaster: '#a2302a',
  euonymus: '#c2385a',
  cornus: '#9a2f3a',
  physocarpus: '#b8712e',
  aesculus: '#b4822e',
  salix: '#c6b44a',
};
const AUTUMN_DEFAULT = '#bf9a38';

export interface Rgb {
  r: number;
  g: number;
  b: number;
}

export function hexRgb(hex: string): Rgb {
  const v = Number.parseInt(hex.replace('#', ''), 16);
  return { r: ((v >> 16) & 255) / 255, g: ((v >> 8) & 255) / 255, b: (v & 255) / 255 };
}

function mix(a: Rgb, b: Rgb, t: number): Rgb {
  return { r: a.r + (b.r - a.r) * t, g: a.g + (b.g - a.g) * t, b: a.b + (b.b - a.b) * t };
}

/** Живой тон из бумажного: насыщенность вверх, светлота вниз, в пространстве HSL. */
export function liveTone(rgb: Rgb, darken = 0.62): Rgb {
  const max = Math.max(rgb.r, rgb.g, rgb.b);
  const min = Math.min(rgb.r, rgb.g, rgb.b);
  const l = (max + min) / 2;
  const d = max - min;
  const s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
  let h = 0;
  if (d !== 0) {
    if (max === rgb.r) h = ((rgb.g - rgb.b) / d) % 6;
    else if (max === rgb.g) h = (rgb.b - rgb.r) / d + 2;
    else h = (rgb.r - rgb.g) / d + 4;
  }
  return hsl(h * 60, Math.min(1, s * 1.25 + 0.08), l * darken);
}

function hsl(h: number, s: number, l: number): Rgb {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((((h / 60) % 2) + 2) % 2) - 1));
  const m = l - c / 2;
  const sector = Math.floor((((h % 360) + 360) % 360) / 60);
  const table: [number, number, number][] = [
    [c, x, 0],
    [x, c, 0],
    [0, c, x],
    [0, x, c],
    [x, 0, c],
    [c, 0, x],
  ];
  const [r, g, b] = table[sector] ?? [c, x, 0];
  return { r: r + m, g: g + m, b: b + m };
}

/** Тон зелёный, если оттенок между жёлто-зелёным и сине-зелёным. */
export function isGreen(rgb: Rgb): boolean {
  const max = Math.max(rgb.r, rgb.g, rgb.b);
  const min = Math.min(rgb.r, rgb.g, rgb.b);
  if (max - min < 0.04) return false;
  return (
    max === rgb.g || (max === rgb.b && rgb.g > rgb.r) || (max === rgb.r && rgb.g > rgb.r * 0.92)
  );
}

/** Летняя листва и цвет цветения по модели карты. У цветущего кустарника без поля bloom
 *  тон модели - это цвет цветка (сирень, жимолость: на плане куст рисуется цветом цветения),
 *  листва у него обычная зелёная. Винный тон с полем bloom - настоящая пурпурная листва
 *  (пузыреплодник, черёмуха виргинская): её оставляем. */
export function foliageOf(
  tone: string,
  bloom: string | undefined,
): { leaf: Rgb; flower: Rgb | null } {
  const rgb = hexRgb(tone);
  if (bloom) return { leaf: rgb, flower: hexRgb(bloom) };
  if (isGreen(rgb)) return { leaf: rgb, flower: null };
  return { leaf: hexRgb('#86a86c'), flower: rgb };
}

/** Цвет листвы экземпляра: тон вида, сезон и небольшой разброс, чтобы ряд лип не был
 *  одинаковым - живые деревья отличаются и по оттенку. */
export function foliageColor(plant: Plant, season: Season): Rgb {
  const model = modelOf(plant.code, plant.type);
  const { leaf, flower } = plant.existing
    ? { leaf: hexRgb('#8fae6c'), flower: null }
    : foliageOf(model.tone, model.bloom);
  const base = liveTone(leaf, SHRUBS.has(archetypeOf(plant)) ? 0.62 : 0.58);
  const jitter = ((plant.seed >>> 8) % 1000) / 1000 - 0.5;
  const shade = 1 + jitter * 0.16;
  let color: Rgb = { r: base.r * shade, g: base.g * shade, b: base.b * shade };
  const evergreen =
    plant.species.evergreen || plant.species.conifer || CONIFERS.has(archetypeOf(plant));
  if (season === 'spring') {
    const young = mix(color, { r: 0.5, g: 0.66, b: 0.26 }, evergreen ? 0.08 : 0.3);
    color = flower ? mix(young, liveTone(flower, 0.95), 0.62) : young;
  } else if (season === 'winter') {
    // Зимняя хвоя темнее летней.
    color = { r: color.r * 0.82, g: color.g * 0.86, b: color.b * 0.86 };
  } else if (season === 'autumn' && !evergreen) {
    const genus = (plant.species.genus || plant.code.split('_')[0] || '').toLowerCase();
    const fall = hexRgb(AUTUMN[genus] ?? AUTUMN_DEFAULT);
    color = mix(color, fall, 0.72 + jitter * 0.3);
  }
  return color;
}
