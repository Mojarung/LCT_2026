"""Раздача веб-интерфейса: собранный React-бандл, маршруты клиента и Swagger без интернета.

Интерфейс - статический SPA из frontend/ (сборка `npm run build`). Сервер отдаёт файлы
бандла, на маршрут клиента - index.html, а к API и /docs не прикасается. Целевой стенд -
Linux без интернета, поэтому и Swagger берёт свою статику из бандла, а не с CDN.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from test_pipeline_synthetic import ROOT

from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.interfaces.api.app import create_app

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

INDEX = (
    '<!doctype html><html><head><script type="module" src="/assets/app.js"></script>'
    '</head><body><div id="root"></div></body></html>'
)
EXTERNAL = re.compile(r"""["'(]\s*(?:https?:)?//[^"')\s]+""")
RUN_ID = "01a0c94f-be4d-70b0-8ba3-f972876e2b4c"


def _bundle(root: Path) -> Path:
    web = root / "dist"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text(INDEX, encoding="utf-8")
    (web / "assets" / "app.js").write_text("console.log('green')", encoding="utf-8")
    (web / "assets" / "app.css").write_text("body{}", encoding="utf-8")
    (web / "mark.svg").write_text("<svg/>", encoding="utf-8")
    vendor = web / "vendor" / "swagger"
    vendor.mkdir(parents=True)
    (vendor / "swagger-ui-bundle.js").write_text("/* swagger */", encoding="utf-8")
    (vendor / "swagger-ui.css").write_text("/* swagger */", encoding="utf-8")
    return web


def _client(work: Path, web_dir: Path) -> TestClient:
    settings = Settings(
        config_dir=ROOT / "config",
        runs_dir=work / "runs",
        streets_dir=work / "без-каталога",
        web_dir=web_dir,
    )
    return TestClient(create_app(build_container(settings)))


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with _client(tmp_path, _bundle(tmp_path)) as test_client:
        yield test_client


@pytest.mark.parametrize("path", ["/", f"/runs/{RUN_ID}"])
def test_client_routes_get_the_app(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<div id="root">' in response.text


def test_bundle_files_are_served_and_cached_for_good(client: TestClient) -> None:
    """Имена файлов в assets/ несут хеш содержимого: их можно кэшировать навсегда."""
    response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert response.text == "console.log('green')"
    assert "javascript" in response.headers["content-type"]
    assert "immutable" in response.headers["cache-control"]


@pytest.mark.parametrize(
    ("path", "media"),
    [
        ("/assets/app.js", "text/javascript"),
        ("/assets/app.css", "text/css"),
        ("/mark.svg", "image/svg+xml"),
        ("/", "text/html"),
    ],
)
def test_files_carry_their_type_on_any_os(client: TestClient, path: str, media: str) -> None:
    """Тип не угадывается по реестру Windows: модульный скрипт с text/plain не исполнится."""
    assert client.get(path).headers["content-type"].startswith(media)


def test_the_page_itself_is_revalidated(client: TestClient) -> None:
    """index.html не кэшируется: иначе после обновления сервиса браузер держит старый бандл."""
    assert client.get("/").headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", ["/assets/missing.js", "/favicon.ico", "/vendor/swagger/x.js"])
def test_a_missing_file_is_404_not_the_page(client: TestClient, path: str) -> None:
    """Битая ссылка на скрипт не превращается в HTML: страница сломалась бы молча."""
    response = client.get(path)

    assert response.status_code == 404
    assert '<div id="root">' not in response.text


def test_nothing_outside_the_bundle_is_served(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("секрет", encoding="utf-8")

    response = client.get("/%2e%2e/secret.txt")

    assert response.status_code == 404
    assert "секрет" not in response.text


def test_the_api_is_not_captured(client: TestClient) -> None:
    assert client.get("/api/v1/health").status_code == 200
    unknown = client.get("/api/v1/no-such-thing")
    assert unknown.status_code == 404
    assert unknown.headers["content-type"].startswith("application/problem+json")


def test_without_a_bundle_the_page_says_how_to_build_it(tmp_path: Path) -> None:
    with _client(tmp_path, tmp_path / "не-собрано") as client:
        page = client.get("/")

        assert page.status_code == 503
        assert "npm run build" in page.text
        assert client.get("/api/v1/health").status_code == 200


def test_docs_take_swagger_from_the_bundle(client: TestClient) -> None:
    page = client.get("/docs").text

    assert "/vendor/swagger/swagger-ui-bundle.js" in page
    assert "/vendor/swagger/swagger-ui.css" in page
    assert "/api/v1/openapi.json" in page
    assert not EXTERNAL.findall(page), "Swagger тянет что-то из интернета"


def test_docs_still_open_without_a_bundle(tmp_path: Path) -> None:
    """Без сборки фронта Swagger остаётся рабочим (со статикой по умолчанию)."""
    with _client(tmp_path, tmp_path / "не-собрано") as client:
        page = client.get("/docs")

        assert page.status_code == 200
        assert "swagger-ui-bundle.js" in page.text


def test_redoc_is_gone(client: TestClient) -> None:
    """ReDoc грузит скрипт с CDN, а ТЗ требует только Swagger."""
    assert "redoc.standalone.js" not in client.get("/redoc").text


def test_external_detector_actually_detects() -> None:
    """Отрицательный контроль: без него проверки выше зелёные и при сломанном выражении."""
    assert EXTERNAL.findall('<script src="https://cdn.jsdelivr.net/x.js"></script>')
    assert EXTERNAL.findall("url(//fonts.example.com/a.woff2)")
    assert not EXTERNAL.findall('<script src="/vendor/swagger/swagger-ui-bundle.js"></script>')


def test_the_real_bundle_loads_nothing_from_the_internet() -> None:
    """Собранный интерфейс: страница и стили ссылаются только на свои файлы."""
    dist = ROOT / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        pytest.skip("фронт не собран: npm run build в frontend/")
    sources = [dist / "index.html", *sorted((dist / "assets").glob("*.css"))]

    found = {path.name: EXTERNAL.findall(path.read_text(encoding="utf-8")) for path in sources}

    assert not {name: hits for name, hits in found.items() if hits}


def test_bundle_text_is_gzipped_when_the_browser_accepts_it(tmp_path: Path) -> None:
    """FileResponse под Granian уходит мимо GZipMiddleware: сервер жмёт текст бандла сам."""
    web = _bundle(tmp_path)
    script = "const green = 1;\n" * 400
    (web / "assets" / "big.js").write_bytes(script.encode())
    with _client(tmp_path, web) as client:
        packed = client.get("/assets/big.js", headers={"Accept-Encoding": "gzip"})
        plain = client.get("/assets/big.js", headers={"Accept-Encoding": "identity"})

    assert packed.headers["content-encoding"] == "gzip"
    assert packed.text == script  # httpx распаковывает сам
    assert packed.headers["vary"] == "Accept-Encoding"
    assert "content-encoding" not in plain.headers
    assert plain.text == script
