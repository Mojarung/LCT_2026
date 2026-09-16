"""Параметры прогона: то, что проектировщик меняет между запусками без правки кода."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from green.domain.norms import PlantingType

if TYPE_CHECKING:
    from collections.abc import Mapping

# Веса факторов пригодности вида; сумма нормируется, поэтому важны пропорции, а не масштаб.
DEFAULT_WEIGHTS: Mapping[str, float] = {
    "site": 0.30,
    "function": 0.20,
    "decor": 0.15,
    "longevity": 0.15,
    "care": 0.10,
    "pilot": 0.10,
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
    surface_cell_m: float = 0.5
    # Приёмы размещения по порядку: аллея вдоль борта, затем заполнение грунта сеткой.
    modes: tuple[str, ...] = ("alley", "lawn")
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
    quota_species: float = 0.10  # правило 10-20-30 (Santamour, 1990)
    quota_genus: float = 0.20
    quota_family: float = 0.30
    conifer_share: tuple[float, float] = (0.15, 0.40)
    # Крупная структура делится на участки: вид назначается участку целиком, поэтому
    # аллея и массив меняют породу кварталами, а не через дерево.
    structure_patch_size: int = 10
    assortment_weights: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
