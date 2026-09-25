import { useEffect, useRef } from 'react';

import type { PlantModel } from '../../map/models';
import { type Look, sprite, stamp } from '../../map/sprites';

/** Образец модели растения тем же спрайтом, что на карте: обозначение в легенде и в составе
 *  плана не может разойтись с тем, что нарисовано на плане. */
export function ModelSwatch({
  model,
  modelKey,
  look = 'plan',
  size = 26,
}: {
  model: PlantModel;
  modelKey: string;
  look?: Look;
  size?: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(size * dpr);
    canvas.height = Math.round(size * dpr);
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size, size);
    // Крона чуть левее и выше центра: тень уходит вниз-вправо и должна поместиться.
    const radius = size * 0.36;
    stamp(ctx, sprite(modelKey, model, radius, look, dpr), size / 2 - 1.5, size / 2 - 1.5, radius);
  }, [model, modelKey, look, size]);
  return (
    <canvas
      ref={ref}
      className="model-swatch"
      style={{ width: `${String(size)}px`, height: `${String(size)}px` }}
      aria-hidden="true"
    />
  );
}
