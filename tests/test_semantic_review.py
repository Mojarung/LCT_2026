"""Unseen CAD names must not silently become safe geometry."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import ezdxf
import orjson
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point, box
from test_audit import PATTERN, _designed

from green.application.audit import AuditRequest
from green.application.classification import (
    ClassificationError,
    LayerMap,
    LayerRule,
    MatchTarget,
    classification_report,
    classify_scene,
    require_classified,
)
from green.application.errors import InputError
from green.application.params import PlanParams
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.domain.objects import Feature, ObjectClass, Scene, SourceRef
from green.infrastructure.config.repositories import YamlLayerMapSource
from green.interfaces.api.app import API_PREFIX, create_app
from green.interfaces.cli.main import run as cli_run

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

ROOT = Path(__file__).resolve().parents[1]
RULES = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()
# Режим проверки тиммейта: незнакомое не выводится по словам, а останавливает прогон.
# По умолчанию (задача 14) незнакомое выводится - эти тесты проверяют механизм уточнения.
VERIFIED = PlanParams(infer_unknown=False)


def feature(layer: str, *, block: str | None = None) -> Feature:
    return Feature(SourceRef("12345678", "00000000", "AB"), layer, Point(2, 3), block)


@pytest.mark.parametrize(
    "layer",
    [
        "0",
        "Layer1",
        "Грунты",
        "0_геоподоснова",
        "11 Ограждения",
        "Defpoints",
        "PDF_4",
        "point0",
        "line0",
        "Не печать",
    ],
)
def test_generic_or_spatial_names_are_not_ignored(layer: str) -> None:
    assert RULES.classify(feature(layer)) is not ObjectClass.IGNORE


@pytest.mark.parametrize("prefix", ["Газон|", "Водопровод$0$", "a|Борт$17$"])
def test_xref_filename_does_not_supply_semantics(prefix: str) -> None:
    assert RULES.classify(feature(prefix + "Здания")) is ObjectClass.BUILDING
    assert RULES.classify(feature(prefix + "layer_837")) is ObjectClass.UNKNOWN


def test_equally_supported_different_classes_require_review() -> None:
    assert RULES.classify(feature("Газон Водопровод")) is ObjectClass.UNKNOWN


def test_unicode_normalization_preserves_meaning() -> None:
    layer = unicodedata.normalize("NFD", "Железные дороги")
    custom = LayerMap(
        (LayerRule(re.compile("й"), MatchTarget.LAYER, ObjectClass.ROAD, confirmed=True),), "x"
    )
    assert custom.classify(feature(unicodedata.normalize("NFD", "й"))) is ObjectClass.ROAD
    assert RULES.classify(feature(layer)) is ObjectClass.RAILWAY


def scene(*features: Feature) -> Scene:
    return Scene("test.dxf", "sha", "AC1032", features)


@pytest.mark.parametrize("geometry", [Point(2, 3), LineString([(0, 0), (5, 5)]), box(0, 0, 5, 5)])
def test_every_unresolved_geometry_type_blocks_strict_planning(geometry: BaseGeometry) -> None:
    source = scene(replace(feature("unknown"), geometry=geometry))
    classified, _ = classify_scene(source, RULES, VERIFIED)
    report = classification_report(classified, RULES, VERIFIED)
    assert report.unresolved_features == 1
    assert report.groups[0].evidence.method == "unmatched"
    with pytest.raises(ClassificationError) as caught:
        require_classified(report, VERIFIED)
    assert caught.value.report is report
    require_classified(report, replace(VERIFIED, require_known_objects=False))


@pytest.mark.parametrize(
    ("geometry", "radius", "expected", "method"),
    [
        (Point(2, 3), None, ObjectClass.IGNORE, "assumed_geometry:point"),
        (Point(2, 3).buffer(0.3), 0.3, ObjectClass.OBSTACLE, "assumed_geometry:small_circle"),
        (LineString([(0, 0), (5, 5)]), None, ObjectClass.CONTOUR, "assumed_geometry:contour"),
        (box(0, 0, 5, 5), None, ObjectClass.CONTOUR, "assumed_geometry:contour"),
        # Рамка листа: прямоугольник и отрезок строго по осям от 100 м - не контур.
        (box(0, 0, 250, 400), None, ObjectClass.IGNORE, "assumed_geometry:sheet_frame"),
        (LineString([(0, 0), (0, 400)]), None, ObjectClass.IGNORE, "assumed_geometry:sheet_frame"),
        (LineString([(0, 0), (1, 400)]), None, ObjectClass.CONTOUR, "assumed_geometry:contour"),
        (LineString([(0, 0), (0, 40)]), None, ObjectClass.CONTOUR, "assumed_geometry:contour"),
    ],
)
def test_unknown_geometry_is_replaced_carefully_by_default(
    geometry: BaseGeometry, radius: float | None, expected: ObjectClass, method: str
) -> None:
    """Задача 14: слов нет - осторожная замена по геометрии, прогон не останавливается."""
    source = scene(replace(feature("unknown"), geometry=geometry, circle_radius_m=radius))
    classified, _ = classify_scene(source, RULES, PlanParams())
    report = classification_report(classified, RULES, PlanParams())
    assert report.ready
    assert classified.features[0].object_class is expected
    assert report.groups[0].evidence.method == method
    if expected is ObjectClass.CONTOUR:
        assert classified.features[0].geometry.geom_type in {"LineString", "LinearRing"}


def test_conflict_has_both_causes_and_is_not_order_dependent() -> None:
    for rules in (RULES, replace(RULES, rules=tuple(reversed(RULES.rules)))):
        classified, _ = classify_scene(scene(feature("Газон Водопровод")), rules, VERIFIED)
        report = classification_report(classified, rules, VERIFIED)
        evidence = report.groups[0].evidence
        assert evidence.method == "conflict"
        assert {rules.rules[i].object_class for i in evidence.chosen_rules} == {
            ObjectClass.LAWN,
            ObjectClass.UTILITY_WATER,
        }
        assert not report.ready


def test_explicit_mapping_resolves_conflict_and_preserves_automatic_evidence() -> None:
    params = PlanParams(layer_classes={"ГАЗОН ВОДОПРОВОД": "utility.water"})
    classified, _ = classify_scene(scene(feature("Газон Водопровод")), RULES, params)
    report = classification_report(classified, RULES, params)
    require_classified(report, params)
    entry = report.groups[0]
    assert entry.object_class is ObjectClass.UTILITY_WATER
    assert entry.evidence.method == "explicit_layer"
    assert entry.evidence.matched_rules
    assert not entry.evidence.chosen_rules
    assert entry.evidence.override_key == "ГАЗОН ВОДОПРОВОД"


def test_explicit_precedence_and_qualified_names_are_exact() -> None:
    f = feature("soil|0", block="symbol")
    params = replace(
        VERIFIED,
        layer_classes={"soil|0": "lawn"},
        block_classes={"symbol": "pole"},
        feature_classes={str(f.ref): "utility.water"},
    )
    classified, _ = classify_scene(scene(f), RULES, params)
    report = classification_report(classified, RULES, params)
    assert report.ready
    assert classified.features[0].object_class is ObjectClass.UTILITY_WATER
    params = replace(params, feature_classes={})
    classified, _ = classify_scene(scene(f), RULES, params)
    assert classified.features[0].object_class is ObjectClass.POLE
    params = replace(params, block_classes={})
    classified, _ = classify_scene(scene(f, replace(f, layer="paved|0")), RULES, params)
    assert [f.object_class for f in classified.features] == [ObjectClass.LAWN, ObjectClass.UNKNOWN]


def test_named_block_overrides_layer_and_retains_both_rules() -> None:
    classified, _ = classify_scene(scene(feature("Водопровод", block="люк")), RULES)
    report = classification_report(classified, RULES)
    group = report.groups[0]
    assert group.object_class is ObjectClass.UTILITY_ACCESS
    assert len(group.evidence.matched_rules) > len(group.evidence.chosen_rules)
    assert all(RULES.rules[i].target is MatchTarget.BLOCK for i in group.evidence.chosen_rules)


@pytest.mark.parametrize("values", [{"й": "lawn", "й": "road"}, {"": "lawn"}, {"0": "misspelling"}])
def test_invalid_and_canonically_duplicate_mappings_fail(values: dict[str, str]) -> None:
    with pytest.raises(InputError):
        classify_scene(scene(feature("0")), RULES, PlanParams(layer_classes=values))


def test_unused_override_rejects_even_exploratory_runs() -> None:
    params = PlanParams(layer_classes={"typo": "lawn"}, require_known_objects=False)
    classified, _ = classify_scene(scene(feature("0")), RULES, params)
    report = classification_report(classified, RULES, params)
    assert report.unused_overrides == ("layer_classes:typo",)
    with pytest.raises(ClassificationError):
        require_classified(report, params)


def test_unknown_utility_rule_is_not_claimed_as_resolved() -> None:
    classified, _ = classify_scene(scene(feature("Топливопровод")), RULES, VERIFIED)
    report = classification_report(classified, RULES, VERIFIED)
    assert report.groups[0].evidence.method == "name_rule"
    assert not report.ready


def test_unknown_utility_is_resolved_with_the_largest_utility_offset_by_default() -> None:
    """Задача 14: сеть неизвестного типа не останавливает прогон - правила R-UTILUNK дают ей
    наибольший отступ из отступов подземных сетей (2 м дерево, 1 м кустарник)."""
    classified, _ = classify_scene(scene(feature("Топливопровод")), RULES, PlanParams())
    report = classification_report(classified, RULES, PlanParams())
    assert classified.features[0].object_class is ObjectClass.UTILITY_UNKNOWN
    assert report.ready


def test_samples_are_bounded_but_counts_are_complete() -> None:
    features = tuple(
        replace(feature("0"), ref=SourceRef("12345678", "00000000", str(i))) for i in range(1000)
    )
    classified, _ = classify_scene(scene(*features), RULES, VERIFIED)
    report = classification_report(classified, RULES, VERIFIED)
    assert report.features == report.unresolved_features == report.groups[0].features == 1000
    assert len(report.groups[0].source_refs) == 5


def unknown_input(path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.units = 6
    doc.modelspace().add_circle((0, 0), 10)
    doc.saveas(path)


def test_pipeline_stops_before_overwriting_previous_result(tmp_path: Path) -> None:
    source = tmp_path / "source.dxf"
    unknown_input(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    output = tmp_path / "out"
    output.mkdir()
    result = output / "result.dxf"
    result.write_bytes(b"previous result")
    with pytest.raises(ClassificationError):
        container.use_case.execute(PlanRequest("x", source, output, "strict", VERIFIED))
    assert result.read_bytes() == b"previous result"


def test_api_failure_preserves_downloadable_review_and_explicit_rerun(tmp_path: Path) -> None:
    source = tmp_path / "source.dxf"
    unknown_input(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    with TestClient(create_app(container)) as client:

        def upload(overrides: dict) -> dict:
            response = client.post(
                f"{API_PREFIX}/runs",
                files={"file": ("source.dxf", source.read_bytes(), "image/vnd.dxf")},
                data={"profile": "strict", "overrides": orjson.dumps(overrides).decode()},
            )
            assert response.status_code == 202
            return client.get(response.headers["Location"]).json()

        failed = upload({"infer_unknown": False})
        assert failed["state"] == "failed"
        review = client.get(f"{API_PREFIX}/runs/{failed['id']}/artifacts/classification.json")
        assert review.status_code == 200
        assert review.json()["unresolved_features"] == 1
        assert not review.json()["ready"]
        assert (
            client.get(f"{API_PREFIX}/runs/{failed['id']}/artifacts/result.dxf").status_code == 404
        )
        # Exact full-name override; this synthetic shape is only a work boundary.
        succeeded = upload(
            {
                "infer_unknown": False,
                "layer_classes": {"0": "work_boundary"},
                "placement_solver": "greedy",
            }
        )
        assert succeeded["state"] == "succeeded", succeeded
        assert succeeded["summary"]["semantic_assignments_complete"] is True


def test_cli_failure_writes_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.dxf"
    unknown_input(source)
    monkeypatch.setenv("GREEN_CONFIG_DIR", str(ROOT / "config"))
    with pytest.raises(ClassificationError):
        cli_run(source, profile="strict", out=tmp_path / "out", set_=("infer_unknown=false",))
    assert (
        orjson.loads((tmp_path / "out/classification.json").read_bytes())["unresolved_features"]
        == 1
    )


def test_audit_in_verified_mode_stops_on_unknown(tmp_path: Path) -> None:
    source = tmp_path / "source.dxf"
    _designed(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    with pytest.raises(ClassificationError):
        container.audit.execute(
            AuditRequest(
                "audit", source, tmp_path / "out", "strict", VERIFIED, planting_layers=PATTERN
            )
        )
    assert not (tmp_path / "out/audit.dxf").exists()


def test_ordinary_demo_runs_with_inferred_semantics(tmp_path: Path) -> None:
    """Задача 14: встроенный фрагмент не ждёт уточнения - незнакомое выведено по словам имени
    и осторожной заменой по геометрии, основание каждого вывода лежит в отчёте распознавания."""
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    with TestClient(create_app(container)) as client:
        created = client.post("/web/demo", follow_redirects=False)
        run_id = created.headers["location"].rsplit("/", 1)[-1]
        state = client.get(f"{API_PREFIX}/runs/{run_id}").json()
        assert state["state"] == "succeeded", state
        assert (container.store.run_dir(run_id) / "result.dxf").exists()
        report = client.get(f"{API_PREFIX}/runs/{run_id}/artifacts/classification.json").json()
        assert report["ready"]
        methods = {group["evidence"]["method"] for group in report["groups"]}
        assert any(m.startswith(("inferred_", "assumed_")) for m in methods)
