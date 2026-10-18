"""Сводка распознавания слоёв: сколько объектов решено правилом, знаком, словами, геометрией.

Чекпоинт 16.10.2026, п. 2: жюри видело отброшенное, но не видело почему. Сводка лежит в
classification.json и показывает имена, которые сервис угадал по геометрии или слабому намёку.
"""

from __future__ import annotations

from green.application.classification import (
    ClassificationGroup,
    ClassificationReport,
    recognition_summary,
)
from green.domain.objects import ClassificationEvidence, ObjectClass

C = ObjectClass


def _g(layer: str, cls: ObjectClass, method: str, n: int) -> ClassificationGroup:
    return ClassificationGroup(
        layer, None, "LineString", cls, ClassificationEvidence(method), n, (), 0.0
    )


REPORT = ClassificationReport(
    source_sha256="x",
    layer_map_fingerprint="y",
    features=164,
    unresolved_features=2,
    groups=(
        _g("Водопровод", C.UTILITY_WATER, "name_rule", 100),
        _g("Знак", C.EXISTING_TREE, "symbol_point:DEREVO", 7),
        _g("ДВ_Газон", C.LAWN, "inferred_name:газон", 20),
        _g("Покрытия", C.SIDEWALK, "inferred_weak:покрыти", 5),
        _g("Слой_0", C.CONTOUR, "assumed_geometry:contour", 30),
        _g("Непонятное", C.UNKNOWN, "unmatched", 2),
    ),
    rules=(),
    unused_overrides=(),
)


def test_counts_by_how_the_class_was_decided() -> None:
    summary = recognition_summary(REPORT)
    assert summary["by_name_rule"] == 100
    assert summary["by_symbol"] == 7
    assert summary["by_words"] == 20
    assert summary["by_weak_hint"] == 5
    assert summary["by_geometry_only"] == 30
    assert summary["unresolved"] == 2
    assert summary["total"] == 164


def test_guessed_names_are_listed_largest_first() -> None:
    guessed = recognition_summary(REPORT)["guessed"]
    assert [(g["layer"], g["features"]) for g in guessed] == [
        ("Слой_0", 30),
        ("Покрытия", 5),
        ("Непонятное", 2),
    ]
    assert guessed[0]["method"] == "assumed_geometry:contour"


def test_sheet_furniture_and_callouts_have_their_own_lines() -> None:
    """Ревью 18.10.2026: оформление листа и выноски (десятки тысяч объектов на улицу) уходили
    в «прочее», и жюри видело растущий непонятный остаток."""
    report = ClassificationReport(
        source_sha256="x",
        layer_map_fingerprint="y",
        features=17,
        unresolved_features=0,
        groups=(
            _g("!ВН_ССЫЛ_ИТП", C.IGNORE, "sheet_furniture:text_strokes", 9),
            _g("Кабель связи", C.IGNORE, "callout_leader:12345678:00000000:s", 5),
            _g("Кабель связи", C.IGNORE, "callout_annotation:12345678:00000000:s", 2),
            _g("Кабель связи", C.UTILITY_TELECOM, "callout_candidate:12345678:00000000:s", 1),
        ),
        rules=(),
        unused_overrides=(),
    )
    summary = recognition_summary(report)
    assert summary["sheet_furniture"] == 9
    assert summary["callouts"] == 8
    assert summary["other"] == 0
