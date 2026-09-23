"""Ряд кустарника у борта под кронами аллеи на синтетической улице (application/shrub_rows)."""

from __future__ import annotations

import math
from collections import defaultdict
from itertools import pairwise
from typing import TYPE_CHECKING

import pytest
from test_pipeline_synthetic import ROOT, _street

from green.application.shrub_rows import ROW_LABEL
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.domain.norms import PlantingType

if TYPE_CHECKING:
    from pathlib import Path

    from green.domain.planting import Plan


def _plan(work: Path, *, rows: bool) -> Plan:
    source = work / f"street-{rows}.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=work / "runs"))
    params = container.profiles.load("strict", {"max_rejections": 50, "shrub_rows": rows})
    request = PlanRequest(f"rows-{rows}", source, work / f"out-{rows}", "strict", params)
    return container.use_case.execute(request).plan


@pytest.fixture(scope="module")
def plans(tmp_path_factory: pytest.TempPathFactory) -> dict[bool, Plan]:
    work = tmp_path_factory.mktemp("rows")
    return {rows: _plan(work, rows=rows) for rows in (True, False)}


def _hedge(plan: Plan) -> list:
    return [p for p in plan.placements if ROW_LABEL in p.notes]


def test_the_row_keeps_every_norm_and_clears_the_trunks(plans: dict[bool, Plan]) -> None:
    plan = plans[True]
    hedge = _hedge(plan)
    assert hedge, "у аллеи вдоль борта есть полоса 1-2 м, ряд обязан встать"
    trees = [p for p in plan.placements if p.planting_type is PlantingType.TREE]
    for shrub in hedge:
        assert shrub.verdict.value != "forbidden"
        assert all(c.outcome.value != "fail" for c in shrub.checks)
        nearest = min(math.dist((shrub.x, shrub.y), (t.x, t.y)) for t in trees)
        assert nearest >= 1.25 - 1e-6  # полуширина ямы дерева + траншеи (SR-4)


def test_a_segment_is_one_species_with_an_even_step(plans: dict[bool, Plan]) -> None:
    segments: dict[str, list] = defaultdict(list)
    for shrub in _hedge(plans[True]):
        assert shrub.assortment is not None
        segments[shrub.assortment.structure_id or ""].append(shrub)
    for members in segments.values():
        assert len({m.species.code for m in members}) == 1
        steps = [math.dist((a.x, a.y), (b.x, b.y)) for a, b in pairwise(members)]
        assert all(0.38 <= step <= 0.42 for step in steps)  # 743-ПП, табл. 3.6.2
        assert sum(steps) >= 3.0 - 1e-6  # короче - одиночные кусты у борта (SR-13)


def test_only_hardy_species_stand_at_the_curb(plans: dict[bool, Plan]) -> None:
    for shrub in _hedge(plans[True]):
        species = shrub.species
        assert species.salt_tolerance == 2
        assert species.compaction_tolerance == 2
        assert not species.thorny
        assert not species.toxic


def test_the_row_gives_the_alley_a_second_tier_and_shields_the_curb(
    plans: dict[bool, Plan],
) -> None:
    with_rows = {t.key: t.score for t in plans[True].quality.terms}  # type: ignore[union-attr]
    without = {t.key: t.score for t in plans[False].quality.terms}  # type: ignore[union-attr]
    assert (with_rows["tiers"] or 0) > (without["tiers"] or 0)
    assert (with_rows["dust"] or 0) > (without["dust"] or 0)
    assert not _hedge(plans[False])
