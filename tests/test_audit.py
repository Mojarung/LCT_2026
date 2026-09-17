"""Нормоконтроль готового чертежа: посадки проектировщика проверяются правилами сервиса.

Чертёж: синтетическая улица из сквозного теста, к ней добавлены посадки «проектировщика» на слоях
вида `06_ДП_<Порода>_план`, как на посадочном плане Берзарина: липа в норме, липа в 1,4 м от
водопровода, липа в трёх метрах от здания, сирень с кругом кроны 3 м в полуметре от трубы,
бузина (рода нет в каталоге) и контур изгороди, который проверке не подлежит.
"""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING

import ezdxf
import orjson
import pytest
from test_pipeline_synthetic import PIPE_DIAMETER_M, PIPE_Y, ROOT, _street

from green.application.audit import AuditRequest, audit_rules
from green.application.errors import InputError
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.domain.norms import PlantingType
from green.domain.planting import Verdict

if TYPE_CHECKING:
    from pathlib import Path

    from green.application.audit import AuditedPlanting, AuditReport

LINDEN = "06_ДП_ЛИПА_Мелк_план"
BOUND_LINDEN = f"plan$0${LINDEN}"
LILAC = "06_ДП_СиреньВЕНГ._план"
ELDER = "06_ДП_БузинаЧерн_план"
PATTERN = r"^0?6_+ДП_.+_план$"
TREE_CROWN_R = 2.5
GOOD = (30.0, 30.0)
PIPE_GAP_M = 1.4
NEAR_PIPE = (50.0, PIPE_Y - PIPE_GAP_M)
NEAR_HOUSE = (70.0, 52.0)
LILAC_NEAR_PIPE = (90.0, PIPE_Y - 0.5)
ELDER_AT = (100.0, 30.0)
NEAR_UNKNOWN_LINE = (40.0, 28.0)
PLANTINGS = 6
UNKNOWN_LAYER = "ZZ_слой_вне_классификатора"


def _designed(path: Path) -> None:
    _street(path)
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    for layer in (LINDEN, BOUND_LINDEN, LILAC, ELDER, UNKNOWN_LAYER):
        doc.layers.add(layer)
    sign = doc.blocks.new("TREE_SIGN")
    sign.add_circle((0, 0), 0.2)
    msp.add_circle(GOOD, TREE_CROWN_R, dxfattribs={"layer": LINDEN})
    msp.add_blockref("TREE_SIGN", GOOD, dxfattribs={"layer": LINDEN})  # знак и крона: одна посадка
    msp.add_circle(NEAR_PIPE, TREE_CROWN_R, dxfattribs={"layer": BOUND_LINDEN})
    msp.add_circle(NEAR_HOUSE, 1.5, dxfattribs={"layer": LINDEN})
    msp.add_circle(LILAC_NEAR_PIPE, 1.5, dxfattribs={"layer": LILAC})
    msp.add_circle(ELDER_AT, 1.0, dxfattribs={"layer": ELDER})
    msp.add_lwpolyline([(10, 25), (20, 25), (20, 26)], dxfattribs={"layer": LINDEN})
    # Линия на слое, которого нет в классификаторе, в полуметре от липы: сетью не считается.
    msp.add_circle(NEAR_UNKNOWN_LINE, TREE_CROWN_R, dxfattribs={"layer": LINDEN})
    msp.add_line((35, 28.5), (45, 28.5), dxfattribs={"layer": UNKNOWN_LAYER})
    doc.saveas(path)


def _audit(work: Path, profile: str = "strict", **options: str) -> AuditReport:
    work.mkdir(parents=True, exist_ok=True)
    source = work / "designed.dxf"
    _designed(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=work / "runs"))
    params = container.profiles.load(profile, {})
    request = AuditRequest(
        "audit", source, work / "out", profile, params, planting_layers=PATTERN, **options
    )
    return container.audit.execute(request)


@pytest.fixture(scope="module")
def audited(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    work = tmp_path_factory.mktemp("audit")
    report = _audit(work)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=work / "runs"))
    return {"report": report, "artifacts": container.audit_artifacts.save(work / "out", report)}


