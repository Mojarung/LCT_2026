/** Место на плане из ссылки: #x=9125.5&y=-8905.2&m=0.05 - центр в точке чертежа (метры) и m
 *  метров на пиксель, север сверху. Такой ссылкой делятся местом: «посмотри вот сюда». */
export function parseViewHash(hash: string): { x: number; y: number; m: number } | null {
  const params = new URLSearchParams(hash.replace(/^#/, ''));
  const rawX = params.get('x');
  const rawY = params.get('y');
  if (rawX === null || rawY === null) return null;
  const x = Number(rawX);
  const y = Number(rawY);
  const m = Number(params.get('m') ?? 0.1);
  if (!Number.isFinite(x) || !Number.isFinite(y) || !(m > 0)) return null;
  return { x, y, m };
}
