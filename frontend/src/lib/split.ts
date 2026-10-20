/** Доля высоты под схему участка в 3D-виде: от 20 до 80 %, как перемычка в просмотре улиц Google. */
export const SPLIT_MIN = 0.2;
export const SPLIT_MAX = 0.8;

export function clampSplit(value: number): number {
  return Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, value));
}
