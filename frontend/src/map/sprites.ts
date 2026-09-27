/* Спрайты моделей растений: крона вектором в скрытом холсте, дальше карта кладёт готовую
 * картинку. Рисовать лопастную крону с тенью и штриховкой на каждый кадр для трёх тысяч
 * посадок дорого, а видов на прогон два-три десятка: спрайт на вид, масштаб и состояние
 * рисуется один раз.
 *
 * Стиль - как в презентации: крона-облако с тёмной рисованной обводкой и тенью вниз-вправо,
 * хвойные - звезда из хвои, кустарник - розетка с точкой в центре. Свет всегда падает с
 * верхнего левого угла экрана, поэтому тень рисуется в экранных координатах и не крутится
 * вместе с видом вдоль улицы. */

import type { Form, PlantModel } from './models';

/** plan - посадка плана; lift - подсвеченный вид; dim - вид в тени подсветки другого;
 *  existing - то, что уже растёт на участке; xray - режим правки: крона прозрачная, ствол
 *  крупной точкой, чтобы в перекрытых кронах было видно, за что хватать. */
export type Look = 'plan' | 'lift' | 'dim' | 'existing' | 'xray';

/** Радиус точки ствола в режиме правки, CSS-пиксели: цель для клика и пальца. */
export const XRAY_TRUNK_PX = 3;

export interface Sprite {
  canvas: HTMLCanvasElement;
  /** Радиус кроны, под который нарисован спрайт, в CSS-пикселях. */
  radius: number;
  /** Половина стороны спрайта в CSS-пикселях: центр кроны - в центре холста. */
  half: number;
}

const INK = '#2d2a22';
const EXISTING_INK = '#8a866d';
const TRUNK = '#4a3527';
const SHADOW = 'rgba(62, 66, 40, 0.28)';
const HALO = '#fbf7ec';
/** Спрайтов в кэше: видов на прогон десятки, состояний четыре, ступеней масштаба при зуме
 *  несколько. Переполнение - признак смены прогона, кэш просто начинается заново. */
const LIMIT = 900;

const cache = new Map<string, Sprite>();

/** Радиус ступенями в четверть октавы: при плавном зуме спрайт перерисовывается раз на 19%
 *  масштаба, а не на каждом кадре. Разницу добирает растяжение при выводе. */
export function quantize(radius: number): number {
  return 2 ** (Math.round(Math.log2(Math.max(radius, 1)) * 4) / 4);
}

export function sprite(
  key: string,
  model: PlantModel,
  radius: number,
  look: Look,
  dpr: number,
): Sprite {
  const r = quantize(radius);
  const id = `${key}|${String(r)}|${look}|${String(dpr)}`;
  const hit = cache.get(id);
  if (hit) return hit;
  if (cache.size >= LIMIT) cache.clear();
  const made = render(key, model, r, look, dpr);
  cache.set(id, made);
  return made;
}

export function clearSprites(): void {
  cache.clear();
}

/** Вывести спрайт кроны радиуса radius с центром в (sx, sy), экранные пиксели. */
export function stamp(
  ctx: CanvasRenderingContext2D,
  s: Sprite,
  sx: number,
  sy: number,
  radius: number,
): void {
  const k = radius / s.radius;
  const half = s.half * k;
  ctx.drawImage(s.canvas, sx - half, sy - half, half * 2, half * 2);
}

function render(key: string, model: PlantModel, r: number, look: Look, dpr: number): Sprite {
  const lit = look === 'plan' || look === 'lift';
  const shadow = lit ? Math.max(1.5, r * 0.12) : 0;
  const half = Math.ceil(r * 1.1 + shadow + (look === 'lift' ? 6 : 3));
  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(half * 2 * dpr);
  canvas.height = canvas.width;
  const made: Sprite = { canvas, radius: r, half };
  const ctx = canvas.getContext('2d');
  if (!ctx) return made;
  ctx.scale(dpr, dpr);
  ctx.translate(half, half);
  const rand = random(seed(key));
  const outline = shape(model.form, r, model.lobes, rand);
  const ink = look === 'existing' ? EXISTING_INK : INK;
  const width = look === 'existing' ? 1 : Math.min(2.2, Math.max(1, r / 14));

  if (shadow) {
    ctx.save();
    ctx.translate(shadow, shadow);
    ctx.fillStyle = SHADOW;
    ctx.fill(outline);
    ctx.restore();
  }
  if (look === 'lift') {
    ctx.lineWidth = width + 5;
    ctx.strokeStyle = HALO;
    ctx.lineJoin = 'round';
    ctx.stroke(outline);
  }
  ctx.globalAlpha = FILL_ALPHA[look];
  ctx.fillStyle = model.tone;
  ctx.fill(outline);
  if (look === 'plan' || look === 'lift') details(ctx, model, r, outline, rand);
  ctx.globalAlpha = look === 'dim' ? 0.4 : look === 'xray' ? 0.65 : 1;
  ctx.lineJoin = 'round';
  ctx.lineWidth = look === 'lift' ? width + 0.8 : look === 'xray' ? 1 : width;
  ctx.strokeStyle = ink;
  ctx.stroke(outline);
  center(ctx, model.form, r, look);
  return made;
}

