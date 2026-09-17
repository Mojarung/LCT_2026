"""Ведомость посадочного материала: количества, стандарт, площадь под посадочные ямы."""

from __future__ import annotations

import math
from pathlib import Path

from green.application.schedule import SECTIONS, build_schedule
from green.domain.norms import PlantingType
from green.domain.planting import AssortmentInfo, Placement, Reason, Verdict
from green.infrastructure.config.repositories import YamlSpeciesCatalog

CATALOG = YamlSpeciesCatalog(Path(__file__).resolve().parents[1] / "config" / "species.yaml")


def _placement(number: int, code: str, *, condition: str = "") -> Placement:
    species = CATALOG.get(code)
    reasons = (Reason("norm", "основание", rule_id="R-X-Y-001", condition=condition),)
    return Placement(
        placement_id=f"p-{number}",
        number=number,
        planting_type=PlantingType.TREE if species.is_tree else PlantingType.SHRUB,
        species=species,
        x=float(number),
        y=0.0,
        verdict=Verdict.ALLOWED,
        checks=(),
        assortment=AssortmentInfo(
            status="assigned", percent=70, factors={}, reasons=reasons if condition else ()
        ),
    )


def test_rows_count_species_and_pit_areas_by_the_743_pp_table() -> None:
    placements = [
        *[_placement(i, "tilia_cordata") for i in range(3)],
        *[_placement(10 + i, "sorbus_aucuparia") for i in range(2)],
        *[_placement(20 + i, "picea_abies") for i in range(4)],
        *[_placement(30 + i, "syringa_vulgaris") for i in range(5)],
    ]
    rows = {row.name_ru: row for row in build_schedule(placements)}
    linden = rows["Липа мелколистная"]
    assert linden.count == 3
    assert linden.stock.ball == "1,3x1,3x0,6"
    assert linden.stock.pit == "2,2x2,2x0,85"
    assert math.isclose(linden.pit_area_m2, 3 * 2.2 * 2.2, abs_tol=0.01)
    assert rows["Рябина обыкновенная"].stock.ball == "1,3x1,3x0,6"
    lilac = rows["Сирень обыкновенная"]
    assert lilac.section == "Лиственные кустарники"
    assert math.isclose(lilac.pit_area_m2, 5 * math.pi * 0.25, abs_tol=0.01)
    assert rows["Ель обыкновенная"].section == "Хвойные деревья"


def test_sections_follow_the_designer_statement_and_numbers_run_through() -> None:
    placements = [
        _placement(1, "syringa_vulgaris"),
        _placement(2, "tilia_cordata"),
        _placement(3, "picea_abies"),
        _placement(4, "juniperus_sabina"),
    ]
    rows = build_schedule(placements)
    assert [row.section for row in rows] == list(SECTIONS)
    assert [row.number for row in rows] == [1, 2, 3, 4]


def test_conditions_are_counted_per_species() -> None:
    placements = [
        _placement(1, "populus_simonii", condition="посадочный материал - только мужские клоны"),
        _placement(2, "populus_simonii", condition="прикорневой барьер со стороны силового кабеля"),
        _placement(3, "populus_simonii", condition="прикорневой барьер со стороны теплосети"),
    ]
    (row,) = build_schedule(placements)
    assert "прикорневой барьер: 2 шт." in row.conditions
    assert "посадочный материал - только мужские клоны: 1 шт." in row.conditions
