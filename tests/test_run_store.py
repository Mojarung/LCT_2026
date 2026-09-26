"""Статус прогона на диске: брошенный прогон не висит «идёт» вечно, живой не объявляется упавшим."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import orjson

from green.application.results import RunState
from green.infrastructure.storage.runs import INTERRUPTED, STATUS, FileSystemRunStore

if TYPE_CHECKING:
    from pathlib import Path


def test_running_status_without_a_live_owner_becomes_interrupted(tmp_path: Path) -> None:
    """Так выглядит прогон после падения процесса: статус «идёт», блокировку никто не держит
    (Макеева, 26.09.2026: пять часов «осталось около 10 мин»)."""
    record = FileSystemRunStore(tmp_path).create("street.dxf", "strict", {})
    status = tmp_path / record.run_id / STATUS
    data = orjson.loads(status.read_bytes())
    status.write_bytes(orjson.dumps({**data, "state": "running"}))

    reread = FileSystemRunStore(tmp_path).get(record.run_id)

    assert reread.state is RunState.FAILED
    assert reread.error == INTERRUPTED
    assert reread.progress is None
    assert orjson.loads(status.read_bytes())["state"] == "failed", "исход не записан на диск"


def test_run_led_by_a_live_store_stays_running_for_another_reader(tmp_path: Path) -> None:
    owner = FileSystemRunStore(tmp_path)
    record = owner.create("street.dxf", "strict", {})
    owner.save(replace(record, state=RunState.RUNNING))

    assert FileSystemRunStore(tmp_path).get(record.run_id).state is RunState.RUNNING
    assert owner.get(record.run_id).state is RunState.RUNNING


def test_queued_run_is_not_taken_for_an_abandoned_one(tmp_path: Path) -> None:
    owner = FileSystemRunStore(tmp_path)
    record = owner.create("street.dxf", "strict", {})

    assert FileSystemRunStore(tmp_path).get(record.run_id).state is RunState.QUEUED


def test_finished_run_releases_its_lease_and_keeps_its_state(tmp_path: Path) -> None:
    owner = FileSystemRunStore(tmp_path)
    record = owner.create("street.dxf", "strict", {})
    owner.save(replace(record, state=RunState.RUNNING))
    owner.save(replace(record, state=RunState.SUCCEEDED))
    other = FileSystemRunStore(tmp_path)

    assert other.get(record.run_id).state is RunState.SUCCEEDED
    # Пересборка правки снова берёт прогон в работу - уже другой экземпляр хранилища.
    other.save(replace(record, state=RunState.RUNNING))
    assert owner.get(record.run_id).state is RunState.RUNNING
