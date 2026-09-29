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
