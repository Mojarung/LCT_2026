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


@dataclass(frozen=True, slots=True)
class PlanParams:
    planting_type: PlantingType = PlantingType.TREE
    species_code: str = "tilia_cordata"
    spacing_m: float = 6.0  # 743-ПП, п. 3.6.4, табл. 3.6.2: однорядная посадка деревьев 5-6 м
    curb_offsets_m: tuple[float, ...] = (2.0, 2.5, 3.0)
    require_utility_data: bool = True
    unknown_lines_as_utility: bool = True
    allow_needs_approval: bool = True
    label_search_radius_m: float = 3.0
    max_rejections: int = 2000
    require_soil: bool = True
    require_work_boundary: bool = True
    # Horizontal envelope of the stock schedule: tree pit 2.2 x 2.2 m fits
    # a radius-1.6 m disk; shrub pit diameter 1 m. Not a rootable-soil volume.
    planting_radius_m: float = 1.6
    shrub_planting_radius_m: float = 0.5
    surface_cell_m: float = 0.5
    # Limits on evidence propagation are project assumptions, not soil measurements.
    surface_max_distance_m: float = 30.0
    surface_ambiguity_m: float = 1.0
    tree_seed_distance_m: float = 2.0
    # auto uses declared $INSUNITS; unitless input needs an explicit override.
    # An override applies to every source of a package. No guess from site size.
    drawing_unit: str = "auto"
    # Приёмы размещения по порядку: аллея вдоль борта, затем заполнение грунта сеткой.
    modes: tuple[str, ...] = ("alley", "lawn")
    # Compare complete validated layouts; baseline always remains an alternative.
    placement_solver: str = "portfolio"
    placement_time_limit_s: float = 5.0
    placement_max_candidates: int = 6000
    placement_max_conflicts: int = 200_000
    lawn_phase: tuple[float, float] = (0.0, 0.0)
    lawn_rotation_deg: float = 0.0
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
    # Доли разнообразия для кустарников. Правило 10-20-30 (Santamour, 1990) написано для
    # городских деревьев, для кустарников источника нет: это параметр проекта, квоты остаются
    # жёсткими. Существующие кустарники из перечётки в квоты по умолчанию не входят: единицы в
    # ведомостях не унифицированы (штуки, погонные метры, группы), см. docs/species.md.
    shrub_quota_species: float = 0.20
    shrub_quota_genus: float = 0.35
    shrub_quota_family: float = 0.50
    shrub_conifer_share: tuple[float, float] = (0.0, 0.30)
    shrub_quotas_use_inventory: bool = False
    quota_species: float = 0.10  # правило 10-20-30 (Santamour, 1990)
    quota_genus: float = 0.20
    quota_family: float = 0.30
    conifer_share: tuple[float, float] = (0.15, 0.40)
    # Крупная структура делится на участки: вид назначается участку целиком, поэтому
    # аллея и массив меняют породу кварталами, а не через дерево.
    structure_patch_size: int = 10
    assortment_weights: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    # --- Индекс качества плана ---
    # Переопределённые веса слагаемых; не названные берутся из DEFAULT_QUALITY_WEIGHTS.
    quality_weights: Mapping[str, float] = field(default_factory=dict)
    # МГСН 1.02-02, прил. В, табл. В.1: улицы и набережные, на 1 км - рекомендуемая вилка.
    density_trees_per_km: tuple[float, float] = (150.0, 180.0)
    density_shrubs_per_km: tuple[float, float] = (600.0, 720.0)
    # 743-ПП, табл. 3.6.2: однорядная посадка деревьев 5-6 м; допуск разбивки 5%.
    row_spacing_m: tuple[float, float] = (5.0, 6.0)
    # Площадь взрослых крон в долях от зоны допустимости, дающая полный балл: кроны по площади
    # равны зоне, где посадка допустима. Не норма, параметр проекта. Правило 3-30-300
    # (Konijnendijk, 2021) говорит о 30% крон на весь квартал, но на улице больше 90%
    # границы работ - проезжая часть и полосы сетей, и такая цель не различает планы.
    canopy_target: float = 1.0
    # Доля бортов под кронами газоустойчивых посадок, дающая полный балл. Параметр проекта.
    dust_target: float = 0.50
    # Относительный запас до ближайшей нормы, дающий полный балл: 20% покрывают неточность
    # подосновы и разбивки на месте. Параметр проекта.
    margin_target: float = 0.20
    # Сколько видов считать достаточным разнообразием: правило 10-20-30 требует не меньше
    # десяти. Если нормы места допускают меньше видов, цель - все допустимые.
    diversity_target: int = 10

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
