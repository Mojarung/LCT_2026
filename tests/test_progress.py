"""Ход прогона: этапы, оценка доли и остатка, подоснова раньше плана.

Оценка - не точное число, а обещание человеку у экрана, поэтому проверяются её свойства:
доля не убывает, затянувшийся этап удлиняет остаток, а не останавливает полосу, у DXF нет
шага «конвертация», а подоснова уходит в артефакты до того, как посадки расставлены.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from test_pipeline_synthetic import ROOT, _street

from green.application.progress import STAGES, estimate, plan_stages
from green.application.results import RunProgress, RunRecord, RunState
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.interfaces.api.app import create_app

if TYPE_CHECKING:
    from pathlib import Path

    from green.application.basemap import Basemap

T0 = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
MB = 1024 * 1024


def _progress(stages: tuple[str, ...], *, size_mb: float = 40.0) -> RunProgress:
    return RunProgress(
        stages=stages, started_at=T0, stage_started_at=T0, source_bytes=int(size_mb * MB)
    )


def test_dxf_run_has_no_conversion_and_a_kit_gets_a_merge() -> None:
    plain = plan_stages(convert=False, merge=False)
    kit = plan_stages(convert=True, merge=True)

    assert "convert" not in plain
    assert "merge" not in plain
    assert kit[:2] == ("convert", "merge")
    assert plain == tuple(s for s in kit if s not in {"convert", "merge"})
    assert set(kit) == {s.id for s in STAGES}


def test_foreign_and_repeated_stages_do_not_change_progress() -> None:
    progress = _progress(plan_stages(convert=False, merge=False))

    assert progress.begin("convert", T0) is progress
    started = progress.begin("read", T0 + timedelta(seconds=1))
    assert started.begin("read", T0 + timedelta(seconds=5)) is started


def test_finished_stage_gets_its_duration() -> None:
    progress = _progress(plan_stages(convert=False, merge=False))
    progress = progress.begin("load_config", T0)
    progress = progress.begin("read", T0 + timedelta(seconds=0.5))

    assert progress.stage == "read"
    assert [(t.stage, t.ms) for t in progress.done] == [("load_config", 500.0)]


def test_fraction_never_decreases_and_stays_below_one() -> None:
    stages = plan_stages(convert=False, merge=False)
    progress = _progress(stages)
    now = T0
    seen: list[float] = []
    for stage in stages:
        progress = progress.begin(stage, now)
        # Внутри этапа опрашиваем каждые две секунды по десять секунд.
        seen.extend(
            estimate(progress, now + timedelta(seconds=2 * tick)).fraction for tick in range(6)
        )
        now += timedelta(seconds=10)

    assert seen == sorted(seen)
    assert seen[-1] < 1.0
    assert seen[0] == 0.0


def test_overrunning_stage_extends_the_estimate_instead_of_freezing_it() -> None:
    progress = _progress(plan_stages(convert=False, merge=False)).begin("read", T0)
    early = estimate(progress, T0 + timedelta(seconds=5))
    late = estimate(progress, T0 + timedelta(minutes=5))

    assert late.fraction >= early.fraction
    assert early.eta_s is not None
    assert late.eta_s is not None
    # Через пять минут чтения остаток не нулевой: этап ещё идёт, полоса стоит у его края.
    assert late.eta_s > 0
    assert late.stage == "read"
    assert late.title == "Чтение чертежа"


def test_measured_stages_replace_the_prior() -> None:
    """Быстрый чертёж: после чтения за секунду оценка всего прогона сжимается."""
    stages = plan_stages(convert=False, merge=False)
    guess = estimate(_progress(stages, size_mb=40).begin("read", T0), T0)
    progress = _progress(stages, size_mb=40)
    progress = progress.begin("load_config", T0)
    progress = progress.begin("read", T0 + timedelta(seconds=0.1))
    progress = progress.begin("classify", T0 + timedelta(seconds=1.1))
    measured = estimate(progress, T0 + timedelta(seconds=1.2))

    assert guess.eta_s is not None
    assert measured.eta_s is not None
    assert measured.eta_s < guess.eta_s / 3


def test_steps_carry_state_and_durations() -> None:
    progress = _progress(plan_stages(convert=False, merge=False))
    progress = progress.begin("load_config", T0).begin("read", T0 + timedelta(seconds=1))
    view = estimate(progress, T0 + timedelta(seconds=3))
    states = {step.id: step.state for step in view.steps}

    assert states["load_config"] == "done"
    assert states["read"] == "active"
    assert states["verify"] == "pending"
    assert next(s.ms for s in view.steps if s.id == "load_config") == 1000.0
    assert view.elapsed_s == 3.0


class _Sink:
    def __init__(self) -> None:
        self.stages: list[str] = []
        self.basemap_after: list[str] | None = None

    def stage(self, name: str) -> None:
        self.stages.append(name)

    def basemap(self, basemap: Basemap) -> None:
        assert basemap.features_out > 0
        self.basemap_after = list(self.stages)


def test_basemap_leaves_the_use_case_before_placement(tmp_path: Path) -> None:
    source = tmp_path / "street.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load("strict", {"max_rejections": 50})
    sink = _Sink()

    container.use_case.execute(
        PlanRequest("test", source, tmp_path / "out", "strict", params), sink
    )

    assert sink.basemap_after is not None
    assert "place" not in sink.basemap_after
    assert sink.basemap_after[-1] == "basemap"
    assert sink.stages[:1] == ["convert"]
    assert sink.stages.index("read") < sink.stages.index("basemap") < sink.stages.index("place")


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    work = tmp_path_factory.mktemp("progress")
    settings = Settings(config_dir=ROOT / "config", runs_dir=work / "runs")
    return TestClient(create_app(build_container(settings)))


def test_api_shows_progress_of_a_running_run(client: TestClient) -> None:
    """Запись идущего прогона отдаёт этап, долю, оценку остатка и список этапов."""
    container = client.app.state.container  # type: ignore[attr-defined]
    record = container.store.create("street.dxf", "strict", {})
    now = datetime.now(UTC)
    progress = RunProgress(
        stages=plan_stages(convert=False, merge=False),
        started_at=now - timedelta(seconds=20),
        stage_started_at=now - timedelta(seconds=20),
        source_bytes=40 * MB,
    )
    progress = progress.begin("load_config", now - timedelta(seconds=20))
    progress = progress.begin("read", now - timedelta(seconds=19))
    container.store.save(
        RunRecord(
            run_id=record.run_id,
            state=RunState.RUNNING,
            source_name=record.source_name,
            profile=record.profile,
            overrides={},
            created_at=record.created_at,
            updated_at=now,
            progress=progress,
        )
    )

    body = client.get(f"/api/v1/runs/{record.run_id}").json()
    assert body["state"] == "running"
    assert body["progress"]["stage"] == "read"
    assert body["progress"]["title"] == "Чтение чертежа"
    assert 0 < body["progress"]["fraction"] < 1
    assert body["progress"]["eta_s"] > 0
    assert [s["state"] for s in body["progress"]["steps"]][:3] == ["done", "active", "pending"]


def test_finished_run_has_no_progress_but_keeps_the_basemap(client: TestClient) -> None:
    created = client.post("/api/v1/runs/demo")
    run_id = created.json()["id"]
    body = client.get(f"/api/v1/runs/{run_id}").json()

    assert body["state"] == "succeeded"
    assert body["progress"] is None
    assert "basemap.geojson" in {a["name"] for a in body["artifacts"]}


def test_demo_run_through_the_api(client: TestClient) -> None:
    """Встроенный фрагмент запускается из JSON API и доходит до плана."""
    created = client.post("/api/v1/runs/demo")

    assert created.status_code == 202, created.text
    run_id = created.json()["id"]
    assert created.headers["location"].endswith(run_id)
    body = client.get(f"/api/v1/runs/{run_id}").json()
    assert body["state"] == "succeeded", body.get("error")
    assert body["summary"]["placements"] > 0
