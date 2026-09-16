"""Посадка, которой назначение не дало вида, получает лучший допустимый вид своей точки."""

from __future__ import annotations

from pathlib import Path

from green.application.assortment import _fill_orphans
from green.application.assortment.assign import Assignment
from green.application.assortment.filters import SpeciesVerdict
from green.application.assortment.scoring import Score
from green.infrastructure.config.repositories import YamlSpeciesCatalog

CATALOG = YamlSpeciesCatalog(Path(__file__).resolve().parents[1] / "config" / "species.yaml")


def _verdict(code: str) -> SpeciesVerdict:
    return SpeciesVerdict(species=CATALOG.get(code), allowed=True, reasons=())


def test_orphan_gets_the_best_allowed_species_of_its_point() -> None:
    solved = Assignment(species_by_placement={"p-1": "sorbus_aucuparia"}, solver="milp")
    verdicts = {
        "p-1": [_verdict("sorbus_aucuparia")],
        "p-2": [_verdict("crataegus_laevigata"), _verdict("acer_ginnala")],
        "p-3": [],
    }
    scores = {
        ("p-1", "sorbus_aucuparia"): Score(0.7, {}),
        ("p-2", "crataegus_laevigata"): Score(0.6, {}),
        ("p-2", "acer_ginnala"): Score(0.8, {}),
    }
    filled = _fill_orphans(solved, verdicts, scores)
    assert filled.species_by_placement == {"p-1": "sorbus_aucuparia", "p-2": "acer_ginnala"}
    assert "p-3" not in filled.species_by_placement  # допустимых видов нет - вида нет
    assert any("1 посадкам" in note for note in filled.notes)


def test_complete_assignment_is_returned_unchanged() -> None:
    solved = Assignment(species_by_placement={"p-1": "sorbus_aucuparia"}, solver="milp")
    verdicts = {"p-1": [_verdict("sorbus_aucuparia")]}
    scores = {("p-1", "sorbus_aucuparia"): Score(0.7, {})}
    assert _fill_orphans(solved, verdicts, scores) is solved
