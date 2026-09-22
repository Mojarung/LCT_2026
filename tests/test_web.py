"""Веб-интерфейс: страницы отвечают, форма запускает прогон, наружу ничего не тянется.

Проверка «ноль внешних запросов» тут механическая и намеренно грубая: целевая среда -
Linux-стенд без интернета, и одна ссылка на CDN, оставленная по невнимательности, превращает
страницу в пустой экран ровно в момент показа жюри.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from test_pipeline_synthetic import ROOT, _street

from green.application.results import RunState
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.interfaces.api.app import create_app
from green.interfaces.web.pages import plural

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
    # Каталог улиц намеренно пуст: этот модуль проверяет стенд без датасета, где остаётся
    # встроенный фрагмент. Каталог по умолчанию указывает в репозиторий, и тогда тесты
    # зависели бы от того, собирал ли разработчик датасет у себя.
    settings = Settings(
        config_dir=ROOT / "config", runs_dir=work / "runs", streets_dir=work / "без-каталога"
    )
    with TestClient(create_app(build_container(settings))) as test_client:
        yield test_client


def test_index_renders_with_profiles(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "strict" in response.text
    assert "Новый прогон" in response.text
    assert "Встроенный участок улицы Берзарина" in response.text, "без датасета показывать нечего"


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
    assert "plan-canvas" in page.text, "на готовом прогоне нет плана"


def test_demo_button_runs_the_built_in_site(client: TestClient) -> None:
    """Кнопка демонстрации обязана работать без единого файла на диске.

    На стенде жюри датасета нет, а показывать сервис надо с первого клика: чертёж строит
    сам сервис, поэтому проверяем весь путь, а не только код ответа.
    """
    created = client.post("/web/demo", follow_redirects=False)

    assert created.status_code == 303
    page = client.get(created.headers["location"])
    assert page.status_code == 200
    assert "plan-canvas" in page.text, "на готовом прогоне нет плана"

    run_id = created.headers["location"].rsplit("/", 1)[-1]
    plan = client.get(f"/api/v1/runs/{run_id}/artifacts/plan.json").json()
    assert plan["placements"], "демонстрационный участок не дал ни одной посадки"
    assert plan["summary"]["integrity_ok"] is True

    basemap = client.get(f"/api/v1/runs/{run_id}/artifacts/basemap.geojson").json()
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


def test_run_page_shows_plan_quality_and_each_planting_has_a_value(
    client: TestClient, work: Path
) -> None:
    """Нормы отвечают «можно ли», индекс - «насколько хорош план»: оба видны на странице."""
    path = work / "street-quality.dxf"
    _street(path)
    created = client.post(
        "/web/runs",
        files={"file": ("street-quality.dxf", path.read_bytes(), "image/vnd.dxf")},
        data={"profile": "strict"},
        follow_redirects=False,
    )
    run_id = created.headers["location"].rsplit("/", 1)[-1]
    page = client.get(created.headers["location"]).text
    quality = client.get(f"/api/v1/runs/{run_id}/artifacts/quality.json").json()
    plan = client.get(f"/api/v1/runs/{run_id}/artifacts/plan.json").json()

    assert "индекс качества" in page
    assert {t["key"] for t in quality["terms"]} >= {"density", "diversity", "canopy", "dust"}
    assert all(t["basis"] for t in quality["terms"])
    assert plan["placements"]
    assert all(p["value"] is not None for p in plan["placements"])
    assert all("Ценность:" in p["explanation"] for p in plan["placements"])


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


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, "норма"),
        (2, "нормы"),
        (4, "нормы"),
        (5, "норм"),
        (11, "норм"),
        (12, "норм"),
        (14, "норм"),
        (21, "норма"),
        (22, "нормы"),
        (25, "норм"),
        (111, "норм"),
        (0, "норм"),
    ],
)
def test_plural_handles_the_teens(count: int, expected: str) -> None:
    """Одиннадцать-четырнадцать - исключение из правила, и именно на них ошибаются."""
    assert plural(count, "норма", "нормы", "норм") == expected


def test_result_files_come_first_and_service_ones_are_folded(client: TestClient) -> None:
    """Файл, ради которого запускали прогон, не должен лежать девятым по алфавиту.

    На странице `result.dxf` и `interpretations.csv` названы тем, чем они являются, а
    остальные одиннадцать уходят под раскрытие. Проверяем разделение, а не вёрстку.
    """
    created = client.post("/web/demo", follow_redirects=False)
    page = client.get(created.headers["location"]).text

    headline = page.index("result.dxf")
    service = page.index("Файлы прогона")
    assert headline < service, "result.dxf оказался ниже служебных файлов"
    assert "план посадок на слоях GREEN_*" in page
    # Служебные перечислены, но за раскрытием: в плоском списке они весили столько же.
    assert '<details class="fold">' in page
    assert page.index("basemap.geojson") > service


def test_every_token_the_map_reads_is_defined_in_css() -> None:
    """Карта берёт цвета из CSS-переменных, и опечатку в имени переменной ничто не ловит.

    `css()` подставляет запасной серый, поэтому несуществующий токен даёт не отказ, а тихую
    деградацию: отметка выбранной посадки рисовалась служебным серым и на общем виде
    пропадала совсем. DOM при этом валиден, консоль чиста, скриншот выглядит нормально.
    """
    script = (WEB_DIR / "static" / "plan.js").read_text(encoding="utf-8")
    styles = (WEB_DIR / "static" / "app.css").read_text(encoding="utf-8")

    wanted = set(re.findall(r"""['"](--[a-z0-9-]+)['"]""", script))
    assert wanted, "в plan.js не нашлось ни одного токена - сломался сам разбор"

    declared = set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:", styles, re.MULTILINE))
    missing = sorted(wanted - declared)

    assert not missing, f"plan.js читает необъявленные токены: {missing}"


def test_the_token_check_would_notice_a_typo() -> None:
    """Отрицательный контроль: без него проверка выше зелёная и при сломанном разборе."""
    declared = set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:", "  --bone: #fff;\n", re.MULTILINE))

    assert declared == {"--bone"}
    assert "--accent-typo" not in declared


def test_plan_changing_warning_is_not_hidden_in_the_fold(client: TestClient) -> None:
    """Предупреждение, меняющее смысл плана, стоит рядом с числом посадок.

    У улицы без границы работ сервис засаживает весь чертёж (Нижние Поля: 18 780 посадок),
    и число читается как результат, пока не сказано обратного. Такие предупреждения не
    должны лежать в свёрнутом списке вместе с «аудит исправил 503 записи».
    """
    container = client.app.state.container  # type: ignore[attr-defined]
    record = container.store.create("street.dxf", "strict", {})
    finished = replace(
        container.store.get(record.run_id),
        state=RunState.SUCCEEDED,
        summary={
            "placements": 18780,
            "rejections": 2000,
            "integrity_ok": True,
            "warnings": [
                "Граница работ не найдена: размещение по всему чертежу.",
                "street.dxf: аудит исправил записей: 503, ошибок: 0",
            ],
        },
    )
    container.store.save(finished)

    page = client.get(f"/runs/{record.run_id}").text

    assert '<div class="notice">' in page
    assert page.index("Граница работ не найдена") < page.index("Предупреждения")
    assert "аудит исправил" not in page.split('<div class="notice">')[1].split("</div>")[0]
