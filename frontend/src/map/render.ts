/* Отрисовка карты: растровый кэш подосновы и живые отметки плана. Перенос из plan.js.
 *
 * Подоснова настоящей улицы - десятки тысяч кусков геометрии, и обходить их на каждый кадр
 * нельзя: на Камчатской это 110 мс на кадр, карта не едет за рукой. Поэтому подоснова
 * рисуется один раз в скрытый холст с запасом вокруг окна, а движение показывает готовую
 * картинку (4 мс). Начисто карта перерисовывается, когда рука остановилась. Посадки и отказы
 * остаются живыми: их двигают и подсвечивают. */

import type { MaterialLabel } from '../api/artifacts';
import type { Chunk } from './chunks';
import { MIN_PX } from './chunks';
import type { ExistingPlant } from './existing';
import type { Box } from './geometry';
import { EXISTING_SHRUB, EXISTING_TREE, modelKey, modelOf } from './models';
import { type Palette, VERDICT_TOKEN } from './palette';
import { paintMaterial, pinToScreen, type Textures, texturesFor } from './paper';
import { isWeak } from './picking';
import { type Look, sprite, stamp } from './sprites';
import type { Area, Layers, MapItem, SurfaceImage, ViewState } from './types';
import { niceLength, toScreen, worldBounds } from './view';

/** Запас растрового кэша вокруг окна, пикселей: панорама на это расстояние - просто перенос. */
export const PAD = 260;
/** Подписи покрытий видны с этого масштаба (пикселей на метр): на общем виде тысячи «А»
 *  сливаются в кашу и прячут сами линии. При 3 они уже висели на первом крупном виде
 *  (жюри, итерация 4), с 5 появляются, только когда человек сам приблизил карту. */
export const LABEL_MIN_SCALE = 5;
/** Клетка экрана для отсева наложенных подписей и зазор между ними, пикселей. */
const LABEL_CELL = 12;
const LABEL_GAP = 4;
/** Крона мельче этого на экране не рисуется: иначе на общем виде план вырождается в россыпь
 *  точек, и о трёхстах деревьях можно узнать только из числа в панели. */
export const MIN_CROWN_PX = 4;

export interface Scene {
  chunks: Chunk[];
  labels: MaterialLabel[];
  surface: SurfaceImage | null;
  /** Существующие деревья и кустарники подосновы: рисуются моделями, а не знаками съёмки. */
  existing: ExistingPlant[];
  placements: MapItem[];
  rejections: MapItem[];
}

export interface Marks {
  layers: Layers;
  speciesOff: ReadonlySet<string>;
  highlight: string | null;
  selected: MapItem | null;
  dragging: MapItem | null;
  dragVerdict: string | null;
  /** Режим правки: кроны прозрачные, стволы точками (look xray). */
  editing: boolean;
}

export interface BaseCache extends ViewState {
  dpr: number;
  width: number;
  height: number;
}

/** Матрица чертёж -> холст: Y в чертеже вверх, на холсте вниз, плюс разворот вдоль улицы. */
function worldTransform(
  ctx: CanvasRenderingContext2D,
  view: ViewState,
  dpr: number,
  dx = 0,
  dy = 0,
) {
  const s = view.scale * dpr;
  const c = Math.cos(view.rot);
  const sn = Math.sin(view.rot);
  ctx.setTransform(s * c, s * sn, s * sn, -s * c, (view.tx + dx) * dpr, (view.ty + dy) * dpr);
}

