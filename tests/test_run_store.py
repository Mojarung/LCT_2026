"""Статус прогона на диске: брошенный прогон не висит «идёт» вечно, живой не объявляется упавшим."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import orjson
import pytest

from green.application.errors import ConflictError, NotFoundError
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


def _filled(store: FileSystemRunStore, root: Path, size: int, state: RunState) -> str:
    record = store.create("street.dxf", "strict", {})
    store.save(replace(record, state=state))
    (root / record.run_id / "output").mkdir(exist_ok=True)
    (root / record.run_id / "output" / "result.dxf").write_bytes(b"0" * size)
    return record.run_id


def test_oldest_finished_runs_go_first_when_the_directory_is_over_the_limit(
    tmp_path: Path,
) -> None:
    """Стенд по ТЗ - 10-20 ГБ SSD: прогоны не копятся бесконечно, уходят самые старые."""
    filler = FileSystemRunStore(tmp_path)
    old, middle, recent = (
        _filled(filler, tmp_path, 4000, RunState.SUCCEEDED),
        _filled(filler, tmp_path, 4000, RunState.FAILED),
        _filled(filler, tmp_path, 4000, RunState.SUCCEEDED),
    )

    removed = FileSystemRunStore(tmp_path, max_bytes=9000).prune()

    assert removed == [old]
    assert not (tmp_path / old).exists()
    assert (tmp_path / middle).is_dir()
    assert (tmp_path / recent).is_dir()


def test_live_run_is_never_removed_even_over_the_limit(tmp_path: Path) -> None:
    owner = FileSystemRunStore(tmp_path)
    live = _filled(owner, tmp_path, 5000, RunState.RUNNING)
    done = _filled(owner, tmp_path, 5000, RunState.SUCCEEDED)

    removed = FileSystemRunStore(tmp_path, max_bytes=1000).prune()

    assert removed == [done]
    assert (tmp_path / live).is_dir()


def test_new_run_makes_room_first_and_no_limit_keeps_everything(tmp_path: Path) -> None:
    filler = FileSystemRunStore(tmp_path)
    old = _filled(filler, tmp_path, 5000, RunState.SUCCEEDED)
    assert FileSystemRunStore(tmp_path).prune() == []

    FileSystemRunStore(tmp_path, max_bytes=1000).create("next.dxf", "strict", {})

    assert not (tmp_path / old).exists()


@pytest.mark.parametrize("state", [RunState.SUCCEEDED, RunState.FAILED], ids=lambda s: s.value)
def test_finished_run_is_deleted_with_all_its_files(tmp_path: Path, state: RunState) -> None:
    store = FileSystemRunStore(tmp_path)
    neighbour = _filled(store, tmp_path, 10, RunState.SUCCEEDED)
    run_id = _filled(store, tmp_path, 10, state)

    FileSystemRunStore(tmp_path).delete(run_id)

    assert not (tmp_path / run_id).exists()
    with pytest.raises(NotFoundError):
        store.get(run_id)
    assert [r.run_id for r in store.recent(10)] == [neighbour]
    assert (tmp_path / neighbour / "output" / "result.dxf").is_file()


@pytest.mark.parametrize("state", [RunState.QUEUED, RunState.RUNNING], ids=lambda s: s.value)
def test_live_run_is_not_deleted_and_keeps_its_files(tmp_path: Path, state: RunState) -> None:
    """Прогон ведёт живой процесс: его не удаляет ни другой процесс (другой экземпляр
    хранилища), ни тот же, что его ведёт."""
    owner = FileSystemRunStore(tmp_path)
    run_id = _filled(owner, tmp_path, 10, state)
    before = sorted(p.relative_to(tmp_path) for p in (tmp_path / run_id).rglob("*"))

    for store in (FileSystemRunStore(tmp_path), owner):
        with pytest.raises(ConflictError, match="идёт"):
            store.delete(run_id)

    assert sorted(p.relative_to(tmp_path) for p in (tmp_path / run_id).rglob("*")) == before
    assert owner.get(run_id).state is state


def test_abandoned_run_is_deleted_like_a_failed_one(tmp_path: Path) -> None:
    """Статус «идёт», а блокировку никто не держит - процесс умер: такой прогон прерван.
    Экземпляр, создавший прогон, уже собран: его блокировка снята, как её сняла бы ОС."""
    record = FileSystemRunStore(tmp_path).create("street.dxf", "strict", {})
    status = tmp_path / record.run_id / STATUS
    status.write_bytes(orjson.dumps({**orjson.loads(status.read_bytes()), "state": "running"}))

    FileSystemRunStore(tmp_path).delete(record.run_id)

    assert not (tmp_path / record.run_id).exists()


def test_run_directory_without_status_is_not_deleted(tmp_path: Path) -> None:
    """Каталог без status.json - прогон как раз создаётся: не найден, но и не удалён."""
    store = FileSystemRunStore(tmp_path)
    run_id = "01a0eac7-e330-7505-883b-f24d08f36d96"
    (tmp_path / run_id / "input").mkdir(parents=True)

    with pytest.raises(NotFoundError):
        store.delete(run_id)

    assert (tmp_path / run_id / "input").is_dir()


@pytest.mark.parametrize(
    "run_id",
    [
        "..",
        "../outside",
        r"..\outside",
        "not-a-run-id",
        "01a0eac7-e330-7505-883b-f24d08f36d96",  # верный вид, такого прогона нет
        "{upper}",  # id соседа заглавными: на Windows тот же каталог
        "{kept}/..",
    ],
)
def test_bad_or_unknown_run_id_deletes_nothing(tmp_path: Path, run_id: str) -> None:
    root = tmp_path / "runs"
    store = FileSystemRunStore(root)
    kept = _filled(store, root, 10, RunState.SUCCEEDED)
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "keep.txt").write_text("x")

    with pytest.raises(NotFoundError):
        store.delete(run_id.format(upper=kept.upper(), kept=kept))

    assert (tmp_path / "outside" / "keep.txt").is_file()
    assert (root / kept / STATUS).is_file()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["outside", "runs"]
