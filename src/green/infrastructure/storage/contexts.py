"""Контекст правки прогона на диске: правка переживает перезапуск сервиса и новый прогон.

Формат - pickle: в контексте прочитанный чертёж, план, отчёт и карта покрытий, сотня с
лишним типов, и свой формат для них был бы второй моделью данных. Файл пишет и читает только
сам сервис, в каталоге прогона рядом со status.json; наружу как артефакт он не отдаётся.
Контекст, сохранённый другой версией кода, не поднимается: классы могли измениться, и
правка по такому контексту была бы проверкой по чужим правилам.

Правки после сохранения контекста - в журнале рядом с ним (edits.jsonl): строка на принятую
пачку правок, с номером. Контекст на каждую правку целиком не переписывается (сцена генплана -
сотни МБ), а все процессы сервиса читают один журнал и видят один черновик. Дописывает журнал
только тот, кто держит блокировку edits.lock, и только если журнал не ушёл дальше его плана.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pickle
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import green
from green.application.editing import Edit, EditKind
from green.application.errors import ConflictError, NotFoundError
from green.domain.norms import PlantingType
from green.infrastructure.storage import lease

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from green.application.editing import RunContext
    from green.infrastructure.storage.runs import FileSystemRunStore

LOGGER = logging.getLogger(__name__)
CONTEXT = "context.pickle"
JOURNAL = "edits.jsonl"
JOURNAL_LOCK = "edits.lock"
# Дозапись строки занимает миллисекунды: ждать блокировку дольше - значит, что-то не так.
LOCK_TIMEOUT_S = 10.0
LOCK_POLL_S = 0.005
BUSY = "Журнал правок прогона занят другим процессом. Повторите правку."

type Stamp = tuple[int, int, int]


def code_fingerprint() -> str:
    """Отпечаток исходников пакета: другой код - другие классы в сохранённом контексте."""
    root = Path(green.__file__).parent
    digest = hashlib.blake2b(digest_size=16)
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class PickleRunContextStore:
    def __init__(self, runs: FileSystemRunStore, fingerprint: str) -> None:
        self._runs = runs
        self._fingerprint = fingerprint

    def save(self, context: RunContext) -> Stamp | None:
        """Сохранить без индексов ограничений: они строятся заново по первой проверке точки.

        Сбой записи прогон не роняет: результат уже записан, теряется только правка после
        перезапуска, и это видно в журнале. Метка снимается с файла до переименования:
        переименование её не меняет, а чужая запись после него - меняет.
        """
        path = self._runs.state_file(context.run_id, CONTEXT)
        pending = path.with_name(f"{CONTEXT}.pending")
        try:
            with pending.open("wb") as handle:
                pickle.dump(
                    (self._fingerprint, replace(context, _indexes={})),
                    handle,
                    protocol=pickle.HIGHEST_PROTOCOL,
                )
            stamp = _stamp(pending.stat())
            pending.replace(path)
        except OSError, pickle.PicklingError, TypeError, AttributeError, RecursionError:
            pending.unlink(missing_ok=True)
            LOGGER.warning("Контекст правки прогона %s не сохранён", context.run_id, exc_info=True)
            return None
        return stamp

    def load(self, run_id: str) -> RunContext | None:
        try:
            path = self._runs.state_file(run_id, CONTEXT)
        except NotFoundError:
            return None
        if not path.is_file():
            return None
        try:
            with path.open("rb") as handle:
                # Файл пишет только сам сервис, в своём каталоге прогона.
                fingerprint, context = pickle.load(handle)  # noqa: S301
        except Exception:  # любой нечитаемый контекст значит «править нельзя»
            LOGGER.warning("Контекст правки прогона %s не прочитан", run_id, exc_info=True)
            return None
        if fingerprint != self._fingerprint:
            LOGGER.info("Контекст правки прогона %s сохранён другой версией кода", run_id)
            return None
        return context

    def stamp(self, run_id: str) -> Stamp | None:
        try:
            return _stamp(self._runs.state_file(run_id, CONTEXT).stat())
        except NotFoundError, OSError:
            return None

    def append_edits(self, run_id: str, edits: Sequence[Edit], after: int) -> int | None:
        journal = self._runs.state_file(run_id, JOURNAL)
        if not journal.parent.is_dir():
            raise NotFoundError(f"Прогон {run_id} не найден")
        seq = after + 1
        line = json.dumps(
            {"seq": seq, "edits": [_edit_payload(edit) for edit in edits]}, ensure_ascii=False
        )
        with _locked(journal.with_name(JOURNAL_LOCK), run_id):
            text = _read(journal)
            entries = _entries(text)
            if (entries[-1][0] if entries else 0) != after:
                return None
            # Строка, оборванная сбоем, не должна склеиться с новой.
            prefix = "\n" if text and not text.endswith("\n") else ""
            with journal.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"{prefix}{line}\n")
                handle.flush()
                os.fsync(handle.fileno())
        return seq

    def edits_since(self, run_id: str, seq: int) -> list[tuple[int, tuple[Edit, ...]]] | None:
        try:
            journal = self._runs.state_file(run_id, JOURNAL)
        except NotFoundError:
            return None
        if not journal.parent.is_dir():
            return None
        return [entry for entry in _entries(_read(journal)) if entry[0] > seq]


def _stamp(info: os.stat_result) -> Stamp:
    return (info.st_ino, info.st_mtime_ns, info.st_size)


@contextmanager
def _locked(path: Path, run_id: str) -> Iterator[None]:
    """Блокировка журнала между процессами; ОС снимает её сама, если процесс умер."""
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            handle = lease.acquire(path)
        except FileNotFoundError:
            raise NotFoundError(f"Прогон {run_id} не найден") from None
        if handle is not None:
            break
        if time.monotonic() > deadline:
            raise ConflictError(BUSY)
        time.sleep(LOCK_POLL_S)
    try:
        yield
    finally:
        lease.release(handle)


def _read(journal: Path) -> str:
    try:
        return journal.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _entries(text: str) -> list[tuple[int, tuple[Edit, ...]]]:
    """Строки журнала по номеру. Недописанная строка (запись идёт прямо сейчас или оборвалась
    сбоем) пропускается: принятой правкой она станет, только когда допишется целиком."""
    entries: list[tuple[int, tuple[Edit, ...]]] = []
    for line in text.splitlines():
        try:
            record = json.loads(line)
            entries.append(
                (int(record["seq"]), tuple(_edit_from(item) for item in record["edits"]))
            )
        except ValueError, KeyError, TypeError:
            continue
    return sorted(entries, key=lambda entry: entry[0])


def _edit_payload(edit: Edit) -> dict[str, object]:
    return {
        "kind": edit.kind.value,
        "placement_id": edit.placement_id,
        "x": edit.x,
        "y": edit.y,
        "species_code": edit.species_code,
        "planting_type": edit.planting_type.value if edit.planting_type else None,
    }


def _edit_from(item: dict[str, Any]) -> Edit:
    kind = item.get("planting_type")
    return Edit(
        kind=EditKind(item["kind"]),
        placement_id=item.get("placement_id"),
        x=item.get("x"),
        y=item.get("y"),
        species_code=item.get("species_code"),
        planting_type=PlantingType(kind) if kind else None,
    )
