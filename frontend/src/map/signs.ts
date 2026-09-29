/* Условные знаки инженерного стиля карты: как на дендроплане и разбивочно-посадочном чертеже
 * проектировщиков пилота. Геометрия - из библиотеки знаков, собранной по файлам организаторов
 * (шаблон значков, дендропланы и РПЧ пяти бюро, подоснова Мосгеотреста; docs/notes/40):
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

import type { ExistingPlant } from './existing';
import type { Box } from './geometry';
import { type Form, isShrubType, MODELS } from './models';
import type { Palette } from './palette';
import { pinToScreen } from './paper';
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
  PlanSign | 'hedge' | 'existing-tree' | 'existing-conifer' | 'existing-shrub';

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
    if (sign === 'shrub') {
      batch.shrub(sx, sy);
      onItem(p, sx, sy, Math.max(crownPx, batch.shrubR));
    } else {
      batch.tree(sx, sy, crownPx, sign === 'conifer');
      onItem(p, sx, sy, Math.max(crownPx, batch.pitR));
    }
  }
  ctx.save();
  if (look === 'dim') ctx.globalAlpha = DIM_ALPHA;
  batch.draw(ctx, ink, dpr, lifted);
  ctx.restore();
}

/** Существующие насаждения знаками дендроплана «сохраняемое» - сервис ничего не вырубает.
 *  Пиксели CSS, матрицу со сдвигом кэша ставит вызывающий. */
export function drawExistingSigns(
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
    case 'existing-shrub': {
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
