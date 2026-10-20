"""Входные сторонние DXF (локальные, в git не идут; без них тесты пропускаются).

Проверка «чужое соглашение» до данных жюри: прогон по умолчанию не падает и не останавливается
на том, что сервис может прочитать сам. Чужой код не запускается, читаются только DXF.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
OTHER = ROOT / "other"
DANKO = OTHER / "DankoDmitry__GreenCAD_prototype_2026/materials/dxf_examples"


def _run(path: Path, tmp_path: Path):  # noqa: ANN202
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load("strict", {})
    return container.use_case.execute(
        PlanRequest(path.stem, path, tmp_path / "out", "strict", params)
    )


@pytest.mark.skipif(not DANKO.exists(), reason="other/ только локально")
def test_overlay_of_invalid_surface_polygons_does_not_crash(tmp_path: Path) -> None:
    """GreenCAD, 3-я Парковая целиком: самопересекающиеся заливки покрытий роняли разность
    полигонов GEOS («Unable to determine overlay result geometry dimension»)."""
    report = _run(DANKO / "02_3ya_Parkovaya_typed_full_corridor.dxf", tmp_path)
    assert report.integrity.ok
