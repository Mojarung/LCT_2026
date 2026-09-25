/* Стили классов подосновы и цвета из CSS-переменных. Цвета не хардкодятся: тема
 * переключается в одном месте, и карта обязана следовать за ней. */

export interface ClassStyle {
  group: 'surfaces' | 'buildings' | 'utilities' | 'existing' | 'lawns';
  fill?: string;
  stroke?: string;
  /** Толщина в экранных пикселях. */
  width: number;
  dash?: number[];
  /** Фактура заливки поверх цвета (paper.ts): трава газона, штриховка здания. */
  texture?: 'grass' | 'hatch';
  /** Тень вниз-вправо, как у зданий на слайдах: план читается объёмным, а не схемой. */
  shadow?: boolean;
}

export const STYLES: Record<string, ClassStyle> = {
  lawn: { group: 'surfaces', fill: '--c-lawn', width: 0, texture: 'grass' },
  building: {
    group: 'buildings',
    fill: '--c-building-fill',
    stroke: '--c-building',
    width: 1.3,
    texture: 'hatch',
    shadow: true,
  },
  structure: { group: 'buildings', stroke: '--c-building', width: 1 },
  road: { group: 'surfaces', stroke: '--c-road', width: 1 },
  sidewalk: { group: 'surfaces', stroke: '--c-pavement', width: 1 },
  pavement_edge: { group: 'surfaces', stroke: '--c-pavement', width: 1 },
  curb: { group: 'surfaces', stroke: '--c-curb', width: 2 },
  tram: { group: 'surfaces', stroke: '--c-road', width: 1.2 },
  railway: { group: 'surfaces', stroke: '--c-road', width: 1.2 },
  slope: { group: 'surfaces', stroke: '--c-slope', width: 1 },
  fence: { group: 'surfaces', stroke: '--c-fence', width: 1, dash: [4, 3] },
  work_boundary: { group: 'surfaces', stroke: '--c-boundary', width: 1.6, dash: [8, 4] },
  'utility.water': { group: 'utilities', stroke: '--c-water', width: 1.3 },
  'utility.sewer': { group: 'utilities', stroke: '--c-sewer', width: 1.3 },
  'utility.storm': { group: 'utilities', stroke: '--c-storm', width: 1.3 },
  'utility.drain': { group: 'utilities', stroke: '--c-storm', width: 1.1 },
  'utility.heat': { group: 'utilities', stroke: '--c-heat', width: 1.3 },
  'utility.gas': { group: 'utilities', stroke: '--c-gas', width: 1.3 },
  'utility.power_cable': { group: 'utilities', stroke: '--c-power', width: 1.3 },
  'utility.telecom': { group: 'utilities', stroke: '--c-telecom', width: 1.3 },
  'utility.unknown': { group: 'utilities', stroke: '--c-utility', width: 1 },
  'utility.access': { group: 'utilities', stroke: '--c-utility', width: 1 },
  power_line_overhead: { group: 'utilities', stroke: '--c-overhead', width: 1.4, dash: [10, 4] },
  pole: { group: 'utilities', stroke: '--c-pole', width: 2 },
  existing_tree: { group: 'existing', stroke: '--c-existing', width: 1.2 },
  existing_shrub: { group: 'existing', stroke: '--c-existing', width: 1 },
  // Газоны плана (lawns.ts): тон поверх травы карты покрытий и контур; устраиваемый газон -
  // своим тоном и пунктиром, как граница работ, которых ещё нет.
  'plan_lawn.kept': {
    group: 'lawns',
    fill: '--c-plan-lawn',
    stroke: '--c-plan-lawn-edge',
    width: 1,
  },
  'plan_lawn.new': {
    group: 'lawns',
    fill: '--c-plan-lawn-new',
    stroke: '--c-plan-lawn-edge',
    width: 1.2,
    dash: [5, 3],
  },
};

export const VERDICT_TOKEN: Record<string, string> = {
  allowed: '--ok',
  needs_approval: '--warn',
  rejected: '--bad',
  forbidden: '--bad',
};

/** Цвет из CSS-переменной с кэшем: getComputedStyle в цикле отрисовки - это пересчёт стилей
 *  на каждый кусок геометрии. Кэш сбрасывается при смене темы. */
export class Palette {
  private readonly cache = new Map<string, string>();

  constructor(private readonly root: HTMLElement = document.documentElement) {}

  get(token: string): string {
    let value = this.cache.get(token);
    if (value === undefined) {
      value = getComputedStyle(this.root).getPropertyValue(token).trim() || '#888';
      this.cache.set(token, value);
    }
    return value;
  }

  clear(): void {
    this.cache.clear();
  }
}
