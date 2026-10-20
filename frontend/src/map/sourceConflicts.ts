import type { SourceConflict } from '../api/artifacts';
import type { ViewState } from './types';
import { toScreen } from './view';

/** Advisory markers are separate from editable planting IDs and verdicts. */
export function drawSourceConflicts(
  ctx: CanvasRenderingContext2D,
  view: ViewState,
  items: readonly SourceConflict[],
  selected: string | null,
  width: number,
  height: number,
): void {
  ctx.save();
  ctx.font = 'bold 12px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (const [index, item] of items.entries()) {
    const { sx, sy } = toScreen(view, item.x, item.y);
    if (sx < -60 || sy < -60 || sx > width + 60 || sy > height + 60) continue;
    const active = item.id === selected;
    const radius = Math.max(14, Math.min(42, view.scale));
    ctx.beginPath();
    ctx.arc(sx, sy, radius, 0, Math.PI * 2);
    ctx.strokeStyle = '#fff9e9';
    ctx.lineWidth = active ? 7 : 5;
    ctx.stroke();
    ctx.strokeStyle = '#ac3e08';
    ctx.lineWidth = active ? 4 : 2;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(sx + radius, sy - radius, 11, 0, Math.PI * 2);
    ctx.fillStyle = '#ac3e08';
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.fillText(String(index + 1), sx + radius, sy - radius);
  }
  ctx.restore();
}

export interface TreeClearanceMark {
  x: number;
  y: number;
  distance: number;
  required: number;
}

/** Screen-sized rings identify source trees without implying a clearance radius. */
export function drawTreeClearanceMarks(
  ctx: CanvasRenderingContext2D,
  view: ViewState,
  items: readonly TreeClearanceMark[],
  width: number,
  height: number,
): void {
  ctx.save();
  ctx.font = 'bold 12px sans-serif';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  for (const item of items) {
    const { sx, sy } = toScreen(view, item.x, item.y);
    if (sx < -100 || sy < -100 || sx > width + 100 || sy > height + 100) continue;
    ctx.beginPath();
    ctx.arc(sx, sy, 16, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(216, 62, 62, 0.18)';
    ctx.fill();
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 6;
    ctx.stroke();
    ctx.strokeStyle = '#c62828';
    ctx.lineWidth = 3;
    ctx.stroke();
    const label = `${item.distance.toLocaleString('ru-RU', { maximumFractionDigits: 1 })} / ${item.required.toLocaleString('ru-RU')} м`;
    ctx.lineWidth = 4;
    ctx.strokeStyle = '#ffffff';
    ctx.strokeText(label, sx + 21, sy);
    ctx.fillStyle = '#a51d1d';
    ctx.fillText(label, sx + 21, sy);
  }
  ctx.restore();
}
