"""Параметры прогона: то, что проектировщик меняет между запусками без правки кода."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from green.domain.norms import PlantingType, Severity

if TYPE_CHECKING:
    from collections.abc import Mapping

    from green.domain.norms import DistanceRule, RuleBook
    from green.domain.planting import Species

# Веса факторов пригодности вида; сумма нормируется, поэтому важны пропорции, а не масштаб.
DEFAULT_WEIGHTS: Mapping[str, float] = {
    "site": 0.30,
    "function": 0.20,
    "decor": 0.15,
    "longevity": 0.15,
    "care": 0.10,
    "pilot": 0.10,
    "category": 0.20,
}

# Веса слагаемых индекса качества плана (docs/plans/2026-09-22-green-index-research.md, п. 22).
# Ни один акт весов не задаёт: это параметр проекта. Профиль переопределяет только названные
# веса, остальные берутся отсюда - иначе новое слагаемое молча обнулилось бы в старом профиле.
DEFAULT_QUALITY_WEIGHTS: Mapping[str, float] = {
    "density": 0.15,
    "fit": 0.15,
    "diversity": 0.10,
    "rows": 0.05,
    "tiers": 0.10,
    "category": 0.10,
    "canopy": 0.10,
    "dust": 0.10,
    "margin": 0.10,
    "season": 0.05,
}


# 743-ПП, п. 3.6.4, табл. 3.6.2: деревья в ряду и в группе - не ближе 5 м. Допуск разбивки 5%
# применяется к шагу проекта, но не опускает шаг деревьев ниже этой границы: шаг 6 м допускает
# 5,7 м, шаг 5 м - ровно 5 м. Шаг ниже нормы можно задать только самим параметром spacing_m.
TREE_STEP_MIN_M = 5.0
STEP_TOLERANCE = 0.95


def step_with_tolerance(step_m: float, planting_type: PlantingType) -> float:
    """Наименьшее допустимое расстояние между соседними посадками одного типа."""
    relaxed = step_m * STEP_TOLERANCE
    if planting_type is PlantingType.TREE:
        return max(relaxed, min(step_m, TREE_STEP_MIN_M))
    return relaxed


@dataclass(frozen=True, slots=True)
class PlanParams:
    planting_type: PlantingType = PlantingType.TREE
    species_code: str = "tilia_cordata"
    # 743-ПП, п. 3.6.4, табл. 3.6.2: однорядная посадка деревьев 5-6 м, групповая 5-7 м. Принята
    # нижняя граница - ею же меряется расстояние до существующих деревьев (R-EXTREE-TREE-001);
    # эксперименты docs/notes/30 (E05, E31): шаг 5 м даёт больше деревьев и тени без нарушений.
    spacing_m: float = 5.0
    curb_offsets_m: tuple[float, ...] = (2.0, 2.5, 3.0)
    require_utility_data: bool = True
    unknown_lines_as_utility: bool = True
    # Name matches are evidence, not proof. Unmatched/conflicting spatial objects
    # stop the run; exact per-input assignments resolve them without editing code.
    require_known_objects: bool = True
    # Незнакомое на новом чертеже (задача 14, решение пользователя 25.09.2026): вывод по словам
    # имени и осторожная замена по геометрии вместо остановки; сеть неизвестного типа получает
    # наибольший отступ сетей и прогон не останавливает. False - поведение проверки тиммейта.
    infer_unknown: bool = True
    # Generated review assignments are pinned to the exact computational DXF.
    semantic_source_sha256: str | None = None
    layer_classes: Mapping[str, str] = field(default_factory=dict)
    block_classes: Mapping[str, str] = field(default_factory=dict)
    feature_classes: Mapping[str, str] = field(default_factory=dict)
    # Exact text source refs; supports custom legends without broad layer guesses.
    label_roles: Mapping[str, str] = field(default_factory=dict)
    allow_needs_approval: bool = True
    label_search_radius_m: float = 3.0
    max_rejections: int = 2000
    require_soil: bool = True
    require_work_boundary: bool = True
    # Посадочное место дерева - яма 2,2 x 2,2 м под ком 1,3 x 1,3 м (743-ПП, табл. 3.3.1; IV группа
    # в ведомости). Яму ставят вдоль полосы: квадрат 2,2 м, повёрнутый по борту, встаёт в полосу
    # 2,2 м. Круг той же площади (r = 1,24 м) требует 2,48 м - с запасом к повёрнутому квадрату;
    # описанный круг (1,6 м) требовал 3,2 м и отнимал у деревьев узкие полосы и место изгороди у
    # борта (notes/34). Яма кустарника - диаметр 1 м. Не объём корнеобитаемого слоя.
    planting_radius_m: float = 1.24
    shrub_planting_radius_m: float = 0.5
    surface_cell_m: float = 0.5
    # Default: a material label can classify only a closed material face.
    # Distance propagation is an explicitly requested exploratory assumption.
    # hybrid (вопрос 3 пользователя, 25.09.2026): замкнутые грани решают сами, подписи вне
    # решённых граней - по расстоянию; closed_faces - строгий режим тиммейта.
    surface_inference_mode: str = "hybrid"
    # Limits on evidence propagation are project assumptions, not soil measurements.
    surface_max_distance_m: float = 30.0
    surface_ambiguity_m: float = 1.0
    tree_seed_distance_m: float = 2.0
    # auto uses declared $INSUNITS; unitless input needs an explicit override.
    # An override applies to every source of a package. No guess from site size.
    drawing_unit: str = "auto"
    # Приёмы размещения по порядку: аллея вдоль борта, заполнение грунта сеткой, добор зоны.
    modes: tuple[str, ...] = ("alley", "lawn", "fill")
    fill_step_m: float = 1.0  # шаг ячеек добора зоны
    # Compare complete validated layouts; baseline always remains an alternative.
    placement_solver: str = "portfolio"
    placement_time_limit_s: float = 5.0
    placement_max_candidates: int = 6000
    placement_max_conflicts: int = 200_000
    lawn_phase: tuple[float, float] = (0.0, 0.0)
    lawn_rotation_deg: float = 0.0
    # Preserve the historical candidate family while comparing an exact-soil frame.
    lawn_anchor: str = "raster"
    # Слой зон допустимости: сетка по грунту с вердиктом каждой ячейки по всем правилам.
    zones: bool = True
    zone_cell_m: float = 1.0
    # --- Подбор ассортимента ---
    # auto - подбирает сервис; given - только виды из given_assortment в заданных количествах;
    # single - прежнее поведение, весь прогон одним видом species_code.
    assortment_mode: str = "auto"
    # auto - целочисленная задача с запасным жадным путём; greedy - сразу жадный обход
    # (быстро на очень больших планах, но квоты соблюдаются хуже).
    assortment_solver: str = "auto"
    given_assortment: Mapping[str, int] = field(default_factory=dict)
    region_hardiness_zone: int = 4  # Москва 4b-5a; вид с зоной выше не переносит зиму
    salt_zone_m: float = 5.0  # полоса у проезжей части, где работают реагенты
    max_height_under_lines_m: float = 4.0  # предельная высота в охранной зоне ВЛ
    # Прим. 1 к табл. 9.1 СП 42.13330 (и к табл. 3.6.1 743-ПП): нормы даны для кроны не более
    # 5 м и «должны быть соответственно увеличены» для большей кроны. Величину увеличения ни
    # один акт не задаёт. Принят прирост радиуса кроны: (крона - 5) / 2, то есть 0,5 м на метр
    # диаметра. Это толкование проекта, и объяснение так его и называет.
    crown_extra_per_m: float = 0.5
    # К каким классам объектов применяется увеличение. Пусто - ко всем строкам таблицы, как
    # написано в примечании. Сужение списка - отступление от буквы нормы, его видно в профиле.
    crown_extra_classes: tuple[str, ...] = ()
    # Тип территории по 369-ПП: green_fund (иные территории зелёного фонда), protected_green
    # (особо охраняемые зелёные), natural (природные), outside_green_fund. Решает, допустима
    # ли высадка видов группы III.
    territory: str = "green_fund"
    # Категория насаждений по табл. В.6 МГСН 1.02-02: parks, squares, streets, yards, special.
    # Заказчик: сначала определяется тип территории, у улиц, дворов и парков свой ассортимент
    # (docs/notes/15-organizers-qa.md, вопрос 15). Кейс про улицы, поэтому streets.
    planting_category: str = "streets"
    # П. 3.6.18 743-ПП (массовые аллергены) видов не называет, МГСН 1.02-02 табл. В.6 и 515-ПП
    # берёзу рекомендуют. True - решает акт, который вид называет (берёза допускается, оценка
    # ниже); False - запрет п. 3.6.18 выше, берёзы в плане нет (species_norms._mass_allergen).
    allergen_act_priority: bool = True
    # Место дерева, которое допустимо по нормам, но не получило вид из-за квот, занимается
    # группой кустарников (docs/notes/14-shrub-groups.md). Шаг группы - толкование табл. 3.6.2
    # 743-ПП: групповая посадка кустарников 0,3 м, однорядная высоких 0,5-1 м; принят 1 м,
    # потому что крона кустарников каталога через 10 лет 0,8-2,5 м.
    # Правила, которые профиль отключает. Заказчик на сессии вопросов 17.09.2026 ответил, что
    # охранные зоны сетей поверх нормативных отступов применять не требуется
    # (docs/notes/15-organizers-qa.md, вопрос 8). Отключённые правила перечисляются в
    # предупреждениях прогона.
    disabled_rules: tuple[str, ...] = ()
    # Прикорневые барьеры (СП 42.13330.2016, табл. 9.1, прим. 5): дерево допускается ближе нормы
    # к сетям и бордюрам улиц, барьер становится условием посадки. Заказчик описал этот приём
    # на сессии вопросов (docs/notes/15-organizers-qa.md, вопрос 29).
    root_barriers: bool = False
    shrub_groups: bool = True
    shrub_group_spacing_m: float = 1.0
    shrub_group_size: int = 3  # квадрат 3 x 3
    # Ряд кустарника у борта под кронами аллеи (docs/plans/2026-09-22-shrub-row-research.md):
    # полоса 1-2 м от борта закрыта для деревьев и открыта для кустарника (СП 42, табл. 9.1;
    # 743-ПП, табл. 3.6.1), СП 82 п. 9.38 велит озеленять её, живыми изгородями в том числе.
    shrub_rows: bool = True
    # Ось ряда от борта: норма 1,0 м, первым пробуется 1,3 м - запас на снег (вопрос 19).
    shrub_row_curb_offsets_m: tuple[float, ...] = (1.3, 1.0)
    shrub_row_spacing_m: float = 0.4  # 743-ПП, табл. 3.6.2: средние и низкие 0,3-0,4 м
    # От ствола дерева: полуширина ямы дерева (ком 1,0 м, 743-ПП табл. 3.3.1) плюс полуширина
    # траншеи изгороди 0,6 м. Нормы нет, выведено из размеров ям - параметр проекта.
    shrub_row_tree_gap_m: float = 1.25
    shrub_row_access_gap_m: float = 1.0  # до люка: доступ для обслуживания, параметр проекта
    # Сводный стандарт улиц (387-РП), п. 32.12: в 5 м от перехода нет кустарника выше 0,5 м.
    # Распространено на любой разрыв газона у борта: въезд, проход.
    shrub_row_gap_buffer_m: float = 5.0
    shrub_row_min_length_m: float = 3.0  # короче - одиночные кусты у борта, их ликвидируют
    shrub_row_height_m: float = 1.0  # СП 82.13330.2016, п. 9.40: стриженая изгородь до 1,0 м
    # Изгородь вдоль всех бортов с грунтом, не только под кронами аллеи (СП 82 п. 9.38 велит
    # озеленять полосы у проезжей части). Шаг - для высоких кустарников: все виды изгороди
    # каталога выше 1,8 м, 743-ПП, табл. 3.6.2 даёт для них 0,5-1 м.
    curb_hedges: bool = True
    curb_hedge_spacing_m: float = 1.0
    # Изгородь не поднимает кустарник выше 720 на 1 км улицы (МГСН 1.02-02, табл. В.1).
    curb_hedge_density_cap: bool = True
    # Кустарник под кроной дерева без нижнего яруса (МГСН 1.02-02, п. 4.2.9.2): малая группа
    # на кольцах от ствола. understory_trees: alley - только деревья аллеи, all - все.
    understory: bool = True
    understory_trees: str = "alley"
    understory_size: int = 3
    # Кольца от ствола: ближе 2,1 м ямы дерева (радиус 1,6 м) и куста (0,5 м) перекрылись бы.
    understory_radii_m: tuple[float, ...] = (2.2, 2.6, 3.0)
    # Группы кустарника на газоне, пока кустарников меньше нижней границы МГСН 1.02-02, табл.
    # В.1 (600 на 1 км): у сетей кустарнику можно там, где дереву нельзя (shrub_fill.py).
    shrub_fill: bool = True
    shrub_fill_tree_gap_m: float = 3.0
    shrub_fill_shrub_gap_m: float = 2.0
    shrub_fill_step_m: float = 4.0
    # Газоны (п. 3 ТЗ, травянистые покрытия): грунт, который итоговый план оставил свободным,
    # сохраняемый по чертежу или устраиваемый (application/lawns.py). Участок меньше порога -
    # обрезок между посадочными местами и бортом, отдельным газоном он не выделяется. Порог -
    # параметр проекта, акты его не задают.
    lawns: bool = True
    lawn_min_area_m2: float = 5.0
    # Вид участка изгороди - самый редкий из допустимых (иначе - лучший, соседний участок другим
    # видом): держит квоты разнообразия кустарников, когда участков много.
    hedge_species_balance: bool = True
    # Доли разнообразия для кустарников. Правило 10-20-30 (Santamour, 1990) написано для
    # городских деревьев, для кустарников источника нет: это параметр проекта, квоты остаются
    # жёсткими. Существующие кустарники из перечётки в квоты по умолчанию не входят: единицы в
    # ведомостях не унифицированы (штуки, погонные метры, группы), см. docs/species.md.
    # Кустарники в проектах пилота: главный вид 27-61% штук, медиана около 35-40% (notes/34).
    shrub_quota_species: float = 0.40
    shrub_quota_genus: float = 0.50
    shrub_quota_family: float = 0.70
    shrub_conifer_share: tuple[float, float] = (0.0, 0.30)
    shrub_quotas_use_inventory: bool = False
    quota_species: float = 0.10  # правило 10-20-30 (Santamour, 1990)
    quota_genus: float = 0.20
    quota_family: float = 0.30
    conifer_share: tuple[float, float] = (0.15, 0.40)
    # Крупная структура делится на участки: вид назначается участку целиком, поэтому
    # аллея и массив меняют породу кварталами, а не через дерево.
    structure_patch_size: int = 10
    # Надбавка за занятое место ряда (аллеи) в задаче назначения видов. Когда квоты 10-20-30
    # не дают занять все места, пустеть должен газон, а не аллея: на ней держатся ряды, ярус
    # под кронами и тень над тротуаром (docs/notes/30-pipeline-experiments.md). Ноль - все
    # места равны.
    alley_priority: float = 2.0
    # Штраф за каждое растение сверх квоты 10-20-30 в задаче назначения видов. Ноль - квоты
    # жёсткие: место, под которое ни один вид в квоту не влезает, пустеет. Больше нуля (но
    # меньше премии 10 за занятое место) - место занимается, перебор доли виден в индексе
    # (разнообразие) и в предупреждениях. Правило 10-20-30 написано для городского древостоя,
    # а не для сотни новых деревьев на улице (docs/notes/30-pipeline-experiments.md).
    quota_penalty: float = 0.0
    # Квота уровня (вид, род, семейство) не строже 1 / (медиана числа вариантов на месте):
    # при малом выборе квоты 10-20-30 невыполнимы и оставляют участок без деревьев.
    quota_adaptive: bool = False
    # До скольких «растений доли» (места x доля) задача держит исключение «один экземпляр
    # квоту не нарушает»: 30 - при квоте вида 10% планы до 300 мест. При 1 (как до 23.09.2026)
    # участок, где квоты дают занять меньше десяти мест, оставался вовсе без деревьев.
    quota_single_places: float = 30.0
    # На сколько снижается оценка вида с условием посадки и слабого аллергена в задаче
    # назначения (оценка вида - от 0 до 1): при равных квотах берётся вид без обязательств.
    condition_penalty: float = 0.2
    assortment_weights: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    # --- Индекс качества плана ---
    # Переопределённые веса слагаемых; не названные берутся из DEFAULT_QUALITY_WEIGHTS.
    quality_weights: Mapping[str, float] = field(default_factory=dict)
    # МГСН 1.02-02, прил. В, табл. В.1: улицы и набережные, на 1 км - рекомендуемая вилка.
    density_trees_per_km: tuple[float, float] = (150.0, 180.0)
    density_shrubs_per_km: tuple[float, float] = (600.0, 720.0)
    # 743-ПП, табл. 3.6.2: однорядная посадка деревьев 5-6 м; допуск разбивки 5%.
    row_spacing_m: tuple[float, float] = (5.0, 6.0)
    # Относительная площадь крон (Kenney, van Wassenaer, Satel 2011, с. 110, 114): кроны против
    # потенциальной площади крон, «optimal» - 75-100%. Потенциал приближаем зоной, где посадка
    # допустима. Абсолютные цели 30-40% (3-30-300, American Forests) относятся к кварталу: на
    # улице проезжая часть и полосы сетей занимают больше 90% границы работ.
    canopy_target: float = 0.75
    # Доля метров борта под сомкнутым нижним ярусом, дающая полный балл. Параметр проекта.
    dust_target: float = 0.50
    # Кустарник прикрывает метр борта, если стоит от него не дальше этого: полоса 2 м у борта -
    # та, что закрыта для деревьев и открыта для кустарника (743-ПП, табл. 3.6.1).
    dust_strip_m: float = 2.0
    # Метр борта только под кроной дерева засчитывается с этим коэффициентом (Abhijith et al.
    # 2017: в уличном каньоне кроны над дорогой ухудшают воздух у земли). Параметр проекта.
    dust_crown_factor: float = 0.5
    # Запас до ближайшей нормы, дающий полный балл: СП 317.1325800.2017, п. 5.3.5.3 - на плане
    # 1:500 положение подземных сетей расходится с натурой до 0,5 м.
    margin_target_m: float = 0.5
    # Сколько видов считать достаточным разнообразием: правило 10-20-30 требует не меньше
    # десяти. Если нормы места допускают меньше видов, цель - все допустимые.
    diversity_target: int = 10
    # Плотность «при условии допустимости насаждений» (МГСН 1.02-02, табл. В.1, сноска **):
    # цель по деревьям не выше того, что вмещает зона допустимости при самом плотном шаге
    # нормы (743-ПП, табл. 3.6.2: 5 м, гексагональная упаковка). Выключено - цель 150-180 на
    # 1 км всей длины улицы, как бы мало места ни оставили сети.
    density_admissible: bool = True
    # Пылезащита меряется по бортам, у которых в полосе dust_strip_m есть грунт: у борта между
    # асфальтом и асфальтом кустарнику встать негде, и штрафовать план за такой борт - то же,
    # что делить тень на проезжую часть. Выключено - по всем бортам в границе работ.
    dust_admissible: bool = True

    @property
    def footprint_radius_m(self) -> float:
        return (
            self.planting_radius_m
            if self.planting_type is PlantingType.TREE
            else self.shrub_planting_radius_m
        )


def active_distance_rules(
    rulebook: RuleBook,
    params: PlanParams,
    species_lat: str | None = None,
    crown_m: float | None = None,
    traits: frozenset[str] = frozenset(),
) -> tuple[DistanceRule, ...]:
    """Правила расстояний для типа посадки и вида, без отключённых профилем."""
    rules = rulebook.distance_rules_for(params.planting_type, species_lat, crown_m, traits)
    return tuple(rule for rule in rules if rule.rule_id not in params.disabled_rules)


def species_distance_rules(
    rulebook: RuleBook, params: PlanParams, species: Species
) -> tuple[DistanceRule, ...]:
    """Actual-species thresholds, including the explicitly configured crown policy.

    Final validation derives thresholds separately, so generator mistakes can be
    detected there. Shared here only by generation and interactive point checks.
    """
    rules = active_distance_rules(
        rulebook, params, species.name_lat, species.crown_mature_m, species.traits
    )
    extra = max(0, species.crown_mature_m - 5) * params.crown_extra_per_m
    return tuple(
        replace(rule, min_distance_m=rule.min_distance_m + extra)
        if rule.severity is Severity.FORBID
        and "табл. 9.1" in rule.citation.clause
        and (
            not params.crown_extra_classes or rule.object_class.value in params.crown_extra_classes
        )
        else rule
        for rule in rules
    )
