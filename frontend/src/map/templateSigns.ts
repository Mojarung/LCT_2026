/* Знаки видов из «Шаблонов значков» заказчика: таблица «Ведомость элементов озеленения»
 * чертежа dataset/Датасет/Шаблоны значков.dwg задаёт свой знак каждому роду или виду -
 * хвойным, лиственным деревьям, кустарникам, лианам - и четыре знака существующих насаждений.
 *
 * Геометрия знаков - templateSigns.json, его пишет tools/extract_template_signs.py (шапка файла:
 * источник, дата, команда). Путь нормирован к радиусу 1, ось y вниз, цвета - из чертежа, ACI 7
 * записан как «ink»: на светлом листе он чёрный, в тёмной теме - светлый, как в модели CAD.
 *
 * Данные - отдельный файл сборки (1,3 МБ), а не часть бандла: они нужны только карте в стиле
 * чертежа и легенде. Пока файл не пришёл, карта рисует общие знаки дерева, хвойного и куста, а
 * после загрузки перерисовывается (onTemplateSigns).
 *
 * Знак на карте - спрайт: у части знаков сотни штрихов («Вяз», «Лапчатка»), а посадок на улице
 * тысячи. Спрайт рисуется один раз на знак, размер и тему; мельче TONE_PX знак - точка главного
 * цвета: деталь на трёх пикселях не читается, а цвет вида - читается. */

import signsUrl from './templateSigns.json?url';
import type { SignInk } from './signs';
import { quantize, type Sprite } from './sprites';

export type SignSection = 'conifer' | 'tree' | 'shrub' | 'liana' | 'existing';
/** [f - заливка | s - штрих, цвет #rrggbb или ink, непрозрачность, вес линии в мм, путь SVG]. */
export type SignPath = [kind: 'f' | 's', color: string, alpha: number, weight: number, d: string];

export interface TemplateSign {
  name: string;
  section: SignSection;
  position: string;
  blocks: string[];
  /** Главный цвет и его непрозрачность: знак на общем виде рисуется точкой этого цвета. */
  tone: [color: string, alpha: number];
  /** Меньшая сторона габарита к большей: у изгороди «З9» полоса облаков вдвое ниже ширины. */
  aspect: number;
  paths: SignPath[];
}

export interface TemplateSignFile {
  source: string;
  converter: string;
  command: string;
  generated: string;
  hash: string;
  empty_rows: string[];
  signs: TemplateSign[];
}

/** Основание: «вид» - строка шаблона называет сам вид («Сосна горная», «Туя западная»);
 *  «род» - строка называет род, и знак общий для всех его видов каталога («Липа» - липы
 *  мелколистная и крупнолистная). Род - по русскому названию: черёмуха в каталоге - Prunus,
 *  но у неё в шаблоне своя строка. */
export type SignBasis = 'вид' | 'род';

/** Виды каталога config/species.yaml -> строка таблицы шаблона. Тест сверяет таблицу с
 *  каталогом: каждый из 55 видов - здесь или в WITHOUT_TEMPLATE_SIGN. */