export function renderBase(
  base: HTMLCanvasElement,
  rect: { width: number; height: number },
  dpr: number,
  view: ViewState,
  scene: Scene,
  layers: Layers,
  palette: Palette,
): BaseCache {
  const width = rect.width + PAD * 2;
  const height = rect.height + PAD * 2;
  if (base.width !== Math.round(width * dpr) || base.height !== Math.round(height * dpr)) {
    base.width = Math.round(width * dpr);
    base.height = Math.round(height * dpr);
  }
  const ctx = base.getContext('2d');
  if (!ctx) return { ...view, dpr, width: rect.width, height: rect.height };
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, base.width, base.height);
  worldTransform(ctx, view, dpr, PAD, PAD);
  // Скошенные стыки вместо круглых: на линии в полтора пикселя разницы не видно, а обход
  // геометрии дешевле почти вдвое (62 мс против 110 мс на Камчатской).
  ctx.lineJoin = 'bevel';
  ctx.lineCap = 'butt';

  const visible = worldBounds(view, -PAD, -PAD, width, height);
  const textures = texturesFor(ctx, palette, dpr);
  const place = (target: CanvasRenderingContext2D) => {
    worldTransform(target, view, dpr, PAD, PAD);
  };
  // Газон и асфальт - под линиями: грунт и твёрдое так, как их понял сервис. Растр строкой 0
  // лежит на минимальном Y, и мировая матрица с разворотом Y кладёт его как надо. Клетка
  // растра на приближении крупнее бордюра: со сглаживанием её край не читается как ступень
  // чертежа.
  if (layers.surfacemap && scene.surface) {
    const { img, x, y, w, h, soil, paved } = scene.surface;
    if (textures && soil && paved) {
      paintMaterial(ctx, paved, scene.surface, textures.asphalt, place);
      paintMaterial(ctx, soil, scene.surface, textures.grass, place);
    } else {
      ctx.drawImage(img, x, y, w, h);
    }
  }
  const shown = scene.chunks.filter(
    (chunk) =>
      layers[chunk.group] &&
      chunk.span * view.scale >= MIN_PX &&
      chunk.maxX >= visible[0] &&
      chunk.minX <= visible[2] &&
      chunk.maxY >= visible[1] &&
      chunk.minY <= visible[3],
  );
  // Тени зданий - отдельным проходом до заливок: тень соседнего куска не ложится на крышу.
  // Сдвиг в экранных пикселях: свет на слайдах всегда слева сверху.
  worldTransform(ctx, view, dpr, PAD + SHADOW_PX, PAD + SHADOW_PX);
  ctx.fillStyle = palette.get('--c-shadow');
  for (const chunk of shown) if (chunk.shadow) ctx.fill(chunk.path);
  place(ctx);
  // Сети на бумаге тише, чем в CAD: на слайдах план - это газон, здания и посадки, а
  // сети - справка под ними. Насколько тише, решает тема (--utility-opacity).
  const utilityAlpha = Number.parseFloat(palette.get('--utility-opacity')) || 1;
  for (const chunk of shown) {
    ctx.globalAlpha = chunk.group === 'utilities' ? utilityAlpha : 1;
    if (chunk.fillVar) {
      ctx.fillStyle = palette.get(chunk.fillVar);
      ctx.fill(chunk.path);
      const texture = textureOf(chunk, textures);
      if (texture) {
        ctx.fillStyle = pinToScreen(ctx, texture);
        ctx.fill(chunk.path);
      }
    }
    if (chunk.strokeVar && chunk.width) {
      ctx.strokeStyle = palette.get(chunk.strokeVar);
      ctx.lineWidth = chunk.width / view.scale;
      if (chunk.dash.length) ctx.setLineDash(chunk.dash.map((d) => d / view.scale));
      ctx.stroke(chunk.path);
      if (chunk.dash.length) ctx.setLineDash([]);
    }
  }
  ctx.globalAlpha = 1;
  if (layers.existing && scene.existing.length) {
    drawExisting(ctx, visible, dpr, view, scene.existing, palette);
  }
  if (layers.labels && scene.labels.length && view.scale >= LABEL_MIN_SCALE) {
    drawLabels(ctx, visible, dpr, view, scene.labels, palette);
  }
  return { ...view, dpr, width: rect.width, height: rect.height };
}

/** Сдвиг тени здания, экранные пиксели. */
const SHADOW_PX = 4;

function textureOf(chunk: Chunk, textures: Textures | null): CanvasPattern | null {
  if (!textures || !chunk.texture) return null;
  return chunk.texture === 'grass' ? textures.grass : textures.hatch;
}

/** Существующие насаждения моделями в экранных пикселях подосновы: бледная крона с крестиком
 *  съёмки. Мельче MIN_CROWN_PX кроны тянутся до него, как и посадки плана. */
function drawExisting(
  ctx: CanvasRenderingContext2D,
  visible: Box,
  dpr: number,
  view: ViewState,
  plants: readonly ExistingPlant[],
  palette: Palette,
): void {
  // Цвет кроны - из темы: бледная на бумаге, приглушённая на графите, где бледная кричала бы.
  const treeTone = palette.get('--c-existing-crown');
  const shrubTone = palette.get('--c-existing-shrub');
  const tree = { ...EXISTING_TREE, tone: treeTone };
  const shrub = { ...EXISTING_SHRUB, tone: shrubTone };
  ctx.save();
  ctx.setTransform(dpr, 0, 0, dpr, PAD * dpr, PAD * dpr);
  for (const plant of plants) {
    if (plant.x < visible[0] - plant.r || plant.x > visible[2] + plant.r) continue;
    if (plant.y < visible[1] - plant.r || plant.y > visible[3] + plant.r) continue;
    const radius = Math.max(plant.r * view.scale, MIN_CROWN_PX * (plant.shrub ? 0.7 : 1));
    const key = plant.shrub ? `~existing-shrub|${shrubTone}` : `~existing-tree|${treeTone}`;
    const s = sprite(key, plant.shrub ? shrub : tree, radius, 'existing', dpr);
    const { sx, sy } = toScreen(view, plant.x, plant.y);
    stamp(ctx, s, sx, sy, radius);
  }
  ctx.restore();
}

