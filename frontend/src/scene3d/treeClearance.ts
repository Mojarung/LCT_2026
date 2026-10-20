/* Проверка существующих стволов по базовому отступу до здания из правил данного прогона.
 * Это визуальная проверка геометрии модели, а не решение о вырубке и не аудит всех норм. */
import type { Rule, RulesJson } from '../api/artifacts';
import { distanceToArea } from './playgrounds';
import type { Plant, World } from './types';

export interface TreeClearanceConflict {
  plant: Plant;
  distance: number;
  required: number;
  rule: Rule;
}

export function treeClearanceConflicts(
  world: World,
  rules: RulesJson | null,
): TreeClearanceConflict[] {
  const rule = rules?.rules['R-BLD-TREE-001'];
  if (
    !rule ||
    rule.status !== 'verified' ||
    rule.object_class !== 'building' ||
    rule.measure_to !== 'edge' ||
    !Number.isFinite(rule.min_distance_m) ||
    rule.min_distance_m === null ||
    rule.min_distance_m <= 0
  )
    return [];
  // Крыльцо, навес и условное сооружение не выдаются за наружную стену дома.
  const buildings = world.buildings.filter((b) => b.kind === 'building');
  const conflicts: TreeClearanceConflict[] = [];
  for (const plant of world.plants) {
    if (!plant.existing || plant.strip || plant.type !== 'existing_tree') continue;
    let distance = Infinity;
    for (const building of buildings)
      distance = Math.min(distance, distanceToArea(building.rings, plant));
    if (distance + 1e-6 < rule.min_distance_m)
      conflicts.push({ plant, distance, required: rule.min_distance_m, rule });
  }
  return conflicts;
}

/** Красная область — маркер дерева, её радиус не является нормативным отступом. */
export const TREE_WARNING_RADIUS = 1.4;
export const TREE_WARNING_Y = 0.18;

/** Наведение на область на земле тоже открывает пояснение, даже если крона вне кадра. */
export function pickTreeWarning(
  ray: { ox: number; oy: number; oz: number; dx: number; dy: number; dz: number },
  conflicts: readonly TreeClearanceConflict[],
): string | null {
  if (ray.dy >= -1e-6) return null;
  const t = (TREE_WARNING_Y - ray.oy) / ray.dy;
  if (t < 0 || t > 250) return null;
  const x = ray.ox + t * ray.dx;
  const z = ray.oz + t * ray.dz;
  let best = TREE_WARNING_RADIUS;
  let id: string | null = null;
  for (const { plant } of conflicts) {
    const distance = Math.hypot(x - plant.x, z - plant.z);
    if (distance <= best) {
      best = distance;
      id = plant.id;
    }
  }
  return id;
}
