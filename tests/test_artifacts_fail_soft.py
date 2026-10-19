"""Сбой необязательного файла прогона не роняет прогон и называется в plan.json.

Чертёж жюри 236287.dxf, 19.10.2026: выгрузка покрытий для 3D падала на мультиполигоне уже после
записи result.dxf, и API показывал прогон проваленным, хотя план, DXF и объяснения были готовы.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from test_pipeline_synthetic import ROOT, _street

from green.application import use_case
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.infrastructure.reports import artifacts

if TYPE_CHECKING:
    from pathlib import Path


def test_broken_optional_file_is_reported_and_the_rest_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "street.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load("strict", {"max_rejections": 50})
    report = container.use_case.execute(
        PlanRequest("test", source, tmp_path / "out", "strict", params)
    )

    def broken(*_args: object, **_kwargs: object) -> None:
        raise AttributeError("'MultiPolygon' object has no attribute 'exterior'")

    monkeypatch.setattr(artifacts, "_surface", broken)
    monkeypatch.setattr(artifacts, "write_note", broken)
    saved = artifacts.FileArtifactSink().save(tmp_path / "out", report)

    assert "surface.json" not in saved
    assert "note.docx" not in saved
    for name in ("result.dxf", "plan.json", "interpretations.csv", "verify.json", "scene.json"):
        assert saved[name].is_file(), name
    plan = json.loads(saved["plan.json"].read_text(encoding="utf-8"))
    assert [e.split(":")[0] for e in plan["artifact_errors"]] == ["note.docx", "surface.json"]
    assert any("note.docx" in w for w in plan["warnings"])


def test_memory_or_disk_failure_is_not_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "street.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load("strict", {"max_rejections": 50})
    report = container.use_case.execute(
        PlanRequest("test", source, tmp_path / "out", "strict", params)
    )

    def full_disk(*_args: object, **_kwargs: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(artifacts, "write_note", full_disk)
    with pytest.raises(OSError, match="No space"):
        artifacts.FileArtifactSink().save(tmp_path / "out", report)


def test_failing_optional_stage_is_skipped_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Объёмы зданий для 3D и карта покрытий для показа не нужны плану по нормам: их сбой на
    незнакомом чертеже пропускает этап с предупреждением, а не роняет прогон."""

    def broken(*_args: object, **_kwargs: object) -> None:
        raise ValueError("A LinearRing must have at least 3 coordinate tuples")

    monkeypatch.setattr(use_case, "build_volumes", broken)
    source = tmp_path / "street.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load("strict", {"max_rejections": 50})
    report = container.use_case.execute(
        PlanRequest("test", source, tmp_path / "out", "strict", params)
    )
    assert report.plan.placements
    assert report.integrity.ok
    assert report.volumes is not None
    assert report.volumes.buildings == ()
    assert any("объёмы зданий для 3D" in w for w in report.warnings)
