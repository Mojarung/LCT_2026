"""Карта покрытий строится на прогон один раз.

Её читают расстановка, группы кустарника, ряды у борта, подлесок, добор кустарника и
независимая проверка плана. Раньше расстановка, группы и проверка строили карту заново в
каждом из восьми вариантов портфеля: на Кустанайской это двадцать с лишним построений по
13 с. Карта - функция чертежа и параметров покрытий, а варианты портфеля меняют только
способ расстановки, поэтому одна карта на прогон даёт тот же план.
"""

from __future__ import annotations

import sys
from dataclasses import fields, replace
from typing import TYPE_CHECKING

import pytest
from test_pipeline_synthetic import ROOT, _street

from green.application import surfaces
from green.application.classification import classify_scene
from green.application.constraints import work_boundary
from green.application.placement import GreedyPlantingStrategy
from green.application.portfolio import _variants
from green.application.surfaces import build_surface_map
from green.application.use_case import PlanRequest
from green.application.validation import validate_plan
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.domain.norms import PlantingType

if TYPE_CHECKING:
    from pathlib import Path

# Параметры, от которых зависит карта покрытий (аргументы build_surface_map).
SURFACE_PARAMS = (
    "surface_cell_m",
    "surface_max_distance_m",
    "surface_ambiguity_m",
    "tree_seed_distance_m",
    "surface_inference_mode",
    "require_soil",
)


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    work: Path = tmp_path_factory.mktemp("shared-surface")
    source = work / "street.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=work / "runs"))
    scene, _ = classify_scene(container.reader.read(source), container.layers.load())
    params = container.profiles.load("strict")
    surface = build_surface_map(
        scene.features,
        scene.labels,
        work_boundary(scene.features),
        params.surface_cell_m,
        max_distance_m=params.surface_max_distance_m,
        ambiguity_m=params.surface_ambiguity_m,
        tree_distance_m=params.tree_seed_distance_m,
        inference_mode=params.surface_inference_mode,
    )
    assert surface is not None
    return {
        "container": container,
        "source": source,
        "features": scene.features,
        "labels": scene.labels,
        "params": params,
        "surface": surface,
    }


def _patch_builders(monkeypatch: pytest.MonkeyPatch, replacement: object) -> None:
    """Подменяет build_surface_map во всех модулях пакета, которые её импортировали."""
    original = surfaces.build_surface_map
    for name, module in list(sys.modules.items()):
        if name.startswith("green.") and getattr(module, "build_surface_map", None) is original:
            monkeypatch.setattr(module, "build_surface_map", replacement)


def _forbid_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    def rebuilt(*_args: object, **_kwargs: object) -> None:
        msg = "карта покрытий строится повторно"
        raise AssertionError(msg)

    _patch_builders(monkeypatch, rebuilt)


def test_placement_takes_the_run_surface_and_plans_the_same(
    site: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    container = site["container"]
    params = site["params"]
    rulebook = container.rules.load()  # type: ignore[attr-defined]
    species = container.species.get(params.species_code)  # type: ignore[attr-defined]
    args = (site["features"], site["labels"], rulebook, species, params)
    strategy = GreedyPlantingStrategy()
    own = strategy.plan(*args)  # type: ignore[arg-type]
    _forbid_rebuild(monkeypatch)
    shared = strategy.plan(*args, surface=site["surface"])  # type: ignore[arg-type]
    assert own.placements
    assert shared.placements == own.placements
    assert shared.rejections == own.rejections
    assert shared.stats == own.stats
    assert shared.warnings == own.warnings
    assert [z.verdict for z in shared.zones] == [z.verdict for z in own.zones]
    assert all(a.geometry.equals(b.geometry) for a, b in zip(shared.zones, own.zones, strict=True))


def test_shrub_groups_take_the_run_surface(
    site: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    container = site["container"]
    params = replace(
        site["params"],  # type: ignore[arg-type]
        planting_type=PlantingType.SHRUB,
        spacing_m=site["params"].shrub_group_spacing_m,  # type: ignore[attr-defined]
    )
    shrub = next(s for s in container.species.all() if s.is_shrub)  # type: ignore[attr-defined]
    args = (site["features"], site["labels"], container.rules.load(), shrub, params)  # type: ignore[attr-defined]
    strategy = GreedyPlantingStrategy()
    own = strategy.shrub_groups(*args, centers=[(60.0, 30.0)])  # type: ignore[arg-type]
    _forbid_rebuild(monkeypatch)
    shared = strategy.shrub_groups(*args, centers=[(60.0, 30.0)], surface=site["surface"])  # type: ignore[arg-type]
    assert own
    assert shared == own


def test_validation_takes_the_run_surface_and_finds_the_same(
    site: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    container = site["container"]
    params = site["params"]
    rulebook = container.rules.load()  # type: ignore[attr-defined]
    species = container.species.get(params.species_code)  # type: ignore[attr-defined]
    plan = GreedyPlantingStrategy().plan(
        site["features"],  # type: ignore[arg-type]
        site["labels"],  # type: ignore[arg-type]
        rulebook,
        species,
        params,  # type: ignore[arg-type]
    )
    catalog = container.species.all()  # type: ignore[attr-defined]
    args = (plan, site["features"], site["labels"], rulebook, params)
    own = validate_plan(*args, catalog=catalog)  # type: ignore[arg-type]
    _forbid_rebuild(monkeypatch)
    shared = validate_plan(*args, catalog=catalog, surface=site["surface"])  # type: ignore[arg-type]
    assert shared == own


def test_portfolio_variants_keep_the_surface_params(site: dict[str, object]) -> None:
    """Одна карта на прогон верна, пока варианты портфеля не трогают параметры покрытий."""
    params = site["params"]
    names = {f.name for f in fields(params)}  # type: ignore[arg-type]
    assert set(SURFACE_PARAMS) <= names
    variants = _variants(params, site["features"])  # type: ignore[arg-type]
    assert len(variants) > 2
    for name, variant in variants:
        for key in SURFACE_PARAMS:
            assert getattr(variant, key) == getattr(params, key), (name, key)


def test_run_builds_the_surface_map_once(
    site: dict[str, object], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[int] = []
    original = surfaces.build_surface_map

    def counted(*args: object, **kwargs: object) -> object:
        calls.append(1)
        return original(*args, **kwargs)  # type: ignore[arg-type]

    _patch_builders(monkeypatch, counted)
    container = site["container"]
    params = container.profiles.load("strict", {"max_rejections": 50})  # type: ignore[attr-defined]
    report = container.use_case.execute(  # type: ignore[attr-defined]
        PlanRequest("once", site["source"], tmp_path / "out", "strict", params)  # type: ignore[arg-type]
    )
    assert report.plan.portfolio is not None
    assert len(report.plan.portfolio.variants) > 2
    assert len(calls) == 1
