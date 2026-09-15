"""Порты: всё, что прикладному слою нужно от внешнего мира."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from green.application.classification import LayerMap
    from green.application.params import PlanParams
    from green.application.results import (
        IntegrityReport,
        RunRecord,
        RunReport,
        SourceSnapshot,
    )
    from green.domain.norms import RuleBook
    from green.domain.objects import Scene
    from green.domain.planting import Plan, Species


class SceneReader(Protocol):
    def read(self, path: Path) -> Scene: ...


class DrawingConverter(Protocol):
    @property
    def name(self) -> str: ...

    def available(self) -> bool: ...

    def to_dxf(self, source: Path, workdir: Path) -> Path: ...


class RuleBookSource(Protocol):
    def load(self) -> RuleBook: ...


class LayerMapSource(Protocol):
    def load(self) -> LayerMap: ...


class SpeciesCatalog(Protocol):
    def get(self, code: str) -> Species: ...

    def all(self) -> tuple[Species, ...]: ...


class ProfileSource(Protocol):
    def names(self) -> tuple[str, ...]: ...

    def load(self, name: str, overrides: Mapping[str, object] | None = None) -> PlanParams: ...


class PlanWriter(Protocol):
    def write(
        self, source: Path, plan: Plan, rulebook: RuleBook, target: Path
    ) -> SourceSnapshot: ...


class IntegrityChecker(Protocol):
    def check(self, before: SourceSnapshot, result: Path) -> IntegrityReport: ...


class ArtifactSink(Protocol):
    def save(self, directory: Path, report: RunReport) -> dict[str, Path]: ...


class RunStore(Protocol):
    def create(
        self, source_name: str, profile: str, overrides: Mapping[str, object]
    ) -> RunRecord: ...

    def input_path(self, run_id: str) -> Path: ...

    def run_dir(self, run_id: str) -> Path: ...

    def get(self, run_id: str) -> RunRecord: ...

    def save(self, record: RunRecord) -> None: ...

    def recent(self, limit: int) -> list[RunRecord]: ...

    def artifact(self, run_id: str, name: str) -> Path: ...
