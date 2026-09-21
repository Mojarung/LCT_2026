"""Веб-интерфейс: страницы отвечают, форма запускает прогон, наружу ничего не тянется.

Проверка «ноль внешних запросов» тут механическая и намеренно грубая: целевая среда -
Linux-стенд без интернета, и одна ссылка на CDN, оставленная по невнимательности, превращает
страницу в пустой экран ровно в момент показа жюри.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from test_pipeline_synthetic import ROOT, _street

from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.interfaces.api.app import create_app

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

WEB_DIR = ROOT / "src" / "green" / "interfaces" / "web"
EXTERNAL = re.compile(r"""["'(]\s*(?:https?:)?//[^"')\s]+""")


@pytest.fixture(scope="module")
def work(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("web")


@pytest.fixture(scope="module")
def client(work: Path) -> Iterator[TestClient]:
    settings = Settings(config_dir=ROOT / "config", runs_dir=work / "runs")
    with TestClient(create_app(build_container(settings))) as test_client:
        yield test_client


def test_index_renders_with_profiles(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "strict" in response.text
    assert "Новый прогон" in response.text


def test_static_files_are_served(client: TestClient) -> None:
    for name in ("app.css", "plan.js"):
        response = client.get(f"/static/{name}")
        assert response.status_code == 200, name


def test_unknown_run_page_is_not_found(client: TestClient) -> None:
    response = client.get("/runs/нет-такого")

    assert response.status_code == 404


@pytest.mark.parametrize(
    "sample",
    [
        '<script src="https://unpkg.com/htmx.org@2"></script>',
        "<link href='//cdn.jsdelivr.net/x.css'>",
        "@import url(https://fonts.googleapis.com/css2?family=Inter);",
        'fetch("http://example.com/a")',
    ],
)
def test_external_detector_actually_detects(sample: str) -> None:
    """Контроль живёт рядом с проверкой: зелёный тест ниже иначе ничего не доказывает."""
    assert EXTERNAL.findall(sample)


@pytest.mark.parametrize(
    "sample",
    [
        '<link rel="stylesheet" href="/static/app.css">',
        "fetch(`/api/v1/runs/${id}/artifacts/plan.json`)",
        "const half = 6 // 2;",
    ],
)
def test_external_detector_ignores_local_paths(sample: str) -> None:
    assert not EXTERNAL.findall(sample)


@pytest.mark.parametrize(
    "path",
    [
        "templates/base.html",
        "templates/index.html",
        "templates/run.html",
        "templates/_run_status.html",
        "static/app.css",
        "static/plan.js",
    ],
)
def test_no_external_resources(path: str) -> None:
    """Ни одной ссылки наружу: ни CDN, ни шрифтов, ни аналитики."""
    found = EXTERNAL.findall((WEB_DIR / path).read_text(encoding="utf-8"))

    assert not found, f"{path}: внешние ссылки {found}"


def test_form_starts_a_run_and_redirects(client: TestClient, work: Path) -> None:
    path = work / "street.dxf"
    _street(path)

    response = client.post(
        "/web/runs",
        files={"file": ("street.dxf", path.read_bytes(), "image/vnd.dxf")},
        data={"profile": "strict", "spacing_m": "7", "shrub_groups": "on"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert "/runs/" in location

    page = client.get(location)
    assert page.status_code == 200
    assert "План готов" in page.text


def test_demo_button_runs_the_built_in_site(client: TestClient) -> None:
    """Кнопка демонстрации обязана работать без единого файла на диске.

    На стенде жюри датасета нет, а показывать сервис надо с первого клика: чертёж строит
    сам сервис, поэтому проверяем весь путь, а не только код ответа.
    """
    created = client.post("/web/demo", follow_redirects=False)

    assert created.status_code == 303
    page = client.get(created.headers["location"])
    assert page.status_code == 200
    assert "План готов" in page.text

    run_id = created.headers["location"].rsplit("/", 1)[-1]
    plan = client.get(f"/api/v1/runs/{run_id}/artifacts/plan.json").json()
    assert plan["placements"], "демонстрационный участок не дал ни одной посадки"
    assert plan["summary"]["integrity_ok"] is True

    basemap = client.get(f"/api/v1/runs/{run_id}/artifacts/basemap.geojson").json()
    classes = {f["properties"]["class"] for f in basemap["features"]}
    # Ради легенды на карте: образец обязан показывать разные типы сетей, а не одну трубу.
    assert {"utility.water", "utility.sewer", "utility.gas", "utility.heat"} <= classes


def test_finished_run_page_shows_the_map_and_artifacts(client: TestClient, work: Path) -> None:
    path = work / "street2.dxf"
    _street(path)
    created = client.post(
        "/web/runs",
        files={"file": ("street2.dxf", path.read_bytes(), "image/vnd.dxf")},
        data={"profile": "strict"},
        follow_redirects=False,
    )
    page = client.get(created.headers["location"])

    assert "plan-canvas" in page.text
    assert "basemap.geojson" in page.text
    assert "rules.json" in page.text


def test_map_payload_is_available_and_joins_rules(client: TestClient, work: Path) -> None:
    """Карта соединяет rule_id посадки с пунктом акта: без этого интерпретируемости нет."""
    path = work / "street3.dxf"
    _street(path)
    created = client.post(
        "/web/runs",
        files={"file": ("street3.dxf", path.read_bytes(), "image/vnd.dxf")},
        data={"profile": "strict"},
        follow_redirects=False,
    )
    run_id = created.headers["location"].rsplit("/", 1)[-1]

    plan = client.get(f"/api/v1/runs/{run_id}/artifacts/plan.json").json()
    rules = client.get(f"/api/v1/runs/{run_id}/artifacts/rules.json").json()["rules"]
    basemap = client.get(f"/api/v1/runs/{run_id}/artifacts/basemap.geojson").json()

    assert basemap["counts"]["features_out"] > 0
    counts = basemap["counts"]
    assert counts["features_out"] + sum(counts["dropped"].values()) == counts["features_in"]

    checked = [c for p in plan["placements"] for c in p["checks"]]
    assert checked, "у посадок нет проверенных правил, объяснять будет нечем"
    for check in checked:
        rule = rules[check["rule_id"]]
        assert rule["act_id"]
        assert rule["clause"]
