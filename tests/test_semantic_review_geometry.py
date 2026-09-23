"""Review the actual source, keep every object and bind assignments to its bytes."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import ezdxf
import orjson
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import mapping

from green.application.classification import classification_report, classify_scene
from green.application.errors import InputError
from green.application.params import PlanParams
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource
from green.infrastructure.reports.artifacts import FileArtifactSink
from green.interfaces.api.app import API_PREFIX, create_app

ROOT = Path(__file__).resolve().parents[1]


def drawing(path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.units = 6
    doc.layers.new("L26")
    doc.modelspace().add_lwpolyline(
        [(0, 0), (20, 0), (20, 20), (0, 20)], close=True, dxfattribs={"layer": "L26"}
    )
    doc.saveas(path)


def test_api_review_rerun_and_changed_source_rejection(tmp_path: Path) -> None:
    source = tmp_path / "source.dxf"
    drawing(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    with TestClient(create_app(container)) as client:

        def upload(data: bytes, overrides: dict) -> dict:
            response = client.post(
                f"{API_PREFIX}/runs",
                files={"file": ("source.dxf", data, "image/vnd.dxf")},
                data={"profile": "strict", "overrides": orjson.dumps(overrides).decode()},
            )
            assert response.status_code == 202
            return client.get(response.headers["Location"]).json()

        failed = upload(source.read_bytes(), {})
        assert failed["state"] == "failed"
        base = f"{API_PREFIX}/runs/{failed['id']}/artifacts/"
        geo = client.get(base + "semantic-review.geojson").json()
        report = client.get(base + "classification.json").json()
        reviewed = client.get(base + "review-input.dxf").content
        assert reviewed == source.read_bytes()
        assert (
            hashlib.sha256(reviewed).hexdigest() == geo["source_sha256"] == report["source_sha256"]
        )
        assert len(geo["features"]) == report["features"] == 1
        assert geo["features"][0]["geometry"]["type"] == "Polygon"
        assert client.get(f"/runs/{failed['id']}/review").status_code == 200
        assert "Уточнить объекты на чертеже" in client.get(f"/runs/{failed['id']}").text

        overrides = {
            "semantic_source_sha256": geo["source_sha256"],
            "feature_classes": {geo["features"][0]["id"]: "work_boundary"},
            "placement_solver": "greedy",
        }
        success = upload(reviewed, overrides)
        assert success["state"] == "succeeded", success
        assert success["summary"]["semantic_assignments_complete"] is True
        # A valid changed DXF must not inherit the review, even with the same layer name.
        doc = ezdxf.readfile(source)
        doc.modelspace().add_line((0, 0), (50, 50), dxfattribs={"layer": "L26"})
        doc.saveas(source)
        other = upload(source.read_bytes(), overrides)
        assert other["state"] == "failed"
        assert "хеш исходника изменился" in other["error"]
        assert "result.dxf" not in other["artifacts"]


def test_review_keeps_all_objects_holes_small_shapes_and_ignored_layers(tmp_path: Path) -> None:
    source = tmp_path / "source.dxf"
    drawing(source)
    doc = ezdxf.readfile(source)
    doc.layers.new("Рамки")
    doc.modelspace().add_line((1, 2), (1.001, 2.001), dxfattribs={"layer": "Рамки"})
    hatch = doc.modelspace().add_hatch()
    hatch.paths.add_polyline_path([(40, 0), (60, 0), (60, 20), (40, 20)], is_closed=True)
    hatch.paths.add_polyline_path([(45, 5), (55, 5), (55, 15), (45, 15)], is_closed=True, flags=0)
    for i in range(25):
        doc.modelspace().add_point((i, i))
    doc.saveas(source)
    rules = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()
    scene, _ = classify_scene(EzdxfSceneReader().read(source), rules)
    report = classification_report(scene, rules)
    output = tmp_path / "review"
    saved = FileArtifactSink().save_classification(output, report, scene=scene, source=source)
    payload = orjson.loads(saved["semantic-review.geojson"].read_bytes())
    assert len(payload["features"]) == len(scene.features) == 28
    assert len({f["id"] for f in payload["features"]}) == 28
    for feature, original in zip(payload["features"], scene.features, strict=True):
        assert feature["geometry"] == orjson.loads(orjson.dumps(mapping(original.geometry)))
        group = report.groups[feature["properties"]["group"]]
        assert group.layer == original.layer
        assert group.object_class == original.object_class
    assert any(f["properties"]["class"] == "ignore" for f in payload["features"])
    # A changing source may not be published under the report's fingerprint.
    source.write_bytes(b"changed")
    saved = FileArtifactSink().save_classification(
        tmp_path / "changed", report, scene=scene, source=source
    )
    assert "review-input.dxf" not in saved
    assert not (tmp_path / "changed/.review-input.dxf.tmp").exists()


def test_direct_application_cannot_bypass_source_binding(tmp_path: Path) -> None:
    source = tmp_path / "source.dxf"
    drawing(source)
    scene = EzdxfSceneReader().read(source)
    rules = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()
    params = PlanParams(
        semantic_source_sha256=scene.source_sha256, layer_classes={"L26": "work_boundary"}
    )
    classify_scene(scene, rules, params)
    with pytest.raises(InputError, match="хеш исходника изменился"):
        classify_scene(
            replace(scene, source_sha256="0" * 64),
            rules,
            replace(params, require_known_objects=False),
        )
