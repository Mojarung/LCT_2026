"""Сдвиг слабых мест: посадка впритык к норме отходит туда, где запас больше."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString, box

from green.application.constraints import ConstraintIndex
from green.application.params import PlanParams, active_distance_rules
from green.application.quality.terms import tightest
from green.application.refine import MIN_GAIN_M, _Mover
from green.domain.norms import PlantingType
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import CheckOutcome, LifeForm, Placement, Species, Verdict
from green.infrastructure.config.repositories import YamlRuleBookSource

CONFIG = Path(__file__).resolve().parents[1] / "config"
RULEBOOK = YamlRuleBookSource(CONFIG / "acts.yaml", CONFIG / "rules.yaml").load()
PARAMS = replace(PlanParams(), require_soil=False, require_utility_data=False)
SHRUB = Species("spiraea", "Спирея", "Spiraea media", 1.5, life_form=LifeForm.SHRUB_MEDIUM)
FEATURES = (
    Feature(
        SourceRef("f", "x", "1"),
        "граница",
        box(-50, -50, 50, 50),
        object_class=ObjectClass.WORK_BOUNDARY,
    ),
    # Силовой кабель: запас до нормы меряется до подземных сетей (СП 317.1325800.2017,
    # п. 5.3.5.3), их положение на плане - с погрешностью до 0,5 м.
    Feature(
        SourceRef("f", "x", "2"),
        "кабель",
        LineString([(-50, 0), (50, 0)]),
        object_class=ObjectClass.UTILITY_POWER,
    ),
)


def _base() -> ConstraintIndex:
    return ConstraintIndex(FEATURES, (), require_utility_data=False)


def _shrub(number: int, x: float, y: float) -> Placement:
    rules = active_distance_rules(RULEBOOK, replace(PARAMS, planting_type=PlantingType.SHRUB))
    index = _base().with_rules(rules)
    batch = index.evaluate(np.array([shapely.Point(x, y)], dtype=object))
    return Placement(
        placement_id=f"p-{number}",
        number=number,
        planting_type=PlantingType.SHRUB,
        species=SHRUB,
        x=x,
        y=y,
        verdict=batch.verdict(0),
        checks=batch.checks(0),
        notes=("группа кустарников на месте дерева",),
    )


def _slack(placement: Placement) -> float:
    found = tightest(placement)
    assert found is not None
    return found[0]


def test_a_shrub_standing_on_the_norm_moves_away_from_the_cable() -> None:
    stuck = _shrub(1, 0.0, 0.7)  # ровно на норме 0,7 м до силового кабеля (СП 42, табл. 9.1)
    assert _slack(stuck) < 0.01
    mover = _Mover((stuck,), _base(), RULEBOOK, PARAMS)

    assert mover.try_move(stuck)
    moved = mover.placements[0]
    assert moved.y > stuck.y
    assert _slack(moved) >= _slack(stuck) + MIN_GAIN_M
    assert all(c.outcome is not CheckOutcome.FAIL for c in moved.checks)
    assert moved.verdict is not Verdict.FORBIDDEN
    assert any(note.startswith("сдвинута сервисом") for note in moved.notes)


def test_a_move_never_brings_neighbours_closer_than_the_group_step() -> None:
    stuck = _shrub(1, 0.0, 0.7)
    # Соседи сверху и сбоку: уйти от кабеля прямо вверх нельзя, ближе полуметра не встанет.
    neighbours = tuple(_shrub(2 + i, x, y) for i, (x, y) in enumerate([(0, 1.3), (-0.6, 1.0)]))
    mover = _Mover((stuck, *neighbours), _base(), RULEBOOK, PARAMS)
    mover.try_move(stuck)
    moved = mover.placements[0]
    for other in neighbours:
        before = np.hypot(stuck.x - other.x, stuck.y - other.y)
        after = np.hypot(moved.x - other.x, moved.y - other.y)
        assert after >= min(0.5, before) - 1e-9


def test_a_planting_with_room_to_spare_stays_where_it_is() -> None:
    roomy = _shrub(1, 0.0, 10.0)
    mover = _Mover((roomy,), _base(), RULEBOOK, PARAMS)
    assert not mover.try_move(roomy)
    assert mover.placements[0] is roomy
