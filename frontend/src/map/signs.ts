/* Условные знаки инженерного стиля карты: как на дендроплане и разбивочно-посадочном чертеже
 * проектировщиков пилота.
 *
 * Вид посадки - знаком своей строки из «Шаблонов значков» заказчика (templateSigns.ts): у липы
 * свой знак, у клёна свой, у спиреи свой. Дерево - знаком по взрослой кроне вида и ямой в
 * центре, куст - знаком размера знака куста. Вид, которого в шаблоне нет (ясень, маакия,
 * скумпия), и все посадки, пока файл знаков не пришёл, - общими знаками ниже. Существующие
 * насаждения - знаками раздела «существующие» того же шаблона.
 *
 * Общие знаки - из файлов организаторов (дендропланы и РПЧ пяти бюро; docs/notes/40):
 *
 * - new_tree_pit - место посадки дерева: Грузинская, РПЧ, блок «Дерево_Л_Пр», слой
 *   ГП_посадочный - залитый чёрный круг r 0,42 м. Тот же знак у Старого Гая, Камчатской,
 *   Харьковского («пм», r 0,49) и Берзарина («Посадочная яма дерева»);
 * - new_tree_crown_outline - контур кроны: там же, слой ГП_зелень_ОПС, окружность по диаметру
 *   кроны вида, 0,4 мм, #007f00. Хвойность на плане проектировщики не показывают (крест у
 *   «Дерево_Х_Пр» лежит на Defpoints), у нас хвойное - тёмным контуром с засечками, как
 *   звёздчатая крона генплана;
 * - new_shrub_single - кустарник: слой «_кусты», круг r 0,40 м, 0,3 мм, штриховка ANSI31 45°;
 * - new_hedge - живая изгородь: блок «ЖИ_Пр», полоса 0,83 м со скруглёнными концами и
 *   штриховкой 45°;
 * - existing_tree_keep - дерево сохраняемое: Камчатская_ДИ, блок «дерево» (*U27, «сохр.»):
 *   белый круг, кольца r 0,649 м (0,35 мм) и r 0,739 м (0,3 мм). В шаблоне - «Дерево_Л_С»;
 * - existing_tree_conifer_keep - хвойное сохраняемое (*U25): плюс кольцо r 0,775 м, 0,7 мм,
 *   ACI 3 (#00ff00, на экране - читаемый зелёный);
 * - existing_shrub_keep - кустарник сохраняемый (_k1, *U28): зубчатый кружок d 1,1 м.
 *
 * Знаки внемасштабные: размер на местности постоянный, а на общем виде - не мельче
 * нескольких пикселей, иначе план вырождается в пустой лист. Рисуются пачкой (один Path2D на
 * цвет), а не спрайтами: кругов тысячи, а заливка одного пути дешевле тысячи drawImage. Цвета -
 * из токенов --sign-* (tokens.css): в тёмной теме чернила светлые, как в модели CAD. */

import type { Position } from '../api/artifacts';
import { type ExistingPlant, SHRUB_STRIP_WIDTH_M } from './existing';
import type { Box } from './geometry';
import { type Form, isShrubType, MODELS } from './models';
import type { Palette } from './palette';
import { pinToScreen } from './paper';
import { stamp } from './sprites';
import {
  EXISTING_SIGNS,
  paintSign,
  signColor,
  signSprite,
  speciesSign,
  type TemplateSign,
  templateSignOf,
  TONE_PX,
} from './templateSigns';
import type { MapItem, ViewState } from './types';
import { toScreen } from './view';

/** Посадочная яма дерева, радиус на местности, метры. */
export const PIT_R_M = 0.42;
/** Одиночный кустарник. */
export const SHRUB_R_M = 0.4;
/** Ширина полосы живой изгороди. */
export const HEDGE_W_M = 0.83;
/** Кольца существующего дерева: внутреннее и наружное. */
export const RING_INNER_M = 0.649;
export const RING_OUTER_M = 0.7394;
/** Толщина зелёного кольца хвойного: 0,7 мм листа 1:500. */
const CONIFER_RING_W_M = 0.35;
/** Зубчатый кружок существующего кустарника. */
export const SHRUB_KEEP_R_M = 0.55;

