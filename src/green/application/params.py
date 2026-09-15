"""Параметры прогона: то, что проектировщик меняет между запусками без правки кода."""

from __future__ import annotations

from dataclasses import dataclass

from green.domain.norms import PlantingType


@dataclass(frozen=True, slots=True)
class PlanParams:
    planting_type: PlantingType = PlantingType.TREE
    species_code: str = "tilia_cordata"
    spacing_m: float = 8.0
    curb_offsets_m: tuple[float, ...] = (2.0, 2.5, 3.0)
    require_utility_data: bool = True
    unknown_lines_as_utility: bool = True
    allow_needs_approval: bool = True
    label_search_radius_m: float = 3.0
    max_rejections: int = 2000
    require_soil: bool = True
    surface_cell_m: float = 0.5
