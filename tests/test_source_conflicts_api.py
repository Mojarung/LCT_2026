"""Saved runs get advisory metadata without rewriting any stored artifact."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Point, box, mapping

from green.application.results import RunState
from green.application.source_conflicts import enrich_saved_basemap
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.interfaces.api.app import create_app


@pytest.mark.parametrize("mode", ["legacy", "source"])
def test_existing_run_conflicts_are_available_without_rerun(tmp_path: Path, mode: str) -> None:
    container = build_container(Settings(config_dir=Path("config"), runs_dir=tmp_path / "runs"))
    record = container.store.create("generic.dxf", "strict", {})
    payload = {
        "type": "FeatureCollection",
        "features": [
            {"properties": {"class": "existing_tree"}, "geometry": mapping(Point(5, 5))},
            {"properties": {"class": "sidewalk"}, "geometry": mapping(box(0, 0, 10, 10))},
        ],
    }
    if mode == "source":
        payload = enrich_saved_basemap(payload)
        payload["source_conflicts"]["basis"] = "source"
    folder = container.store.run_dir(record.run_id)
    folder.mkdir(exist_ok=True)
    artifact = folder / "basemap.geojson"
    original = json.dumps(payload).encode()
    artifact.write_bytes(original)
    container.store.save(replace(record, state=RunState.SUCCEEDED, artifacts=("basemap.geojson",)))
    with TestClient(create_app(container)) as client:
        response = client.get(f"/api/v1/runs/{record.run_id}/artifacts/basemap.geojson")
        assert response.status_code == 200
        result = response.json()["source_conflicts"]
        assert len(result["items"]) == 1
        assert result["basis"] == ("source" if mode == "source" else "saved_basemap")
        assert artifact.read_bytes() == original
        assert container.store.get(record.run_id).state == RunState.SUCCEEDED