/* Нижние пределы знаков на экране, пиксели CSS. */
export const PIT_MIN_PX = 1.7;
const PIT_LIFT_PX = 3.4;
const SHRUB_MIN_PX = 2.4;
const FAR_SHRUB_PX = 1.2;
const HEDGE_MIN_PX = 3;
/** Полоса изгороди уже этого - на общем виде: тонкая линия ряда без заливки и штриховки.
 *  Иначе две тысячи кустов вдоль бортов Куликовской заливали общий вид чёрным. */
const THIN_STRIP_PX = 2.5;
const RING_MIN_PX = 3;
const RING_FAR_PX = 2.3;
const SCALLOP_MIN_PX = 3;
/** Контур кроны рисуется, когда он заметно шире ямы: иначе на общем виде он сливается с ней. */
const CROWN_GAP_PX = 2.5;
/** Засечки хвойной кроны - с этого радиуса кроны на экране. */
const TICKS_MIN_PX = 7;
const TICKS = 12;

/** Непрозрачность знаков вида в тени подсветки другого. */
export const DIM_ALPHA = 0.26;

export type PlanSign = 'tree' | 'conifer' | 'shrub';
export type SwatchSign =
  PlanSign | 'hedge' | 'existing-tree' | 'existing-conifer' | 'existing-shrub' | 'existing-hedge';

/** Знак шаблона у существующего растения: хвойное - по знаку съёмки из подосновы. */
export function existingSignName(plant: ExistingPlant): string {
  if (plant.shrub) return EXISTING_SIGNS.shrub;
  return plant.conifer ? EXISTING_SIGNS.conifer : EXISTING_SIGNS.tree;
}

const EXISTING_SWATCH: Partial<Record<SwatchSign, string>> = {
  'existing-tree': EXISTING_SIGNS.tree,
  'existing-conifer': EXISTING_SIGNS.conifer,
  'existing-shrub': EXISTING_SIGNS.shrub,
  'existing-hedge': EXISTING_SIGNS.hedge,
};

/** Точка главного цвета знака на общем виде не бледнее этого: полупрозрачная заливка знака
 *  («Жимолость», 0,7) точкой в три пикселя иначе не видна. */
const TONE_MIN_ALPHA = 0.6;
/** Знак шаблона у ямы на общем виде - кольцо цвета вида вокруг ямы такой ширины, пиксели. */
const TONE_RING_PX = 1.4;

export interface SignInk {
  ink: string;
  paper: string;
  crown: string;
  coniferCrown: string;
  coniferRing: string;
  halo: string;
}

export function signInk(palette: Palette): SignInk {
  return {
    ink: palette.get('--sign-ink'),
    paper: palette.get('--sign-paper'),
    crown: palette.get('--sign-crown'),
    coniferCrown: palette.get('--sign-crown-conifer'),
    coniferRing: palette.get('--sign-conifer'),
    halo: palette.get('--accent-halo'),
  };
}

const CONIFER_FORMS: ReadonlySet<Form> = new Set(['conifer', 'dwarf_conifer', 'creeper']);

/** Знак посадки: кустарник по типу посадки, хвойное дерево - по форме модели вида. */
export function planSign(plantingType: string, code: string | undefined): PlanSign {
  if (isShrubType(plantingType)) return 'shrub';
  const form = code ? MODELS.get(code)?.form : undefined;
  return form && CONIFER_FORMS.has(form) ? 'conifer' : 'tree';
}

/** Посадка ряда: живая изгородь вдоль борта («C001-004») и ряд кустарника под кронами аллеи
 *  («H001-004») - application/shrub_rows.py, кусты ряда по порядку через метр. */
const ROW_ID = /^([CH]\d+)-(\d+)$/;
/** Дальше этого соседние кусты ряда - уже не одна полоса: шаг 1 м, пропуск - до 2 м. */
const ROW_BREAK_M = 2.6;

export interface Rows {
  rows: MapItem[][];
  member: ReadonlySet<MapItem>;
}

const rowsCache = new WeakMap<readonly MapItem[], Rows>();

