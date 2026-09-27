/* База моделей растений: как выглядит на плане каждый вид каталога и то, что уже растёт.
 *
 * Модель - не картинка, а рецепт: форма кроны, цвет листвы или хвои и цвет цветения или
 * плодов. Спрайт рисует её вектором под нужный размер (sprites.ts), поэтому крона одинаково
 * чёткая на общем виде и на приближении к одному дереву, а стенду без интернета нечего
 * скачивать. Коды видов - из config/species.yaml. Вид без записи получает модель по типу
 * посадки. У существующих насаждений своя приглушённая модель: на плане сразу видно, что
 * сажаем мы, а что уже росло. */

export type Form =
  /** Крупное лиственное дерево: крона-облако с лопастями. */
  | 'broadleaf'
  /** Мелкое лиственное дерево: плотная крона с мелкими лопастями. */
  | 'rounded'
  /** Колонновидное: узкая крона с тугими лопастями. */
  | 'columnar'
  /** Плакучее: мелкие лопасти и свисающие ветви лучами от центра. */
  | 'weeping'
  /** Хвойное дерево: звезда из хвои. */
  | 'conifer'
  /** Низкое хвойное: звезда с короткими лучами. */
  | 'dwarf_conifer'
  /** Кустарник: розетка с цветением точками. */
  | 'shrub'
  /** Стелющееся хвойное: лохматая низкая звезда. */
  | 'creeper';

export interface PlantModel {
  form: Form;
  /** Листва или хвоя летом. */
  tone: string;
  /** Цветение или плоды: точки поверх кроны. У кустарника с яркими цветами это цвет куста. */
  bloom?: string;
  /** Число лопастей кроны или лучей звезды. */
  lobes: number;
}

export interface ModelEntry extends PlantModel {
  code: string;
  name: string;
}

/** Модели видов каталога. Цвета подобраны под бумажную подоснову презентации: листва от
 *  светлой салатовой (липа, берёза) до глубокой (дуб, каштан), хвоя тёмная, у голубой ели -
 *  сизая, пурпурнолистные формы (черёмуха виргинская, пузыреплодник, скумпия) - винные. */