export const SPECIES_SIGNS: Readonly<Record<string, readonly [sign: string, basis: SignBasis]>> = {
  // Хвойные деревья и кустарники.
  picea_abies: ['Ель', 'род'],
  picea_pungens: ['Ель', 'род'],
  pinus_sylvestris: ['Сосна', 'род'],
  pinus_mugo: ['Сосна горная', 'вид'],
  juniperus_sabina: ['Можжевельник', 'род'],
  // Стелющийся можжевельник обыкновенный - не горизонтальный (J. horizontalis): знак рода.
  juniperus_communis_repens: ['Можжевельник', 'род'],
  pseudotsuga_menziesii: ['Псевдотсуга', 'род'],
  thuja_occidentalis: ['Туя западная', 'вид'],
  // Лиственные деревья.
  betula_pendula: ['Береза', 'род'],
  crataegus_laevigata: ['Боярышник', 'род'],
  ulmus_laevis: ['Вяз', 'род'],
  ulmus_pumila: ['Вяз', 'род'],
  quercus_robur: ['Дуб', 'род'],
  salix_alba_tristis: ['Ива', 'род'],
  acer_platanoides: ['Клен', 'род'],
  acer_saccharinum: ['Клен', 'род'],
  acer_ginnala: ['Клен', 'род'],
  acer_negundo: ['Клен', 'род'],
  aesculus_hippocastanum: ['Конский каштан', 'вид'],
  tilia_cordata: ['Липа', 'род'],
  tilia_platyphyllos: ['Липа', 'род'],
  sorbus_aucuparia: ['Рябина', 'род'],
  populus_simonii: ['Тополь', 'род'],
  populus_balsamifera: ['Тополь', 'род'],
  prunus_maackii: ['Черемуха', 'род'],
  prunus_padus: ['Черемуха', 'род'],
  prunus_virginiana: ['Черемуха', 'род'],
  malus_decorative: ['Яблоня', 'род'],
  malus_niedzwetzkyana: ['Яблоня', 'род'],
  // Лиственные кустарники. Лох в каталоге - малое дерево, в шаблоне - строка кустарников.
  euonymus_europaeus: ['Бересклет', 'род'],
  weigela_florida: ['Вегейла', 'род'],
  hydrangea_paniculata: ['Гортензия', 'род'],
  hydrangea_arborescens: ['Гортензия', 'род'],
  cornus_alba: ['Дерен', 'род'],
  cornus_sericea: ['Дерен', 'род'],
  lonicera_tatarica: ['Жимолость', 'род'],
  amelanchier_spicata: ['Ирга', 'род'],
  cotoneaster_lucidus: ['Кизильник', 'род'],
  potentilla_fruticosa: ['Лапчатка', 'род'],
  corylus_avellana: ['Лещина', 'род'],
  elaeagnus_angustifolia: ['Лох', 'род'],
  physocarpus_opulifolius: ['Пузыреплодник калинолистный', 'вид'],
  sorbaria_sorbifolia: ['Рябинник', 'род'],
  syringa_vulgaris: ['Сирень', 'род'],
  syringa_josikaea: ['Сирень', 'род'],
  syringa_meyeri: ['Сирень', 'род'],
  spiraea_vanhouttei: ['Спирея', 'род'],
  spiraea_cinerea: ['Спирея', 'род'],
  spiraea_japonica: ['Спирея', 'род'],
  spiraea_betulifolia: ['Спирея', 'род'],
  forsythia_ovata: ['Форзиция', 'род'],
  philadelphus_coronarius: ['Чубушник', 'род'],
};

/** Виды каталога, которых в шаблоне нет ни родом, ни видом: ясень, маакия (бархат амурский -
 *  другой род) и скумпия. Они рисуются общим знаком дерева или куста - явно, а не молча. */
export const WITHOUT_TEMPLATE_SIGN: readonly string[] = [
  'fraxinus_excelsior',
  'maackia_amurensis',
  'cotinus_coggygria',
];

/** Раздел «Существующие зеленые насаждения» шаблона - имена строк как в таблице. */
export const EXISTING_SIGNS = {
  tree: 'Существующие древесное насаждение',
  shrub: 'Существующие кустарниковое насаждение',
  conifer: 'Существующие хвойное насаждение',
  hedge: 'Существующая живая изгородь',
} as const;

let file: TemplateSignFile | null = null;
let byName = new Map<string, TemplateSign>();
let loading: Promise<void> | null = null;
let version = 0;
const listeners = new Set<() => void>();

/** Положить данные знаков: загрузчик и тесты. Подписчики перерисовываются. */
export function setTemplateSignFile(data: TemplateSignFile): void {
  file = data;
  byName = new Map(data.signs.map((sign) => [sign.name, sign]));
  version += 1;
  paths.clear();
  cache.clear();
  for (const listener of listeners) listener();
}

/** Загрузить данные знаков один раз на страницу. Ошибка сети не ломает карту: остаются общие
 *  знаки. */
export function loadTemplateSigns(): Promise<void> {
  loading ??= fetch(signsUrl)
    .then((response) =>
      response.ok ? response.json() : Promise.reject(new Error(String(response.status))),
    )
    .then((data: TemplateSignFile) => {
      setTemplateSignFile(data);
    })
    .catch(() => {
      /* файл знаков не пришёл: карта остаётся с общими знаками */
    });
  return loading;
}