/** Ряды кустарника плана в порядке посадки. Считается один раз на список посадок. */
export function hedgeRows(placements: readonly MapItem[]): Rows {
  const hit = rowsCache.get(placements);
  if (hit) return hit;
  const byRow = new Map<string, [number, MapItem][]>();
  for (const p of placements) {
    if (p.kind !== 'placement' || !isShrubType(p.planting_type)) continue;
    const match = ROW_ID.exec(p.id);
    if (!match) continue;
    const key = match[1] ?? '';
    let list = byRow.get(key);
    if (!list) {
      list = [];
      byRow.set(key, list);
    }
    list.push([Number(match[2]), p]);
  }
  const rows: MapItem[][] = [];
  const member = new Set<MapItem>();
  for (const list of byRow.values()) {
    if (list.length < 2) continue;
    list.sort((a, b) => a[0] - b[0]);
    const row = list.map(([, p]) => p);
    for (const p of row) member.add(p);
    rows.push(row);
  }
  const made = { rows, member };
  rowsCache.set(placements, made);
  return made;
}

let hatchMade: { key: string; pattern: CanvasPattern } | null = null;

/** Штриховка 45° в пикселях устройства: плитка с диагональю, шаг 4,5 px CSS. */
function hatch(ctx: CanvasRenderingContext2D, color: string, dpr: number): CanvasPattern | null {
  const key = `${color}|${String(dpr)}`;
  if (hatchMade?.key === key) return hatchMade.pattern;
  const size = Math.max(3, Math.round(4.5 * dpr));
  const tile = document.createElement('canvas');
  tile.width = size;
  tile.height = size;
  const t = tile.getContext('2d');
  if (!t) return null;
  t.strokeStyle = color;
  t.lineWidth = Math.max(0.8, 0.85 * dpr);
  t.beginPath();
  // Диагональ с перехлёстом за край плитки: иначе на стыках штрих рвётся.
  for (const shift of [-size, 0, size]) {
    t.moveTo(shift, size);
    t.lineTo(shift + size, 0);
  }
  t.stroke();
  const pattern = ctx.createPattern(tile, 'repeat');
  if (!pattern) return null;
  hatchMade = { key, pattern };
  return pattern;
}

function circle(path: Path2D, sx: number, sy: number, r: number): void {
  path.moveTo(sx + r, sy);
  path.arc(sx, sy, r, 0, Math.PI * 2);
}

/** Зубчатый кружок: лопасти на окружности, соседние сходятся острым углом внутрь. */
function scallop(path: Path2D, sx: number, sy: number, r: number): void {
  const n = 9;
  const half = Math.PI / n;
  const lobe = r * 0.36;
  const reach = r - lobe;
  const t =
    reach * Math.cos(half) + Math.sqrt(Math.max(0, lobe * lobe - (reach * Math.sin(half)) ** 2));
  const span = Math.atan2(t * Math.sin(half), t * Math.cos(half) - reach);
  for (let i = 0; i < n; i++) {
    const a = i * 2 * half;
    const cx = sx + reach * Math.cos(a);
    const cy = sy + reach * Math.sin(a);
    if (i === 0) path.moveTo(cx + lobe * Math.cos(a - span), cy + lobe * Math.sin(a - span));
    path.arc(cx, cy, lobe, a - span, a + span);
  }
  path.closePath();
}

/** Засечки хвойной кроны наружу: звёздчатая крона генплана, упрощённая до чертёжной. */
function ticks(path: Path2D, sx: number, sy: number, r: number): void {
  const len = Math.min(5, Math.max(2, r * 0.13));
  for (let i = 0; i < TICKS; i++) {
    const a = (i / TICKS) * Math.PI * 2;
    const c = Math.cos(a);
    const s = Math.sin(a);
    path.moveTo(sx + c * r, sy + s * r);
    path.lineTo(sx + c * (r + len), sy + s * (r + len));
  }
}

/** Пачка знаков плана одного прохода: полосы изгородей, контуры крон, кусты, ямы. Всё в
 *  пикселях CSS; вызывающий ставит матрицу dpr. */
class PlanBatch {
  private readonly strips = new Path2D();
  private readonly crowns = new Path2D();
  private readonly conifers = new Path2D();
  private readonly shrubs = new Path2D();
  private readonly pits = new Path2D();
  private hasStrips = false;
  private hasShrubs = false;
  readonly pitR: number;
  readonly shrubR: number;
  readonly stripW: number;
  private readonly thin: boolean;
  /** Общий вид: куст мельче пикселя - серая точка, а не кружок. Тысяча кружков по 5 px на
   *  фрагменте Берзарина сливались в чёрную массу и прятали ямы деревьев. */
  private readonly far: boolean;

