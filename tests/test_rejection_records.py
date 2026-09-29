"""Каждое отклонённое место - в плане, plan.json, интерпретациях и на слое GREEN_REJECT.

Жюри (R-25): на Олимпийской деревне записано ровно 2000 отказов - прежний предел
max_rejections, остальные места отклонены без записи. Предел остаётся предохранителем от
вырожденного чертежа: если он достигнут, предупреждение называет параметр и число
незаписанных мест.
"""

from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING

import ezdxf
import orjson
import pytest
from shapely.geometry import LineString
from test_pipeline_synthetic import ROOT, _street

from green.application.constraints import ConstraintIndex
from green.application.params import PlanParams
from green.application.placement import MODE_ALLEY, _Candidate, _offer, _Selector
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.domain.norms import (
    Citation,
    CitationStatus,
    DistanceRule,
    MeasureTo,
    PlantingType,
    Severity,
)
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import Species
from green.infrastructure.cad.documents import APPID
from green.infrastructure.cad.writer import LAYER_REJECT

if TYPE_CHECKING:
    from pathlib import Path

    from green.application.results import RunReport

OLD_LIMIT = 2000
STATION_STEP_M = 10.0


def _pipe_selector(stations: int, params: PlanParams) -> _Selector:
    """Станции через 10 м в 1 м от водопровода: каждая - отказ по норме 2,2 м, и соседние
    отказы не сливаются в один (шаг 6 м меньше расстояния между станциями)."""
    rule = DistanceRule(
        "test-distance",
        ObjectClass.UTILITY_WATER,
        PlantingType.TREE,
        2.2,
        MeasureTo.AXIS,
        Severity.FORBID,
        Citation("test", "test", "Synthetic distance", CitationStatus.UNVERIFIED),
    )
    pipe = Feature(
        SourceRef("00000000", "00000000", "water"),
        "arbitrary",
        LineString([(-STATION_STEP_M, 0), ((stations + 1) * STATION_STEP_M, 0)]),
        object_class=ObjectClass.UTILITY_WATER,
    )
    selector = _Selector(Species("test", "Тест", "Test test", 3), params)
    index = ConstraintIndex([pipe], [rule], require_utility_data=False)
    candidates = [_Candidate(i, MODE_ALLEY, i * STATION_STEP_M, 1.0) for i in range(stations)]
    _offer(index, selector, candidates)
    return selector


def test_every_rejected_place_is_recorded_beyond_the_old_limit() -> None:
    stations = OLD_LIMIT + 500
    selector = _pipe_selector(stations, PlanParams(spacing_m=6.0))
    assert not selector.placements
    assert len(selector.rejections) == stations
    assert [r.number for r in selector.rejections] == list(range(1, stations + 1))
    assert selector.unrecorded == 0


def test_record_limit_counts_places_left_unrecorded() -> None:
    selector = _pipe_selector(15, PlanParams(spacing_m=6.0, max_rejections=10))
    assert len(selector.rejections) == 10
    assert selector.unrecorded == 5


# --- сквозной прогон: план, plan.json, интерпретации, DXF ------------------------------------


@pytest.fixture(scope="module")
def street(tmp_path_factory: pytest.TempPathFactory) -> Path:
    source = tmp_path_factory.mktemp("street") / "street.dxf"
    _street(source)
    return source


def _run(
    street: Path, tmp_path: Path, overrides: dict[str, object]
) -> tuple[RunReport, dict[str, Path]]:
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    # Жадный отбор без добавочных этапов кустарника: отказы здесь - только отказы отбора мест.
    params = container.profiles.load(
        "strict",
        {
            "placement_solver": "greedy",
            "shrub_rows": False,
            "understory": False,
            "shrub_fill": False,
            **overrides,
        },
    )
    out = tmp_path / "out"
    report = container.use_case.execute(PlanRequest("test", street, out, "strict", params))
    return report, container.artifacts.save(out, report)


def _csv_rejection_ids(path: Path) -> set[str]:
    rows = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig")), delimiter=";")
    return {row["subject_id"] for row in rows if row["kind"] == "rejection"}


def _dxf_marks(path: Path) -> list[str]:
    doc = ezdxf.readfile(path)
    return [
        str(insert.get_xdata(APPID)[0].value)
        for insert in doc.modelspace().query(f"INSERT[layer=='{LAYER_REJECT}']")
    ]


def test_every_rejection_reaches_plan_json_interpretations_and_layer(
    street: Path, tmp_path: Path
) -> None:
    report, artifacts = _run(street, tmp_path, {})
    ids = {r.rejection_id for r in report.plan.rejections}
    assert len(ids) == len(report.plan.rejections) >= 3, "у синтетической улицы есть отказы"
    plan_json = orjson.loads(artifacts["plan.json"].read_bytes())
    assert {r["id"] for r in plan_json["rejections"]} == ids
    assert _csv_rejection_ids(artifacts["interpretations.csv"]) == ids
    interpretations = orjson.loads(artifacts["interpretations.json"].read_bytes())
    assert {row["subject_id"] for row in interpretations if row["kind"] == "rejection"} == ids
    assert sorted(_dxf_marks(report.output_dxf)) == sorted(ids)
    assert not any("max_rejections" in w for w in report.warnings)


def test_record_limit_warning_names_the_parameter_and_the_unrecorded(
    street: Path, tmp_path: Path
) -> None:
    full, _ = _run(street, tmp_path / "full", {})
    total = len(full.plan.rejections)
    limited, _ = _run(street, tmp_path / "limited", {"max_rejections": 2})
    assert len(limited.plan.rejections) == 2
    notes = [w for w in limited.warnings if "max_rejections" in w]
    assert len(notes) == 1
    # Незаписанных ровно столько, сколько записал бы прогон без предела.
    assert f"ещё в {total - 2} " in notes[0]
