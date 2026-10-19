/* Подгонка модели дерева под размеры плана.
 *
 * Модель ez-tree растёт по своим правилам: ширина кроны по двум осям разная, отдельные листья
 * торчат далеко за силуэт, и масштаб по рамке листвы давал крону уже, чем в подписи. Здесь
 * размеры модели меряются так, как их видит глаз: ширина - по 0,5-99,5 % листвы вдоль каждой оси,
 * высота - верх 99,5 % всех вершин. Масштаб по осям ставит обе ширины ровно в диаметр кроны
 * плана, высоту - в высоту вида: подпись в 3D-виде и рамка размеров совпадают с моделью. */

export interface Measured {
  /** Ширина кроны вдоль X и Z модели и высота до верха, в единицах модели. */
  widthX: number;
  widthZ: number;
  height: number;
  /** Середина кроны относительно ствола (ствол модели - в начале координат). */
  centerX: number;
  centerZ: number;
}

export const SIDE_QUANTILES = [0.005, 0.995] as const;
export const TOP_QUANTILE = 0.995;
const MIN_SIZE = 1e-3;

/** Квантиль отсортированного массива (линейная интерполяция). */
export function quantile(sorted: Float32Array | number[], q: number): number {
  if (!sorted.length) return 0;
  const at = (sorted.length - 1) * q;
  const lo = Math.floor(at);
  const hi = Math.min(lo + 1, sorted.length - 1);
  const a = sorted[lo] ?? 0;
  const b = sorted[hi] ?? a;
  return a + (b - a) * (at - lo);
}

function column(positions: ArrayLike<number>, axis: number): Float32Array {
  const out = new Float32Array(Math.floor(positions.length / 3));
  for (let i = 0; i < out.length; i++) out[i] = positions[i * 3 + axis] ?? 0;
  return out.sort();
}

/** Размеры кроны по вершинам листвы и высота по вершинам всей модели (x, y, z подряд). */
export function measureCrown(leaves: ArrayLike<number>, all: ArrayLike<number>): Measured {
  const source = leaves.length >= 9 ? leaves : all;
  const xs = column(source, 0);
  const zs = column(source, 2);
  const ys = column(all.length ? all : source, 1);
  const [lo, hi] = SIDE_QUANTILES;
  const x0 = quantile(xs, lo);
  const x1 = quantile(xs, hi);
  const z0 = quantile(zs, lo);
  const z1 = quantile(zs, hi);
  return {
    widthX: Math.max(x1 - x0, MIN_SIZE),
    widthZ: Math.max(z1 - z0, MIN_SIZE),
    height: Math.max(quantile(ys, TOP_QUANTILE), MIN_SIZE),
    centerX: (x0 + x1) / 2,
    centerZ: (z0 + z1) / 2,
  };
}

/** Масштаб модели по осям, чтобы крона стала crown м в обе стороны, а верх - height м. */
export function fitScale(
  measured: Measured,
  crown: number,
  height: number,
): { x: number; y: number; z: number } {
  return {
    x: crown / measured.widthX,
    y: height / measured.height,
    z: crown / measured.widthZ,
  };
}