  constructor(scale: number, lifted: boolean) {
    this.pitR = Math.max(PIT_R_M * scale, lifted ? PIT_LIFT_PX : PIT_MIN_PX);
    this.far = SHRUB_R_M * scale < FAR_SHRUB_PX && !lifted;
    this.shrubR = this.far
      ? FAR_SHRUB_PX
      : Math.max(SHRUB_R_M * scale, lifted ? SHRUB_MIN_PX + 1 : SHRUB_MIN_PX);
    this.thin = HEDGE_W_M * scale < THIN_STRIP_PX;
    this.stripW = this.thin
      ? Math.max(HEDGE_W_M * scale, lifted ? 2.4 : 1.3)
      : Math.max(HEDGE_W_M * scale, HEDGE_MIN_PX);
  }

  /** Яма дерева без контура кроны: крону рисует знак шаблона. */
  pit(sx: number, sy: number): void {
    circle(this.pits, sx, sy, this.pitR);
  }

  get farShrubs(): boolean {
    return this.far;
  }

  tree(sx: number, sy: number, crownPx: number, conifer: boolean): void {
    circle(this.pits, sx, sy, this.pitR);
    if (crownPx < this.pitR + CROWN_GAP_PX) return;
    const target = conifer ? this.conifers : this.crowns;
    circle(target, sx, sy, crownPx);
    if (conifer && crownPx >= TICKS_MIN_PX) ticks(target, sx, sy, crownPx);
  }

  shrub(sx: number, sy: number): void {
    circle(this.shrubs, sx, sy, this.shrubR);
    this.hasShrubs = true;
  }

  strip(points: readonly { sx: number; sy: number }[]): void {
    const [first, ...rest] = points;
    if (!first) return;
    this.strips.moveTo(first.sx, first.sy);
    for (const point of rest) this.strips.lineTo(point.sx, point.sy);
    this.hasStrips = true;
  }

  draw(ctx: CanvasRenderingContext2D, ink: SignInk, dpr: number, lifted: boolean): void {
    const pattern = this.hasStrips || this.hasShrubs ? hatch(ctx, ink.ink, dpr) : null;
    if (this.hasStrips && this.thin) {
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      if (lifted) {
        ctx.lineWidth = this.stripW + 3;
        ctx.strokeStyle = ink.halo;
        ctx.stroke(this.strips);
      }
      ctx.lineWidth = this.stripW;
      ctx.strokeStyle = ink.ink;
      ctx.stroke(this.strips);
    } else if (this.hasStrips) {
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      if (lifted) {
        ctx.lineWidth = this.stripW + 6;
        ctx.strokeStyle = ink.halo;
        ctx.stroke(this.strips);
      }
      ctx.lineWidth = this.stripW + 2;
      ctx.strokeStyle = ink.ink;
      ctx.stroke(this.strips);
      ctx.lineWidth = this.stripW;
      ctx.strokeStyle = ink.paper;
      ctx.stroke(this.strips);
      if (pattern && this.stripW >= 4) {
        ctx.strokeStyle = pinToScreen(ctx, pattern);
        ctx.stroke(this.strips);
      }
    }
    ctx.lineWidth = lifted ? 1.7 : 1;
    ctx.strokeStyle = ink.crown;
    ctx.stroke(this.crowns);
    ctx.strokeStyle = ink.coniferCrown;
    ctx.stroke(this.conifers);
    if (this.hasShrubs && this.far) {
      ctx.save();
      ctx.globalAlpha *= 0.55;
      ctx.fillStyle = ink.ink;
      ctx.fill(this.shrubs);
      ctx.restore();
    } else if (this.hasShrubs) {
      if (lifted) {
        ctx.lineWidth = 4;
        ctx.strokeStyle = ink.halo;
        ctx.stroke(this.shrubs);
      }
      ctx.fillStyle = ink.paper;
      ctx.fill(this.shrubs);
      if (pattern && this.shrubR >= 3.5) {
        ctx.fillStyle = pinToScreen(ctx, pattern);
        ctx.fill(this.shrubs);
      }
      ctx.lineWidth = 1;
      ctx.strokeStyle = ink.ink;
      ctx.stroke(this.shrubs);
    }
    if (lifted) {
      ctx.lineWidth = 3;
      ctx.strokeStyle = ink.halo;
      ctx.stroke(this.pits);
    }
    ctx.fillStyle = ink.ink;
    ctx.fill(this.pits);
  }
}

