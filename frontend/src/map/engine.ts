/* Движок карты плана: состояние вида, растровый кэш, ввод. Перенос static/plan.js без
 * изменения алгоритмов; React отдаёт ему данные и получает события через EngineHooks.
 *
 * Три вещи определяют конструкцию:
 * 1. На настоящем чертеже десятки тысяч объектов, поэтому геометрия собирается в Path2D один раз
 *    в координатах чертежа, а зум, панорама и разворот делаются трансформацией холста.
 * 2. Цвета берутся из CSS-переменных: тема переключается в одном месте, карта следует за ней.
 * 3. Вид разворачивается вдоль улицы: участок работ - лента. */

import type { BasemapJson } from '../api/artifacts';
import { parseViewHash } from '../lib/viewHash';
import { buildChunks } from './chunks';
import { type Box, boundsOfPoints, contentPoints, type Point, principalAxis } from './geometry';
import { Palette } from './palette';
import { orderItems, pick, shown } from './picking';
import {
  type BaseCache,
  drawGrid,
  drawNorth,
  drawPlan,
  drawScaleBar,
  drawSelection,
  type Marks,
  PAD,
  renderBase,
  type Scene,
  uncovered,
  worldTransform,
} from './render';
import {
  type Area,
  DEFAULT_LAYERS,
  type EngineHooks,
  type Layers,
  type MapItem,
  type SurfaceImage,
  type ViewState,
} from './types';
import {
  extentOf,
  fitView,
  focusOf,
  scaleFromShare,
  toScreen,
  toWorld,
  worldBounds,
  zoomAt,
  zoomShare,
} from './view';

/** Через сколько после остановки руки карта перерисовывается начисто. */
const SETTLE_MS = 110;
/** Длительность довоза вида до выбранной посадки. Единственная анимация на странице, и она
 *  служебная: при выборе с клавиатуры скачок карты неотличим от перезагрузки. */
const PAN_MS = 220;
/** Живая проверка точки при переносе - не чаще раза в столько миллисекунд. */
const PROBE_MS = 120;
/** Шаг сдвига с клавиатуры (Alt со стрелками) и крупный шаг (Alt+Shift), метров. */
const NUDGE_M = 0.5;
const NUDGE_FAR_M = 2;
/** Сдвиг с клавиатуры уходит на сервер, когда стрелки отпустили на столько миллисекунд:
 *  десять нажатий подряд - одна правка, а не десять. */