/** Подписи материала с чертежа («А», «ГАЗОН», «ДЕТ.ПЛ.») в экранных пикселях: текст не
 *  вращается вместе с видом и не растёт с масштабом. */
function drawLabels(
  ctx: CanvasRenderingContext2D,
  visible: Box,
  dpr: number,
  view: ViewState,
  labels: readonly MaterialLabel[],
  palette: Palette,
): void {
  ctx.setTransform(dpr, 0, 0, dpr, PAD * dpr, PAD * dpr);
  ctx.font = `600 11px ${palette.get('--sans')}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.lineJoin = 'round';
  ctx.lineWidth = 3;
  ctx.strokeStyle = palette.get('--accent-halo');
  // Один нейтральный цвет: зелёным подпись «ГАЗОН» читалась как существующее дерево, а
  // материал и так назван словом.
  ctx.fillStyle = palette.get('--bone-3');
  // Подписи с чертежа стоят гуще, чем их можно прочесть: на месте, где уже есть подпись,
  // вторая не рисуется. Занятость считается по клеткам экрана.
  const taken = new Set<string>();
  for (const [x, y, text] of labels) {
    if (x < visible[0] || x > visible[2] || y < visible[1] || y > visible[3]) continue;
    const { sx, sy } = toScreen(view, x, y);
    const cells = labelCells(sx, sy, ctx.measureText(text).width / 2 + LABEL_GAP);
    if (cells.some((cell) => taken.has(cell))) continue;
    for (const cell of cells) taken.add(cell);
    ctx.strokeText(text, sx, sy);
    ctx.fillText(text, sx, sy);
  }
}

/** Клетки экрана, которые займёт подпись шириной 2 * half с центром в (sx, sy). */
function labelCells(sx: number, sy: number, half: number): string[] {
  const cells: string[] = [];
  const left = Math.floor((sx - half) / LABEL_CELL);
  const right = Math.floor((sx + half) / LABEL_CELL);
  const top = Math.floor((sy - 8) / LABEL_CELL);
  const bottom = Math.floor((sy + 8) / LABEL_CELL);
  for (let cx = left; cx <= right; cx++) {
    for (let cy = top; cy <= bottom; cy++) cells.push(`${String(cx)}:${String(cy)}`);
  }
  return cells;
}

/** Картинка кэша больше не закрывает окно: запас израсходован панорамой или зумом. */
export function uncovered(
  cache: BaseCache,
  view: ViewState,
  rect: { width: number; height: number },
): boolean {
  const k = view.scale / cache.scale;
  const left = (-PAD - cache.tx) * k + view.tx;
  const right = (cache.width + PAD - cache.tx) * k + view.tx;
  const top = (-PAD - cache.ty) * k + view.ty;
  const bottom = (cache.height + PAD - cache.ty) * k + view.ty;
  return left > 0 || top > 0 || right < rect.width || bottom < rect.height;
}

/** Координатная сетка чертёжного листа в круглых метрах. Привязана к осям экрана, а не
 *  чертежа: при развороте вдоль улицы наклонная сетка спорила бы с самим планом. */
export function drawGrid(
  ctx: CanvasRenderingContext2D,
  dpr: number,
  rect: { width: number; height: number },
  view: ViewState,
  palette: Palette,
): void {
  const stepM = niceLength(90 / view.scale);
  const step = stepM * view.scale;
  if (step < 14 || !Number.isFinite(step)) return;
  ctx.save();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.strokeStyle = palette.get('--grid');
  ctx.lineWidth = 1;
  ctx.beginPath();
  // Остаток берётся с приведением к положительному: при отрицательном сдвиге первая линия
  // иначе уезжает за левый край, и сетка съезжает на шаг.
  for (let x = ((view.tx % step) + step) % step; x < rect.width; x += step) {
    ctx.moveTo(Math.round(x) + 0.5, 0);
    ctx.lineTo(Math.round(x) + 0.5, rect.height);
  }
  for (let y = ((view.ty % step) + step) % step; y < rect.height; y += step) {
    ctx.moveTo(0, Math.round(y) + 0.5);
    ctx.lineTo(rect.width, Math.round(y) + 0.5);
  }
  ctx.stroke();
  ctx.restore();
}

/** Масштабная линейка. На чертеже она есть всегда, а весь спор в этом кейсе - про метры. */
export function drawScaleBar(
  ctx: CanvasRenderingContext2D,
  area: Area,
  view: ViewState,
  palette: Palette,
  font: string,
): void {
  const meters = niceLength(150 / view.scale);
  const width = meters * view.scale;
  if (width < 30 || width > area.width / 2) return;
  const right = area.left + area.width - 64;
  const left = right - width;
  const y = area.top + area.height - 26;
  const bar = new Path2D();
  bar.moveTo(left, y);
  bar.lineTo(right, y);
  for (const x of [left, (left + right) / 2, right]) {
    bar.moveTo(x, y - 4);
    bar.lineTo(x, y + 4);
  }
  const label = `${String(meters)} м`;
  const cx = (left + right) / 2;
  ctx.save();
  ctx.lineCap = 'butt';
  ctx.lineJoin = 'round';
  ctx.font = `500 12px ${font}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'bottom';
  // Плашка цвета панели: на приближении под линейкой лежат кроны, и обводки у штрихов мало.
  plate(ctx, palette, () => {
    ctx.roundRect(left - 12, y - 25, width + 24, 35, 6);
  });
  // Подложка цвета фона: линейка лежит поверх чертежа и обязана читаться над любой линией.
  ctx.strokeStyle = palette.get('--accent-halo');
  ctx.lineWidth = 4;
  ctx.stroke(bar);
  ctx.strokeText(label, cx, y - 7);
  ctx.strokeStyle = palette.get('--bone-3');
  ctx.fillStyle = palette.get('--bone-3');
  ctx.lineWidth = 1.5;
  ctx.stroke(bar);
  ctx.fillText(label, cx, y - 7);
  ctx.restore();
}