/** Знаки шаблона одного прохода: спрайты знаков и точки главного цвета на общем виде. */
class TemplateBatch {
  private readonly stamps: { sign: TemplateSign; sx: number; sy: number; r: number }[] = [];
  private readonly tones = new Map<string, { color: string; alpha: number; path: Path2D }>();
  private readonly halos = new Path2D();
  private hasHalo = false;

  /** Знак радиуса r пикселей; мельче TONE_PX - точка главного цвета с непрозрачностью alpha. */
  add(sign: TemplateSign, sx: number, sy: number, r: number, lifted: boolean, alpha = 1): void {
    if (r < TONE_PX) this.tone(sign, sx, sy, r, alpha);
    else this.stamps.push({ sign, sx, sy, r });
    if (lifted) {
      circle(this.halos, sx, sy, r + 1);
      this.hasHalo = true;
    }
  }

  tone(sign: TemplateSign, sx: number, sy: number, r: number, alpha: number): void {
    const [color, own] = sign.tone;
    const a = Math.max(TONE_MIN_ALPHA, own) * alpha;
    const key = `${color}|${String(a)}`;
    let entry = this.tones.get(key);
    if (!entry) {
      entry = { color, alpha: a, path: new Path2D() };
      this.tones.set(key, entry);
    }
    circle(entry.path, sx, sy, r);
  }

  draw(ctx: CanvasRenderingContext2D, ink: SignInk, dpr: number): void {
    const base = ctx.globalAlpha;
    if (this.hasHalo) {
      ctx.lineWidth = 3;
      ctx.strokeStyle = ink.halo;
      ctx.stroke(this.halos);
    }
    for (const { color, alpha, path } of this.tones.values()) {
      ctx.globalAlpha = base * alpha;
      ctx.fillStyle = signColor(color, ink);
      ctx.fill(path);
    }
    ctx.globalAlpha = base;
    for (const { sign, sx, sy, r } of this.stamps) {
      stamp(ctx, signSprite(sign, r, ink, dpr), sx, sy, r);
    }
  }
}

export type SignLook = 'plan' | 'dim' | 'lift';

/** Посадки одного прохода знаками плана. include - попадает ли посадка в этот проход;
 *  onItem - для колец вердикта: центр и радиус знака на экране. */
export function drawPlanSigns(
  ctx: CanvasRenderingContext2D,
  placements: readonly MapItem[],
  visible: Box,
  view: ViewState,
  ink: SignInk,
  dpr: number,
  look: SignLook,
  include: (p: MapItem) => boolean,
  onItem: (p: MapItem, sx: number, sy: number, radius: number) => void,
): void {
  const lifted = look === 'lift';
  const batch = new PlanBatch(view.scale, lifted);
  const templates = new TemplateBatch();
  const near = (p: MapItem) => {
    const pad = p.radius + 2;
    return (
      p.x >= visible[0] - pad &&
      p.x <= visible[2] + pad &&
      p.y >= visible[1] - pad &&
      p.y <= visible[3] + pad
    );
  };
  const { rows, member } = hedgeRows(placements);
  // Ряды - полосой: кусты подряд, пока между соседями не больше ROW_BREAK_M и вид тот же.
  for (const row of rows) {
    let run: { p: MapItem; sx: number; sy: number }[] = [];
    const flush = () => {
      if (run.length > 1) batch.strip(run);
      else for (const one of run) batch.shrub(one.sx, one.sy);
      run = [];
    };
    for (const p of row) {
      if (!include(p) || !near(p)) {
        flush();
        continue;
      }
      const last = run.at(-1);
      if (
        last &&
        (Math.hypot(p.x - last.p.x, p.y - last.p.y) > ROW_BREAK_M ||
          p.species_code !== last.p.species_code)
      )
        flush();
      const { sx, sy } = toScreen(view, p.x, p.y);
      run.push({ p, sx, sy });
      onItem(p, sx, sy, Math.max(p.radius * view.scale, batch.stripW / 2));
    }
    flush();
  }
  for (const p of placements) {
    if (member.has(p) || !include(p) || !near(p)) continue;
    const { sx, sy } = toScreen(view, p.x, p.y);
    const sign = planSign(p.planting_type, p.species_code);
    const crownPx = p.radius * view.scale;
    const template = speciesSign(p.species_code);
    if (sign === 'shrub') {
      if (!template) batch.shrub(sx, sy);
      else if (batch.farShrubs) templates.tone(template, sx, sy, batch.shrubR, 0.8);
      else templates.add(template, sx, sy, batch.shrubR, lifted);
      onItem(p, sx, sy, Math.max(crownPx, batch.shrubR));
    } else if (template) {
      // Знак по кроне вида; на общем виде - кольцо цвета вида вокруг ямы.
      const r = Math.max(crownPx, batch.pitR + TONE_RING_PX);
      templates.add(template, sx, sy, r, lifted);
      batch.pit(sx, sy);
      onItem(p, sx, sy, Math.max(crownPx, batch.pitR));
    } else {
      batch.tree(sx, sy, crownPx, sign === 'conifer');
      onItem(p, sx, sy, Math.max(crownPx, batch.pitR));
    }
  }
  ctx.save();
  if (look === 'dim') ctx.globalAlpha = DIM_ALPHA;
  // Знаки шаблона - под ямами и полосами изгородей: яма дерева читается поверх кроны.
  templates.draw(ctx, ink, dpr);
  batch.draw(ctx, ink, dpr, lifted);
  ctx.restore();
}

