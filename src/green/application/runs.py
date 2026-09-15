"""Фоновые прогоны для API: очередь с ограничением параллельности и статусы."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from green.application.errors import GreenError
from green.application.results import RunRecord, RunState
from green.application.use_case import PlanRequest

if TYPE_CHECKING:
    from collections.abc import Mapping

    from green.application.ports import ArtifactSink, ProfileSource, RunStore
    from green.application.use_case import PlanSite


class RunService:
    def __init__(
        self,
        *,
        store: RunStore,
        use_case: PlanSite,
        profiles: ProfileSource,
        artifacts: ArtifactSink,
        max_parallel: int,
    ) -> None:
        self._store = store
        self._use_case = use_case
        self._profiles = profiles
        self._artifacts = artifacts
        self._slots = threading.BoundedSemaphore(max_parallel)

    def register(
        self, source_name: str, profile: str, overrides: Mapping[str, object]
    ) -> RunRecord:
        """Проверяет профиль до загрузки файла, чтобы ошибка параметров не стоила прогона."""
        self._profiles.load(profile, overrides)
        return self._store.create(source_name, profile, overrides)

    def reject(self, run_id: str, reason: str) -> RunRecord:
        return self._transition(self._store.get(run_id), RunState.FAILED, error=reason)

    def execute(self, run_id: str) -> RunRecord:
        """Синхронный прогон: вызывается из пула потоков, CPU-работа не блокирует event loop."""
        record = self._store.get(run_id)
        with self._slots:
            record = self._transition(record, RunState.RUNNING)
            try:
                params = self._profiles.load(record.profile, record.overrides)
                run_dir = self._store.run_dir(run_id)
                report = self._use_case.execute(
                    PlanRequest(
                        run_id=run_id,
                        source=self._store.input_path(run_id),
                        work_dir=run_dir,
                        profile=record.profile,
                        params=params,
                    )
                )
                saved = self._artifacts.save(run_dir, report)
            except GreenError as error:
                return self._transition(record, RunState.FAILED, error=str(error))
            except Exception as error:  # noqa: BLE001 - любой сбой прогона фиксируется в статусе
                return self._transition(
                    record, RunState.FAILED, error=f"{type(error).__name__}: {error}"
                )
            return self._transition(
                record,
                RunState.SUCCEEDED,
                summary=report.summary(),
                artifacts=tuple(sorted(saved)),
            )

    def _transition(
        self,
        record: RunRecord,
        state: RunState,
        *,
        error: str | None = None,
        summary: Mapping[str, object] | None = None,
        artifacts: tuple[str, ...] = (),
    ) -> RunRecord:
        updated = replace(
            record,
            state=state,
            updated_at=datetime.now(UTC),
            error=error,
            summary=dict(summary or record.summary),
            artifacts=artifacts or record.artifacts,
        )
        self._store.save(updated)
        return updated
