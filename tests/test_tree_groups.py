"""Группы деревьев на газоне (задача 14 плана финала: композиция как у проектировщика).

Проектировщики пилота сажают деревья на газоне группами (2-я Прядильная: все деревья
«группы»), а не сеткой. Приём groups ставит на газон группы по три дерева треугольником со
стороной tree_group_side_m (743-ПП, табл. 3.6.2: групповая посадка 5-7 м) и газонными
разрывами между группами: центры групп не ближе tree_group_step_m. Каждое место проходит те же
нормы, что место сетки; что лучше для улицы - сетка или группы - решает индекс в портфеле.
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import shapely
from shapely.geometry import box

from green.application.constraints import work_boundary
from green.application.params import PlanParams
from green.application.placement import MODE_GROUPS, MODE_LABELS, _group_candidates
from green.application.portfolio import _variants
from green.application.surfaces import Material, build_surface_map
from green.domain.objects import Feature, ObjectClass, SourceRef

LAWN = box(0, 0, 100, 40)


def _feature(cls: ObjectClass, geometry: object, name: str) -> Feature:
    return Feature(SourceRef("12345678", "00000000", name), name, geometry, object_class=cls)  # type: ignore[arg-type]


FEATURES = [
    _feature(ObjectClass.WORK_BOUNDARY, box(-5, -5, 105, 45), "boundary"),
    _feature(ObjectClass.LAWN, LAWN, "lawn"),
]


def _candidates(params: PlanParams | None = None) -> list:
    surface = build_surface_map(FEATURES, [], work_boundary(FEATURES), 0.5)
    assert surface is not None
    return _group_candidates(surface, params or PlanParams())


def test_groups_are_triangles_of_three_with_the_given_side() -> None:
    params = PlanParams(tree_group_side_m=6.0, tree_group_step_m=18.0)
    candidates = _candidates(params)

    groups: dict[int, list] = {}
    for c in candidates:
        groups.setdefault(c.station // 3, []).append(c)
    full = [g for g in groups.values() if len(g) == 3]
    assert len(full) >= 6
    for group in full:
        for a, b in itertools.combinations(group, 2):
            assert math.dist((a.x, a.y), (b.x, b.y)) == np.float64(6.0) or math.isclose(
                math.dist((a.x, a.y), (b.x, b.y)), 6.0, abs_tol=1e-6
            )
    assert {c.mode for c in candidates} == {MODE_GROUPS}


def test_groups_keep_lawn_gaps_between_them() -> None:
    params = PlanParams(tree_group_side_m=6.0, tree_group_step_m=18.0)
    candidates = _candidates(params)

    for a, b in itertools.combinations(candidates, 2):
        if a.station // 3 != b.station // 3:
            # Сторона 6 м, центры через 18 м: между деревьями соседних групп не меньше 18 - 2r.
            assert math.dist((a.x, a.y), (b.x, b.y)) >= 18.0 - 2 * 6.0 / math.sqrt(3) - 1e-6


def test_group_places_are_only_on_soil() -> None:
    candidates = _candidates()
    surface = build_surface_map(FEATURES, [], work_boundary(FEATURES), 0.5)
    assert surface is not None

    points = shapely.points([(c.x, c.y) for c in candidates])
    assert (surface.material(points) == Material.SOIL).all()
    assert all(LAWN.contains(p) for p in points)


def test_portfolio_tries_groups_next_to_the_grid() -> None:
    names = [name for name, _ in _variants(PlanParams(), FEATURES)]
    groups = dict(_variants(PlanParams(), FEATURES))["joint_groups"]

    assert "joint_groups" in names
    assert MODE_GROUPS in groups.modes
    assert "lawn" not in groups.modes
    assert groups.placement_solver == "milp"
    assert MODE_LABELS[MODE_GROUPS].startswith("группа деревьев")
