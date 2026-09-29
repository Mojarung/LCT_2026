"""Правка, которая переводит посадку в отказ, называет её в ответе, а не молча.

Перенос в запретное место по-прежнему отвечает 200: правка принята, план пересчитан, а
посадка, не прошедшая нормы, ушла в отказы. Ответ перечисляет такие посадки с той же причиной,
что даёт проверка точки: без этого о них узнают только по счётчику отказов.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from test_pipeline_synthetic import PIPE_Y, ROOT, _street

from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.interfaces.api.app import API_PREFIX, create_app

if TYPE_CHECKING:
    from collections.abc import Iterator

# Точка на оси водопровода синтетической улицы и точка вне границы работ.
ON_PIPE = (60.0, PIPE_Y)
OFF_SITE = (-30.0, -30.0)
# Причина - фраза по-русски: начинается с кириллической буквы, не пустая. Регистр первой
# буквы - как в ответе проверки точки: фразы берутся дословно.
RUSSIAN_SENTENCE = re.compile(r"^[А-Яа-яЁё].{10,}", re.DOTALL)


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    work = tmp_path_factory.mktemp("edit-rejections")
    settings = Settings(config_dir=ROOT / "config", runs_dir=work / "runs")
    with TestClient(create_app(build_container(settings))) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def run_id(client: TestClient, tmp_path_factory: pytest.TempPathFactory) -> str:
    path = tmp_path_factory.mktemp("edit-rejections-source") / "street.dxf"
    _street(path)
    response = client.post(
        f"{API_PREFIX}/runs",
        files={"file": ("street.dxf", path.read_bytes(), "image/vnd.dxf")},
        data={"profile": "strict"},
    )
    run_id = str(response.json()["id"])
    assert client.get(f"{API_PREFIX}/runs/{run_id}").json()["state"] == "succeeded"
    return run_id


def _draft(client: TestClient, run_id: str) -> dict:
    return client.get(f"{API_PREFIX}/runs/{run_id}/draft").json()["plan"]


def _tree(client: TestClient, run_id: str) -> dict:
    return next(p for p in _draft(client, run_id)["placements"] if p["planting_type"] == "tree")


def _check(client: TestClient, run_id: str, point: tuple[float, float], species: str) -> dict:
    x, y = point
    response = client.post(
        f"{API_PREFIX}/runs/{run_id}/check", json={"x": x, "y": y, "species": species}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _edit(client: TestClient, run_id: str, edit: dict) -> dict:
    response = client.post(f"{API_PREFIX}/runs/{run_id}/edits", json={"edits": [edit]})
    assert response.status_code == 200, response.text
    return response.json()


def test_move_onto_the_pipe_names_the_planting_and_the_broken_rule(
    client: TestClient, run_id: str
) -> None:
    tree = _tree(client, run_id)
    check = _check(client, run_id, ON_PIPE, tree["species"]["code"])
    failed = [c["rule_id"] for c in check["checks"] if c["outcome"] == "fail"]
    assert check["verdict"] == "forbidden"
    assert failed, "точка на оси трубы обязана нарушать отступ"

    x, y = ON_PIPE
    body = _edit(client, run_id, {"kind": "move", "placement_id": tree["id"], "x": x, "y": y})

    assert [r["placement_id"] for r in body["rejected_by_edit"]] == [tree["id"]]
    reason = body["rejected_by_edit"][0]["reason"]
    assert RUSSIAN_SENTENCE.match(reason), reason
    for rule_id in failed:
        assert rule_id in reason, (rule_id, reason)
    assert check["note"] in reason
    assert tree["id"] in {r["id"] for r in _draft(client, run_id)["rejections"]}


def test_move_off_the_site_gives_the_point_check_note(client: TestClient, run_id: str) -> None:
    """Место непригодно, а не нарушен отступ: причина - та же фраза, что в note проверки."""
    tree = _tree(client, run_id)
    check = _check(client, run_id, OFF_SITE, tree["species"]["code"])
    assert check["plantable"] is False
    assert check["note"], "у непригодного места проверка точки называет причину"

    x, y = OFF_SITE
    body = _edit(client, run_id, {"kind": "move", "placement_id": tree["id"], "x": x, "y": y})

    assert [r["placement_id"] for r in body["rejected_by_edit"]] == [tree["id"]]
    assert check["note"] in body["rejected_by_edit"][0]["reason"]


def test_planting_added_onto_the_pipe_is_named_as_rejected(client: TestClient, run_id: str) -> None:
    """Добавленная в запретное место посадка тоже уходит в отказ - и тоже не молча."""
    before = {p["id"] for p in _draft(client, run_id)["placements"]}
    species = _tree(client, run_id)["species"]["code"]
    x, y = ON_PIPE

    body = _edit(client, run_id, {"kind": "add", "x": x, "y": y, "species": species})

    assert len(body["rejected_by_edit"]) == 1
    added = body["rejected_by_edit"][0]["placement_id"]
    assert added not in before
    assert added in {r["id"] for r in _draft(client, run_id)["rejections"]}
    assert RUSSIAN_SENTENCE.match(body["rejected_by_edit"][0]["reason"])


def test_edit_that_keeps_its_plantings_reports_no_rejections(
    client: TestClient, run_id: str
) -> None:
    """Отказы прошлых правок в ответ новой правки не попадают: список - только этой правки."""
    placements = _draft(client, run_id)["placements"]
    assert _draft(client, run_id)["rejections"], "прошлые правки уже дали отказы"

    deleted = _edit(client, run_id, {"kind": "delete", "placement_id": placements[0]["id"]})
    stay = placements[1]
    moved = _edit(
        client,
        run_id,
        {"kind": "move", "placement_id": stay["id"], "x": stay["x"], "y": stay["y"]},
    )

    assert deleted["rejected_by_edit"] == []
    assert moved["rejected_by_edit"] == []