/** Непрозрачность заливки кроны по состоянию. */
const FILL_ALPHA: Record<Look, number> = {
  plan: 1,
  lift: 1,
  dim: 0.34,
  existing: 0.9,
  xray: 0.25,
};

/** Контур модели: лопастное облако, звезда из хвои или розетка кустарника. */
function shape(form: Form, r: number, lobes: number, rand: () => number): Path2D {
  switch (form) {
    case 'conifer':
      return star(r, lobes, 0.56, 0.05, rand);
    case 'dwarf_conifer':
      return star(r, lobes, 0.68, 0.08, rand);
    case 'creeper':
      return star(r, lobes, 0.62, 0.3, rand);
    case 'shrub':
      return cloud(r, lobes, 0.86, 1.1, rand);
    case 'columnar':
      return cloud(r, lobes, 0.8, 1.12, rand);
    case 'weeping':
      return cloud(r, lobes, 0.84, 1.12, rand);
    case 'rounded':
      return cloud(r, lobes, 0.8, 1.16, rand);
    case 'broadleaf':
      return cloud(r, lobes, 0.78, 1.18, rand);
  }
}

/** Облако: опорные точки на окружности base * r, между ними дуги, выпяченные до bulge * r.
 *  Лёгкий разброс опор и выпуклостей делает контур рисованным, а не циркульным. */
function cloud(r: number, lobes: number, base: number, bulge: number, rand: () => number): Path2D {
  const path = new Path2D();
  const phase = rand() * Math.PI * 2;
  const points: [number, number][] = [];
  for (let i = 0; i < lobes; i++) {
    const a = phase + (i / lobes) * Math.PI * 2;
    const j = 1 + (rand() - 0.5) * 0.12;
    points.push([Math.cos(a) * base * r * j, Math.sin(a) * base * r * j]);
  }
  const [first] = points;
  if (!first) return path;
  path.moveTo(first[0], first[1]);
  for (let i = 0; i < lobes; i++) {
    const a = phase + ((i + 0.5) / lobes) * Math.PI * 2;
    const k = bulge * r * (1 + (rand() - 0.5) * 0.1);
    const next = points[(i + 1) % lobes] ?? first;
    path.quadraticCurveTo(Math.cos(a) * k, Math.sin(a) * k, next[0], next[1]);
  }
  path.closePath();
  return path;
}

/** Звезда: spikes лучей до r, впадины на inner * r; ragged - разброс длины лучей. */
function star(
  r: number,
  spikes: number,
  inner: number,
  ragged: number,
  rand: () => number,
): Path2D {
  const path = new Path2D();
  const phase = rand() * Math.PI;
  for (let i = 0; i < spikes * 2; i++) {
    const a = phase + (i / (spikes * 2)) * Math.PI * 2;
    const reach = i % 2 === 0 ? r * (1 - ragged * rand()) : r * inner * (1 + (rand() - 0.5) * 0.08);
    const x = Math.cos(a) * reach;
    const y = Math.sin(a) * reach;
    if (i === 0) path.moveTo(x, y);
    else path.lineTo(x, y);
  }
  path.closePath();
  return path;
}

/** Объём и фактура: блик на кроне, штриховка на крупных, свисающие ветви у плакучих,
 *  внутренняя звезда у хвойных и точки цветения. */
