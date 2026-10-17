/* Адаптивное качество 3D-вида: кадр держится не ниже порога на любом компьютере.
 *
 * Сцена следит за временем кадра (сглаженным за секунду). Не укладывается в TARGET_FPS -
 * сначала снижается разрешение рендера (до MIN_SCALE от выбранного на пульте), потом дальность
 * детализации крон (до MIN_LOD). Появился запас выше RECOVER_FPS - возвращается в обратном
 * порядке. Шаги не чаще раза в COOLDOWN_S, первые WARMUP_S после старта не считаются: там
 * собираются шейдеры. Кадр длиннее полсекунды - вкладка была скрыта, его тоже не считаем. */

export const TARGET_FPS = 50;
export const RECOVER_FPS = 72;
const MIN_SCALE = 0.55;
const MIN_LOD = 0.45;
const SCALE_STEP = 0.85;
const LOD_STEP = 0.75;
const COOLDOWN_S = 1.2;
const WARMUP_S = 2;
const SMOOTH = 0.1;
const STALL_S = 0.5;

export class AdaptiveQuality {
  /** Доля разрешения от выбранного качества, 0,55..1. */
  scale = 1;
  /** Доля дальности детализации крон, 0,45..1. */
  lod = 1;
  private average = 0;
  private started = -1;
  private lastStep = -Infinity;

  /** Учесть кадр длительностью dt секунд в момент now (секунды). True - качество изменилось. */
  sample(dt: number, now: number): boolean {
    if (dt <= 0 || dt > STALL_S) return false;
    if (this.started < 0) this.started = now;
    this.average = this.average ? this.average + (dt - this.average) * SMOOTH : dt;
    if (now - this.started < WARMUP_S || now - this.lastStep < COOLDOWN_S) return false;
    const fps = 1 / this.average;
    if (fps < TARGET_FPS) {
      if (this.scale > MIN_SCALE) this.scale = Math.max(MIN_SCALE, this.scale * SCALE_STEP);
      else if (this.lod > MIN_LOD) this.lod = Math.max(MIN_LOD, this.lod * LOD_STEP);
      else return false;
    } else if (fps > RECOVER_FPS) {
      if (this.lod < 1) this.lod = Math.min(1, this.lod / LOD_STEP);
      else if (this.scale < 1) this.scale = Math.min(1, this.scale / SCALE_STEP);
      else return false;
    } else {
      return false;
    }
    this.lastStep = now;
    return true;
  }

  /** Новая сцена или смена качества на пульте: начать подбор заново. */
  reset(): void {
    this.scale = 1;
    this.lod = 1;
    this.average = 0;
    this.started = -1;
    this.lastStep = -Infinity;
  }
}
