"""Каталог на прогон: input/ (исходник), output/ (артефакты), status.json. Id: uuid7."""

from __future__ import annotations

import re
import threading
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

import orjson

from green.application.errors import InputError, NotFoundError
from green.application.results import RunProgress, RunRecord, RunState, StageTiming
from green.infrastructure.storage import lease

if TYPE_CHECKING:
    from collections.abc import Mapping

_RUN_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_ARTIFACT = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_UNSAFE = re.compile(r"[^\w.\- ]", re.UNICODE)
ALLOWED_SUFFIXES = frozenset({".dxf", ".dwg"})
MAX_NAME = 120
STATUS = "status.json"
LEASE = "lease"
_ACTIVE = frozenset({RunState.QUEUED, RunState.RUNNING})
INTERRUPTED = (
    "Прогон прерван: процесс сервиса остановился до конца расчёта. Запустите прогон заново."
)


class FileSystemRunStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        # Блокировки прогонов, которые ведёт этот экземпляр: от постановки в очередь до конца.
        self._leases: dict[str, IO[bytes]] = {}
        self._guard = threading.Lock()

    def create(self, source_name: str, profile: str, overrides: Mapping[str, object]) -> RunRecord:
        safe = _safe_name(source_name)
        run_id = str(uuid.uuid7())
        (self._root / run_id / "input").mkdir(parents=True)
        now = datetime.now(UTC)
        record = RunRecord(
            run_id=run_id,
            state=RunState.QUEUED,
            source_name=safe,
            profile=profile,
            overrides=dict(overrides),
            created_at=now,
            updated_at=now,
        )
        self.save(record)
        return record

    def input_path(self, run_id: str) -> Path:
        return self._dir(run_id) / "input" / self.get(run_id).source_name

    def run_dir(self, run_id: str) -> Path:
        return self._dir(run_id) / "output"

    def get(self, run_id: str) -> RunRecord:
        path = self._dir(run_id) / STATUS
        if not path.is_file():
            raise NotFoundError(f"Прогон {run_id} не найден")
        data = orjson.loads(path.read_bytes())
        record = RunRecord(
            run_id=data["run_id"],
            state=RunState(data["state"]),
            source_name=data["source_name"],
            profile=data["profile"],
            overrides=data["overrides"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            error=data.get("error"),
            summary=data.get("summary", {}),
            artifacts=tuple(data.get("artifacts", ())),
            progress=_progress_from(data.get("progress")),
        )
        if record.state in _ACTIVE and self._orphaned(run_id):
            record = replace(
                record,
                state=RunState.FAILED,
                error=INTERRUPTED,
                progress=None,
                updated_at=datetime.now(UTC),
            )
            self.save(record)
        return record

    def save(self, record: RunRecord) -> None:
        """Записать статус. Идущий прогон этот экземпляр держит заблокированным, пока он не
        закончится: по блокировке другой процесс (и перезапущенный сервис) отличает живой
        прогон от брошенного."""
        if record.state in _ACTIVE:
            self._hold(record.run_id)
        payload = {
            "run_id": record.run_id,
            "state": record.state.value,
            "source_name": record.source_name,
            "profile": record.profile,
            "overrides": dict(record.overrides),
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "error": record.error,
            "summary": dict(record.summary),
            "artifacts": list(record.artifacts),
            "progress": _progress_payload(record.progress),
        }
        path = self._dir(record.run_id) / STATUS
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2))
        temporary.replace(path)
        if record.state not in _ACTIVE:
            self._drop(record.run_id)

    def recent(self, limit: int) -> list[RunRecord]:
        ids = sorted(
            (p.name for p in self._root.iterdir() if _RUN_ID.fullmatch(p.name)), reverse=True
        )
        return [
            self.get(run_id) for run_id in ids[:limit] if (self._root / run_id / STATUS).is_file()
        ]

    def _hold(self, run_id: str) -> None:
        with self._guard:
            if run_id in self._leases:
                return
            handle = lease.acquire(self._dir(run_id) / LEASE)
            if handle is not None:
                self._leases[run_id] = handle

    def _drop(self, run_id: str) -> None:
        with self._guard:
            handle = self._leases.pop(run_id, None)
        if handle is not None:
            lease.release(handle)

    def _orphaned(self, run_id: str) -> bool:
        """Статус «идёт», а блокировку никто не держит: процесс, который вёл прогон, умер."""
        with self._guard:
            if run_id in self._leases:
                return False
        return not lease.held(self._dir(run_id) / LEASE)

    def state_file(self, run_id: str, name: str) -> Path:
        """Служебный файл прогона рядом со status.json: не артефакт, наружу не отдаётся."""
        return self._dir(run_id) / name

    def artifact(self, run_id: str, name: str) -> Path:
        if not _ARTIFACT.fullmatch(name) or name not in self.get(run_id).artifacts:
            raise NotFoundError(f"Артефакт {name} не найден")
        path = self.run_dir(run_id) / name
        if not path.is_file():
            raise NotFoundError(f"Артефакт {name} не найден")
        return path

    def _dir(self, run_id: str) -> Path:
        if not _RUN_ID.fullmatch(run_id):
            raise NotFoundError(f"Прогон {run_id} не найден")
        return self._root / run_id


def _progress_payload(progress: RunProgress | None) -> dict[str, object] | None:
    if progress is None:
        return None
    return {
        "stages": list(progress.stages),
        "stage": progress.stage,
        "started_at": progress.started_at.isoformat(),
        "stage_started_at": progress.stage_started_at.isoformat(),
        "done": [{"stage": t.stage, "ms": t.ms} for t in progress.done],
        "source_bytes": progress.source_bytes,
    }


def _progress_from(data: Mapping[str, Any] | None) -> RunProgress | None:
    if not data:
        return None
    return RunProgress(
        stages=tuple(str(s) for s in data["stages"]),
        stage=data.get("stage"),
        started_at=datetime.fromisoformat(data["started_at"]),
        stage_started_at=datetime.fromisoformat(data["stage_started_at"]),
        done=tuple(StageTiming(str(t["stage"]), float(t["ms"])) for t in data.get("done", ())),
        source_bytes=int(data.get("source_bytes", 0)),
    )


def _safe_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    suffix = Path(base).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise InputError("Принимаются только файлы .dxf и .dwg")
    stem = _UNSAFE.sub("_", Path(base).stem).strip(" .") or "drawing"
    return f"{stem[:MAX_NAME]}{suffix}"