const NUDGE_COMMIT_MS = 450;
/** Направление сдвига на экране по стрелке: x вправо, y вниз. */
const NUDGE_KEYS: Record<string, readonly [number, number]> = {
  ArrowRight: [1, 0],
  ArrowLeft: [-1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};
/** Отступ свободной области от панелей, пикселей. */
const PANEL_GAP = 14;

const validBox = (box: Box | null | undefined): Box | null =>
  box && (box[2] - box[0] > 0 || box[3] - box[1] > 0) ? box : null;

export class PlanEngine {
  private readonly view: ViewState = { scale: 1, tx: 0, ty: 0, rot: 0 };
  private readonly scene: Scene = {
    chunks: [],
    labels: [],
    surface: null,
    placements: [],
    rejections: [],
  };
  private readonly marks: Marks = {
    layers: DEFAULT_LAYERS,
    speciesOff: new Set(),
    highlight: null,
    selected: null,
    dragging: null,
    dragVerdict: null,
  };
  private readonly palette = new Palette();
  private readonly base = document.createElement('canvas');
  private readonly cleanup: (() => void)[] = [];
  private outline: Point[] = [];
  private mapBox: Box | null = null;
  private bbox: Box | null = null;
  private axis = 0;
  private fitScale = 0;
  /** Человек сам трогал вид: после этого вид не пересобирается, а удерживается. */
  private touched = false;
  private editing = false;
  /** Следующий клик по карте переносит выбранную посадку туда (перенос без перетаскивания). */
  private placing = false;
  private nudgeTimer = 0;
  private ordered: MapItem[] = [];
  private cache: BaseCache | null = null;
  private frame = 0;
  private settleTimer = 0;
  private pan = 0;
  private lastCenter: Point | null = null;
  private reportedScale = 0;

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly root: HTMLElement,
    private readonly hooks: EngineHooks,
  ) {
    this.bindInput();
    const resize = new ResizeObserver(() => {
      this.relayout();
    });
    resize.observe(canvas);
    this.cleanup.push(() => {
      resize.disconnect();
    });
    // Тема меняет цвета из CSS-переменных: сбросить их кэш и перерисовать карту.
    const theme = new MutationObserver(() => {
      this.repaint();
    });
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    const scheme = window.matchMedia('(prefers-color-scheme: dark)');
    const onScheme = () => {
      this.repaint();
    };
    scheme.addEventListener('change', onScheme);
    this.cleanup.push(() => {
      theme.disconnect();
      scheme.removeEventListener('change', onScheme);
    });
    this.resize();
  }

  destroy(): void {
    clearTimeout(this.nudgeTimer);
    cancelAnimationFrame(this.frame);
    cancelAnimationFrame(this.pan);
    clearTimeout(this.settleTimer);
    for (const undo of this.cleanup.splice(0)) undo();
  }

  /* ---------- данные ---------- */

  /** Подоснова: чертёж становится картой, по которой можно ездить, пока считаются посадки. */
  setBasemap(basemap: BasemapJson): void {
    this.scene.chunks = buildChunks(basemap.features, basemap.bbox);
    this.scene.labels = basemap.labels ?? [];
    this.outline = contentPoints(basemap.features);
    this.mapBox = validBox(basemap.bbox);
    if (!this.hasPlan()) {
      // Пока посадок нет, опора вписывания и разворота - центры объектов подосновы.
      this.bbox = boundsOfPoints(this.outline, 25) ?? this.mapBox;
      if (!this.touched) {
        this.axis = principalAxis(this.outline);
        this.view.rot = this.axis;
      }
    }
    this.layout();
  }

  /** План: вид подгоняется под посадки, а не под всю подоснову - на генплане она раскинута на
   *  километры из-за нескольких далёких объектов, и участок в таком окне стал бы точкой. */
  setPlan(placements: MapItem[], rejections: MapItem[]): void {
    this.scene.placements = placements;
    this.scene.rejections = rejections;
    const all = [...placements, ...rejections];
    this.bbox = boundsOfPoints(all, 25) ?? this.bbox ?? this.mapBox;
    this.axis = principalAxis(placements.length ? placements : rejections);
    if (!this.touched) this.view.rot = this.axis;
    this.ordered = orderItems(all, this.view.rot);
    if (this.marks.selected && !all.includes(this.marks.selected)) this.select(null);
    this.layout();
  }

  setSurface(surface: SurfaceImage | null): void {
    this.scene.surface = surface;
    this.invalidate();
    this.schedule();
  }

  setLayers(layers: Layers): void {
    this.marks.layers = layers;
    this.dropHiddenSelection();
    this.invalidate();
    this.schedule();
  }

  setSpeciesOff(codes: ReadonlySet<string>): void {
    this.marks.speciesOff = codes;
    this.dropHiddenSelection();
    this.schedule();
  }

  setHighlight(code: string | null): void {
    this.marks.highlight = code;
    this.schedule();
  }

  setSelected(item: MapItem | null): void {
    if (item !== this.marks.selected) this.setPlacing(false);
    this.marks.selected = item;
    this.schedule();
  }

  setEditing(on: boolean): void {
    this.editing = on;
    this.canvas.classList.toggle('editable', on);
    if (!on) this.setPlacing(false);
  }

  /** Перенос без перетаскивания (WCAG 2.2, 2.5.7): следующий клик по карте становится новым
   *  местом выбранной посадки. Работает только в режиме правки и только для посадки. */
  armPlacing(): boolean {
    if (!this.editing || this.marks.selected?.kind !== 'placement') return false;
    this.setPlacing(true);
    return true;
  }

  cancelPlacing(): void {
    this.setPlacing(false);
  }

  private setPlacing(on: boolean): void {
    if (this.placing === on) return;
    this.placing = on;
    this.canvas.classList.toggle('placing', on);
    this.hooks.placingChanged(on);
  }

  setDragVerdict(verdict: string | null): void {
    this.marks.dragVerdict = verdict;
    this.schedule();
  }

  /** Отметка изменилась (перенос, новый вердикт): перерисовать живой слой. */
  touchItems(): void {
    this.ordered = orderItems([...this.scene.placements, ...this.scene.rejections], this.view.rot);
    this.schedule();
  }

  /* ---------- вид ---------- */

  /** Вписать план. whole - весь, close - лента крупно (вид при открытии, см. view.fitView). */
  fit(mode: 'whole' | 'close' = 'whole'): void {
    if (!this.bbox) return;
    const points = this.extentPoints();
    const ext = extentOf(this.view, points);
    const area = this.clearArea();
    this.fitScale = fitView(ext, area, 'whole').scale;
    // Внимание - на посадках: отказы теснятся у сетей и тянули бы вид в узел коммуникаций.
    const focus = focusOf(this.view, this.scene.placements.length ? this.scene.placements : points);
    Object.assign(this.view, fitView(ext, area, mode, focus));
    this.touched = false;
    this.lastCenter = center(area);
    this.schedule();
  }

  zoomBy(factor: number): void {
    this.applyZoom(this.canvas.clientWidth / 2, this.canvas.clientHeight / 2, factor);
  }

  zoomShare(): number {
    return zoomShare(this.view.scale, this.fitScale || this.view.scale);
  }

  setZoomShare(share: number): void {
    const wanted = scaleFromShare(share, this.fitScale || this.view.scale);
    const area = this.clearArea();
    this.applyZoom(
      area.left + area.width / 2,
      area.top + area.height / 2,
      wanted / this.view.scale,
    );
  }

  orientation(): 'street' | 'north' {
    return this.view.rot !== 0 ? 'street' : 'north';
  }

  toggleOrientation(): void {
    this.view.rot = this.view.rot !== 0 ? 0 : this.axis;
    this.ordered = orderItems([...this.scene.placements, ...this.scene.rejections], this.view.rot);
    this.touched = false;
    this.sizeHolder();
    this.resize();
    this.fit('whole');
  }

  /** Вид из ссылки: #x=..&y=..&m=.. - центр в точке чертежа и метров на пиксель, север сверху. */
  applyHash(hash: string): boolean {
    const place = parseViewHash(hash);
    if (!place) return false;
    Object.assign(this.view, {
      rot: 0,
      scale: 1 / place.m,
      tx: this.canvas.clientWidth / 2 - place.x / place.m,
      ty: this.canvas.clientHeight / 2 + place.y / place.m,
    });
    this.touched = true;
    this.schedule();
    return true;
  }

  /** Панели сменили размер или окно: удержать вид за центр прежней свободной области, а
   *  нетронутый вид собрать заново. */
  relayout(): void {
    this.sizeHolder();
    this.resize();
    if (!this.bbox) return;
    const previous = this.lastCenter;
    if (!this.touched || !previous) {
      this.fit(this.hasPlan() || this.outline.length ? 'close' : 'whole');
      return;
    }
    const area = this.clearArea();
    this.view.tx += area.left + area.width / 2 - previous.x;
    this.view.ty += area.top + area.height / 2 - previous.y;
    this.lastCenter = center(area);
    // Сдвиг сохраняет масштаб, а он мог стать великоват: если от плана не осталось ничего
    // видимого - вид собирается заново.
    const ext = extentOf(this.view, this.extentPoints());
    const s = this.view.scale;
    const left = ext.minU * s + this.view.tx;
    const right = ext.maxU * s + this.view.tx;
    const top = ext.minV * s + this.view.ty;
    const bottom = ext.maxV * s + this.view.ty;
    const visible =
      right > area.left + 40 &&
      left < area.left + area.width - 40 &&
      bottom > area.top + 40 &&
      top < area.top + area.height - 40;
    if (!visible) this.fit('close');
    this.schedule();
  }

  /** Перерисовать начисто: вместе с подосновой могли смениться цвета темы. */
  repaint(): void {
    this.palette.clear();
    this.invalidate();
    this.schedule();
  }

  /* ---------- выбор с клавиатуры ---------- */

  step(delta: number): void {
    const list = this.ordered.filter((item) => this.isShown(item));
    if (!list.length) return;
    const at = this.marks.selected ? list.indexOf(this.marks.selected) : -1;
    const next =
      at < 0 ? (delta > 0 ? 0 : list.length - 1) : (at + delta + list.length) % list.length;
    this.select(list[next] ?? null);
    this.revealSelected();
  }

  centerSelected(): void {
    const item = this.marks.selected;
    if (!item) return;
    const area = this.clearArea();
    const { sx, sy } = toScreen(this.view, item.x, item.y);
    this.touched = true;
    this.panTo(
      this.view.tx + area.left + area.width / 2 - sx,
      this.view.ty + area.top + area.height / 2 - sy,
    );
  }

  /* ---------- внутреннее ---------- */

  private hasPlan(): boolean {
    return this.scene.placements.length > 0 || this.scene.rejections.length > 0;
  }

  private extentPoints(): Point[] {
    if (this.hasPlan()) return [...this.scene.placements, ...this.scene.rejections];
    if (this.outline.length) return this.outline;
    const [minX, minY, maxX, maxY] = this.bbox ?? [0, 0, 0, 0];
    return [
      { x: minX, y: minY },
      { x: minX, y: maxY },
      { x: maxX, y: minY },
      { x: maxX, y: maxY },
    ];
  }

  private isShown(item: MapItem): boolean {
    return shown(item, this.marks.layers, this.marks.speciesOff);
  }

  private select(item: MapItem | null): void {
    // Место указывают для той посадки, что была выбрана: сменился выбор - режим снят.
    if (item !== this.marks.selected) this.setPlacing(false);
    this.marks.selected = item;
    this.hooks.select(item);
    this.schedule();
  }

  private dropHiddenSelection(): void {
    if (this.marks.selected && !this.isShown(this.marks.selected)) this.select(null);
  }

  private layout(): void {
    if (!this.bbox) return;
    this.sizeHolder();
    this.resize();
    if (!this.touched) this.fit('close');
    this.invalidate();
    this.schedule();
  }

  /** Свободная область холста: панели лежат поверх плана и закрывают его края, поэтому
   *  вписывание считается по тому прямоугольнику, который действительно видно. */
  private clearArea(): Area {
    const rect = this.canvas.getBoundingClientRect();
    let left = 0;
    let right = rect.width;
    let top = 0;
    let bottom = rect.height;
    for (const panel of this.root.querySelectorAll<HTMLElement>('[data-map-obstacle="side"]')) {
      const box = panel.getBoundingClientRect();
      if (box.width === 0 || getComputedStyle(panel).position !== 'absolute') continue;
      if (box.left - rect.left < rect.width / 2)
        left = Math.max(left, box.right - rect.left + PANEL_GAP);
      else right = Math.min(right, box.left - rect.left - PANEL_GAP);
    }
    // Кнопки масштаба и полоса хода лежат по нижней кромке: план не прячется под ними.
    for (const strip of this.root.querySelectorAll<HTMLElement>('[data-map-obstacle="bottom"]')) {
      if (strip.hidden || getComputedStyle(strip).position !== 'absolute') continue;
      bottom = Math.min(bottom, strip.getBoundingClientRect().top - rect.top - PANEL_GAP);
    }
    // Значки шапки висят над правой панелью; отступ сверху нужен, только где они накрывают план.
    const bar = document.querySelector<HTMLElement>('.topbar');
    if (bar && getComputedStyle(bar).position === 'fixed') {
      const box = bar.getBoundingClientRect();
      if (box.left - rect.left < right) top = Math.max(top, box.bottom - rect.top + 12);
    }
    return {
      left,
      top,
      width: Math.max(right - left, 240),
      height: Math.max(bottom - top, 200),
    };
  }

  /** На узком экране высота карты подгоняется под форму участка: лента 6:1 в колодце 375 x 558
   *  занимает десятую часть площади, и первый экран телефона - пустое поле с ниткой. */
  private sizeHolder(): void {
    const holder = this.canvas.parentElement;
    if (!holder) return;
    if (getComputedStyle(holder).position === 'absolute' || !this.bbox) {
      holder.style.height = '';
      return;
    }
    const ext = extentOf(this.view, this.extentPoints());
    const width = holder.getBoundingClientRect().width;
    const wanted = (width * ext.h) / ext.w + 90;
    const limit = window.innerHeight * 0.62;
    holder.style.height = `${String(Math.round(Math.min(Math.max(wanted, 260), limit)))}px`;
  }

  private resize(): void {
    const rect = this.canvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.round(rect.width * dpr);
    const height = Math.round(rect.height * dpr);
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
      this.invalidate();
    }
    this.draw();
  }

  private invalidate(): void {
    this.cache = null;
  }

  private schedule(): void {
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this.draw();
    });
  }

  private settleLater(): void {
    clearTimeout(this.settleTimer);
    this.settleTimer = window.setTimeout(() => {
      this.invalidate();
      this.schedule();
    }, SETTLE_MS);
  }

  private draw(): void {
    const ctx = this.canvas.getContext('2d');
    if (!ctx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = this.canvas.getBoundingClientRect();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    // Сетка листа рисуется и пустой карте: пока чертёж читается, под полосой хода лежит лист,
    // на котором он появится.
    drawGrid(ctx, dpr, rect, this.view, this.palette);
    if (!this.bbox) return;

    const stale =
      !this.cache ||
      this.cache.rot !== this.view.rot ||
      this.cache.dpr !== dpr ||
      this.cache.width !== rect.width ||
      this.cache.height !== rect.height;
    if (stale || !this.cache) {
      this.cache = renderBase(
        this.base,
        rect,
        dpr,
        this.view,
        this.scene,
        this.marks.layers,
        this.palette,
      );
    }
    const cache = this.cache;
    // Перенос картинки: разницу масштаба между кадром и кэшем отрабатывает растяжение, поэтому
    // зум идёт гладко, а чёткость возвращается перерисовкой после остановки.
    const k = this.view.scale / cache.scale;
    ctx.setTransform(
      k * dpr,
      0,
      0,
      k * dpr,
      (this.view.tx - cache.tx * k) * dpr,
      (this.view.ty - cache.ty * k) * dpr,
    );
    ctx.drawImage(this.base, -PAD, -PAD, this.base.width / cache.dpr, this.base.height / cache.dpr);

    worldTransform(ctx, this.view, dpr);
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    const visible = worldBounds(this.view, 0, 0, rect.width, rect.height);
    drawPlan(ctx, visible, this.view, this.scene, this.marks, this.palette);

    // Отметка выбранного, север и линейка - в экранных пикселях: их размер не зависит от
    // масштаба, иначе на общем виде обводка вырождается в волос.
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const area = this.clearArea();
    const font = this.palette.get('--sans');
    drawSelection(ctx, this.view, this.marks, this.palette);
    drawNorth(ctx, area, this.view, this.palette, font);
    drawScaleBar(ctx, area, this.view, this.palette, font);

    if (this.view.scale !== this.reportedScale) {
      this.reportedScale = this.view.scale;
      this.hooks.viewChanged();
    }
    if (k !== 1 || uncovered(cache, this.view, rect)) this.settleLater();
  }

  private applyZoom(px: number, py: number, factor: number): void {
    Object.assign(this.view, zoomAt(this.view, px, py, factor));
    this.touched = true;
    this.schedule();
  }

  private panTo(tx: number, ty: number): void {
    cancelAnimationFrame(this.pan);
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced || (Math.abs(tx - this.view.tx) < 2 && Math.abs(ty - this.view.ty) < 2)) {
      this.view.tx = tx;
      this.view.ty = ty;
      this.schedule();
      return;
    }
    const from = { tx: this.view.tx, ty: this.view.ty };
    const started = performance.now();
    const tick = (now: number) => {
      const k = Math.min((now - started) / PAN_MS, 1);
      const eased = 1 - (1 - k) ** 3;
      this.view.tx = from.tx + (tx - from.tx) * eased;
      this.view.ty = from.ty + (ty - from.ty) * eased;
      this.draw();
      if (k < 1) this.pan = requestAnimationFrame(tick);
    };
    this.pan = requestAnimationFrame(tick);
  }

  /** Довести выбранное до видимой области, не меняя масштаб. */
  private revealSelected(): void {
    const item = this.marks.selected;
    if (!item) return;
    const area = this.clearArea();
    const { sx, sy } = toScreen(this.view, item.x, item.y);
    const pad = 60;
    let { tx, ty } = this.view;
    if (sx < area.left + pad) tx += area.left + pad - sx;
    if (sx > area.left + area.width - pad) tx += area.left + area.width - pad - sx;
    if (sy < area.top + pad) ty += area.top + pad - sy;
    if (sy > area.top + area.height - pad) ty += area.top + area.height - pad - sy;
    this.panTo(tx, ty);
  }

  /** Alt со стрелками двигает выбранную посадку по экрану на полметра (с Shift - на два),
   *  с живой проверкой точки; на сервер правка уходит одна, когда стрелки отпустили.
   *  Перенос мышью без клавиатурной замены - отказ по WCAG 2.1.1. */
  private nudge(key: string, far: boolean): boolean {
    const item = this.marks.selected;
    const direction = NUDGE_KEYS[key];
    if (!this.editing || item?.kind !== 'placement' || !direction) return false;
    const step = (far ? NUDGE_FAR_M : NUDGE_M) * this.view.scale;
    const at = toScreen(this.view, item.x, item.y);
    const world = toWorld(this.view, at.sx + direction[0] * step, at.sy + direction[1] * step);
    item.x = world.x;
    item.y = world.y;
    this.marks.dragging = item;
    this.hooks.probe(item, world.x, world.y);
    clearTimeout(this.nudgeTimer);
    this.nudgeTimer = window.setTimeout(() => {
      this.marks.dragging = null;
      this.marks.dragVerdict = null;
      this.hooks.move(item, item.x, item.y);
      this.schedule();
    }, NUDGE_COMMIT_MS);
    this.schedule();
    return true;
  }

  private worldOf(event: PointerEvent | MouseEvent): Point {
    const rect = this.canvas.getBoundingClientRect();
    return toWorld(this.view, event.clientX - rect.left, event.clientY - rect.top);
  }

  private pickAt(event: PointerEvent | MouseEvent): MapItem | null {
    return pick(
      this.worldOf(event),
      [...this.scene.placements, ...this.scene.rejections],
      this.view.scale,
      this.marks.layers,
      this.marks.speciesOff,
    );
  }

  private listen<K extends keyof HTMLElementEventMap>(
    type: K,
    handler: (event: HTMLElementEventMap[K]) => void,
    options?: AddEventListenerOptions,
  ): void {
    this.canvas.addEventListener(type, handler, options);
    this.cleanup.push(() => {
      this.canvas.removeEventListener(type, handler, options);
    });
  }

  private bindInput(): void {
    let dragging = false;
    let moved = 0;
    let last = { x: 0, y: 0 };
    let grabbed: MapItem | null = null;
    let probed = 0;
    let hovered = false;

    this.listen('pointerdown', (event) => {
      dragging = true;
      moved = 0;
      last = { x: event.clientX, y: event.clientY };
      // Пока ждём клик с новым местом, другую посадку не хватаем: клик ставит выбранную.
      const hit = this.editing && !this.placing ? this.pickAt(event) : null;
      grabbed = hit?.kind === 'placement' ? hit : null;
      this.canvas.setPointerCapture(event.pointerId);
      this.canvas.classList.add('dragging');
    });

    this.listen('pointermove', (event) => {
      if (!dragging) {
        // Курсор-указатель над посадкой: подсказка про клик без единого слова в панели.
        const over = this.pickAt(event) !== null;
        if (over !== hovered) {
          hovered = over;
          this.canvas.style.cursor = over ? 'pointer' : '';
        }
        return;
      }
      const dx = event.clientX - last.x;
      const dy = event.clientY - last.y;
      moved += Math.abs(dx) + Math.abs(dy);
      last = { x: event.clientX, y: event.clientY };
      if (grabbed) {
        const world = this.worldOf(event);
        grabbed.x = world.x;
        grabbed.y = world.y;
        this.marks.dragging = grabbed;
        if (event.timeStamp - probed > PROBE_MS) {
          probed = event.timeStamp;
          this.hooks.probe(grabbed, world.x, world.y);
        }
      } else {
        this.view.tx += dx;
        this.view.ty += dy;
        this.touched = true;
      }
      this.schedule();
    });

    this.listen('pointerup', (event) => {
      dragging = false;
      this.canvas.classList.remove('dragging');
      const item = grabbed;
      grabbed = null;
      this.marks.dragging = null;
      if (item && moved >= 4) {
        const world = this.worldOf(event);
        item.x = world.x;
        item.y = world.y;
        this.marks.dragVerdict = null;
        this.hooks.move(item, world.x, world.y);
        this.schedule();
        return;
      }
      this.marks.dragVerdict = null;
      const target = this.marks.selected;
      if (moved < 4 && this.placing && target?.kind === 'placement') {
        const world = this.worldOf(event);
        target.x = world.x;
        target.y = world.y;
        this.setPlacing(false);
        this.hooks.move(target, world.x, world.y);
        this.schedule();
        return;
      }
      if (moved < 4) this.select(this.pickAt(event));
      this.schedule();
    });

    // Карта доступна с клавиатуры: требование заказчика - увидеть норму по посадке - иначе
    // выполнимо только мышью, а это отказ по WCAG 2.1.1.
    this.listen('keydown', (event) => {
      const middle = () => ({ x: this.canvas.clientWidth / 2, y: this.canvas.clientHeight / 2 });
      const keys: Record<string, () => void> = {
        ArrowRight: () => {
          this.step(1);
        },
        ArrowDown: () => {
          this.step(1);
        },
        ArrowLeft: () => {
          this.step(-1);
        },
        ArrowUp: () => {
          this.step(-1);
        },
        Home: () => {
          this.marks.selected = null;
          this.step(1);
        },
        End: () => {
          this.marks.selected = null;
          this.step(-1);
        },
        Enter: () => {
          this.centerSelected();
        },
        ' ': () => {
          this.centerSelected();
        },
        Escape: () => {
          this.select(null);
        },
        '+': () => {
          this.applyZoom(middle().x, middle().y, 1.4);
        },
        '=': () => {
          this.applyZoom(middle().x, middle().y, 1.4);
        },
        '-': () => {
          this.applyZoom(middle().x, middle().y, 1 / 1.4);
        },
      };
      if (event.key === 'Delete' && this.editing && this.marks.selected?.kind === 'placement') {
        event.preventDefault();
        this.hooks.remove(this.marks.selected);
        return;
      }
      if (event.key === 'Escape' && this.placing) {
        event.preventDefault();
        this.setPlacing(false);
        return;
      }
      if (event.altKey && this.nudge(event.key, event.shiftKey)) {
        event.preventDefault();
        return;
      }
      const action = keys[event.key];
      if (!action) return;
      event.preventDefault();
      action();
    });

    this.listen(
      'wheel',
      (event) => {
        event.preventDefault();
        const rect = this.canvas.getBoundingClientRect();
        this.applyZoom(
          event.clientX - rect.left,
          event.clientY - rect.top,
          Math.exp(-event.deltaY * 0.0015),
        );
      },
      { passive: false },
    );
  }
}

function center(area: Area): Point {
  return { x: area.left + area.width / 2, y: area.top + area.height / 2 };
}