/** Существующие насаждения знаками раздела «существующие» шаблона: серая крона дерева, хвойного
 *  (по знаку съёмки в подоснове) и кустарника размером кроны по съёмке. Сервис ничего не
 *  вырубает, поэтому других состояний нет. Пиксели CSS, матрицу со сдвигом кэша ставит
 *  вызывающий. Пока файл знаков не пришёл - кольца дендроплана «сохраняемое». */
export function drawExistingSigns(
  ctx: CanvasRenderingContext2D,
  plants: readonly ExistingPlant[],
  visible: Box,
  view: ViewState,
  ink: SignInk,
  dpr = 1,
): void {
  const signs = new Map<string, TemplateSign>();
  for (const name of [EXISTING_SIGNS.tree, EXISTING_SIGNS.conifer, EXISTING_SIGNS.shrub]) {
    const sign = templateSignOf(name);
    if (sign) signs.set(name, sign);
  }
  if (signs.size < 3) {
    drawExistingRings(ctx, plants, visible, view, ink);
    return;
  }
  const templates = new TemplateBatch();
  for (const plant of plants) {
    if (plant.x < visible[0] - plant.r || plant.x > visible[2] + plant.r) continue;
    if (plant.y < visible[1] - plant.r || plant.y > visible[3] + plant.r) continue;
    const sign = signs.get(existingSignName(plant));
    if (!sign) continue;
    const { sx, sy } = toScreen(view, plant.x, plant.y);
    const r = plant.r * view.scale;
    // На общем виде - бледная точка не мельче пары пикселей: тысячи крон съёмки иначе
    // заливают план серым, а главное на нём - наши посадки. Серая крона мельче
    // EXISTING_TONE_PX и так читается точкой, а спрайт на каждую из двух тысяч крон
    // Куликовской удлинял перерисовку карты на пятую часть.
    if (r < EXISTING_TONE_PX)
      templates.tone(sign, sx, sy, Math.max(r, RING_FAR_PX), EXISTING_FAR_ALPHA);
    else templates.add(sign, sx, sy, r, false);
  }
  templates.draw(ctx, ink, dpr);
}

/** Полоса живой изгороди на экране тоньше этого - залитой полосой подосновы, а не знаком. */
const HEDGE_SIGN_MIN_PX = 4;

/** Хватает ли масштаба, чтобы рисовать полосу кустарника съёмки знаком шаблона. */
export function hedgeSignFits(view: ViewState): boolean {
  return (
    templateSignOf(EXISTING_SIGNS.hedge) !== undefined &&
    SHRUB_STRIP_WIDTH_M * view.scale >= HEDGE_SIGN_MIN_PX
  );
}

/** Существующая живая изгородь знаком «З9» шаблона: облака вдоль оси полосы, высота знака -
 *  условная ширина полосы, каждый повёрнут по своему отрезку. Пиксели CSS. */
