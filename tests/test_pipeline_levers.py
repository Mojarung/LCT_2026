"""Приёмы, найденные экспериментами docs/notes/30: добор зоны, изгородь вдоль бортов, кустарник
под кроной, исключение «один экземпляр» в квотах, вместимость зоны для индекса."""

from __future__ import annotations

import math
from collections import defaultdict
from itertools import pairwise
from typing import TYPE_CHECKING

import pytest
from shapely.geometry import box
from test_assortment_assign import CATALOG, SCORES
from test_pipeline_synthetic import CURB_Y, ROOT, _street

from green.application.assortment.assign import Candidate, assign
from green.application.params import PlanParams
from green.application.shrub_fill import FILL_LABEL
from green.application.shrub_rows import CURB_LABEL
from green.application.understory import UNDER_LABEL
from green.application.use_case import PlanRequest
from green.application.zones import zone_capacity
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.domain.norms import PlantingType
from green.domain.planting import Verdict, Zone

if TYPE_CHECKING:
    from pathlib import Path

    from green.domain.planting import Plan

COMMON = {"max_rejections": 50, "spacing_m": 5.0}
LEVERS = {
    **COMMON,
    "modes": ["alley", "lawn", "fill"],
    "curb_hedges": True,
    "understory": True,
    "hedge_species_balance": True,
    "alley_priority": 2.0,
}
PLAIN = {**COMMON, "modes": ["alley", "lawn"], "curb_hedges": False, "understory": False}
# Изгородь без аллеи и без предела плотности: весь борт с грунтом - для изгороди.
HEDGE_ONLY = {
    **COMMON,
    "modes": ["lawn"],
    "curb_hedges": True,
    "curb_hedge_density_cap": False,
    "understory": False,
    "shrub_groups": False,
}


def _plan(work: Path, name: str, overrides: dict[str, object]) -> Plan:
    source = work / f"{name}.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=work / "runs"))
    params = container.profiles.load("strict", overrides)
    request = PlanRequest(name, source, work / f"out-{name}", "strict", params)
    return container.use_case.execute(request).plan


@pytest.fixture(scope="module")
def plans(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Plan]:
    work = tmp_path_factory.mktemp("levers")
    variants = {"levers": LEVERS, "plain": PLAIN, "hedges": HEDGE_ONLY}
    return {name: _plan(work, name, overrides) for name, overrides in variants.items()}


def _trees(plan: Plan) -> list:
    return [p for p in plan.placements if p.planting_type is PlantingType.TREE]


def test_every_new_planting_keeps_every_norm(plans: dict[str, Plan]) -> None:
    for plan in plans.values():
        for placement in plan.placements:
            assert placement.verdict is not Verdict.FORBIDDEN
            assert all(c.outcome.value != "fail" for c in placement.checks)
        assert plan.quality is not None
        assert plan.quality.index is not None


def test_zone_fill_adds_trees_and_keeps_the_step(plans: dict[str, Plan]) -> None:
    filled, plain = _trees(plans["levers"]), _trees(plans["plain"])
    assert len(filled) >= len(plain)
    step = 5.0 * 0.95
    points = [(p.x, p.y) for p in filled]
    closest = min(math.dist(a, b) for i, a in enumerate(points) for b in points[i + 1 :])
    assert closest >= step - 1e-6


def test_understory_groups_stand_under_their_crown(plans: dict[str, Plan]) -> None:
    plan = plans["levers"]
    trees = {p.placement_id: p for p in _trees(plan)}
    groups: dict[str, list] = defaultdict(list)
    for shrub in plan.placements:
        if UNDER_LABEL in shrub.notes:
            assert shrub.assortment is not None
            groups[shrub.assortment.structure_id or ""].append(shrub)
    for structure, members in groups.items():
        tree = trees[structure.removeprefix("under-")]
        radius = max(tree.species.crown_mature_m or tree.species.crown_diameter_m, 0.0) / 2
        assert len(members) <= 3  # 743-ПП, п. 10.8.1: малая группа - 2-3 растения
        assert len({m.species.code for m in members}) == 1
        for shrub in members:
            distance = math.dist((shrub.x, shrub.y), (tree.x, tree.y))
            assert 1.25 - 1e-6 <= distance < radius
            assert shrub.species.light in {"shade", "semi"}