def _at(report: AuditReport, point: tuple[float, float]) -> AuditedPlanting:
    return next(p for p in report.plantings if (round(p.x, 3), round(p.y, 3)) == point)


def test_every_planting_is_found_once(audited: dict[str, object]) -> None:
    report: AuditReport = audited["report"]  # type: ignore[assignment]
    assert len(report.plantings) == PLANTINGS  # знак и круг кроны в одной точке не задваиваются
    assert [p.number for p in report.plantings] == list(range(1, PLANTINGS + 1))
    assert report.skipped == {"LineString": 1}
    assert _at(report, GOOD).crown_m == 2 * TREE_CROWN_R


def test_tree_within_the_norms_has_no_violations(audited: dict[str, object]) -> None:
    good = _at(audited["report"], GOOD)  # type: ignore[arg-type]
    assert good.verdict is Verdict.ALLOWED
    assert good.violations == ()
    assert "липа" in good.type_basis


def test_tree_near_the_pipe_breaks_the_water_rule(audited: dict[str, object]) -> None:
    planting = _at(audited["report"], NEAR_PIPE)  # type: ignore[arg-type]
    assert planting.verdict is Verdict.FORBIDDEN
    assert [c.rule_id for c in planting.violations] == ["R-WATER-TREE-001"]
    check = planting.violations[0]
    assert check.threshold_m == 2.0
    assert check.measured_m == pytest.approx(PIPE_GAP_M - PIPE_DIAMETER_M / 2, abs=0.01)


def test_tree_near_the_house_breaks_the_building_rule(audited: dict[str, object]) -> None:
    planting = _at(audited["report"], NEAR_HOUSE)  # type: ignore[arg-type]
    assert [c.rule_id for c in planting.violations] == ["R-BLD-TREE-001"]
    assert planting.violations[0].measured_m == pytest.approx(3.0, abs=0.01)


def test_genus_from_the_catalog_beats_the_crown_size(audited: dict[str, object]) -> None:
    """Сирень нарисована кругом 3 м, как дерево. По каталогу это кустарник, а для кустарника
    у водопровода нормы нет (прочерк в таблице): в полуметре от трубы он допустим."""
    lilac = _at(audited["report"], LILAC_NEAR_PIPE)  # type: ignore[arg-type]
    assert lilac.planting_type is PlantingType.SHRUB
    assert "сирень" in lilac.type_basis
    assert lilac.violations == ()
    assert not any(c.rule_id == "R-WATER-TREE-001" for c in lilac.checks)


def test_unknown_genus_falls_back_to_the_crown_and_to_explicit_layers(tmp_path: Path) -> None:
    by_crown = _at(_audit(tmp_path / "a"), ELDER_AT)
    assert by_crown.planting_type is PlantingType.TREE
    assert "круг кроны 2.0 м" in by_crown.type_basis
    named = _at(_audit(tmp_path / "b", shrub_layers="Бузина"), ELDER_AT)
    assert named.planting_type is PlantingType.SHRUB
    assert "в параметрах" in named.type_basis


def test_unknown_layers_and_project_parameters_are_not_violations(
    audited: dict[str, object],
) -> None:
    report: AuditReport = audited["report"]  # type: ignore[assignment]
    near_line = _at(report, NEAR_UNKNOWN_LINE)
    assert near_line.violations == ()
    assert not any(c.rule_id.startswith("R-UTILUNK") for c in near_line.checks)
    assert any("Не вошли в классификатор" in w for w in report.warnings)
    rules = audit_rules(report.rulebook, report.params, PlantingType.TREE)
    assert rules
    assert all(rule.citation.act_id != "PROJECT" for rule in rules)
    # Шаг до существующих деревьев не проверяется: вырубаемые на чертеже не отличить.
    assert all(rule.object_class.value != "existing_tree" for rule in rules)


def test_summary_counts_types_and_violations(audited: dict[str, object]) -> None:
    summary = audited["report"].summary()  # type: ignore[attr-defined]
    assert summary["trees"] == 5
    assert summary["shrubs"] == 1
    assert summary["with_violations"] == 2
    assert summary["violations"] == 2


