/* Типы движка карты. Движок не знает про React: страница отдаёт ему данные и получает
 * события через EngineHooks. */

import type { PlantingValue, RuleCheck } from '../api/artifacts';

export type LayerKey =
  | 'utilities'
  | 'surfaces'
  | 'buildings'
  | 'existing'
  | 'placements'
  | 'rejections'
  | 'weak'
  | 'barrier'
  | 'surfacemap'
  | 'labels';

export type Layers = Record<LayerKey, boolean>;

/** Что видно по умолчанию: отказы выключены - их сотни, и без вопроса «почему здесь нет»
 *  они только засоряют план. */
export const DEFAULT_LAYERS: Layers = {
  utilities: true,
  surfaces: true,
  buildings: true,
  existing: true,
  placements: true,
  rejections: false,
  weak: true,
  barrier: true,
  surfacemap: true,
  labels: true,
};

/** Посадка или отказ на карте. Объект изменяемый: при переносе движок двигает его сам, а
 *  правка плана обновляет вердикт и проверки по ответу сервиса. */
export interface MapItem {
  kind: 'placement' | 'rejection';
  id: string;
  number: number;
  planting_type: string;
  x: number;
  y: number;
  radius: number;
  verdict: string;
  species_code?: string;
  species_ru?: string;
  species_lat?: string;
  explanation: string;
  value: PlantingValue | null;
  checks: RuleCheck[];
  note?: string;
  barrier_m?: number | null;
}

/** Карта покрытий растром, привязанная к координатам чертежа. */
export interface SurfaceImage {
  img: CanvasImageSource;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ViewState {
  scale: number;
  tx: number;
  ty: number;
  rot: number;
}

export interface Area {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface EngineHooks {
  /** Выбрана посадка или отказ (или выбор снят). */
  select(item: MapItem | null): void;
  /** Посадку тянут в режиме правки: живая проверка точки. */
  probe(item: MapItem, x: number, y: number): void;
  /** Посадку отпустили на новом месте. */
  move(item: MapItem, x: number, y: number): void;
  /** Delete в режиме правки. */
  remove(item: MapItem): void;
  /** Вид изменился: масштаб, сдвиг или разворот (для ползунка масштаба). */
  viewChanged(): void;
  /** Включён или снят режим «следующий клик по карте - новое место выбранной посадки». */
  placingChanged(on: boolean): void;
}
