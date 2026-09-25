"""Каталог улиц пилотного проекта: чтение с диска, список в API, прогон по выбору.

Датасет в репозиторий не кладут, поэтому каталог здесь собирается из синтетического
чертежа: проверяется не содержимое улиц, а то, что сервис переживает и пустой каталог, и
битую запись, и доводит выбранную улицу до готового плана.
"""

from __future__ import annotations

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


def test_index_offers_the_street(client: TestClient) -> None:
    page = client.get("/").text

    assert "Улица пилотного проекта" in page
    assert "07-test-street" in page


def test_built_in_fragment_gives_way_to_the_catalog(client: TestClient) -> None:
    """Когда улицы есть, встроенный фрагмент с первого экрана уходит.

    Он нужен ровно там, где датасет не смонтирован: иначе он занимает первое место формы
    и предлагает триста метров улицы вместо девятнадцати настоящих.
    """
    page = client.get("/").text

    assert "Встроенный участок" not in page
    assert "/web/demo" not in page
    assert "Тестовая улица" in page


def test_unknown_street_is_refused(client: TestClient) -> None:
    response = client.post("/web/runs", data={"street": "нет-такой-улицы"}, follow_redirects=False)

    assert response.status_code == 422
    assert "нет в каталоге" in response.json()["detail"]


def test_run_without_any_source_says_what_to_do(client: TestClient) -> None:
    response = client.post("/web/runs", data={}, follow_redirects=False)

    assert response.status_code == 422
    assert "улицу" in response.json()["detail"]


def test_street_run_goes_all_the_way_to_a_plan(client: TestClient) -> None:
    """Главное: выбранная улица копируется в прогон и доходит до плана с посадками."""
    created = client.post(
        "/web/runs",
        data={"street": "07-test-street", "profile": "strict", "spacing_m": "6"},
        follow_redirects=False,
    )

    assert created.status_code == 303
    run_id = created.headers["location"].rsplit("/", 1)[-1]
    record = client.get(f"/api/v1/runs/{run_id}").json()
    assert record["state"] == "succeeded", record.get("error")
    assert record["summary"]["placements"] > 0
    assert record["source_name"] == "Тестовая улица.dxf", "в реестре улица названа улицей"


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

    record = accept_street_run(container=container, background=BackgroundTasks(), street=street)
    own = accept_street_run(
        container=container,
        background=BackgroundTasks(),
        street=street,
        overrides='{"drawing_unit": "mm"}',
    )

    assert record.overrides["drawing_unit"] == "m"
    assert own.overrides["drawing_unit"] == "mm"