def test_curb_hedge_runs_along_the_curb_with_a_tall_shrub_step(plans: dict[str, Plan]) -> None:
    hedge = [p for p in plans["hedges"].placements if CURB_LABEL in p.notes]
    assert hedge, "у борта полоса газона, изгородь обязана встать"
    segments: dict[str, list] = defaultdict(list)
    for shrub in hedge:
        assert abs(shrub.y - CURB_Y) >= 1.0 - 1e-6  # кустарник от борта - 1,0 м (743-ПП)
        assert shrub.assortment is not None
        segments[shrub.assortment.structure_id or ""].append(shrub)
    for members in segments.values():
        assert len({m.species.code for m in members}) == 1
        ordered = sorted(members, key=lambda p: p.x)
        steps = [math.dist((a.x, a.y), (b.x, b.y)) for a, b in pairwise(ordered)]
        # 743-ПП, табл. 3.6.2: высокие кустарники в ряду 0,5-1 м.
        assert all(0.95 <= step <= 1.05 for step in steps)


def test_curb_hedge_stops_at_the_upper_shrub_density(plans: dict[str, Plan]) -> None:
    plan = plans["levers"]
    assert plan.quality is not None
    measure = next(t.measure for t in plan.quality.terms if t.key == "density")
    hedge = [p for p in plan.placements if CURB_LABEL in p.notes]
    assert not hedge or measure["shrubs_per_km"] <= 720 + 1e-6  # МГСН 1.02-02, табл. В.1


def _candidates(places: int, codes: tuple[str, ...]) -> list[Candidate]:
    return [
        Candidate(f"p-{i:03d}", f"single-{i}", "single", CATALOG[code], SCORES[code])
        for i in range(places)
        for code in codes
    ]


def test_one_of_a_kind_does_not_break_the_quota_on_a_small_site() -> None:
    """Три вида из трёх семейств на пятнадцати местах: доля 10% - меньше одного растения."""
    candidates = _candidates(15, ("tilia_cordata", "acer_platanoides", "ulmus_laevis"))
    old = assign(candidates, (), CATALOG, {}, PlanParams(quota_single_places=1.0))
    new = assign(candidates, (), CATALOG, {}, PlanParams())
    assert len(old.species_by_placement) == 0  # как было: ни одного дерева
    assert len(new.species_by_placement) == 3  # по одному каждого вида, рода и семейства
    assert not new.quota_violations


def test_zone_capacity_is_length_over_step_on_a_strip() -> None:
    strip = Zone(verdict=Verdict.ALLOWED, geometry=box(0.0, 0.0, 100.0, 1.0))
    assert zone_capacity((strip,)) == 20  # полоса 100 м при шаге 5 м
    square = Zone(verdict=Verdict.NEEDS_APPROVAL, geometry=box(0.0, 0.0, 20.0, 20.0))
    assert 16 <= zone_capacity((square,)) <= 20  # 4 x 4 по сетке или чуть плотнее


def test_lawn_shrub_groups_stay_clear_of_trunks_and_stop_at_the_norm(
    plans: dict[str, Plan],
) -> None:
    plan = plans["levers"]
    trees = _trees(plan)
    fill = [p for p in plan.placements if FILL_LABEL in p.notes]
    for shrub in fill:
        nearest = min(math.dist((shrub.x, shrub.y), (t.x, t.y)) for t in trees)
        assert nearest >= 1.25 - 1e-6
        assert shrub.assortment is not None
        assert shrub.assortment.structure_kind == "group"
    assert plan.quality is not None
    measure = next(t.measure for t in plan.quality.terms if t.key == "density")
    # Группы ставятся, пока кустарников меньше 600 на 1 км: перебор - не больше одной группы.
    km = measure["street_length_m"] / 1000
    assert (
        not fill
        or len([p for p in plan.placements if p.planting_type is PlantingType.SHRUB])
        <= 600 * km + 9
    )
