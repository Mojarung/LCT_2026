"""HTTP API: полный цикл прогона, ошибки в формате RFC 9457, OpenAPI.

Клиент тестов выполняет фоновую задачу до возврата ответа, поэтому после POST прогон уже завершён.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import ezdxf
import orjson
import pytest
from fastapi.testclient import TestClient
from test_multi_dxf import _genplan, _utilities
from test_pipeline_synthetic import ROOT, _street

from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.interfaces.api.app import API_PREFIX, create_app

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from httpx2 import Response

PROBLEM_JSON = "application/problem+json"
UPLOAD_LIMIT_MB = 1
OVERRIDES = '{"max_rejections": 50}'


@pytest.fixture(scope="module")
def work(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("api")


@pytest.fixture(scope="module")
def client(work: Path) -> Iterator[TestClient]:
    settings = Settings(
        config_dir=ROOT / "config", runs_dir=work / "runs", max_upload_mb=UPLOAD_LIMIT_MB
    )
    with TestClient(create_app(build_container(settings))) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def street(work: Path) -> bytes:
    path = work / "street.dxf"
    _street(path)
    return path.read_bytes()


@pytest.fixture(scope="module")
def finished(client: TestClient, street: bytes) -> dict[str, object]:
    response = client.post(
        f"{API_PREFIX}/runs",
        files={"file": ("street.dxf", street, "image/vnd.dxf")},
        data={"profile": "strict", "overrides": OVERRIDES},
    )
    assert response.status_code == 202, response.text
    created = response.json()
    assert response.headers["Location"] == f"{API_PREFIX}/runs/{created['id']}"
    return client.get(response.headers["Location"]).json()


def _assert_problem(response: Response, status: int) -> dict[str, object]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    body = response.json()
    assert body["status"] == status
    assert body["title"]
    return body


def test_health_and_meta_describe_the_service(client: TestClient) -> None:
    assert client.get(f"{API_PREFIX}/health").json()["status"] == "ok"
    meta = client.get(f"{API_PREFIX}/meta").json()
    assert {"strict", "no_utilities", "barriers"} <= set(meta["profiles"])
    assert meta["default_profile"] == "strict"
    assert meta["rules"]["total"] >= meta["rules"]["verified"] > 0
    assert "GREEN_TREES" in meta["result_layers"]
    assert any(s["code"] == "tilia_cordata" for s in meta["species"])


def test_openapi_documents_every_route(client: TestClient) -> None:
    schema = client.get(f"{API_PREFIX}/openapi.json").json()
    paths = schema["paths"]
    for route in ("/health", "/meta", "/runs", "/runs/{run_id}", "/runs/{run_id}/artifacts/{name}"):
        assert f"{API_PREFIX}{route}" in paths
    form = paths[f"{API_PREFIX}/runs"]["post"]["requestBody"]["content"]["multipart/form-data"]
    assert "$ref" in form["schema"]
    assert "422" in paths[f"{API_PREFIX}/runs"]["post"]["responses"]
    assert client.get("/docs").status_code == 200


def test_committed_openapi_file_matches_the_code(client: TestClient) -> None:
    """docs/openapi.json сдаётся вместе с документацией: он не должен отставать от кода."""
    committed = orjson.loads((ROOT / "docs" / "openapi.json").read_bytes())
    assert committed == client.get(f"{API_PREFIX}/openapi.json").json(), (
        "схема устарела: uv run green openapi --out docs/openapi.json"
    )


def test_run_succeeds_and_lists_artifacts(finished: dict[str, object]) -> None:
    assert finished["state"] == "succeeded", finished
    assert finished["error"] is None
    assert finished["overrides"] == {"max_rejections": 50}
    summary = finished["summary"]
    assert summary["placements"] >= 10  # type: ignore[index]
    assert summary["integrity_ok"] is True  # type: ignore[index]
    names = {a["name"] for a in finished["artifacts"]}  # type: ignore[union-attr]
    assert {
        "result.dxf",
        "plan.json",
        "interpretations.json",
        "interpretations.csv",
        "planting_schedule.csv",
        "verify.json",
        "run_manifest.json",
    } <= names


def test_artifacts_download_and_match_the_summary(
    client: TestClient, finished: dict[str, object], work: Path
) -> None:
    urls = {a["name"]: a["url"] for a in finished["artifacts"]}  # type: ignore[union-attr]
    drawing = client.get(urls["result.dxf"])
    assert drawing.status_code == 200
    assert drawing.headers["content-type"].startswith("image/vnd.dxf")
    target = work / "downloaded.dxf"
    target.write_bytes(drawing.content)
    doc = ezdxf.readfile(target)
    trees = doc.modelspace().query("INSERT[layer=='GREEN_TREES']")
    plan = orjson.loads(client.get(urls["plan.json"]).content)
    assert len(plan["placements"]) == finished["summary"]["placements"]  # type: ignore[index]
    assert len(trees) == sum(1 for p in plan["placements"] if p["verdict"] == "allowed")
    schedule = client.get(urls["planting_schedule.csv"])
    assert schedule.headers["content-type"].startswith("text/csv")
    assert "Всего деревьев" in schedule.content.decode("utf-8-sig")


def test_finished_run_is_listed(client: TestClient, finished: dict[str, object]) -> None:
    listed = client.get(f"{API_PREFIX}/runs", params={"limit": 5}).json()["items"]
    assert finished["id"] in {item["id"] for item in listed}


def test_kit_of_two_drawings_is_merged(client: TestClient, work: Path) -> None:
    genplan, utilities = work / "genplan.dxf", work / "utilities.dxf"
    _genplan(genplan)
    _utilities(utilities)
    response = client.post(
        f"{API_PREFIX}/runs",
        files=[
            ("file", ("genplan.dxf", genplan.read_bytes(), "image/vnd.dxf")),
            ("extra", ("utilities.dxf", utilities.read_bytes(), "image/vnd.dxf")),
        ],
        data={"overrides": OVERRIDES},
    )
    assert response.status_code == 202, response.text
    run = client.get(response.headers["Location"]).json()
    assert run["state"] == "succeeded", run
    assert any("Склейка комплекта" in w for w in run["summary"]["warnings"])


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        ({"overrides": "{not json"}, "overrides"),
        ({"overrides": "[1, 2]"}, "JSON-объект"),
        ({"overrides": '{"spacing_m": -1}'}, "spacing_m"),
        ({"overrides": '{"no_such_parameter": 1}'}, "no_such_parameter"),
        ({"profile": "no_such_profile"}, "no_such_profile"),
    ],
)
def test_bad_parameters_are_refused_before_the_run(
    client: TestClient, street: bytes, data: dict[str, str], fragment: str
) -> None:
    before = len(client.get(f"{API_PREFIX}/runs", params={"limit": 200}).json()["items"])
    response = client.post(
        f"{API_PREFIX}/runs", files={"file": ("street.dxf", street, "image/vnd.dxf")}, data=data
    )
    body = _assert_problem(response, 422)
    assert fragment in str(body["detail"])
    after = len(client.get(f"{API_PREFIX}/runs", params={"limit": 200}).json()["items"])
    assert after == before  # прогон не создан


def test_framework_errors_use_the_same_format(client: TestClient) -> None:
    """Нет маршрута и не тот метод - ответы фреймворка, но формат у них общий."""
    _assert_problem(client.get(f"{API_PREFIX}/no-such-route"), 404)
    refused = client.delete(f"{API_PREFIX}/runs")
    _assert_problem(refused, 405)
    assert refused.headers["allow"]  # заголовок фреймворка доезжает до клиента


def test_request_without_a_file_is_a_validation_problem(client: TestClient) -> None:
    body = _assert_problem(client.post(f"{API_PREFIX}/runs", data={"profile": "strict"}), 422)
    assert body["errors"]


def test_extra_file_that_is_not_a_drawing_is_refused(client: TestClient, street: bytes) -> None:
    response = client.post(
        f"{API_PREFIX}/runs",
        files=[
            ("file", ("street.dxf", street, "image/vnd.dxf")),
            ("extra", ("notes.txt", b"hello", "text/plain")),
        ],
    )
    body = _assert_problem(response, 422)
    assert ".txt" in str(body["detail"])


def test_upload_over_the_limit_is_refused_and_recorded(client: TestClient) -> None:
    payload = io.BytesIO(b"0" * (UPLOAD_LIMIT_MB * 1024 * 1024 + 1))
    response = client.post(
        f"{API_PREFIX}/runs", files={"file": ("big.dxf", payload, "image/vnd.dxf")}
    )
    _assert_problem(response, 413)
    newest = client.get(f"{API_PREFIX}/runs", params={"limit": 1}).json()["items"][0]
    assert newest["source_name"] == "big.dxf"
    assert newest["state"] == "failed"


def test_broken_drawing_fails_the_run_with_a_reason(client: TestClient) -> None:
    response = client.post(
        f"{API_PREFIX}/runs", files={"file": ("broken.dxf", b"this is not a drawing", "text/plain")}
    )
    assert response.status_code == 202
    run = client.get(response.headers["Location"]).json()
    assert run["state"] == "failed"
    assert "broken.dxf" in run["error"] or "DXF" in run["error"]
    assert run["artifacts"] == []


@pytest.mark.parametrize(
    "path",
    [
        "/runs/00000000000000000000000000000000",
        "/runs/not-a-run-id",
        "/runs/{run}/artifacts/secret.txt",
        "/runs/{run}/artifacts/..%2F..%2Fpyproject.toml",
        "/runs/{run}/artifacts/%2E%2E%5Cmeta.json",
    ],
)
def test_unknown_runs_and_artifacts_are_not_found(
    client: TestClient, finished: dict[str, object], path: str
) -> None:
    response = client.get(f"{API_PREFIX}{path.format(run=finished['id'])}")
    _assert_problem(response, 404)