export function onTemplateSigns(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Номер версии данных: 0 - ещё не загружены. Для useSyncExternalStore. */
export function templateSignsVersion(): number {
  return version;
}

export function templateSignFile(): TemplateSignFile | null {
  return file;
}

export function templateSignOf(name: string): TemplateSign | undefined {
  return byName.get(name);
}

/** Знак шаблона вида каталога; undefined - вид без знака или данные ещё не пришли. */
export function speciesSign(code: string | undefined): TemplateSign | undefined {
  const entry = code ? SPECIES_SIGNS[code] : undefined;
  return entry ? byName.get(entry[0]) : undefined;
}

/** Мельче этого радиуса на экране знак рисуется точкой главного цвета, пиксели CSS. */
export const TONE_PX = 3.5;

const paths = new Map<TemplateSign, Path2D[]>();

function pathsOf(sign: TemplateSign): Path2D[] {
  let made = paths.get(sign);
  if (!made) {
    made = sign.paths.map(([, , , , d]) => new Path2D(d));
    paths.set(sign, made);
  }
  return made;
}

/** Яркость, до которой в тёмной теме поднимаются тёмные цвета чертежа: тёмно-зелёная хвоя
 *  можжевельника и дёрен иначе пропадают на тёмном газоне. */
const DARK_THEME_MIN_LUMINANCE = 0.5;
/** Ярче этого цвет чертежа - белая маска под знаком (кружок ствола, подложка), то есть лист. */
const PAPER_LUMINANCE = 0.92;

/** Цвет знака в текущей теме. На светлом листе - как в чертеже, ACI 7 - чернила. В тёмной
 *  теме, как в модели CAD на тёмном фоне, ACI 7 - светлые чернила, белая маска - цвет листа,
 *  а тёмные цвета светлеют до DARK_THEME_MIN_LUMINANCE с тем же оттенком: знаки видов должны
 *  различаться и на графите. */
export function signColor(color: string, ink: SignInk): string {
  if (color === 'ink') return ink.ink;
  if (!isDark(ink.paper)) return color;
  const lum = luminance(color);
  if (lum > PAPER_LUMINANCE) return ink.paper;
  if (lum >= DARK_THEME_MIN_LUMINANCE) return color;
  // Смесь с белым поднимает яркость линейно: доля t доводит её ровно до порога.
  const t = (DARK_THEME_MIN_LUMINANCE - lum) / (1 - lum);
  const n = Number.parseInt(color.slice(1, 7), 16);
  const channel = (value: number) => Math.round(value + (255 - value) * t);
  return `rgb(${[(n >> 16) & 255, (n >> 8) & 255, n & 255].map(channel).join(', ')})`;
}

function luminance(hex: string): number {
  const n = Number.parseInt(hex.slice(1, 7), 16);
  if (Number.isNaN(n)) return 1;
  return (0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)) / 255;
}

function isDark(hex: string): boolean {
  return luminance(hex) < 0.5;
}

/** Толщина штриха на экране по весу линии чертежа: как в CAD - в пикселях, а не в метрах, но
 *  на мелком знаке тоньше, иначе сотня штрихов «Ели» сливается в пятно. */
function strokePx(weight: number, radius: number): number {
  const base = Math.min(1.4, Math.max(0.5, weight * 2.4));
  // Тоньше 0,45 пикселя штрих в образце легенды (радиус 11) уже не виден, особенно в тёмной
  // теме: знак из одних тонких линий («Спирея», «Гортензия») пропадал.
  return Math.max(0.45, base * Math.min(1, 0.45 + radius / 36));
}

/** Нарисовать знак с центром (0, 0) радиусом radius пикселей: матрица уже стоит. */
export function paintSign(
  ctx: CanvasRenderingContext2D,
  sign: TemplateSign,
  radius: number,
  ink: SignInk,
): void {
  const made = pathsOf(sign);
  const base = ctx.globalAlpha;
  ctx.save();
  ctx.scale(radius, radius);
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  sign.paths.forEach(([kind, color, alpha, weight], i) => {
    const path = made[i];
    if (!path) return;
    ctx.globalAlpha = base * alpha;
    const paint = signColor(color, ink);
    if (kind === 'f') {
      ctx.fillStyle = paint;
      // Контуры одной заливки - острова штриховки: чётно-нечётное правило, как в CAD.
      ctx.fill(path, 'evenodd');
    } else {
      ctx.strokeStyle = paint;
      ctx.lineWidth = strokePx(weight, radius) / radius;
      ctx.stroke(path);
    }
  });
  ctx.restore();
}

const cache = new Map<string, Sprite>();
/** Знаков на прогон десятки, ступеней масштаба при зуме несколько, тем две. */
const LIMIT = 600;

/** Спрайт знака радиуса radius (ступенями quantize), тема - по чернилам. */
export function signSprite(sign: TemplateSign, radius: number, ink: SignInk, dpr: number): Sprite {
  const r = quantize(radius);
  const id = `${sign.name}|${String(r)}|${String(dpr)}|${ink.ink}|${ink.paper}`;
  const hit = cache.get(id);
  if (hit) return hit;
  if (cache.size >= LIMIT) cache.clear();
  const half = Math.ceil(r * 1.05 + 1);
  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(half * 2 * dpr);
  canvas.height = canvas.width;
  const made: Sprite = { canvas, radius: r, half };
  const ctx = canvas.getContext('2d');
  if (ctx) {
    ctx.scale(dpr, dpr);
    ctx.translate(half, half);
    paintSign(ctx, sign, r, ink);
  }
  cache.set(id, made);
  return made;
}