def test_marks_go_to_audit_layers_and_the_source_stays_intact(audited: dict[str, object]) -> None:
    report: AuditReport = audited["report"]  # type: ignore[assignment]
    assert report.integrity.ok
    doc = ezdxf.readfile(report.output_dxf)
    msp = doc.modelspace()
    assert len(msp.query("INSERT[layer=='GREEN_AUDIT_VIOLATION']")) == len(report.violating)
    assert len(msp.query("INSERT[layer=='GREEN_AUDIT_OK']")) == PLANTINGS - len(report.violating)
    assert len(msp.query(f"CIRCLE[layer=='{LINDEN}']")) == 3  # посадки проектировщика на месте
    mark = msp.query("INSERT[layer=='GREEN_AUDIT_VIOLATION']").first
    assert {a.dxf.tag for a in mark.attribs} == {"NUM", "NPA"}
    legend = " ".join(e.text for e in msp.query("MTEXT[layer=='GREEN_AUDIT_LABELS']"))
    assert f"с нарушением отступов: {len(report.violating)}" in legend
    assert "СП 42.13330.2016" in legend


def test_artifacts_name_the_act_for_every_violation(audited: dict[str, object]) -> None:
    artifacts: dict[str, Path] = audited["artifacts"]  # type: ignore[assignment]
    document = orjson.loads(artifacts["audit.json"].read_bytes())
    assert document["summary"]["with_violations"] == 2
    by_rule = document["summary"]["violations_by_rule"]
    assert by_rule["R-WATER-TREE-001"] == 1
    assert by_rule["R-BLD-TREE-001"] == 1
    with artifacts["audit.csv"].open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter=";"))
    failed = [row for row in rows if row["outcome"] == "fail"]
    assert failed
    for row in failed:
        assert row["act_id"] in {"SP42_13330_2016", "PP743"}
        assert row["clause"]
        assert row["quote"]
        assert float(row["shortfall_m"]) > 0
        assert row["type_basis"]
    assert {row["number"] for row in rows} == {str(n) for n in range(1, PLANTINGS + 1)}
    text = artifacts["audit.md"].read_text(encoding="utf-8")
    assert "Посадок с нарушением отступов | 2 (нарушений 2)" in text
    assert "до водопровода до наружной стенки" in text


def test_root_barrier_profile_turns_the_pipe_violation_into_a_condition(tmp_path: Path) -> None:
    report = _audit(tmp_path, profile="barriers")
    near_pipe = _at(report, NEAR_PIPE)
    assert near_pipe.violations == ()
    assert [c.rule_id for c in near_pipe.with_barrier] == ["R-WATER-TREE-001"]
    assert _at(report, NEAR_HOUSE).violations  # здание барьером не лечится
    assert report.summary()["only_with_root_barrier"] >= 1


def test_missing_layers_and_bad_patterns_are_refused(tmp_path: Path) -> None:
    source = tmp_path / "street.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load("strict", {})
    with pytest.raises(InputError, match="в чертеже нет"):
        container.audit.execute(
            AuditRequest("a", source, tmp_path / "o1", "strict", params, planting_layers=PATTERN)
        )
    with pytest.raises(InputError, match="некорректен"):
        container.audit.execute(
            AuditRequest("b", source, tmp_path / "o2", "strict", params, planting_layers="(")
        )


def test_our_own_plan_passes_the_audit(tmp_path: Path) -> None:
    """Генератор и нормоконтроль обязаны сходиться: план сервиса не даёт ни одного нарушения.

    На Берзарина расхождение было: 10 деревьев ровно в 2,000 м от борта после записи в DXF
    отличались от нормы на доли микрона, и допуск 1e-6 делал их нарушением."""
    source = tmp_path / "street.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load("strict", {"max_rejections": 50})
    generated = container.use_case.execute(
        PlanRequest("plan", source, tmp_path / "plan", "strict", params)
    )
    assert len(generated.plan.placements) >= 10
    report = container.audit.execute(
        AuditRequest(
            "self",
            generated.output_dxf,
            tmp_path / "audit",
            "strict",
            params,
            planting_layers=r"^GREEN_(TREES|SHRUBS)",
            shrub_layers=r"^GREEN_SHRUBS",
        )
    )
    assert len(report.plantings) == len(generated.plan.placements)
    assert report.summary()["with_violations"] == 0
    assert report.integrity.ok
