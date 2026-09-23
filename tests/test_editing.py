"""Правка плана: проверка точки, перенос, удаление, добавление и пересборка DXF.

Главное, что тут проверяется, - что правка не обходит нормы. Перенос в запрещённое место
обязан стать отказом, а не молча остаться допустимой посадкой: интерфейс, позволяющий
поставить дерево на водопровод и назвать это планом, хуже, чем отсутствие интерфейса.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from test_pipeline_synthetic import PIPE_Y, ROOT, _street

from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.infrastructure.config.repositories import YamlSpeciesCatalog
from green.interfaces.api.app import API_PREFIX, create_app

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

CONFLICT = 409


@pytest.fixture(scope="module")
def work(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("editing")


@pytest.fixture(scope="module")
def client(work: Path) -> Iterator[TestClient]:
    settings = Settings(config_dir=ROOT / "config", runs_dir=work / "runs")
    with TestClient(create_app(build_container(settings))) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def run_id(client: TestClient, work: Path) -> str:
    path = work / "street.dxf"
    _street(path, material_areas=False)
    response = client.post(
        f"{API_PREFIX}/runs",
        files={"file": ("street.dxf", path.read_bytes(), "image/vnd.dxf")},
        # Preserve the historical exploratory layout for this quota-deletion
        # regression. Strict surface evidence has separate end-to-end coverage.
        data={
            "profile": "strict",
            "overrides": '{"placement_solver":"greedy","surface_inference_mode":"distance"}',
        },
    )
    return str(response.json()["id"])


def _plan(client: TestClient, run_id: str) -> dict:
    return client.get(f"{API_PREFIX}/runs/{run_id}/artifacts/plan.json").json()


def test_point_far_from_everything_is_allowed(client: TestClient, run_id: str) -> None:
    placement = _plan(client, run_id)["placements"][0]

    response = client.post(
        f"{API_PREFIX}/runs/{run_id}/check",
        json={"x": placement["x"], "y": placement["y"], "species": placement["species"]["code"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "allowed"
    assert body["plantable"] is True
    assert body["checks"], "проверка без трассы правил ничего не объясняет"


def test_point_on_the_pipe_is_refused_with_the_rule_named(client: TestClient, run_id: str) -> None:
    """Точно на оси водопровода: отступ нарушен, и в ответе видно, какой нормой."""
    response = client.post(
        f"{API_PREFIX}/runs/{run_id}/check",
        json={"x": 60.0, "y": PIPE_Y, "species": "tilia_cordata"},
    )

    body = response.json()
    assert body["verdict"] != "allowed"
    failed = [c for c in body["checks"] if c["outcome"] == "fail"]
    assert failed, "нарушение есть, а правила, которое нарушено, в ответе нет"
    assert any(c["object_class"] == "utility.water" for c in failed)


def test_moving_a_planting_onto_the_pipe_makes_it_a_rejection(
    client: TestClient, run_id: str
) -> None:
    """Нарушающая посадка уходит в отказы, а не остаётся деревом с нарушенным отступом.

    Иначе она попадёт в DXF на слой «требует согласования», и в просмотрщике нарушение
    нормы прочитается как решение, которое достаточно согласовать.
    """
    before = _plan(client, run_id)
    placement = before["placements"][0]

    response = client.post(
        f"{API_PREFIX}/runs/{run_id}/edits",
        json={"edits": [{"kind": "move", "placement_id": placement["id"], "x": 60.0, "y": PIPE_Y}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stale"] is True
    assert body["placements"] == len(before["placements"]) - 1
    assert body["rejections"] == len(before["rejections"]) + 1


def test_deleting_a_planting_shrinks_the_plan(client: TestClient, run_id: str) -> None:
    """Считаем от состояния в памяти: plan.json на диске правок ещё не видел."""
    placements = _plan(client, run_id)["placements"]

    first = client.post(
        f"{API_PREFIX}/runs/{run_id}/edits",
        json={"edits": [{"kind": "delete", "placement_id": placements[1]["id"]}]},
    ).json()
    second = client.post(
        f"{API_PREFIX}/runs/{run_id}/edits",
        json={"edits": [{"kind": "delete", "placement_id": placements[2]["id"]}]},
    ).json()

    assert second["placements"] == first["placements"] - 1


def test_unknown_placement_is_rejected_with_a_readable_message(
    client: TestClient, run_id: str
) -> None:
    response = client.post(
        f"{API_PREFIX}/runs/{run_id}/edits",
        json={"edits": [{"kind": "delete", "placement_id": "нет-такой"}]},
    )

    assert response.status_code == 422
    assert "нет-такой" in response.json()["detail"]


def test_rebuild_writes_the_edited_plan_into_the_dxf(client: TestClient, run_id: str) -> None:
    """Правка обязана дойти до файлов, а не остаться картинкой на экране."""
    before = _plan(client, run_id)

    response = client.post(f"{API_PREFIX}/runs/{run_id}/rebuild")
    assert response.status_code == 202

    # Removing only broadleaves can exceed the hard Pinaceae quota. The old
    # exporter reused stale counts; final validation must refuse that export.
    status = client.get(f"{API_PREFIX}/runs/{run_id}").json()
    assert status["state"] == "failed"
    assert "quota" in status["error"]
    assert len(_plan(client, run_id)["placements"]) == len(before["placements"])
    catalog = YamlSpeciesCatalog(ROOT / "config" / "species.yaml")
    conifer = next(
        p
        for p in before["placements"][3:]
        if catalog.get(p["species"]["code"]).family == "Pinaceae"
    )
    client.post(
        f"{API_PREFIX}/runs/{run_id}/edits",
        json={"edits": [{"kind": "delete", "placement_id": conifer["id"]}]},
    )
    client.post(f"{API_PREFIX}/runs/{run_id}/rebuild")
    assert client.get(f"{API_PREFIX}/runs/{run_id}").json()["state"] == "succeeded"

    after = _plan(client, run_id)
    assert len(after["placements"]) < len(before["placements"])
    assert after["summary"]["integrity_ok"] is True
    numbers = [p["number"] for p in after["placements"]]
    assert numbers == list(range(1, len(numbers) + 1)), "нумерация после правки разъехалась"
    summary = client.get(f"{API_PREFIX}/runs/{run_id}/artifacts/assortment.json").json()
    actual = Counter(
        p["species"]["code"] for p in after["placements"] if p["planting_type"] == "tree"
    )
    assert summary["counts"] == actual, "сводка видов осталась от плана до правки"


def test_unknown_run_answers_409_not_a_made_up_verdict(client: TestClient) -> None:
    response = client.post(f"{API_PREFIX}/runs/нет-такого-прогона/check", json={"x": 0.0, "y": 0.0})

    assert response.status_code == CONFLICT
    assert "памяти" in response.json()["detail"]


def test_evicted_run_stops_accepting_edits(client: TestClient, work: Path, run_id: str) -> None:
    """Кэш контекстов хранит один прогон: новый прогон вытесняет прежний, и правка ему 409.

    Тест идёт последним в модуле намеренно - он вытесняет прогон, которым пользуются
    остальные проверки.
    """
    assert client.post(f"{API_PREFIX}/runs/{run_id}/check", json={"x": 0.0, "y": 0.0}).status_code

    path = work / "street3.dxf"
    _street(path)
    client.post(
        f"{API_PREFIX}/runs",
        files={"file": ("street3.dxf", path.read_bytes(), "image/vnd.dxf")},
        data={"profile": "strict"},
    )

    response = client.post(f"{API_PREFIX}/runs/{run_id}/check", json={"x": 0.0, "y": 0.0})

    assert response.status_code == CONFLICT