const TABLE: readonly ModelEntry[] = [
  // Деревья первой величины.
  {
    code: 'tilia_cordata',
    name: 'Липа мелколистная',
    form: 'broadleaf',
    tone: '#9dbd79',
    lobes: 9,
  },
  {
    code: 'tilia_platyphyllos',
    name: 'Липа крупнолистная',
    form: 'broadleaf',
    tone: '#93b673',
    lobes: 8,
  },
  {
    code: 'acer_platanoides',
    name: 'Клён остролистный',
    form: 'broadleaf',
    tone: '#b3bd5a',
    lobes: 9,
  },
  {
    code: 'acer_saccharinum',
    name: 'Клён сахаристый',
    form: 'broadleaf',
    tone: '#b9c98d',
    lobes: 10,
  },
  {
    code: 'acer_negundo',
    name: 'Клён ясенелистный',
    form: 'broadleaf',
    tone: '#aac47b',
    lobes: 10,
  },
  { code: 'ulmus_laevis', name: 'Вяз гладкий', form: 'broadleaf', tone: '#7fa66c', lobes: 9 },
  {
    code: 'betula_pendula',
    name: 'Берёза повислая',
    form: 'broadleaf',
    tone: '#c3cf8b',
    lobes: 12,
  },
  { code: 'quercus_robur', name: 'Дуб черешчатый', form: 'broadleaf', tone: '#6f9a5f', lobes: 8 },
  {
    code: 'fraxinus_excelsior',
    name: 'Ясень обыкновенный',
    form: 'broadleaf',
    tone: '#8db27a',
    lobes: 10,
  },
  {
    code: 'aesculus_hippocastanum',
    name: 'Каштан конский обыкновенный',
    form: 'broadleaf',
    tone: '#618f5d',
    bloom: '#f4efe4',
    lobes: 7,
  },
  { code: 'populus_simonii', name: 'Тополь Симона', form: 'columnar', tone: '#a0bd7a', lobes: 7 },
  {
    code: 'populus_balsamifera',
    name: 'Тополь бальзамический',
    form: 'columnar',
    tone: '#8fb07a',
    lobes: 7,
  },
  { code: 'salix_alba_tristis', name: 'Ива плакучая', form: 'weeping', tone: '#b7c77c', lobes: 14 },
  // Хвойные деревья.
  {
    code: 'pinus_sylvestris',
    name: 'Сосна обыкновенная',
    form: 'conifer',
    tone: '#3d6b4a',
    lobes: 18,
  },
  { code: 'picea_abies', name: 'Ель обыкновенная', form: 'conifer', tone: '#2f5a3e', lobes: 22 },
  { code: 'picea_pungens', name: 'Ель колючая', form: 'conifer', tone: '#5b8a86', lobes: 22 },
  {
    code: 'pseudotsuga_menziesii',
    name: 'Псевдотсуга Мензиса',
    form: 'conifer',
    tone: '#3a6650',
    lobes: 20,
  },
  {
    code: 'thuja_occidentalis',
    name: 'Туя западная',
    form: 'dwarf_conifer',
    tone: '#4b7a4f',
    lobes: 14,
  },
  { code: 'pinus_mugo', name: 'Сосна горная', form: 'dwarf_conifer', tone: '#416f4b', lobes: 16 },
  // Деревья второй и третьей величины.
  {
    code: 'sorbus_aucuparia',
    name: 'Рябина обыкновенная',
    form: 'rounded',
    tone: '#93b574',
    bloom: '#d8643c',
    lobes: 9,
  },
  {
    code: 'prunus_maackii',
    name: 'Черёмуха Маака',
    form: 'rounded',
    tone: '#88aa6a',
    bloom: '#f6f2e9',
    lobes: 9,
  },
  {
    code: 'prunus_padus',
    name: 'Черёмуха обыкновенная',
    form: 'rounded',
    tone: '#7ea466',
    bloom: '#f6f2e9',
    lobes: 9,
  },
  {
    code: 'prunus_virginiana',
    name: 'Черёмуха виргинская',
    form: 'rounded',
    tone: '#9d7180',
    lobes: 8,
  },
  {
    code: 'acer_ginnala',
    name: 'Клён Гиннала',
    form: 'rounded',
    tone: '#a9b865',
    bloom: '#c8573f',
    lobes: 9,
  },
  {
    code: 'malus_decorative',
    name: 'Яблоня декоративная',
    form: 'rounded',
    tone: '#a2b86b',
    bloom: '#eaa3b5',
    lobes: 8,
  },
  {
    code: 'malus_niedzwetzkyana',
    name: 'Яблоня Недзвецкого',
    form: 'rounded',
    tone: '#a67b80',
    bloom: '#d77fa0',
    lobes: 8,
  },
  {
    code: 'crataegus_laevigata',
    name: 'Боярышник обыкновенный',
    form: 'rounded',
    tone: '#9cbd78',
    bloom: '#f3eee4',
    lobes: 9,
  },
  {
    code: 'maackia_amurensis',
    name: 'Маакия амурская',
    form: 'rounded',
    tone: '#93ae84',
    lobes: 9,
  },
  {
    code: 'elaeagnus_angustifolia',
    name: 'Лох узколистный',
    form: 'rounded',
    tone: '#bac4a9',
    lobes: 10,
  },
  { code: 'ulmus_pumila', name: 'Вяз приземистый', form: 'rounded', tone: '#8aae6b', lobes: 10 },
  // Кустарники. Яркое цветение красит сам куст: так в презентации стоят сиреневые и розовые
  // группы, и вид читается издалека без легенды.
  {
    code: 'amelanchier_spicata',
    name: 'Ирга колосистая',
    form: 'shrub',
    tone: '#93b27a',
    bloom: '#f4f0e6',
    lobes: 7,
  },
  {
    code: 'syringa_vulgaris',
    name: 'Сирень обыкновенная',
    form: 'shrub',
    tone: '#b8a4dc',
    lobes: 7,
  },
  { code: 'syringa_josikaea', name: 'Сирень венгерская', form: 'shrub', tone: '#a892d2', lobes: 7 },
  { code: 'syringa_meyeri', name: 'Сирень Мейера', form: 'shrub', tone: '#c4b0e2', lobes: 7 },
  {
    code: 'cotoneaster_lucidus',
    name: 'Кизильник блестящий',
    form: 'shrub',
    tone: '#6f9660',
    bloom: '#c75c3c',
    lobes: 8,
  },
  {
    code: 'physocarpus_opulifolius',
    name: 'Пузыреплодник калинолистный',
    form: 'shrub',
    tone: '#a06f73',
    bloom: '#f1e7dd',
    lobes: 7,
  },
  {
    code: 'hydrangea_paniculata',
    name: 'Гортензия метельчатая',
    form: 'shrub',
    tone: '#8db37a',
    bloom: '#f4efe2',
    lobes: 7,
  },
  {
    code: 'hydrangea_arborescens',
    name: 'Гортензия древовидная',
    form: 'shrub',
    tone: '#99bb80',
    bloom: '#eef0dc',
    lobes: 7,
  },
  {
    code: 'cornus_alba',
    name: 'Дёрен белый',
    form: 'shrub',
    tone: '#9fbd8c',
    bloom: '#c65a4a',
    lobes: 7,
  },
  {
    code: 'cornus_sericea',
    name: 'Дёрен отпрысковый',
    form: 'shrub',
    tone: '#8fc3a6',
    bloom: '#b9573f',
    lobes: 7,
  },
  {
    code: 'sorbaria_sorbifolia',
    name: 'Рябинник рябинолистный',
    form: 'shrub',
    tone: '#a0c07f',
    bloom: '#f2efe3',
    lobes: 8,
  },
  {
    code: 'euonymus_europaeus',
    name: 'Бересклет европейский',
    form: 'shrub',
    tone: '#86a96f',
    bloom: '#d6557a',
    lobes: 7,
  },
  {
    code: 'corylus_avellana',
    name: 'Лещина обыкновенная',
    form: 'shrub',
    tone: '#7fa46a',
    lobes: 8,
  },
  {
    code: 'philadelphus_coronarius',
    name: 'Чубушник венечный',
    form: 'shrub',
    tone: '#95b77e',
    bloom: '#f8f4ea',
    lobes: 7,
  },
  {
    code: 'lonicera_tatarica',
    name: 'Жимолость татарская',
    form: 'shrub',
    tone: '#e3a58c',
    lobes: 7,
  },
  {
    code: 'cotinus_coggygria',
    name: 'Скумпия кожевенная',
    form: 'shrub',
    tone: '#a3707c',
    bloom: '#dcaebd',
    lobes: 8,
  },
  {
    code: 'forsythia_ovata',
    name: 'Форзиция яйцевидная',
    form: 'shrub',
    tone: '#dcc45a',
    lobes: 7,
  },
  {
    code: 'spiraea_vanhouttei',
    name: 'Спирея Вангутта',
    form: 'shrub',
    tone: '#98bc7f',
    bloom: '#f6f3ea',
    lobes: 7,
  },
  {
    code: 'spiraea_cinerea',
    name: 'Спирея серая',
    form: 'shrub',
    tone: '#aabf96',
    bloom: '#f3f0e8',
    lobes: 7,
  },
  { code: 'spiraea_japonica', name: 'Спирея японская', form: 'shrub', tone: '#e6a0ae', lobes: 7 },
  {
    code: 'spiraea_betulifolia',
    name: 'Спирея берёзолистная',
    form: 'shrub',
    tone: '#8fb27b',
    bloom: '#f0eae1',
    lobes: 7,
  },
  {
    code: 'potentilla_fruticosa',
    name: 'Лапчатка кустарниковая',
    form: 'shrub',
    tone: '#e2c957',
    lobes: 7,
  },
  { code: 'weigela_florida', name: 'Вейгела цветущая', form: 'shrub', tone: '#e08da3', lobes: 7 },
  // Хвойные кустарники.
  {
    code: 'juniperus_sabina',
    name: 'Можжевельник казацкий',
    form: 'creeper',
    tone: '#4f7a5a',
    lobes: 16,
  },
  {
    code: 'juniperus_communis_repens',
    name: 'Можжевельник обыкновенный стелющийся',
    form: 'creeper',
    tone: '#5a8466',
    lobes: 16,
  },
];

