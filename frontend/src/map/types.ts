/* Типы движка карты. Движок не знает про React: страница отдаёт ему данные и получает
 * события через EngineHooks. */

import type { Assortment, PlantingValue, RuleCheck } from '../api/artifacts';

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
 *  они только засоряют план. Слабые места тоже: чёрный треугольник был самым контрастным
 *  знаком обзора и главным, что запоминалось о плане (жюри дизайна, итерация 7); их
 *  включают галочкой в обозначениях, когда план разбирают. Карта покрытий включена: это
 *  газон и асфальт бумажной подосновы, по ним же видно, как сервис понял участок. */
export const DEFAULT_LAYERS: Layers = {
  utilities: true,
  surfaces: true,
  buildings: true,
  existing: true,
  placements: true,
  rejections: false,
  weak: false,
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
  /** Почему выбран вид (только у посадок). */
  assortment?: Assortment | null;
  note?: string;
  barrier_m?: number | null;
}

/** Ответ живой проверки точки при переносе: вердикт и трасса правил сервиса. По трассе карта
 *  рисует выноски у перетаскиваемой посадки, как у выбранной. */
export interface DragProbe {
  verdict: string;
  checks: readonly RuleCheck[];
}

/** Карта покрытий растром, привязанная к координатам чертежа. */
export interface SurfaceImage {
  img: CanvasImageSource;
  x: number;
  y: number;
  w: number;
  h: number;
  /** Маски грунта и твёрдого покрытия: по ним подоснова красится газоном и асфальтом. */
  soil: CanvasImageSource | null;
  paved: CanvasImageSource | null;
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
  /** Под щелчком стволы нескольких посадок: выбор за человеком. items - ближайшие первыми,
   *  x и y - точка щелчка в пикселях холста. */
  ambiguous(items: MapItem[], x: number, y: number): void;
}
