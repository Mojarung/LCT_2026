"""Файлы прогона, из которых браузер собирает карту и объяснения.

Интерфейс - SPA на /api/v1 (frontend/): всё, что он показывает, приходит артефактами прогона.
Здесь проверяется, что они есть и сходятся друг с другом; как они выглядят на экране, проверяют
тесты фронта и живой браузер.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient
from test_pipeline_synthetic import ROOT, _street

from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.interfaces.api.app import create_app

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(scope="module")
def work(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("map")


@pytest.fixture(scope="module")
def client(work: Path) -> Iterator[TestClient]:
    # Каталог улиц намеренно пуст: стенд без датасета, где остаётся встроенный фрагмент.
    settings = Settings(
        config_dir=ROOT / "config", runs_dir=work / "runs", streets_dir=work / "без-каталога"
    )
    with TestClient(create_app(build_container(settings))) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def run_id(client: TestClient, work: Path) -> str:
    """Один прогон синтетической улицы на весь модуль: каждый тест читает свои артефакты."""
    path = work / "street.dxf"
    _street(path)
    created = client.post(
        "/api/v1/runs",
        files={"file": ("street.dxf", path.read_bytes(), "image/vnd.dxf")},
        data={"profile": "strict"},
    )
    assert created.status_code == 202, created.text
    record = client.get(f"/api/v1/runs/{created.json()['id']}").json()
    assert record["state"] == "succeeded", record.get("error")
    return str(record["id"])


def _artifact(client: TestClient, run_id: str, name: str) -> Any:  # noqa: ANN401 - JSON
    response = client.get(f"/api/v1/runs/{run_id}/artifacts/{name}")
    assert response.status_code == 200, name
    return response.json()


def test_the_run_lists_everything_the_map_reads(client: TestClient, run_id: str) -> None:
    names = {a["name"] for a in client.get(f"/api/v1/runs/{run_id}").json()["artifacts"]}

    assert {
        "result.dxf",
        "interpretations.csv",
        "plan.json",
        "rules.json",
        "quality.json",
        "basemap.geojson",
        "surface.json",
        "surface.png",
    } <= names


def test_every_planting_has_a_value_and_the_plan_a_quality(client: TestClient, run_id: str) -> None:
    """Нормы отвечают «можно ли», индекс - «насколько хорош план»: у браузера есть оба."""
    quality = _artifact(client, run_id, "quality.json")
    plan = _artifact(client, run_id, "plan.json")

    assert {t["key"] for t in quality["terms"]} >= {"density", "diversity", "canopy", "dust"}
    assert all(t["basis"] for t in quality["terms"])
    assert plan["placements"]
    assert all(p["value"] is not None for p in plan["placements"])
    assert all(
        "Ценность:" in p["explanation"] or "Слабое место" in p["explanation"]
        for p in plan["placements"]
    )


def test_every_checked_rule_joins_an_act_and_a_clause(client: TestClient, run_id: str) -> None:
    """Панель посадки соединяет rule_id с пунктом акта: без этого интерпретируемости нет."""
    plan = _artifact(client, run_id, "plan.json")
    rules = _artifact(client, run_id, "rules.json")["rules"]
    basemap = _artifact(client, run_id, "basemap.geojson")

    counts = basemap["counts"]
    assert counts["features_out"] > 0
    assert counts["features_out"] + sum(counts["dropped"].values()) == counts["features_in"]
    checked = [c for p in plan["placements"] for c in p["checks"]]
    assert checked, "у посадок нет проверенных правил, объяснять будет нечем"
    for check in checked:
        rule = rules[check["rule_id"]]
        assert rule["act_id"]
        assert rule["clause"]


def test_the_map_gets_the_surface_map_and_the_material_labels(
    client: TestClient, run_id: str
) -> None:
    """Карта обязана показывать, где сервис увидел грунт: без этого посадку на площадке со
    спецпокрытием не отличить от посадки на газоне (Харьковская, 23.09.2026)."""
    meta = _artifact(client, run_id, "surface.json")
    image = client.get(f"/api/v1/runs/{run_id}/artifacts/surface.png")
    basemap = _artifact(client, run_id, "basemap.geojson")

    assert image.status_code == 200
    assert image.content.startswith(b"\x89PNG\r\n\x1a\n")
    width = int.from_bytes(image.content[16:20], "big")
    height = int.from_bytes(image.content[20:24], "big")
    assert (width, height) == (meta["width"], meta["height"])
    assert meta["counts"]["soil"] > 0
    assert basemap["labels"], "подписи материала с чертежа не доехали до карты"
    assert {label[3] for label in basemap["labels"]} <= {"paved", "soil"}


def test_the_built_in_site_is_a_real_street(client: TestClient) -> None:
    """Демонстрация обязана работать без единого файла на диске.

    На стенде жюри датасета нет, а показывать сервис надо с первого клика: чертёж встроен в
    сервис, поэтому проверяем весь путь, а не только код ответа.
    """
    created = client.post("/api/v1/runs/demo")
    assert created.status_code == 202, created.text
    run_id = created.json()["id"]

    plan = _artifact(client, run_id, "plan.json")
    assert plan["placements"], "демонстрационный участок не дал ни одной посадки"
    assert plan["summary"]["integrity_ok"] is True
    basemap = _artifact(client, run_id, "basemap.geojson")
    classes = {f["properties"]["class"] for f in basemap["features"]}
    # Образец - фрагмент настоящей улицы, а не нарисованная схема: на нём обязаны быть
    # разные типы сетей, застройка и существующие деревья, иначе показывать нечего.
    assert {
        "utility.water",
        "utility.sewer",
        "utility.gas",
        "utility.heat",
        "utility.power_cable",
        "utility.telecom",
        "building",
        "existing_tree",
        "curb",
    } <= classes, f"в демонстрационном участке не хватает классов: {classes}"
