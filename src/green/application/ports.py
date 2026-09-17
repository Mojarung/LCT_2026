"""Порты: всё, что прикладному слою нужно от внешнего мира."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
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


@dataclass(frozen=True, slots=True)
class MergeResult:
    """Объединённый чертёж комплекта и заметки о склейке для предупреждений прогона."""

    path: Path
    notes: tuple[str, ...] = ()


class DrawingMerger(Protocol):
    def merge(self, sources: Sequence[Path], target: Path) -> MergeResult: ...


class RuleBookSource(Protocol):
    def load(self) -> RuleBook: ...


class LayerMapSource(Protocol):
    def load(self) -> LayerMap: ...


class SpeciesCatalog(Protocol):
    def get(self, code: str) -> Species: ...

    def all(self) -> tuple[Species, ...]: ...


@dataclass(frozen=True, slots=True)
class InventoryCounts:
    """Существующие деревья по перечётной ведомости.

    Рядом с тем, что сопоставлено, стоит то, что не сопоставлено и что отброшено: иначе
    ведомость на 868 строк, от которой доехало двести, выглядит как успешный разбор.
    """

    matched: Mapping[str, int]  # код вида -> сколько экземпляров
    unmatched: Mapping[str, int] = field(default_factory=dict)  # название -> сколько
    approximate: Mapping[str, str] = field(default_factory=dict)  # название -> код по роду
    rows_read: int = 0
    rows_removed: int = 0  # заключение «вырубить»: этих деревьев после работ не будет
    rows_matched: int = 0
    rows_unmatched: int = 0
    rows_without_count: int = 0  # количество не указано, принято за одно дерево

    @property
    def total(self) -> int:
        return sum(self.matched.values())

    @property
    def balanced(self) -> bool:
        """Каждая прочитанная строка куда-то делась: отброшена, опознана или нет."""
        return self.rows_read == self.rows_removed + self.rows_matched + self.rows_unmatched


class InventorySource(Protocol):
    def read(self, path: Path, catalog: Sequence[Species]) -> InventoryCounts: ...


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
