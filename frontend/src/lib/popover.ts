/* Где поставить карточку у точки на карте: рядом с точкой, внутри карты и не на панелях. */

export interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Поле от точки и от краёв карты, пиксели. */
const GAP = 12;
const EDGE = 8;

function overlaps(a: Rect, b: Rect): boolean {
  return (
    a.left < b.left + b.width &&
    a.left + a.width > b.left &&
    a.top < b.top + b.height &&
    a.top + a.height > b.top
  );
}

/** Левый верхний угол карточки size у точки (x, y) в области area. Пробуются четыре стороны:
 *  справа-снизу, слева-снизу, справа-сверху, слева-сверху. Берётся первая, где карточка
 *  целиком внутри области и не закрывает ни одной панели; если такой нет - первая, что
 *  помещается; если и такой нет - справа-снизу, прижатая к краям. */
export function placeNear(
  x: number,
  y: number,
  size: { width: number; height: number },
  area: { width: number; height: number },
  obstacles: readonly Rect[] = [],
): { left: number; top: number } {
  const { width, height } = size;
  const sides = [
    { left: x + GAP, top: y + GAP },
    { left: x - GAP - width, top: y + GAP },
    { left: x + GAP, top: y - GAP - height },
    { left: x - GAP - width, top: y - GAP - height },
  ];
  const inside = (p: { left: number; top: number }) =>
    p.left >= EDGE &&
    p.top >= EDGE &&
    p.left + width <= area.width - EDGE &&
    p.top + height <= area.height - EDGE;
  const clear = (p: { left: number; top: number }) =>
    !obstacles.some((o) => overlaps({ ...p, width, height }, o));
  const chosen = sides.find((p) => inside(p) && clear(p)) ??
    sides.find(inside) ?? { left: x + GAP, top: y + GAP };
  return {
    left: Math.max(EDGE, Math.min(chosen.left, area.width - EDGE - width)),
    top: Math.max(EDGE, Math.min(chosen.top, area.height - EDGE - height)),
  };
}
