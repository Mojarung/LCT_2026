"""«Почему здесь пусто»: какая норма закрыла какую часть грунта.

Идея LPN1KoL (`greening/annotate.py`, `blocked_by`): у зоны без посадок - нормы и доля площади,
которую каждая закрыла. Отвечает на вопрос жюри «почему так мало деревьев на плотной улице».
Схема: газон 100 x 30 м, водопровод по середине (y = 15). Дереву нужно 2 м до трубы
(СП 42.13330.2016, табл. 9.1), полоса шириной около 4 м + диаметр трубы закрыта только им.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from shapely.geometry import LineString, box

from green.application.params import PlanParams
from green.application.placement import GreedyPlantingStrategy
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import Plan, Species
from green.infrastructure.config.repositories import YamlRuleBookSource
from green.infrastructure.reports.interpretation_report import blocked_rows

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

ROOT = Path(__file__).resolve().parents[1]
BOOK = YamlRuleBookSource(ROOT / "config" / "acts.yaml", ROOT / "config" / "rules.yaml").load()


def _feature(kind: ObjectClass, geometry: BaseGeometry, number: int) -> Feature:
    return Feature(SourceRef("t", "t", str(number)), "t", geometry, object_class=kind)


def _stats() -> dict[str, float]:
    boundary = box(0, 0, 100, 30)
    features = [
        _feature(ObjectClass.WORK_BOUNDARY, boundary, 0),
        _feature(ObjectClass.LAWN, boundary, 1),
        _feature(ObjectClass.UTILITY_WATER, LineString([(0, 15), (100, 15)]), 2),
    ]
    plan = GreedyPlantingStrategy().plan(
        features,
        (),
        BOOK,
        Species("test", "test", "test", 4),
        PlanParams(modes=("lawn",), require_utility_data=False, placement_solver="greedy"),
    )
    return dict(plan.stats)


def test_the_pipe_closes_a_strip_along_it_and_is_the_only_reason_there() -> None:
    stats = _stats()
    closed = stats["blocked_R-WATER-TREE-001_m2"]
    assert 380 <= closed <= 560  # 100 м x (2 x 2 м + диаметр трубы) с точностью сетки зон
    assert stats["blocked_only_R-WATER-TREE-001_m2"] == pytest.approx(closed)


def test_closed_area_never_exceeds_the_soil() -> None:
    stats = _stats()
    soil = 100 * 30
    assert sum(v for k, v in stats.items() if k.startswith("blocked_only_")) <= soil


def test_report_rows_name_the_rule_its_basis_and_the_share_of_soil() -> None:
    plan = Plan(
        (),
        (),
        stats={
            "surface_cell_m": 0.5,
            "surface_cells_soil": 4000,  # 1000 м² грунта
            "blocked_R-WATER-TREE-001_m2": 400.0,
            "blocked_only_R-WATER-TREE-001_m2": 300.0,
            "blocked_R-OBST-TREE-001_m2": 50.0,
            "blocked_only_R-OBST-TREE-001_m2": 50.0,
        },
    )
    rows = blocked_rows(plan, BOOK)
    assert [row[0].split(" ")[0] for row in rows] == ["R-WATER-TREE-001", "R-OBST-TREE-001"]
    water, obstacle = rows
    assert water[1] == "норма акта"
    assert obstacle[1] == "проектный параметр"
    assert water[2:] == ["400", "300", "40%"]
