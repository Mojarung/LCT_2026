"""Пересборка после правки ждёт общей очереди прогонов и говорит об этом статусом.

20.10.2026: пока пересборка ждала свободного места, прогон оставался «готов», и интерфейс
не знал об очереди: клиент сдавался на 10-й минуте, а сервер заканчивал через 10,5 (27 с
пересборки, остальное - очередь).
"""

from __future__ import annotations

import threading
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING

from green.application.results import RunState
from green.application.runs import RunService
from green.infrastructure.storage.runs import FileSystemRunStore

if TYPE_CHECKING:
    from pathlib import Path

WAIT_S = 10.0


class _Report:
    def summary(self) -> dict[str, object]:
        return {"placements": 1}


class _UseCase:
    """Пересборка прогона `busy` держит единственное место, пока тест её не отпустит."""

    def __init__(self, busy: str) -> None:
        self.busy = busy
        self.started = threading.Event()
        self.release = threading.Event()

    def rebuild(self, context: SimpleNamespace, plan: object, run_dir: Path) -> _Report:
        del plan, run_dir
        if context.run_id == self.busy:
            self.started.set()
            self.release.wait(WAIT_S)
        return _Report()


class _Contexts:
    def get(self, run_id: str) -> SimpleNamespace:
        return SimpleNamespace(run_id=run_id, plan=None, report=None)

    def put(self, context: SimpleNamespace) -> None:
        del context


class _Artifacts:
    def save(self, run_dir: Path, report: _Report) -> dict[str, Path]:
        del report
        return {"result.dxf": run_dir / "result.dxf"}


def _service(store: FileSystemRunStore, use_case: _UseCase) -> RunService:
    return RunService(
        store=store,
        use_case=use_case,  # ty: ignore[invalid-argument-type]
        profiles=SimpleNamespace(),  # ty: ignore[invalid-argument-type]
        artifacts=_Artifacts(),  # ty: ignore[invalid-argument-type]
        max_parallel=1,
        contexts=_Contexts(),  # ty: ignore[invalid-argument-type]
    )


def _finished(store: FileSystemRunStore, name: str) -> str:
    record = store.create(name, "strict", {})
    store.save(
        replace(
            record,
            state=RunState.SUCCEEDED,
            artifacts=("plan.json", "result.dxf"),
            summary={"placements": 2},
        )
    )
    return record.run_id


def test_rebuild_waiting_for_a_slot_is_queued_and_keeps_the_result(tmp_path: Path) -> None:
    store = FileSystemRunStore(tmp_path)
    busy = _finished(store, "busy.dxf")
    edited = _finished(store, "edited.dxf")
    use_case = _UseCase(busy)
    service = _service(store, use_case)
    first = threading.Thread(target=service.rebuild, args=(busy,))
    first.start()
    assert use_case.started.wait(WAIT_S), "первая пересборка не заняла место"
    before = store.get(edited)

    assert service.queue_rebuild(edited).state is RunState.QUEUED
    waiting = threading.Thread(target=service.rebuild, args=(edited,))
    waiting.start()
    waiting.join(0.3)
    assert waiting.is_alive(), "место занято: пересборка обязана ждать очереди"
    queued = store.get(edited)
    assert queued.state is RunState.QUEUED, "ожидание места видно в статусе прогона"
    assert queued.artifacts == before.artifacts, "прежний результат остаётся доступен"
    assert queued.summary == before.summary

    use_case.release.set()
    first.join(WAIT_S)
    waiting.join(WAIT_S)
    done = store.get(edited)
    assert done.state is RunState.SUCCEEDED
    assert done.updated_at > queued.updated_at > before.updated_at


def test_rebuild_keeps_the_source_review_artifacts(tmp_path: Path) -> None:
    """Пересборка пишет файлы плана; разбор исходника для уточнения объектов остаётся."""
    store = FileSystemRunStore(tmp_path)
    record = store.create("edited.dxf", "strict", {})
    review = ("review-classification.json", "review-input.dxf", "semantic-review.geojson")
    store.save(replace(record, state=RunState.SUCCEEDED, artifacts=("result.dxf", *review)))
    service = _service(store, _UseCase(""))
    service.queue_rebuild(record.run_id)
    done = service.rebuild(record.run_id)
    assert done.state is RunState.SUCCEEDED
    assert set(review) <= set(done.artifacts)
    assert store.get(record.run_id).artifacts == done.artifacts


def test_queue_rebuild_does_not_override_a_live_run(tmp_path: Path) -> None:
    store = FileSystemRunStore(tmp_path)
    record = store.create("live.dxf", "strict", {})
    store.save(replace(record, state=RunState.RUNNING))
    service = _service(store, _UseCase(""))
    assert service.queue_rebuild(record.run_id).state is RunState.RUNNING
    assert store.get(record.run_id).state is RunState.RUNNING
    store.save(replace(store.get(record.run_id), state=RunState.SUCCEEDED))
