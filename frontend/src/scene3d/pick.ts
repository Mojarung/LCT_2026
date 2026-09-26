/* Что под прицелом: луч из камеры против упрощённых объёмов посадок. Пересекать луч с
 * листвой нельзя - в ней сотни тысяч треугольников на кадр, - а для подписи «что это за
 * дерево» хватает цилиндра ствола до низа кроны и шара кроны. */

export interface Ray {
  ox: number;
  oy: number;
  oz: number;
  dx: number;
  dy: number;
  dz: number;
}

export interface Body {
  x: number;
  z: number;
  /** Высота до верха кроны. */
  height: number;
  /** Радиус кроны. */
  radius: number;
}

/** Дальше этого подпись не нужна: на таком расстоянии дерево одно из сотни. */
export const PICK_RANGE_M = 250;

/** Расстояние по лучу до шара кроны или null. Центр шара - на двух третях высоты. */
export function hitCrown(ray: Ray, body: Body): number | null {
  const r = Math.max(body.radius, 0.3);
  const cy = Math.max(body.height - r, body.height * 0.6);
  const lx = body.x - ray.ox;
  const ly = cy - ray.oy;
  const lz = body.z - ray.oz;
  const t = lx * ray.dx + ly * ray.dy + lz * ray.dz;
  if (t < 0) return null;
  const d2 = lx * lx + ly * ly + lz * lz - t * t;
  if (d2 > r * r) return null;
  const hit = t - Math.sqrt(r * r - d2);
  return hit >= 0 ? hit : t;
}

/** Ближайшая посадка на луче: индекс в bodies или -1. */
export function pick(ray: Ray, bodies: readonly Body[], range = PICK_RANGE_M): number {
  let best = -1;
  let bestT = range;
  for (let i = 0; i < bodies.length; i++) {
    const body = bodies[i];
    if (!body) continue;
    const t = hitCrown(ray, body);
    if (t !== null && t < bestT) {
      bestT = t;
      best = i;
    }
  }
  return best;
}
