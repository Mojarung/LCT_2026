/* Вид карты: переходы между чертежом, видом и экраном, вписывание, масштаб. Чистые функции.
 *
 * Вид разворачивается вдоль улицы. Участок работ - лента: на Берзарина 552 x 88 м под углом
 * 23 градуса, и её прямоугольная обёртка вчетверо больше самой ленты по площади. Без разворота
 * план занимает четверть экрана и деревья вырождаются в точки. */

import type { Box, Point } from './geometry';
import type { Area, ViewState } from './types';

/** Координаты вида: горизонталь экрана - вдоль улицы, вертикаль - поперёк. */
export function toView(
  view: Pick<ViewState, 'rot'>,
  x: number,
  y: number,
): { u: number; v: number } {
  const c = Math.cos(view.rot);
  const s = Math.sin(view.rot);
  return { u: c * x + s * y, v: s * x - c * y };
}

export function toScreen(view: ViewState, x: number, y: number): { sx: number; sy: number } {
  const { u, v } = toView(view, x, y);
  return { sx: u * view.scale + view.tx, sy: v * view.scale + view.ty };
}

/** Экран -> чертёж. Матрица разворота вида совпадает со своей обратной, поэтому обратный
 *  переход считается теми же косинусом и синусом. */
export function toWorld(view: ViewState, px: number, py: number): Point {
  const dx = px - view.tx;
  const dy = py - view.ty;
  const c = Math.cos(view.rot);
  const s = Math.sin(view.rot);
  return { x: (dx * c + dy * s) / view.scale, y: (dx * s - dy * c) / view.scale };
}

/** Габарит прямоугольника экрана в координатах чертежа. Для повёрнутого вида - габарит
 *  четырёх углов: он шире самого прямоугольника, и отсечение обязано ошибаться в плюс. */
export function worldBounds(
  view: ViewState,
  left: number,
  top: number,
  width: number,
  height: number,
): Box {
  const box: Box = [Infinity, Infinity, -Infinity, -Infinity];
  const corners: [number, number][] = [
    [left, top],
    [left + width, top],
    [left, top + height],
    [left + width, top + height],
  ];
  for (const [sx, sy] of corners) {
    const { x, y } = toWorld(view, sx, sy);
    if (x < box[0]) box[0] = x;
    if (y < box[1]) box[1] = y;
    if (x > box[2]) box[2] = x;
    if (y > box[3]) box[3] = y;
  }
  return box;
}

/** Круглая длина для масштабной линейки и сетки: 1, 2 или 5 на порядок. */
export function niceLength(meters: number): number {
  const power = 10 ** Math.floor(Math.log10(meters));
  const head = meters / power;
  return (head >= 5 ? 5 : head >= 2 ? 2 : 1) * power;
}

export interface Extent {
  minU: number;
  maxU: number;
  minV: number;
  maxV: number;
  w: number;
  h: number;
}

/** Запас вокруг плана при вписывании, метры. Было 8: вместе с панелями поверх карты он
 *  отдавал пустоте заметную долю кадра. */
export const FIT_MARGIN_M = 4;

/** Габарит точек в координатах вида. Считается по самим точкам, а не по углам их bbox:
 *  прямоугольник, повёрнутый вместе с лентой, снова становится большим. */
export function extentOf(
  view: Pick<ViewState, 'rot'>,
  points: readonly Point[],
  margin = FIT_MARGIN_M,
): Extent {
  let minU = Infinity;
  let maxU = -Infinity;
  let minV = Infinity;
  let maxV = -Infinity;
  for (const { x, y } of points) {
    const { u, v } = toView(view, x, y);
    minU = Math.min(minU, u);
    maxU = Math.max(maxU, u);
    minV = Math.min(minV, v);
    maxV = Math.max(maxV, v);
  }
  return {
    minU: minU - margin,
    maxU: maxU + margin,
    minV: minV - margin,
    maxV: maxV + margin,
    w: Math.max(maxU - minU + 2 * margin, 1),
    h: Math.max(maxV - minV + 2 * margin, 1),
  };
}

/** Вписать план целиком в свободную область, по её центру. Это и вид при открытии: крупный
 *  вид, где лента по длине уходила под панели, прятал около трети улицы, а на 768 и 375
 *  обрезал её с обоих концов (жюри дизайна, итерация 7). Приблизить - одно движение колеса
 *  или ползунка; найти спрятанный конец улицы на незнакомом плане - нет. */
export function fitView(ext: Extent, area: Area): Omit<ViewState, 'rot'> {
  const scale = Math.min(area.width / ext.w, area.height / ext.h);
  return {
    scale,
    tx: area.left + area.width / 2 - ((ext.minU + ext.maxU) / 2) * scale,
    ty: area.top + area.height / 2 - ((ext.minV + ext.maxV) / 2) * scale,
  };
}

/** Группу посадок крупнее не вписывать: при 6 px/м крона 5 м - 30 px, и вокруг видно улицу, а
 *  не одну точку на весь экран. Подписи материала появляются с 5 px/м (render.LABEL_MIN_SCALE). */
export const GROUP_MAX_SCALE = 6;
/** Посадка ближе этого к краю свободной области считается невидной: её перекрывает кромка. */
const GROUP_PAD_PX = 24;

/** Вид на посадки одного вида из состава плана: вписать их в свободную область. null - все
 *  уже видны, и вид не двигается: лишний скачок сбивает того, кто сам выбрал кадр. */
export function groupView(
  view: ViewState,
  points: readonly Point[],
  area: Area,
): Omit<ViewState, 'rot'> | null {
  if (!points.length) return null;
  const seen = points.every(({ x, y }) => {
    const { sx, sy } = toScreen(view, x, y);
    return (
      sx >= area.left + GROUP_PAD_PX &&
      sx <= area.left + area.width - GROUP_PAD_PX &&
      sy >= area.top + GROUP_PAD_PX &&
      sy <= area.top + area.height - GROUP_PAD_PX
    );
  });
  if (seen) return null;
  const ext = extentOf(view, points);
  const fitted = fitView(ext, area);
  if (fitted.scale <= GROUP_MAX_SCALE) return fitted;
  const scale = GROUP_MAX_SCALE;
  return {
    scale,
    tx: area.left + area.width / 2 - ((ext.minU + ext.maxU) / 2) * scale,
    ty: area.top + area.height / 2 - ((ext.minV + ext.maxV) / 2) * scale,
  };
}

/** Масштаб вокруг точки экрана: точка под курсором остаётся на месте. */
export function zoomAt(view: ViewState, px: number, py: number, factor: number): ViewState {
  const next = Math.min(Math.max(view.scale * factor, 0.002), 400);
  const applied = next / view.scale;
  return {
    rot: view.rot,
    scale: next,
    tx: px - (px - view.tx) * applied,
    ty: py - (py - view.ty) * applied,
  };
}

/** Границы ползунка масштаба: от вида «весь план» вчетверо мельче и в шестьдесят четыре раза
 *  крупнее. Шкала логарифмическая - иначе весь полезный диапазон сидит в первых процентах. */
export const ZOOM_OUT = 0.25;
export const ZOOM_IN = 64;

export function zoomShare(scale: number, fitScale: number): number {
  const lo = fitScale * ZOOM_OUT;
  const hi = fitScale * ZOOM_IN;
  const share = Math.log(scale / lo) / Math.log(hi / lo);
  return Math.min(Math.max(share, 0), 1);
}

export function scaleFromShare(share: number, fitScale: number): number {
  const lo = fitScale * ZOOM_OUT;
  const hi = fitScale * ZOOM_IN;
  return lo * (hi / lo) ** share;
}
