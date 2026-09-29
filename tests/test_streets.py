"""Каталог улиц пилотного проекта: чтение с диска, список в API, прогон по выбору.

Датасет в репозиторий не кладут, поэтому каталог здесь собирается из синтетического
чертежа: проверяется не содержимое улиц, а то, что сервис переживает и пустой каталог, и
битую запись, и доводит выбранную улицу до готового плана.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from test_pipeline_synthetic import ROOT, _street

from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.infrastructure.streets import JsonStreetCatalog
from green.interfaces.api.app import create_app
from green.interfaces.api.intake import accept_street_run

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def _catalog_with_street(root: Path, *, extra: bool = False) -> Path:
    """Каталог из одной улицы: подоснова и, если попросили, второй файл комплекта."""
    folder = root / "07-test-street"
    folder.mkdir(parents=True)
    _street(folder / "main.dxf")
    files = ["main.dxf"]
    if extra:
        _street(folder / "utilities.dxf")
        files.append("utilities.dxf")
    (root / "catalog.json").write_text(
        json.dumps(
            [
                {
                    "slug": "07-test-street",
                    "number": 7,
                    "title": "Тестовая улица",
                    "main": "main.dxf",
                    "files": files,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return folder


@pytest.fixture(scope="module")
def work(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("streets")


@pytest.fixture(scope="module")
def client(work: Path) -> Iterator[TestClient]:
    _catalog_with_street(work / "catalog", extra=True)
    settings = Settings(
        config_dir=ROOT / "config",
        runs_dir=work / "runs",
        streets_dir=work / "catalog",
    )
    with TestClient(create_app(build_container(settings))) as test_client:
        yield test_client


def test_missing_directory_is_an_empty_catalog(tmp_path: Path) -> None:
    """Датасет монтируется не везде: отсутствие каталога - не ошибка, а пустой список."""
    assert JsonStreetCatalog(tmp_path / "нет-такой-папки").all() == ()


def test_catalog_reads_the_complete_set(tmp_path: Path) -> None:
    folder = _catalog_with_street(tmp_path, extra=True)

    streets = JsonStreetCatalog(tmp_path).all()

    assert len(streets) == 1
    street = streets[0]
    assert street.slug == "07-test-street"
    assert street.title == "Тестовая улица"
    assert street.main == folder / "main.dxf"
    assert street.extra == (folder / "utilities.dxf",)
    assert street.size_mb > 0


def test_street_without_its_drawing_is_skipped(tmp_path: Path) -> None:
    """Строка в списке, которая падает при выборе, хуже отсутствия строки."""
    (tmp_path / "catalog.json").write_text(
        json.dumps([{"slug": "gone", "number": 1, "title": "Улица без файла", "main": "main.dxf"}]),
        encoding="utf-8",
    )

    assert JsonStreetCatalog(tmp_path).all() == ()


def test_broken_catalog_does_not_break_the_page(tmp_path: Path) -> None:
    """Каталог собирается скриптом снаружи: его можно испортить, сервис от этого не падает."""
    (tmp_path / "catalog.json").write_text("{не json", encoding="utf-8")

    assert JsonStreetCatalog(tmp_path).all() == ()


def test_api_lists_streets(client: TestClient) -> None:
    response = client.get("/api/v1/streets")

    assert response.status_code == 200
    rows = response.json()
    assert [row["slug"] for row in rows] == ["07-test-street"]
    assert rows[0]["files"] == 2, "комплект считается вместе с сетями"


def test_api_street_run_goes_all_the_way_to_a_plan(client: TestClient) -> None:
    """Главное: выбранная улица копируется в прогон и доходит до плана с посадками."""
    created = client.post(
        "/api/v1/runs",
        data={"street": "07-test-street", "profile": "strict", "overrides": '{"spacing_m": 6}'},
    )

    assert created.status_code == 202, created.text
    record = client.get(f"/api/v1/runs/{created.json()['id']}").json()
    assert record["state"] == "succeeded", record.get("error")
    assert record["summary"]["placements"] > 0
    assert record["source_name"] == "Тестовая улица.dxf"
    assert record["overrides"] == {"spacing_m": 6}


def test_api_refuses_unknown_street(client: TestClient) -> None:
    response = client.post("/api/v1/runs", data={"street": "нет-такой-улицы"})

    assert response.status_code == 422
    assert "нет в каталоге" in response.json()["detail"]


def test_api_street_with_bad_overrides_is_refused_before_the_queue(client: TestClient) -> None:
    """Улица из каталога идёт мимо загрузки файла - параметры проверяются и здесь до
    регистрации прогона, ответ 422 по-русски с обоими неверными полями."""
    before = len(client.get("/api/v1/runs", params={"limit": 200}).json()["items"])

    response = client.post(
        "/api/v1/runs",
        data={"street": "07-test-street", "overrides": '{"spacing_m": -3, "bogus": 1}'},
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert "spacing_m: должно быть не меньше 0.3 (получено -3)" in detail
    assert "bogus: такого параметра нет (получено 1)" in detail
    assert "pydantic" not in detail
    assert len(client.get("/api/v1/runs", params={"limit": 200}).json()["items"]) == before


def test_api_run_needs_a_source(client: TestClient) -> None:
    response = client.post("/api/v1/runs", data={"profile": "strict"})

    assert response.status_code == 422
    assert "улицу" in response.json()["detail"]


def test_api_refuses_street_and_file_together(client: TestClient, work: Path) -> None:
    """Два источника - два разных прогона: сервис не выбирает за человека, какой из них нужен."""
    path = work / "own.dxf"
    _street(path)
    response = client.post(
        "/api/v1/runs",
        data={"street": "07-test-street"},
        files={"file": ("own.dxf", path.read_bytes(), "image/vnd.dxf")},
    )

    assert response.status_code == 422
    assert "одно" in response.json()["detail"]


def test_api_street_takes_no_extra_drawings(client: TestClient, work: Path) -> None:
    """У улицы свой комплект: чужой лист сети рядом с ним склеился бы молча."""
    path = work / "extra.dxf"
    _street(path)
    response = client.post(
        "/api/v1/runs",
        data={"street": "07-test-street"},
        files={"extra": ("extra.dxf", path.read_bytes(), "image/vnd.dxf")},
    )

    assert response.status_code == 422
    assert "комплект" in response.json()["detail"]


def test_catalog_gives_archive_paths_and_absent_references(tmp_path: Path) -> None:
    """Сборка ищет файл ссылки по пути в архиве, как AutoCAD; ссылки без файла у заказчика
    каталог перечисляет, чтобы прогон показал пробел, а не молча его проглотил."""
    folder = _catalog_with_street(tmp_path, extra=True)
    catalog = json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))
    catalog[0]["sources"] = {
        "main.dxf": "Исходные данные/ГП.dwg",
        "utilities.dxf": "Исходные данные/сети/tp.dwg",
    }
    catalog[0]["missing_xrefs"] = [
        {"host": "main.dxf", "block": "НО", "reference": r".\НО.dwg", "why": "нет в архиве"},
        {"host": "gone.dxf", "block": "X", "reference": "X.dwg", "why": "нет в архиве"},
    ]
    (tmp_path / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False), "utf-8")

    street = JsonStreetCatalog(tmp_path).get("07-test-street")

    assert street is not None
    assert street.main == folder / "main.dxf"
    assert street.sources == ("Исходные данные/ГП.dwg", "Исходные данные/сети/tp.dwg")
    assert street.absent_references == (("Исходные данные/ГП.dwg", r".\НО.dwg"),)


def test_street_units_from_the_catalog_reach_the_run(tmp_path: Path) -> None:
    """Песчаный: заголовок генплана говорит «миллиметры», геометрия метровая. Каталог знает
    ответ, и прогон улицы получает drawing_unit из него, если человек не задал единицы сам."""
    _catalog_with_street(tmp_path)
    catalog = json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))
    catalog[0]["drawing_unit"] = "m"
    (tmp_path / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False), "utf-8")
    street = JsonStreetCatalog(tmp_path).get("07-test-street")
    assert street is not None
    assert street.drawing_unit == "m"
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))

    # Приём прогона асинхронный (перечётная ведомость читается из запроса), фон не запускается.
    record = asyncio.run(
        accept_street_run(container=container, background=BackgroundTasks(), street=street)
    )
    own = asyncio.run(
        accept_street_run(
            container=container,
            background=BackgroundTasks(),
            street=street,
            overrides='{"drawing_unit": "mm"}',
        )
    )

    assert record.overrides["drawing_unit"] == "m"
    assert own.overrides["drawing_unit"] == "mm"
