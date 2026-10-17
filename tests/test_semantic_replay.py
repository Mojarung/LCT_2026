"""Replays preserve inputs and reject mismatched or stale semantic assignments."""

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import ezdxf
import pytest
from fastapi import BackgroundTasks

from green.application.classification import classification_report, classify_scene
from green.application.errors import ConflictError, InputError
from green.application.params import PlanParams
from green.application.results import RunRecord, RunState
from green.bootstrap.container import Container, build_container
from green.bootstrap.settings import Settings

if TYPE_CHECKING:
    from green.domain.objects import Scene
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource
from green.interfaces.api.review import SemanticReviewIn, replay_review

ROOT = Path(__file__).resolve().parents[1]


def prepared(tmp_path: Path) -> tuple[Container, RunRecord, Scene]:
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    record = container.runs.register("source.dxf", "strict", {"spacing_m": 6, "name_model": False})
    source = container.store.input_path(record.run_id)
    doc = ezdxf.new("R2018")
    doc.units = 6
    doc.layers.new("opaque")
    doc.modelspace().add_lwpolyline(
        [(0, 0), (8, 0), (8, 8), (0, 8)], close=True, dxfattribs={"layer": "opaque"}
    )
    doc.saveas(source)
    layers = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()
    scene, _ = classify_scene(EzdxfSceneReader().read(source), layers, PlanParams(name_model=False))
    report = classification_report(scene, layers)
    paths = container.artifacts.save_classification(
        container.store.run_dir(record.run_id), report, scene=scene, source=source
    )
    failed = container.runs.reject(record.run_id, "Требуется уточнение")
    container.store.save(replace(failed, artifacts=tuple(paths)))
    return container, record, scene


def test_replay_copies_exact_source_inventory_gis_and_params(tmp_path: Path) -> None:
    container, record, scene = prepared(tmp_path)
    original = container.store.input_path(record.run_id)
    original.with_name("inventory.xlsx").write_bytes(b"inventory")
    gis = original.parent / "gis"
    gis.mkdir()
    (gis / "buildings.geojson").write_bytes(b"{}")
    tasks = BackgroundTasks()
    body = SemanticReviewIn(
        source_sha256=scene.source_sha256, feature_classes={str(scene.features[0].ref): "building"}
    )
    result = replay_review(container, tasks, record.run_id, body)
    target = container.store.input_path(result.run_id)
    assert target.read_bytes() == original.read_bytes()
    assert target.with_name("inventory.xlsx").read_bytes() == b"inventory"
    assert (target.parent / "gis/buildings.geojson").read_bytes() == b"{}"
    assert result.profile == record.profile
    assert result.overrides["spacing_m"] == 6
    assert result.overrides["require_reviewed_objects"] is True
    assert tasks.tasks[0].args == (result.run_id, target.with_name("inventory.xlsx"))
    assert tasks.tasks[0].kwargs["gis_layers"] == (target.parent / "gis/buildings.geojson",)
    assert "extra_sources" not in tasks.tasks[0].kwargs
    replayed, _ = classify_scene(
        EzdxfSceneReader().read(target),
        YamlLayerMapSource(ROOT / "config/layer_map.yaml").load(),
        PlanParams(**result.overrides),
    )
    assert replayed.features[0].geometry.area == 64
    assert replayed.features[0].object_class.value == "building"


@pytest.mark.parametrize("case", ["hash", "ref", "changed", "active"])
def test_replay_rejects_unusable_assignments(tmp_path: Path, case: str) -> None:
    container, record, scene = prepared(tmp_path)
    digest = "b" * 64 if case == "hash" else scene.source_sha256
    refs = {"missing": "building"} if case == "ref" else {}
    if case == "changed":
        container.store.artifact(record.run_id, "review-input.dxf").write_bytes(b"changed")
    if case == "active":
        original = container.store.get(record.run_id)
        container.store.save(replace(original, state=RunState.RUNNING))
    with pytest.raises((InputError, ConflictError)):
        replay_review(
            container,
            BackgroundTasks(),
            record.run_id,
            SemanticReviewIn(source_sha256=digest, feature_classes=refs),
        )
    assert len(container.store.recent(20)) == 1
