/* Данные прогона -> отметки карты. */

import { artifactUrl } from '../api/client';
import type { PlanJson, SurfaceMeta } from '../api/artifacts';
import { surfaceMasks } from './paper';
import type { MapItem, SurfaceImage } from './types';

/** Крона по умолчанию, если у посадки нет вида: радиус такой, чтобы отметка читалась. */
const DEFAULT_CROWN_M = 3;
const REJECTION_RADIUS_M = 1.2;

export function toMapItems(plan: PlanJson): { placements: MapItem[]; rejections: MapItem[] } {
  return {
    placements: plan.placements.map((p) => ({
      kind: 'placement',
      id: p.id,
      number: p.number,
      planting_type: p.planting_type,
      x: p.x,
      y: p.y,
      radius: (p.species?.crown_diameter_m || DEFAULT_CROWN_M) / 2,
      verdict: p.verdict,
      species_code: p.species?.code,
      species_ru: p.species?.name_ru,
      species_lat: p.species?.name_lat,
      explanation: p.explanation,
      value: p.value,
      checks: p.checks,
      assortment: p.assortment,
    })),
    rejections: plan.rejections.map((r) => ({
      kind: 'rejection',
      id: r.id,
      number: r.number,
      planting_type: r.planting_type,
      x: r.x,
      y: r.y,
      radius: REJECTION_RADIUS_M,
      verdict: r.verdict,
      explanation: r.explanation,
      note: r.note,
      barrier_m: r.barrier_m,
      value: null,
      checks: r.blocking,
    })),
  };
}

/** Карта покрытий: PNG и его привязка к координатам чертежа (surface.json). */
export async function loadSurface(runId: string, meta: SurfaceMeta): Promise<SurfaceImage | null> {
  const img = new Image();
  img.src = artifactUrl(runId, 'surface.png');
  try {
    await img.decode();
  } catch {
    return null;
  }
  const masks = surfaceMasks(img);
  return {
    img,
    x: meta.origin[0],
    y: meta.origin[1],
    w: meta.width * meta.cell_m,
    h: meta.height * meta.cell_m,
    soil: masks?.soil ?? null,
    paved: masks?.paved ?? null,
  };
}
