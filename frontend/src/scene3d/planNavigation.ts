import type { Flat, World } from './types';

/** В плане север — +y, в 3D — -z; начало сцены вынесено из координат чертежа. */
export function planToScene(x: number, y: number, origin: World['origin']): Flat {
  return { x: x - origin[0], z: origin[1] - y };
}

export function sceneToPlan(point: Flat, origin: World['origin']) {
  return { x: point.x + origin[0], y: origin[1] - point.z };
}
