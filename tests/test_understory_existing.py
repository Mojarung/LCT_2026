"""Подлесок под существующим деревом: группа под кроной, не ближе 3 м к стволу (743-ПП п. 9.8)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import ezdxf
import pytest
from test_pipeline_synthetic import ROOT, _street

from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings

if TYPE_CHECKING:
    from pathlib import Path

    from green.domain.planting import Placement, Plan

TRUNK = (60.0, 30.0)
ONLY_UNDERSTORY = {
    "max_rejections": 50,
    "shrub_rows": False,
    "shrub_fill": False,
    "shrub_groups": False,
    "curb_hedges": False,
    "understory": True,
}


SECOND = (TRUNK[0] + 1.7, TRUNK[1])  # вторая метка того же дерева: разобранный знак


def _plan(work: Path, name: str, overrides: dict[str, object]) -> Plan:
    source = work / f"{name}.dxf"
    _street(source)
    doc = ezdxf.readfile(source)
    doc.layers.add("Отдельно стоящее дерево")
    for centre in (TRUNK, SECOND):
        doc.modelspace().add_circle(centre, 0.3, dxfattribs={"layer": "Отдельно стоящее дерево"})
    doc.saveas(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=work / "runs"))
    params = container.profiles.load("strict", {**ONLY_UNDERSTORY, **overrides})
    request = PlanRequest(name, source, work / f"out-{name}", "strict", params)
    return container.use_case.execute(request).plan


@pytest.fixture(scope="module")
def plans(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Plan]:
    work = tmp_path_factory.mktemp("under-existing")
    return {
        "on": _plan(work, "on", {}),
        "off": _plan(work, "off", {"understory_existing": False}),
    }


def _under_existing(plan: Plan) -> list[Placement]:
    return [
        p
        for p in plan.placements
        if p.assortment is not None
        and (p.assortment.structure_id or "").startswith("under-existing")
    ]


def test_group_under_the_existing_crown(plans: dict[str, Plan]) -> None:
    group = _under_existing(plans["on"])
    assert 2 <= len(group) <= 3
    assert len({s.assortment.structure_id for s in group if s.assortment}) == 1
    for shrub in group:
        for mark in (TRUNK, SECOND):
            assert math.dist((shrub.x, shrub.y), mark) >= 3.0 - 1e-6
        assert all(c.outcome.value != "fail" for c in shrub.checks)


def test_switched_off(plans: dict[str, Plan]) -> None:
    assert not _under_existing(plans["off"])


def test_existing_tree_with_understory_counts_in_tiers(plans: dict[str, Plan]) -> None:
    quality = plans["on"].quality
    assert quality is not None
    tiers = next(t for t in quality.terms if t.key == "tiers")
    assert tiers.measure["existing"] == 1
