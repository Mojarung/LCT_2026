"""Контекст правки прогона на диске: правка переживает перезапуск сервиса и новый прогон.

Формат - pickle: в контексте прочитанный чертёж, план, отчёт и карта покрытий, сотня с
лишним типов, и свой формат для них был бы второй моделью данных. Файл пишет и читает только
сам сервис, в каталоге прогона рядом со status.json; наружу как артефакт он не отдаётся.
Контекст, сохранённый другой версией кода, не поднимается: классы могли измениться, и
правка по такому контексту была бы проверкой по чужим правилам.
"""

from __future__ import annotations

import hashlib
import logging
import pickle
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import green
from green.application.errors import NotFoundError

if TYPE_CHECKING:
    from green.application.editing import RunContext
    from green.infrastructure.storage.runs import FileSystemRunStore

LOGGER = logging.getLogger(__name__)
CONTEXT = "context.pickle"


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

    def save(self, context: RunContext) -> None:
        """Сохранить без индексов ограничений: они строятся заново по первой проверке точки.

        Сбой записи прогон не роняет: результат уже записан, теряется только правка после
        перезапуска, и это видно в журнале.
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
            pending.replace(path)
        except OSError, pickle.PicklingError, TypeError, AttributeError, RecursionError:
            pending.unlink(missing_ok=True)
            LOGGER.warning("Контекст правки прогона %s не сохранён", context.run_id, exc_info=True)

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
