import type { Box } from './geometry';
import type { Area, ViewState } from './types';
import { extentOf, fitView, toScreen } from './view';

/** Сохраняем вид, если объект уже крупно и целиком виден между панелями. */
export function semanticReviewTarget(view: ViewState, box: Box, area: Area, automatic: boolean) {
  const [x0, y0, x1, y1] = box;
  const corners = [
    { x: x0, y: y0 },
    { x: x1, y: y0 },
    { x: x1, y: y1 },
    { x: x0, y: y1 },
  ];
  const screen = corners.map((p) => toScreen(view, p.x, p.y));
  const visible = screen.every(
    (p) =>
      p.sx >= area.left + 20 &&
      p.sx <= area.left + area.width - 20 &&
      p.sy >= area.top + 20 &&
      p.sy <= area.top + area.height - 20,
  );
  const span = Math.max(
    Math.max(...screen.map((p) => p.sx)) - Math.min(...screen.map((p) => p.sx)),
    Math.max(...screen.map((p) => p.sy)) - Math.min(...screen.map((p) => p.sy)),
  );
  if (automatic && visible && span >= 40) return null;
  const margin = Math.max(3, Math.max(x1 - x0, y1 - y0) * 0.08);
  const points = [
    { x: x0 - margin, y: y0 - margin },
    { x: x1 + margin, y: y0 - margin },
    { x: x1 + margin, y: y1 + margin },
    { x: x0 - margin, y: y1 + margin },
  ];
  return fitView(extentOf(view, points), area);
}