export function drawExistingHedges(
  ctx: CanvasRenderingContext2D,
  lines: readonly Position[][],
  visible: Box,
  view: ViewState,
  ink: SignInk,
  dpr = 1,
): void {
  const sign = templateSignOf(EXISTING_SIGNS.hedge);
  if (!sign) return;
  const height = SHRUB_STRIP_WIDTH_M * view.scale;
  // Нормированный знак вписан в круг радиуса 1 по ширине; его высота - aspect от ширины.
  const r = height / (2 * Math.max(sign.aspect, 0.2));
  const sprite = signSprite(sign, r, ink, dpr);
  // Шаг чуть меньше ширины знака: облака соседних знаков смыкаются, как у секций «ЖИ_С».
  const step = (2 * r * 0.92) / view.scale;
  const pad = SHRUB_STRIP_WIDTH_M + step;
  for (const line of lines) {
    if (
      !line.some(
        ([x, y]) =>
          x >= visible[0] - pad &&
          x <= visible[2] + pad &&
          y >= visible[1] - pad &&
          y <= visible[3] + pad,
      )
    )
      continue;
    let carry = step / 2;
    for (let i = 1; i < line.length; i++) {
      const a = line[i - 1];
      const b = line[i];
      if (!a || !b) continue;
      const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (!length) continue;
      const from = toScreen(view, a[0], a[1]);
      const to = toScreen(view, b[0], b[1]);
      const angle = Math.atan2(to.sy - from.sy, to.sx - from.sx);
      for (let at = carry; at <= length; at += step) {
        const k = at / length;
        ctx.save();
        ctx.translate(from.sx + (to.sx - from.sx) * k, from.sy + (to.sy - from.sy) * k);
        ctx.rotate(angle);
        stamp(ctx, sprite, 0, 0, r);
        ctx.restore();
      }
      carry = carry > length ? carry - length : step - ((length - carry) % step);
    }
  }
}

/** Непрозрачность точки существующего растения на общем виде. */
const EXISTING_FAR_ALPHA = 0.45;
/** Существующее растение мельче этого радиуса на экране - точкой, пиксели CSS. */
const EXISTING_TONE_PX = 6;

/** Кольца дендроплана «сохраняемое» (Камчатская_ДИ): запасной вид существующих насаждений,
 *  пока файл знаков шаблона не пришёл. */
function drawExistingRings(
  ctx: CanvasRenderingContext2D,
  plants: readonly ExistingPlant[],
  visible: Box,
  view: ViewState,
  ink: SignInk,
): void {
  const natural = RING_OUTER_M * view.scale;
  // На совсем общем виде (меньше пикселя на метр) кольцо ещё меньше: иначе оно в пять раз
  // крупнее натурального и участок превращается в россыпь колец.
  const outer = Math.max(natural, natural < 0.8 ? RING_FAR_PX : RING_MIN_PX);
  const k = outer / RING_OUTER_M;
  // Знак крупнее натурального (общий вид) - тише: тысячи колец съёмки иначе заливают план, а
  // главное на нём - ямы наших посадок. На приближении кольцо в полную силу, как на чертеже.
  const alpha = Math.min(1, Math.max(0.32, natural / (RING_MIN_PX * 1.4)));
  const inner = RING_INNER_M * k;
  // Двойное кольцо различимо, только когда между кольцами хотя бы полтора пикселя.
  const double = outer - inner >= 1.5;
  const green = Math.min(3, Math.max(1.5, CONIFER_RING_W_M * view.scale));
  const greenR = outer + green / 2 + 0.4;
  const shrubR = Math.max(
    SHRUB_KEEP_R_M * view.scale,
    natural < 0.8 ? RING_FAR_PX : SCALLOP_MIN_PX,
  );
  const discs = new Path2D();
  const rings = new Path2D();
  const conifers = new Path2D();
  const shrubs = new Path2D();
  for (const plant of plants) {
    if (plant.x < visible[0] - 2 || plant.x > visible[2] + 2) continue;
    if (plant.y < visible[1] - 2 || plant.y > visible[3] + 2) continue;
    const { sx, sy } = toScreen(view, plant.x, plant.y);
    if (plant.shrub) {
      scallop(shrubs, sx, sy, shrubR);
      continue;
    }
    circle(discs, sx, sy, outer);
    circle(rings, sx, sy, outer);
    if (double) circle(rings, sx, sy, inner);
    if (plant.conifer) circle(conifers, sx, sy, greenR);
  }
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.fillStyle = ink.paper;
  ctx.fill(discs);
  ctx.fill(shrubs);
  ctx.lineWidth = 1;
  ctx.strokeStyle = ink.ink;
  ctx.stroke(rings);
  ctx.stroke(shrubs);
  ctx.lineWidth = green;
  ctx.strokeStyle = ink.coniferRing;
  ctx.stroke(conifers);
  ctx.restore();
}