/** Виден ли объект в кадре. Запас - крона: центр бывает за краем, а крона в кадре. */
function inView(item: MapItem, visible: Box, pad: number): boolean {
  return (
    item.x >= visible[0] - pad &&
    item.x <= visible[2] + pad &&
    item.y >= visible[1] - pad &&
    item.y <= visible[3] + pad
  );
}

/** Отметки плана: вызывающий уже поставил мировую матрицу. Кроны моделей кладутся в экранных
 *  пикселях (dpr - плотность холста), отказы и знаки - в мировых координатах. */
export function drawPlan(
  ctx: CanvasRenderingContext2D,
  visible: Box,
  view: ViewState,
  scene: Scene,
  marks: Marks,
  palette: Palette,
  dpr: number,
): void {
  if (marks.layers.rejections) drawRejections(ctx, visible, view, scene, palette);
  if (marks.layers.barrier) drawBarrierPlaces(ctx, visible, view, scene, palette);
  if (marks.layers.placements) drawPlacements(ctx, visible, view, scene, marks, palette, dpr);
  if (marks.layers.placements && marks.layers.weak)
    drawWeak(ctx, visible, view, scene, marks, palette);
}

/** Посадки моделями видов (models.ts): крона своей формы и цвета, тень, ствол. Вердикт виден
 *  отдельно: «требует согласования» - пунктирное кольцо поверх кроны, иначе цвет кроны спорил
 *  бы с цветом вида. */