export const MODELS: ReadonlyMap<string, ModelEntry> = new Map(TABLE.map((m) => [m.code, m]));

/** Все модели каталога: для страницы моделей и сверки с config/species.yaml в тестах. */
export const ALL_MODELS: readonly ModelEntry[] = TABLE;

/** Вид вне базы: модель по типу посадки, чтобы новая запись каталога не рисовалась пустотой. */
const FALLBACK_TREE: PlantModel = { form: 'broadleaf', tone: '#94b574', lobes: 9 };
const FALLBACK_SHRUB: PlantModel = { form: 'shrub', tone: '#9ec07f', lobes: 7 };

/** Существующее дерево и кустарник с подосновы: бледная крона без тени. Вид по чертежу не
 *  известен, поэтому модель одна, а отличие от наших посадок - в самом приглушении. */
export const EXISTING_TREE: PlantModel = { form: 'broadleaf', tone: '#d6d5bd', lobes: 9 };
export const EXISTING_SHRUB: PlantModel = { form: 'shrub', tone: '#d9dcc0', lobes: 7 };

export function isShrubType(plantingType: string): boolean {
  return plantingType.startsWith('shrub') || plantingType === 'hedge';
}

export function modelOf(code: string | undefined, plantingType: string): PlantModel {
  const known = code ? MODELS.get(code) : undefined;
  if (known) return known;
  return isShrubType(plantingType) ? FALLBACK_SHRUB : FALLBACK_TREE;
}

/** Самый частый вид плана с моделью этой формы, или null. По нему легенда рисует образец:
 *  сирень в легенде при 26 сиренях из 1127 кустов учила читать карту по чужому образцу
 *  (жюри дизайна, итерация 7). При равенстве - вид, встреченный раньше. */
export function commonest(codes: Iterable<string | undefined>, form: Form): string | null {
  const counts = new Map<string, number>();
  for (const code of codes) {
    if (code && MODELS.get(code)?.form === form) counts.set(code, (counts.get(code) ?? 0) + 1);
  }
  let best: string | null = null;
  let most = 0;
  for (const [code, count] of counts) {
    if (count > most) {
      best = code;
      most = count;
    }
  }
  return best;
}

/** Ключ модели для кэша спрайтов: вид или запасная модель по типу посадки. */
export function modelKey(code: string | undefined, plantingType: string): string {
  if (code && MODELS.has(code)) return code;
  return isShrubType(plantingType) ? '~shrub' : '~tree';
}
