"""The current draft is distinct from the last successfully saved CAD artifacts."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient
from test_pipeline_synthetic import ROOT, _street

from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.interfaces.api.app import create_app

if TYPE_CHECKING:
    from pathlib import Path


def test_draft_survives_failed_export_and_becomes_saved_only_after_success(tmp_path: Path) -> None:
    source = tmp_path / "street.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    with TestClient(create_app(container)) as client:
        created = client.post(
            "/api/v1/runs",
            files={"file": ("street.dxf", source.read_bytes(), "image/vnd.dxf")},
            data={"profile": "strict"},
        )
        run_id = created.json()["id"]
        url = f"/api/v1/runs/{run_id}"
        response = client.get(url + "/draft")
        assert response.status_code == 200
        initial = response.json()
        assert initial["stale"] is False
        saved = client.get(url + "/artifacts/plan.json").json()
        assert initial["plan"]["placements"] == saved["placements"]
        original_dxf = client.get(url + "/artifacts/result.dxf").content
        groups: dict[str, list[dict]] = defaultdict(list)
        for plant in initial["plan"]["placements"]:
            groups[plant["species"]["code"]].append(plant)
        left, right = next(plants[:2] for plants in groups.values() if len(plants) >= 2)
        moved = client.post(
            url + "/edits",
            json={
                "edits": [
                    {
                        "kind": "move",
                        "placement_id": right["id"],
                        "x": left["x"],
                        "y": left["y"],
                    }
                ]
            },
        )
        assert moved.status_code == 200
        # С 16.10.2026 (чекпоинт, п. 3) перенос впритык к соседу - отказ правки с причиной, а
        # не черновик, который пересборка отклоняет по шагу: интерфейс и файлы не расходятся.
        # Сохранение только после успешной пересборки при черновике с нарушением состава (квота)
        # проверяет test_editing.py::test_rebuild_writes_the_edited_plan_into_the_dxf.
        assert [r["placement_id"] for r in moved.json()["rejected_by_edit"]] == [right["id"]]
        draft = client.get(url + "/draft").json()
        assert draft["stale"] is True
        assert right["id"] not in {p["id"] for p in draft["plan"]["placements"]}
        assert client.get(url + "/artifacts/plan.json").json() == saved
        assert client.get(url + "/artifacts/result.dxf").content == original_dxf
        client.post(url + "/rebuild")
        assert client.get(url).json()["state"] == "succeeded"
        final = client.get(url + "/draft").json()
        assert final["stale"] is False
        assert final["quality"] == client.get(url + "/artifacts/quality.json").json()
        assert (
            final["plan"]["placements"]
            == client.get(url + "/artifacts/plan.json").json()["placements"]
        )
        # Вытесненный из памяти прогон поднимается с диска - с планом после пересборки.
        container.contexts.drop(run_id)
        reopened = client.get(url + "/draft").json()
        assert reopened["stale"] is False
        assert reopened["plan"]["placements"] == final["plan"]["placements"]
