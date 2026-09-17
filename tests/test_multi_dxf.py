"""Комплект из нескольких DXF: генплан в одном файле, сети в другом.

Заказчик подаёт на вход несколько DXF (docs/notes/15-organizers-qa.md, вопросы 3 и 4). Сервис
склеивает их в один документ, результат пишет в него. Водопровод лежит только во втором файле:
если план держит от него отступ, значит комплект прочитан целиком.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import pytest
from test_pipeline_synthetic import CURB_Y, PIPE_DIAMETER_M, PIPE_Y, ROOT, WATER_RULE_M

from green.application.use_case import MERGED_DXF, PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings

if TYPE_CHECKING:
    from pathlib import Path


def _genplan(path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    for layer in ("Граница заказа", "Бортовой камень", "Граница улицы", "Леса и газоны", "Здания"):
        doc.layers.add(layer)
    msp.add_lwpolyline(
        [(0, 0), (120, 0), (120, 60), (0, 60)], close=True, dxfattribs={"layer": "Граница заказа"}
    )
    for x in range(0, 120, 1):
        msp.add_line((x, CURB_Y), (x + 0.7, CURB_Y), dxfattribs={"layer": "Бортовой камень"})
    msp.add_text("А", dxfattribs={"layer": "Граница улицы"}).set_placement((60, 10))
    msp.add_text("ГАЗОН", dxfattribs={"layer": "Леса и газоны"}).set_placement((60, 30))
    msp.add_lwpolyline(
        [(0, 55), (120, 55), (120, 60), (0, 60)], close=True, dxfattribs={"layer": "Здания"}
    )
    doc.saveas(path)


def _utilities(path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    doc.layers.add("Водопровод")
    msp = doc.modelspace()
    msp.add_line((0, PIPE_Y), (120, PIPE_Y), dxfattribs={"layer": "Водопровод"})
    msp.add_text("d=300ст.", dxfattribs={"layer": "Водопровод"}).set_placement((60, PIPE_Y + 0.5))
    doc.saveas(path)


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory):  # noqa: ANN201 - RunReport из сценария
    work = tmp_path_factory.mktemp("kit")
    genplan, utilities = work / "genplan.dxf", work / "utilities.dxf"
    _genplan(genplan)
    _utilities(utilities)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=work / "runs"))
    params = container.profiles.load("strict", {"max_rejections": 50})
    request = PlanRequest(
        "kit", genplan, work / "out", "strict", params, extra_sources=(utilities,)
    )
    return container.use_case.execute(request)


def test_plan_keeps_distance_to_the_pipe_from_the_second_file(report) -> None:  # noqa: ANN001
    trees = [p for p in report.plan.placements if p.species.is_tree]
    assert len(trees) >= 10
    for placement in trees:
        assert abs(placement.y - PIPE_Y) - PIPE_DIAMETER_M / 2 >= WATER_RULE_M - 1e-3


def test_merge_is_reported_and_the_result_holds_both_files(report) -> None:  # noqa: ANN001
    assert any("Склейка комплекта" in w and "utilities.dxf" in w for w in report.warnings)
    assert report.integrity.ok
    assert (report.output_dxf.parent / MERGED_DXF).exists()
    doc = ezdxf.readfile(report.output_dxf)
    layers = {layer.dxf.name for layer in doc.layers}
    assert {"Бортовой камень", "Водопровод", "GREEN_TREES"} <= layers
    assert len(doc.modelspace().query("LINE[layer=='Водопровод']")) == 1


def test_single_file_run_does_not_merge(tmp_path: Path) -> None:
    source = tmp_path / "genplan.dxf"
    _genplan(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load("no_utilities", {"max_rejections": 10})
    result = container.use_case.execute(
        PlanRequest("one", source, tmp_path / "out", "no_utilities", params)
    )
    assert not any("Склейка" in w for w in result.warnings)
    assert not (tmp_path / "out" / MERGED_DXF).exists()


def test_kit_from_different_places_is_reported(tmp_path: Path) -> None:
    """Файл с другого листа склеится, но предупреждение назовёт его: габариты не перекрываются."""
    genplan, far_away = tmp_path / "genplan.dxf", tmp_path / "far.dxf"
    _genplan(genplan)
    doc = ezdxf.new("R2018")
    doc.layers.add("Водопровод")
    doc.modelspace().add_line((5000, 5000), (5100, 5000), dxfattribs={"layer": "Водопровод"})
    doc.saveas(far_away)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load("no_utilities", {"max_rejections": 10})
    result = container.use_case.execute(
        PlanRequest(
            "far", genplan, tmp_path / "out", "no_utilities", params, extra_sources=(far_away,)
        )
    )
    assert any("перекрываются на 0%" in w and "far.dxf" in w for w in result.warnings)
