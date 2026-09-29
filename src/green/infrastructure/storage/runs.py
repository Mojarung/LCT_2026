"""Каталог на прогон: input/ (исходник), output/ (артефакты), status.json. Id: uuid7."""

from __future__ import annotations

import logging
import re
import shutil
import threading
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

import orjson

from green.application.errors import ConflictError, InputError, NotFoundError
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
LOGGER = logging.getLogger(__name__)
_ACTIVE = frozenset({RunState.QUEUED, RunState.RUNNING})
INTERRUPTED = (
    "Прогон прерван: процесс сервиса остановился до конца расчёта. Запустите прогон заново."
)
BUSY = (
    "Прогон ещё идёт: удалить можно только законченный прогон. Дождитесь конца расчёта"
    " или пересборки плана."
)
# Приставка каталога, который стирается: под _RUN_ID она не подходит, и ни список, ни
# очистка по пределу объёма такой каталог прогоном не считают.
DELETED = ".deleted-"
RENAME_ATTEMPTS = 5


class FileSystemRunStore:
    def __init__(self, root: Path, max_bytes: int | None = None) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        # Предел объёма каталога прогонов: стенд по ТЗ - 10-20 ГБ SSD, а прогон тяжёлой улицы
        # занимал до 5 ГБ (Нижние Поля, 26.09.2026). None - без предела.
        self._max_bytes = max_bytes
        # Блокировки прогонов, которые ведёт этот экземпляр: от постановки в очередь до конца.
        self._leases: dict[str, IO[bytes]] = {}
        self._guard = threading.Lock()

    def create(self, source_name: str, profile: str, overrides: Mapping[str, object]) -> RunRecord:
        self.prune()
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

    def prune(self) -> list[str]:
        """Удалить самые старые законченные прогоны, пока каталог не уложится в предел.

        Идущий прогон (живая блокировка) и каталог без статуса (прогон как раз создаётся) не
        удаляются никогда. Id - uuid7, поэтому порядок имён - порядок создания.
        """
        if not self._max_bytes:
            return []
        ids = sorted(p.name for p in self._root.iterdir() if _RUN_ID.fullmatch(p.name))
        sizes = {run_id: _tree_size(self._root / run_id) for run_id in ids}
        total = sum(sizes.values())
        removed: list[str] = []
        for run_id in ids:
            if total <= self._max_bytes:
                break
            if self._busy(run_id):
                continue
            shutil.rmtree(self._root / run_id, ignore_errors=True)
            total -= sizes[run_id]
            removed.append(run_id)
        if removed:
            LOGGER.info(
                "Удалено старых прогонов: %d, каталог теперь %.1f ГБ (предел %.1f ГБ)",
                len(removed),
                total / 2**30,
                self._max_bytes / 2**30,
            )
        return removed

    def _busy(self, run_id: str) -> bool:
        path = self._dir(run_id) / STATUS
        if not path.is_file():
            return True
        try:
            state = RunState(orjson.loads(path.read_bytes())["state"])
        except orjson.JSONDecodeError, KeyError, ValueError:
            return True
        return state in _ACTIVE and not self._orphaned(run_id)

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

    def delete(self, run_id: str) -> None:
        """Удалить законченный прогон целиком: исходник, артефакты, контекст правки.

        Идущий прогон (блокировку держит этот или другой живой процесс) не трогается -
        ConflictError. Брошенный (статус «идёт», блокировки нет) удаляется, как упавший.
        Проверка и переименование каталога идут под блокировкой прогона и под замком
        экземпляра: пока они у нас, прогон не возьмёт в работу ни этот процесс, ни другой.
        Каталог сначала переименовывается - прогон пропадает из списка сразу, - а стирается
        потом: прогон тяжёлой улицы весит гигабайты и стирается секундами.
        """
        folder = self._dir(run_id)
        if not (folder / STATUS).is_file():
            raise NotFoundError(f"Прогон {run_id} не найден")
        trash = self._root / f"{DELETED}{run_id}"
        with self._guard:
            if run_id in self._leases:
                raise ConflictError(BUSY)
            handle = lease.acquire(folder / LEASE)
            if handle is None:
                raise ConflictError(BUSY)
            # Под Windows каталог с открытым файлом не переименовать: блокировку отпускаем
            # до переименования, а замок экземпляра не даёт этому процессу взять её снова.
            lease.release(handle)
            _rename(folder, trash)
        shutil.rmtree(trash, ignore_errors=True)
        if trash.exists():
            LOGGER.warning("Каталог удалённого прогона стёрт не полностью: %s", trash)
        LOGGER.info("Прогон %s удалён", run_id)

    def _dir(self, run_id: str) -> Path:
        if not _RUN_ID.fullmatch(run_id):
            raise NotFoundError(f"Прогон {run_id} не найден")
        return self._root / run_id


def _rename(folder: Path, target: Path) -> None:
    """Переименовать каталог прогона. Под Windows файл внутри бывает на мгновение открыт
    чужим процессом (антивирус, индексатор, читатель статуса) - тогда ещё несколько попыток."""
    for attempt in range(RENAME_ATTEMPTS):
        try:
            folder.rename(target)
        except PermissionError:
            if attempt == RENAME_ATTEMPTS - 1:
                msg = "Файлы прогона сейчас заняты другим процессом. Попробуйте удалить ещё раз."
                raise ConflictError(msg) from None
            time.sleep(0.1 * (attempt + 1))
        else:
            return


def _tree_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


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
