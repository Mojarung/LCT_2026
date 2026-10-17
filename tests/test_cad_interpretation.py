"""Regression cases for numbered layers, exploded callouts and review decisions."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from shapely.affinity import rotate
from shapely.geometry import LineString, Point, box
from test_shrub_strips import drawing

from green.application.callouts import recognise_callouts
from green.application.classification import (
    ClassificationError,
    classification_report,
    classify_scene,
    recognition_summary,
    require_classified,
)
from green.application.constraints import ConstraintIndex
from green.application.params import PlanParams
from green.domain.objects import Feature, ObjectClass, Scene, SourceRef, TextLabel
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource, YamlRuleBookSource

ROOT = Path(__file__).resolve().parents[1]
LAYERS = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()


def feature(handle: str, coords: list, layer: str = "Кабель связи") -> Feature:
    return Feature(SourceRef("12345678", "00000000", handle), layer, LineString(coords))


def motif() -> Scene:
    return Scene(
        "callout.dxf",
        "a" * 64,
        "AC1032",
        (
            feature("shaft", [(10, 0), (8, 2), (0, 2)]),
            feature("left", [(10, 0), (9.2, 0.3)]),
            feature("right", [(10, 0), (9.7, 0.8)]),
        ),
        (
            TextLabel(
                SourceRef("12345678", "00000000", "text"), "Кабель связи", 0, 2.5, "каб. кол."
            ),
        ),
    )


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("08TREE", ObjectClass.EXISTING_TREE),
        ("05STOLB", ObjectClass.POLE),
        ("DOROGA", ObjectClass.ROAD),
        ("DOM", ObjectClass.BUILDING),
        ("ZABOR", ObjectClass.FENCE),
        ("other$0$08TREE", ObjectClass.EXISTING_TREE),
    ],
)
def test_numbered_names_and_transliteration(name: str, kind: ObjectClass) -> None:
    source = replace(
        motif(),
        features=(
            replace(
                feature("1", [(0, 0), (2, 0)], name),
                geometry=box(0, 0, 5, 5),
                source_entity_type="LWPOLYLINE",
            ),
        ),
        labels=(),
    )
    result, _ = classify_scene(source, LAYERS, PlanParams(name_model=False))
    assert result.features[0].object_class is kind
    assert result.features[0].layer == name
    if kind in {ObjectClass.BUILDING, ObjectClass.ROAD}:
        assert result.features[0].geometry.area == 25
    if kind is ObjectClass.FENCE:
        assert result.features[0].geometry.area == 0


@pytest.mark.parametrize("name", ["1072KR", "X08TREEZ", "05STOLBxyz", "DOMESTIC"])
def test_opaque_codes_do_not_gain_numbered_word_meaning(name: str) -> None:
    assert LAYERS.vocabulary.infer(name) is None


def test_callout_is_preserved_but_stops_producing_cable_clearance() -> None:
    source = motif()
    result, _ = classify_scene(source, LAYERS)
    assert len(result.callouts) == 1
    assert result.callouts[0].certain
    assert all(f.object_class is ObjectClass.IGNORE for f in result.features)
    assert [f.geometry.wkt for f in result.features] == [f.geometry.wkt for f in source.features]
    assert result.labels[0].text == source.labels[0].text
    rules = YamlRuleBookSource(ROOT / "config/acts.yaml", ROOT / "config/rules.yaml").load()
    rule = rules.rule("R-TELECOM-TREE-001")
    probe = np.array([Point(4, 2)], dtype=object)
    wrong = tuple(replace(f, object_class=ObjectClass.UTILITY_TELECOM) for f in source.features)
    before = ConstraintIndex(wrong, [rule], require_utility_data=False).evaluate(probe)
    after = ConstraintIndex(result.features, [rule], require_utility_data=False).evaluate(probe)
    assert before.checks(0)[0].outcome.value == "fail"
    assert after.checks(0)[0].outcome.value == "no_data"
    assert after.verdict(0).value != "allowed"


def test_real_pontryagina_motif() -> None:
    source = Scene(
        "real.dxf",
        "a" * 64,
        "AC1027",
        (
            feature(
                "C107",
                [
                    (92.42799999994844, -14070.793),
                    (90.59218478957489, -14067.6187226783),
                    (84.68941526535845, -14067.49818973357),
                ],
            ),
            feature(
                "C108", [(92.42799999994784, -14070.793), (92.19383500221744, -14069.88875058538)]
            ),
            feature(
                "C109", [(92.42799999994784, -14070.793), (91.7610072653722, -14070.13907267833)]
            ),
        ),
        (
            TextLabel(
                SourceRef("12345678", "00000000", "C10A"),
                "Кабель связи",
                84.71901774000357,
                -14066.04848993931,
                "каб. кол.",
            ),
        ),
    )
    assert recognise_callouts(source)[0].certain


def test_continuation_and_competing_labels_require_review() -> None:
    source = motif()
    cable = feature("cable", [(10, 0), (15, -2)])
    result, _ = classify_scene(replace(source, features=(*source.features, cable)), LAYERS)
    assert not result.callouts[0].certain
    assert result.features[-1].object_class is ObjectClass.UTILITY_TELECOM
    report = classification_report(result, LAYERS)
    assert report.review_required_features == 3
    with pytest.raises(ClassificationError):
        require_classified(report, PlanParams(require_reviewed_objects=True))
    other = replace(source.labels[0], ref=replace(source.labels[0].ref, handle="text2"))
    assert not recognise_callouts(replace(source, labels=(*source.labels, other)))[0].certain


def test_nearby_real_cable_remains_a_cable() -> None:
    source = motif()
    cable = feature("real", [(3, -5), (3, 5)])
    result, _ = classify_scene(replace(source, features=(*source.features, cable)), LAYERS)
    assert result.callouts[0].certain
    assert result.features[-1].object_class is ObjectClass.UTILITY_TELECOM


def test_rotation_missing_text_and_different_xrefs() -> None:
    source = motif()
    angle = 53
    point = rotate(Point(source.labels[0].x, source.labels[0].y), angle, origin=(0, 0))
    turned = replace(
        source,
        features=tuple(
            replace(f, geometry=rotate(f.geometry, angle, origin=(0, 0))) for f in source.features
        ),
        labels=(replace(source.labels[0], x=point.x, y=point.y),),
    )
    assert recognise_callouts(turned)[0].certain
    assert not recognise_callouts(replace(source, labels=()))
    assert not recognise_callouts(
        replace(
            source,
            labels=(
                replace(source.labels[0], ref=replace(source.labels[0].ref, xref_hash8="other")),
            ),
        )
    )


def test_manual_override_wins_over_automatic_exclusion() -> None:
    source = motif()
    result, _ = classify_scene(
        source, LAYERS, PlanParams(feature_classes={str(source.features[0].ref): "utility.telecom"})
    )
    assert result.features[0].object_class is ObjectClass.UTILITY_TELECOM
    assert result.features[0].classification.method == "explicit_feature"
    assert classification_report(result, LAYERS).review_required_features == 2


def test_fallbacks_remain_visible_until_confirmed() -> None:
    source = replace(motif(), features=(feature("opaque", [(0, 0), (1, 1)], "ZZ_7462"),), labels=())
    params = PlanParams(name_model=False)
    result, _ = classify_scene(source, LAYERS, params)
    report = classification_report(result, LAYERS, params)
    assert report.unresolved_features == 0
    assert report.review_required_features == 1
    assert not report.ready
    assert recognition_summary(report)["review_required"] == 1
    explicit = replace(params, feature_classes={str(source.features[0].ref): "contour"})
    result, _ = classify_scene(source, LAYERS, explicit)
    assert classification_report(result, LAYERS, explicit).ready


def test_review_assignment_applies_to_a_derived_strip(tmp_path: Path) -> None:
    path = tmp_path / "strip.dxf"
    drawing(path)
    raw = EzdxfSceneReader().read(path)
    first, _ = classify_scene(raw, LAYERS)
    strip = next(f for f in first.features if f.source_entity_type == "SHRUB_STRIP")
    reviewed, _ = classify_scene(
        raw, LAYERS, PlanParams(feature_classes={str(strip.ref): "ignore"})
    )
    assigned = next(f for f in reviewed.features if f.ref == strip.ref)
    assert assigned.object_class is ObjectClass.IGNORE
    assert assigned.classification.method == "explicit_feature"