function drawPlacements(
  ctx: CanvasRenderingContext2D,
  visible: Box,
  view: ViewState,
  scene: Scene,
  marks: Marks,
  palette: Palette,
  dpr: number,
): void {
  const minRadius = MIN_CROWN_PX / view.scale;
  // При подсветке вида его кроны подрастают: на общем виде разница одной прозрачности на
  // кроне в четыре пикселя почти не читается.
  const liftRadius = (MIN_CROWN_PX + 2.5) / view.scale;
  // Кольца вердикта: needs_approval - янтарное, запрет после переноса - красное.
  const rings = new Map<string, Path2D>();
  // В режиме правки кроны прозрачные, стволы - точками (look xray): в перекрытых кронах видно,
  // за что хватать. Выбранная и перетаскиваемая остаются обычными и ложатся поверх всех.
  const top = new Set<MapItem>();
  if (marks.editing) {
    if (marks.selected?.kind === 'placement') top.add(marks.selected);
    if (marks.dragging) top.add(marks.dragging);
  }
  const put = (p: MapItem, look: Look, lifted: boolean) => {
    const radius = Math.max(p.radius, lifted ? liftRadius : minRadius) * view.scale;
    const key = modelKey(p.species_code, p.planting_type);
    const s = sprite(key, modelOf(p.species_code, p.planting_type), radius, look, dpr);
    const { sx, sy } = toScreen(view, p.x, p.y);
    stamp(ctx, s, sx, sy, radius);
    if (look !== 'dim' && p.verdict !== 'allowed') {
      const token = VERDICT_TOKEN[p.verdict] ?? '--warn';
      let ring = rings.get(token);
      if (!ring) {
        ring = new Path2D();
        rings.set(token, ring);
      }
      ring.moveTo(sx + radius + 3, sy);
      ring.arc(sx, sy, radius + 3, 0, Math.PI * 2);
    }
  };
  ctx.save();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  // Приглушённые рисуются первым проходом, чтобы подсвеченный вид лёг поверх. Приглушённые не
  // исчезают: подсветка вида оставляет план на месте, иначе вместо «где эти тридцать»
  // получается «где остальные двести семьдесят».
  for (const pass of [true, false]) {
    for (const p of scene.placements) {
      if (marks.speciesOff.has(p.species_code ?? '') || top.has(p)) continue;
      const dim = marks.highlight !== null && p.species_code !== marks.highlight;
      if (dim !== pass) continue;
      if (!inView(p, visible, p.radius + liftRadius)) continue;
      const lifted = !dim && marks.highlight !== null;
      put(p, dim ? 'dim' : lifted ? 'lift' : marks.editing ? 'xray' : 'plan', lifted);
    }
  }
  for (const p of top) {
    if (marks.speciesOff.has(p.species_code ?? '')) continue;
    if (!inView(p, visible, p.radius + liftRadius)) continue;
    put(p, 'plan', false);
  }
  ctx.setLineDash([4, 3]);
  for (const [token, ring] of rings) {
    ctx.lineWidth = 3.5;
    ctx.strokeStyle = palette.get('--accent-halo');
    ctx.stroke(ring);
    ctx.lineWidth = 1.8;
    ctx.strokeStyle = palette.get(token);
    ctx.stroke(ring);
  }
  ctx.setLineDash([]);
  ctx.restore();
}

function drawRejections(
  ctx: CanvasRenderingContext2D,
  visible: Box,
  view: ViewState,
  scene: Scene,
  palette: Palette,
): void {
  const path = new Path2D();
  const r = Math.max(1.2, 3 / view.scale);
  for (const p of scene.rejections) {
    if (!inView(p, visible, r)) continue;
    path.moveTo(p.x - r, p.y - r);
    path.lineTo(p.x + r, p.y + r);
    path.moveTo(p.x - r, p.y + r);
    path.lineTo(p.x + r, p.y - r);
  }
  ctx.strokeStyle = palette.get('--bad');
  ctx.lineWidth = 1 / view.scale;
  ctx.stroke(path);
}

/** Слабое место - треугольник над кроной без цвета вердикта: посадка допустима, слабость не
 *  в норме, а в качестве плана. */
function drawWeak(
  ctx: CanvasRenderingContext2D,
  visible: Box,
  view: ViewState,
  scene: Scene,
  marks: Marks,
  palette: Palette,
): void {
  const size = 4.5 / view.scale;
  const path = new Path2D();
  for (const p of scene.placements) {
    if (!isWeak(p) || marks.speciesOff.has(p.species_code ?? '')) continue;
    if (!inView(p, visible, p.radius + size * 3)) continue;
    const top = p.y + Math.max(p.radius, MIN_CROWN_PX / view.scale) + size * 1.6;
    path.moveTo(p.x, top - size);
    path.lineTo(p.x + size, top + size * 0.8);
    path.lineTo(p.x - size, top + size * 0.8);
    path.closePath();
  }
  ctx.lineWidth = 3 / view.scale;
  ctx.strokeStyle = palette.get('--accent-halo');
  ctx.stroke(path);
  ctx.fillStyle = palette.get('--bone');
  ctx.fill(path);
}