function details(
  ctx: CanvasRenderingContext2D,
  model: PlantModel,
  r: number,
  outline: Path2D,
  rand: () => number,
): void {
  if (r < 5) return;
  ctx.save();
  ctx.clip(outline);
  const conifer =
    model.form === 'conifer' || model.form === 'dwarf_conifer' || model.form === 'creeper';
  if (conifer) {
    ctx.fillStyle = shade(model.tone, 0.22);
    ctx.fill(star(r * 0.55, Math.max(8, Math.round(model.lobes * 0.6)), 0.55, 0.1, rand));
  } else {
    // Блик сверху слева: свет падает оттуда же, откуда тень уходит вниз-вправо.
    ctx.fillStyle = shade(model.tone, 0.2);
    ctx.globalAlpha = 0.55;
    ctx.beginPath();
    ctx.ellipse(-r * 0.28, -r * 0.3, r * 0.5, r * 0.4, -0.6, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
  }
  if (model.form === 'weeping' && r >= 8) {
    ctx.strokeStyle = shade(model.tone, -0.35);
    ctx.lineWidth = 0.9;
    ctx.beginPath();
    for (let i = 0; i < 12; i++) {
      const a = (i / 12) * Math.PI * 2 + rand() * 0.2;
      ctx.moveTo(Math.cos(a) * r * 0.15, Math.sin(a) * r * 0.15);
      ctx.lineTo(Math.cos(a) * r * 0.95, Math.sin(a) * r * 0.95);
    }
    ctx.stroke();
  }
  // Штриховка крупной кроны, как на слайде с объяснением посадки.
  if (!conifer && model.form !== 'shrub' && r >= 22) {
    ctx.strokeStyle = 'rgba(45, 42, 34, 0.2)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    const step = Math.max(5, r / 7);
    for (let d = -r * 2; d <= r * 2; d += step) {
      ctx.moveTo(d - r, r);
      ctx.lineTo(d + r, -r);
    }
    ctx.stroke();
  }
  if (model.bloom && r >= 6) {
    ctx.fillStyle = model.bloom;
    const count = model.form === 'shrub' ? 4 : 7;
    const dot = Math.max(0.9, r * (model.form === 'shrub' ? 0.13 : 0.075));
    for (let i = 0; i < count; i++) {
      const a = rand() * Math.PI * 2;
      const d = (0.25 + rand() * 0.45) * r;
      ctx.beginPath();
      ctx.arc(Math.cos(a) * d, Math.sin(a) * d, dot, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();
}

/** Центр: ствол у дерева, точка у кустарника, крестик съёмки у существующего; в режиме
 *  правки - крупная точка чернил со светлой каймой, одна для всех форм. */
function center(ctx: CanvasRenderingContext2D, form: Form, r: number, look: Look): void {
  if (look === 'xray') {
    ctx.globalAlpha = 1;
    ctx.beginPath();
    ctx.arc(0, 0, XRAY_TRUNK_PX, 0, Math.PI * 2);
    ctx.fillStyle = INK;
    ctx.fill();
    ctx.lineWidth = 1;
    ctx.strokeStyle = HALO;
    ctx.stroke();
    return;
  }
  ctx.globalAlpha = look === 'dim' ? 0.4 : 1;
  if (look === 'existing') {
    const arm = Math.max(1.6, r * 0.22);
    ctx.strokeStyle = EXISTING_INK;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(-arm, 0);
    ctx.lineTo(arm, 0);
    ctx.moveTo(0, -arm);
    ctx.lineTo(0, arm);
    ctx.stroke();
    ctx.globalAlpha = 1;
    return;
  }
  const shrub = form === 'shrub' || form === 'creeper';
  ctx.fillStyle = shrub ? INK : TRUNK;
  ctx.beginPath();
  ctx.arc(0, 0, Math.max(shrub ? 0.8 : 1.2, r * (shrub ? 0.09 : 0.08)), 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 1;
}

/** Светлее (k > 0) или темнее (k < 0) цвета #rrggbb. */
export function shade(hex: string, k: number): string {
  const n = Number.parseInt(hex.slice(1), 16);
  const channel = (value: number) => {
    const moved = k >= 0 ? value + (255 - value) * k : value * (1 + k);
    return Math.round(Math.min(255, Math.max(0, moved)));
  };
  const rgb = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(channel);
  return `rgb(${rgb.join(', ')})`;
}

/** Семя из ключа модели: у каждого вида свой рисунок кроны, одинаковый от кадра к кадру. */
function seed(key: string): number {
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** mulberry32: короткий детерминированный генератор, Math.random здесь не годится. */
function random(state: number): () => number {
  let a = state;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
