"""Группы кустарников на местах, которые квоты деревьев оставили пустыми.

Синтетическая улица из test_pipeline_synthetic: газон между бортом (y=20) и зданием (y=55),
водопровод d=300 по y=40. Место на газоне помечено как отказ по квотам деревьев.
Для водопровода у кустарника в табл. 9.1 СП 42 норма не задана, поэтому отступ проверяется
от стены здания: 1,5 м (R-BLD-SHRUB-001).
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from test_pipeline_synthetic import ROOT, _street

from green.application.classification import classify_scene
from green.application.placement import GreedyPlantingStrategy
from green.application.shrub_groups import fill_shrub_groups
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.domain.norms import PlantingType
from green.domain.planting import Plan, Rejection, Verdict

if TYPE_CHECKING:
    from pathlib import Path

QUOTA_NOTE = "ни один из 7 допустимых по нормам видов не укладывается в квоты разнообразия"


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    work: Path = tmp_path_factory.mktemp("shrubs")
    source = work / "street.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=work / "runs"))
    scene, _ = classify_scene(container.reader.read(source), container.layers.load())
    return {
        "container": container,
        "features": scene.features,
        "labels": scene.labels,
        "params": container.profiles.load("strict"),
    }


def _plan(*rejections: Rejection) -> Plan:
    return Plan(placements=(), rejections=rejections)


def _empty_place(x: float, y: float, note: str = QUOTA_NOTE) -> Rejection:
    return Rejection(
        rejection_id=f"p-{x:.0f}-{y:.0f}",
        number=1,
        planting_type=PlantingType.TREE,
        x=x,
        y=y,
        verdict=Verdict.ALLOWED,
        blocking=(),
        note=note,
    )


def _fill(site: dict[str, object], plan: Plan, **overrides: object) -> Plan:
    container = site["container"]
    params = site["params"]
    return fill_shrub_groups(
        plan,
        strategy=GreedyPlantingStrategy(),
        features=site["features"],  # type: ignore[arg-type]
        labels=site["labels"],  # type: ignore[arg-type]
        rulebook=container.rules.load(),  # type: ignore[attr-defined]
        catalog=container.species.all(),  # type: ignore[attr-defined]
        params=replace(params, **overrides),  # type: ignore[arg-type]
    )


def test_quota_empty_place_becomes_a_group_of_shrubs(site: dict[str, object]) -> None:
    # Жёсткие квоты (quota_penalty = 0): группа занимает столько мест, сколько квоты позволяют.
    result = _fill(site, _plan(_empty_place(60.0, 30.0)), quota_penalty=0.0)
    shrubs = result.placements
    assert 1 <= len(shrubs) <= 9
    assert all(p.planting_type is PlantingType.SHRUB for p in shrubs)
    assert all(p.species.is_shrub for p in shrubs)
    assert all(abs(p.x - 60.0) <= 1.0 + 1e-6 and abs(p.y - 30.0) <= 1.0 + 1e-6 for p in shrubs)
    assert result.rejections == ()  # отказ дерева на этом месте снят
    summary = result.shrub_assortment_summary
    assert summary is not None
    assert not summary.quota_violations
    assert any("Группы кустарников" in w for w in result.warnings)


def test_soft_quotas_fill_the_whole_group(site: dict[str, object]) -> None:
    """Мягкие квоты профиля (notes/34): место, прошедшее нормы, не пустеет, перебор доли виден."""
    hard = _fill(site, _plan(_empty_place(60.0, 30.0)), quota_penalty=0.0)
    soft = _fill(site, _plan(_empty_place(60.0, 30.0)))
    assert site["params"].quota_penalty > 0  # type: ignore[attr-defined]
    assert len(soft.placements) >= len(hard.placements)
    assert soft.rejections == ()
    summary = soft.shrub_assortment_summary
    assert summary is not None
    # Одна группа 3 x 3 - один вид: доля 100% больше квоты, это перебор мягкой квоты, а не отказ.
    # Вид назван по-русски, как его читает эксперт, а не кодом каталога.
    assert all("квота" in violation for violation in summary.quota_violations)
    assert not any("_" in violation for violation in summary.quota_violations)


BUILDING_Y = 55.0
SHRUB_TO_WALL_M = 1.5


def test_shrub_points_keep_the_shrub_distance_to_a_wall(site: dict[str, object]) -> None:
    """Центр в 2 м от стены: нижний ряд группы в 3 м проходит, верхний в 1 м - нет."""
    result = _fill(site, _plan(_empty_place(60.0, BUILDING_Y - 2.0)))
    assert result.placements
    for placement in result.placements:
        assert BUILDING_Y - placement.y >= SHRUB_TO_WALL_M - 1e-6
        wall = next(c for c in placement.checks if c.rule_id == "R-BLD-SHRUB-001")
        assert wall.measured_m is not None
        assert wall.measured_m >= SHRUB_TO_WALL_M - 1e-6
    assert max(p.y for p in result.placements) < BUILDING_Y - 1.5


def test_norm_rejections_are_not_turned_into_shrubs(site: dict[str, object]) -> None:
    """Отказ по нормам (без note) не место для кустарника: заполняются только места квот."""
    plan = _plan(_empty_place(60.0, 30.0, note=""))
    assert _fill(site, plan) is plan


def test_shrub_groups_can_be_switched_off(site: dict[str, object]) -> None:
    plan = _plan(_empty_place(60.0, 30.0))
    assert _fill(site, plan, shrub_groups=False) is plan