/** Образец знака для легенды и списков: size - сторона квадрата в пикселях CSS, матрица dpr
 *  уже стоит. */
export function drawSignSwatch(
  ctx: CanvasRenderingContext2D,
  sign: SwatchSign,
  size: number,
  ink: SignInk,
  dpr: number,
  alpha = 1,
): void {
  const c = size / 2;
  const template = EXISTING_SWATCH[sign];
  const existing = template ? templateSignOf(template) : undefined;
  if (existing) {
    drawTemplateSwatch(ctx, existing, size, ink, alpha);
    return;
  }
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.lineJoin = 'round';
  switch (sign) {
    case 'tree':
    case 'conifer': {
      const crown = new Path2D();
      const r = size * (sign === 'conifer' ? 0.34 : 0.42);
      circle(crown, c, c, r);
      if (sign === 'conifer') ticks(crown, c, c, r);
      ctx.lineWidth = 1;
      ctx.strokeStyle = sign === 'conifer' ? ink.coniferCrown : ink.crown;
      ctx.stroke(crown);
      ctx.fillStyle = ink.ink;
      ctx.beginPath();
      ctx.arc(c, c, Math.max(2.5, size * 0.13), 0, Math.PI * 2);
      ctx.fill();
      break;
    }
    case 'shrub': {
      const body = new Path2D();
      circle(body, c, c, size * 0.3);
      fillHatched(ctx, body, ink, dpr);
      break;
    }
    case 'hedge': {
      const axis = new Path2D();
      axis.moveTo(size * 0.2, size * 0.62);
      axis.lineTo(size * 0.8, size * 0.38);
      const w = size * 0.3;
      ctx.lineCap = 'round';
      ctx.lineWidth = w + 2;
      ctx.strokeStyle = ink.ink;
      ctx.stroke(axis);
      ctx.lineWidth = w;
      ctx.strokeStyle = ink.paper;
      ctx.stroke(axis);
      const pattern = hatch(ctx, ink.ink, dpr);
      if (pattern) {
        ctx.strokeStyle = pinToScreen(ctx, pattern);
        ctx.stroke(axis);
      }
      break;
    }
    case 'existing-tree':
    case 'existing-conifer': {
      const outer = size * 0.3;
      ctx.fillStyle = ink.paper;
      ctx.beginPath();
      ctx.arc(c, c, outer, 0, Math.PI * 2);
      ctx.fill();
      const rings = new Path2D();
      circle(rings, c, c, outer);
      circle(rings, c, c, outer * (RING_INNER_M / RING_OUTER_M) - 0.6);
      ctx.lineWidth = 1;
      ctx.strokeStyle = ink.ink;
      ctx.stroke(rings);
      if (sign === 'existing-conifer') {
        ctx.lineWidth = 2.2;
        ctx.strokeStyle = ink.coniferRing;
        ctx.beginPath();
        ctx.arc(c, c, outer + 1.6, 0, Math.PI * 2);
        ctx.stroke();
      }
      break;
    }
    case 'existing-shrub':
    case 'existing-hedge': {
      const body = new Path2D();
      scallop(body, c, c, size * 0.34);
      ctx.fillStyle = ink.paper;
      ctx.fill(body);
      ctx.lineWidth = 1;
      ctx.strokeStyle = ink.ink;
      ctx.stroke(body);
      break;
    }
  }
  ctx.restore();
}

/** Образец знака шаблона: тот же рисунок, что на карте, вписанный в квадрат size. */
export function drawTemplateSwatch(
  ctx: CanvasRenderingContext2D,
  sign: TemplateSign,
  size: number,
  ink: SignInk,
  alpha = 1,
): void {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.translate(size / 2, size / 2);
  paintSign(ctx, sign, size * 0.46, ink);
  ctx.restore();
}

function fillHatched(ctx: CanvasRenderingContext2D, body: Path2D, ink: SignInk, dpr: number): void {
  ctx.fillStyle = ink.paper;
  ctx.fill(body);
  const pattern = hatch(ctx, ink.ink, dpr);
  if (pattern) {
    ctx.fillStyle = pinToScreen(ctx, pattern);
    ctx.fill(body);
  }
  ctx.lineWidth = 1;
  ctx.strokeStyle = ink.ink;
  ctx.stroke(body);
}
