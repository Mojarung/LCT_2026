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
    housing_zone_m: float = 30.0  # 743-ПП п. 3.6.18: пух и засорение у жилья
    max_height_under_lines_m: float = 4.0  # предельная высота в охранной зоне ВЛ
    crown_extra_per_m: float = 0.5  # прим. к табл. 9.1: прибавка отступа на метр кроны сверх 5 м
    # К каким объектам прибавка применяется. Примечание к табл. 9.1 писано для всей таблицы,
    # но буквальное применение ко всем строкам запрещает липу с кроной 12 м в двух метрах от
    # борта, то есть обычную московскую аллею. Крона мешает там, где есть стена или габарит:
    # у зданий и сооружений. Список - параметр, чтобы толкование было видно и проверяемо.
    crown_extra_classes: tuple[str, ...] = ("building", "structure")
    quota_species: float = 0.10  # правило 10-20-30 (Santamour, 1990)
    quota_genus: float = 0.20
    quota_family: float = 0.30
    conifer_share: tuple[float, float] = (0.15, 0.40)
    # Крупная структура делится на участки: вид назначается участку целиком, поэтому
    # аллея и массив меняют породу кварталами, а не через дерево.
    structure_patch_size: int = 10
    assortment_weights: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