/** Отказ, который снял бы прикорневой барьер: пунктирное кольцо цвета «на согласование». */
function drawBarrierPlaces(
  ctx: CanvasRenderingContext2D,
  visible: Box,
  view: ViewState,
  scene: Scene,
  palette: Palette,
): void {
  const r = Math.max(2.2, 6 / view.scale);
  const path = new Path2D();
  for (const p of scene.rejections) {
    if (p.barrier_m == null || !inView(p, visible, r)) continue;
    path.moveTo(p.x + r, p.y);
    path.arc(p.x, p.y, r, 0, Math.PI * 2);
  }
  ctx.setLineDash([3 / view.scale, 2.5 / view.scale]);
  ctx.strokeStyle = palette.get('--warn');
  ctx.lineWidth = 1.4 / view.scale;
  ctx.stroke(path);
  ctx.setLineDash([]);
}

/** Кольцо с подложкой цвета фона и четыре засечки: на общем виде среди трёхсот одинаковых
 *  кружков выбранный иначе не найти. Рисуется в экранных пикселях. */
function ring(
  ctx: CanvasRenderingContext2D,
  item: MapItem,
  color: string,
  width: number,
  view: ViewState,
  palette: Palette,
): void {
  const { sx, sy } = toScreen(view, item.x, item.y);
  const radius = Math.max((item.radius || 1) * view.scale, 9) + 4;
  ctx.lineWidth = width + 3;
  ctx.strokeStyle = palette.get('--accent-halo');
  ctx.beginPath();
  ctx.arc(sx, sy, radius, 0, Math.PI * 2);
  ctx.stroke();
  ctx.lineWidth = width;
  ctx.strokeStyle = color;
  ctx.stroke();
  ctx.beginPath();
  for (const [dx, dy] of [
    [0, -1],
    [0, 1],
    [-1, 0],
    [1, 0],
  ] as const) {
    ctx.moveTo(sx + dx * (radius + 3), sy + dy * (radius + 3));
    ctx.lineTo(sx + dx * (radius + 9), sy + dy * (radius + 9));
  }
  ctx.lineWidth = width + 3;
  ctx.strokeStyle = palette.get('--accent-halo');
  ctx.stroke();
  ctx.lineWidth = width;
  ctx.strokeStyle = color;
  ctx.stroke();
}

/** Выбранная посадка и перетаскиваемая - в экранных пикселях. Перетаскиваемая рисуется цветом
 *  живого вердикта: запрет виден до того, как отпущена кнопка. */
export function drawSelection(
  ctx: CanvasRenderingContext2D,
  view: ViewState,
  marks: Marks,
  palette: Palette,
): void {
  ctx.lineCap = 'round';
  if (marks.dragging) {
    const token = marks.dragVerdict ? VERDICT_TOKEN[marks.dragVerdict] : undefined;
    ring(ctx, marks.dragging, palette.get(token ?? '--accent'), 2.5, view, palette);
  }
  if (marks.selected) ring(ctx, marks.selected, palette.get('--accent'), 2, view, palette);
}

/** Стрелка севера. Север в чертеже - это +Y, и после разворота вида он больше не наверху:
 *  без стрелки план читается как произвольно повёрнутая картинка. */
export function drawNorth(
  ctx: CanvasRenderingContext2D,
  area: Area,
  view: ViewState,
  palette: Palette,
  font: string,
): void {
  const x = area.left + area.width - 26;
  const y = area.top + area.height - 44;
  const nx = Math.sin(view.rot);
  const ny = -Math.cos(view.rot);
  const len = 15;
  ctx.save();
  ctx.translate(x, y);
  plate(ctx, palette, () => {
    ctx.arc(0, 0, 31, 0, Math.PI * 2);
  });
  ctx.strokeStyle = palette.get('--bone-3');
  ctx.fillStyle = palette.get('--bone-3');
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(-nx * len, -ny * len);
  ctx.lineTo(nx * len, ny * len);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(nx * len, ny * len);
  ctx.lineTo(nx * (len - 7) - ny * 4, ny * (len - 7) + nx * 4);
  ctx.lineTo(nx * (len - 7) + ny * 4, ny * (len - 7) - nx * 4);
  ctx.closePath();
  ctx.fill();
  ctx.font = `500 12px ${font}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('С', nx * (len + 10), ny * (len + 10));
  ctx.restore();
}

/** Полупрозрачная плашка цвета панели под служебным знаком карты (масштаб, север). */
function plate(ctx: CanvasRenderingContext2D, palette: Palette, shape: () => void): void {
  ctx.save();
  ctx.globalAlpha = 0.8;
  ctx.fillStyle = palette.get('--panel');
  ctx.beginPath();
  shape();
  ctx.fill();
  ctx.restore();
}

export { worldTransform };
