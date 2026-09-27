"""Правка плана: проверка точки, перенос, удаление, добавление и пересборка DXF.

Главное, что тут проверяется, - что правка не обходит нормы. Перенос в запрещённое место
обязан стать отказом, а не молча остаться допустимой посадкой: интерфейс, позволяющий
поставить дерево на водопровод и назвать это планом, хуже, чем отсутствие интерфейса.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from test_pipeline_synthetic import PIPE_Y, ROOT, _street

from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.infrastructure.config.repositories import YamlSpeciesCatalog
from green.infrastructure.storage.contexts import PickleRunContextStore, code_fingerprint
from green.infrastructure.storage.runs import FileSystemRunStore
from green.interfaces.api.app import API_PREFIX, create_app

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

CONFLICT = 409


# Потолок доли хвойных в прогоне этого модуля: единственный жёсткий предел состава.
CONIFER_CEILING = 0.30


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
        # Историческая раскладка - и без этапов, пришедших позже: шаг 6 м, аллея и газон без
        # добора зоны, без ряда кустарника, подлеска и групп на газоне.
        data={
            "profile": "strict",
            "overrides": json.dumps(
                {
                    "placement_solver": "greedy",
                    "surface_inference_mode": "distance",
                    "spacing_m": 6,
                    "modes": ["alley", "lawn"],
                    "shrub_rows": False,
                    "curb_hedges": False,
                    "understory": False,
                    "shrub_fill": False,
                    # Квоты вида, рода и семейства мягкие (профиль, notes/34), жёсткий предел
                    # состава - потолок хвойных; нижняя граница даёт плану хвойные.
                    "conifer_share": [0.15, CONIFER_CEILING],
                }
            ),
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
    """Правка обязана дойти до файлов, а не остаться картинкой на экране. Правка, которая
    ломает жёсткий предел состава (потолок хвойных), до DXF не доходит: экспорт не берёт
    старые подсчёты, проверка плана пересчитывает состав заново."""
    before = _plan(client, run_id)
    catalog = YamlSpeciesCatalog(ROOT / "config" / "species.yaml")
    draft = client.get(f"{API_PREFIX}/runs/{run_id}/draft").json()["plan"]["placements"]
    trees = [p for p in draft if p["planting_type"] == "tree"]
    conifers = [p for p in trees if catalog.get(p["species"]["code"]).is_conifer]
    broadleaves = [p for p in trees if not catalog.get(p["species"]["code"]).is_conifer]
    assert conifers, "в плане есть хвойные - потолок есть чем перейти"
    removed: list[str] = []
    while broadleaves and len(conifers) <= CONIFER_CEILING * (len(trees) - len(removed)):
        removed.append(broadleaves.pop()["id"])
    client.post(
        f"{API_PREFIX}/runs/{run_id}/edits",
        json={"edits": [{"kind": "delete", "placement_id": pid} for pid in removed]},
    )

    response = client.post(f"{API_PREFIX}/runs/{run_id}/rebuild")
    assert response.status_code == 202
    status = client.get(f"{API_PREFIX}/runs/{run_id}").json()
    assert status["state"] == "failed"
    assert "quota" in status["error"]
    assert len(_plan(client, run_id)["placements"]) == len(before["placements"])

    remaining = len(trees) - len(removed)
    dropped: list[str] = []
    while conifers and len(conifers) > CONIFER_CEILING * remaining:
        dropped.append(conifers.pop()["id"])
        remaining -= 1
    client.post(
        f"{API_PREFIX}/runs/{run_id}/edits",
        json={"edits": [{"kind": "delete", "placement_id": pid} for pid in dropped]},
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
    # Трёхмерная сцена пересобрана вместе с планом, а здания в ней остались.
    scene = client.get(f"{API_PREFIX}/runs/{run_id}/artifacts/scene.json").json()
    assert [p["id"] for p in scene["plants"]] == [p["id"] for p in after["placements"]]
    assert scene["buildings"], "пересборка после правки потеряла объёмы зданий"


def test_unknown_run_answers_409_not_a_made_up_verdict(client: TestClient) -> None:
    response = client.post(f"{API_PREFIX}/runs/нет-такого-прогона/check", json={"x": 0.0, "y": 0.0})

    assert response.status_code == CONFLICT
    assert "не открыт для правки" in response.json()["detail"]


def test_restarted_service_reopens_the_rebuilt_plan_for_editing(work: Path, run_id: str) -> None:
    """Сервис поднят заново над тем же каталогом прогонов: правка идёт по плану после
    пересборки, а не по исходному и не отказом 409, как было, пока контекст жил только в
    памяти (жюри, поднявшее контейнер заново, не могло бы править ни один прогон)."""
    settings = Settings(config_dir=ROOT / "config", runs_dir=work / "runs")
    with TestClient(create_app(build_container(settings))) as restarted:
        draft = restarted.get(f"{API_PREFIX}/runs/{run_id}/draft")
        check = restarted.post(f"{API_PREFIX}/runs/{run_id}/check", json={"x": 60.0, "y": PIPE_Y})
        saved = _plan(restarted, run_id)

    assert draft.status_code == 200
    body = draft.json()
    assert [p["id"] for p in body["plan"]["placements"]] == [p["id"] for p in saved["placements"]]
    assert body["stale"] is False, "поднятый план разошёлся с записанным результатом"
    assert check.status_code == 200
    assert check.json()["verdict"] != "allowed"


def test_context_saved_by_other_code_is_not_reopened(work: Path, run_id: str) -> None:
    """Классы могли измениться: правка по такому контексту была бы проверкой по чужим правилам."""
    runs = FileSystemRunStore(work / "runs")

    assert PickleRunContextStore(runs, code_fingerprint()).load(run_id) is not None
    assert PickleRunContextStore(runs, "другой код").load(run_id) is None


def test_evicted_run_is_reopened_from_disk(client: TestClient, work: Path, run_id: str) -> None:
    """Кэш в памяти хранит один прогон: новый прогон вытесняет прежний, и прежний поднимается
    с диска при первой правке - с тем же ответом проверки точки.

    Тест идёт последним в модуле намеренно - он вытесняет прогон, которым пользуются
    остальные проверки.
    """
    point = {"x": 60.0, "y": PIPE_Y, "species": "tilia_cordata"}
    before = client.post(f"{API_PREFIX}/runs/{run_id}/check", json=point).json()

    path = work / "street3.dxf"
    _street(path)
    client.post(
        f"{API_PREFIX}/runs",
        files={"file": ("street3.dxf", path.read_bytes(), "image/vnd.dxf")},
        data={"profile": "strict"},
    )

    response = client.post(f"{API_PREFIX}/runs/{run_id}/check", json=point)

    assert response.status_code == 200
    after = response.json()
    assert after["verdict"] == before["verdict"]
    assert [c["rule_id"] for c in after["checks"]] == [c["rule_id"] for c in before["checks"]]


def test_edit_recomputes_the_street_effect(client: TestClient, run_id: str) -> None:
    def trees(effect: dict) -> float:
        return next(m for m in effect["measures"] if m["key"] == "trees")["after"]

    before = client.get(f"{API_PREFIX}/runs/{run_id}/draft").json()["quality"]["effect"]
    placements = _plan(client, run_id)["placements"]
    tree = next(p for p in placements if p["planting_type"] == "tree")
    client.post(
        f"{API_PREFIX}/runs/{run_id}/edits",
        json={"edits": [{"kind": "delete", "placement_id": tree["id"]}]},
    )
    after = client.get(f"{API_PREFIX}/runs/{run_id}/draft").json()["quality"]["effect"]
    assert trees(after) == trees(before) - 1


def test_edited_plantings_get_a_place(client: TestClient, run_id: str) -> None:
    placements = _plan(client, run_id)["placements"]
    tree = next(p for p in placements if p["planting_type"] == "tree")
    client.post(
        f"{API_PREFIX}/runs/{run_id}/edits",
        json={
            "edits": [{"kind": "add", "x": 100.0, "y": 40.0, "species": tree["species"]["code"]}]
        },
    )
    draft = client.get(f"{API_PREFIX}/runs/{run_id}/draft").json()["plan"]["placements"]
    assert all(p["place"] for p in draft)
