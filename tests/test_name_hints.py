"""Подсказки LLM по именам слоёв: только подсказка, классы плана не меняются.

Пользователь 17.10.2026: имена, которые не поняли ни правила, ни словарь, ни модель имён,
показать LLM - «только как подсказка, не больше». Здесь проверяется отбор имён, сведение ответа
к классам и то, что план от подсказки не зависит. Качество ответа самой модели здесь не
проверяется: живой прогон - tools/research/ml/llm_hints_smoke.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from green.application.classification import ClassificationGroup, ClassificationReport
from green.application.name_hints import hint_candidates, name_hints
from green.domain.objects import ClassificationEvidence, ObjectClass

if TYPE_CHECKING:
    from collections.abc import Sequence


def _group(layer: str, method: str, cls: ObjectClass, n: int = 5, block: str | None = None):  # noqa: ANN202
    return ClassificationGroup(
        layer=layer,
        block=block,
        geometry="LineString",
        object_class=cls,
        evidence=ClassificationEvidence(method=method),
        features=n,
        source_refs=(),
        max_geometry_error_m=None,
    )


REPORT = ClassificationReport(
    source_sha256="x",
    layer_map_fingerprint="y",
    features=40,
    unresolved_features=0,
    groups=(
        _group("Наружное освещение", "assumed_geometry", ObjectClass.CONTOUR, 26),
        _group("Наружное освещение", "assumed_geometry", ObjectClass.OBSTACLE, 4),
        _group("ПЕШ.переход Сущ", "assumed_geometry", ObjectClass.CONTOUR, 7),
        _group("0", "assumed_geometry", ObjectClass.CONTOUR, 900),
        _group("Вн.ссылка_Первомайская", "assumed_geometry", ObjectClass.CONTOUR, 500),
        _group("Level 41", "assumed_geometry", ObjectClass.CONTOUR, 3),
        _group("Газон", "name_rule", ObjectClass.LAWN, 50),
        _group("Борт", "inferred_name:борт", ObjectClass.CURB, 20),
    ),
    rules=(),
    unused_overrides=(),
)


class Scripted:
    """Ответ модели задан заранее: номер имени -> класс и уверенность."""

    model = "scripted"

    def __init__(self, answers: dict[str, tuple[str | None, float]]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    def suggest(self, names: Sequence[str]) -> list[tuple[str | None, float]]:
        self.asked.extend(names)
        return [self.answers.get(n, (None, 0.0)) for n in names]


def test_only_names_resolved_by_geometry_with_meaning_are_asked() -> None:
    names = [c.name for c in hint_candidates(REPORT)]
    assert names == ["Наружное освещение", "ПЕШ.переход Сущ"]


def test_candidate_carries_objects_and_current_classes() -> None:
    first = hint_candidates(REPORT)[0]
    assert first.features == 30
    assert first.current == {"contour": 26, "obstacle": 4}


def test_hint_is_kept_only_when_it_differs_and_is_confident() -> None:
    hinter = Scripted(
        {
            "Наружное освещение": ("utility.power_cable", 0.9),
            "ПЕШ.переход Сущ": ("contour", 0.9),  # совпадает с нынешним - не подсказка
        }
    )
    hints = name_hints(REPORT, hinter)
    assert [(h.name, h.suggestion) for h in hints] == [
        ("Наружное освещение", "utility.power_cable")
    ]
    assert hints[0].model == "scripted"
    assert hints[0].features == 30


def test_unknown_or_unconfident_answer_is_not_a_hint() -> None:
    hinter = Scripted({"Наружное освещение": ("pole", 0.3), "ПЕШ.переход Сущ": (None, 0.9)})
    assert name_hints(REPORT, hinter) == ()


def test_answer_outside_the_class_list_is_dropped() -> None:
    hinter = Scripted({"Наружное освещение": ("streetlight", 0.95)})
    assert name_hints(REPORT, hinter) == ()


def test_limit_takes_the_names_with_most_objects() -> None:
    hinter = Scripted({})
    name_hints(REPORT, hinter, limit=1)
    assert hinter.asked == ["Наружное освещение"]


def test_hint_never_drops_a_network_or_a_surface_into_annotation() -> None:
    """Живой прогон 17.10.2026: qwen3:8b отправлял в «оформление» слои сетей «ЭН_КМВ_удс»
    (силовой кабель по слабому намёку). Подсказка «ignore» допустима только для того, что
    сервис и так считал линией без смысла или препятствием."""
    report = ClassificationReport(
        source_sha256="x",
        layer_map_fingerprint="y",
        features=10,
        unresolved_features=0,
        groups=(
            _group("ЭН_КМВ_удс", "inferred_weak:эн", ObjectClass.UTILITY_POWER, 5),
            _group("Съемка LEG21", "assumed_geometry", ObjectClass.CONTOUR, 5),
        ),
        rules=(),
        unused_overrides=(),
    )
    hinter = Scripted({"ЭН_КМВ_удс": ("ignore", 0.95), "Съемка LEG21": ("ignore", 0.95)})
    assert [h.name for h in name_hints(report, hinter)] == ["Съемка LEG21"]


def test_hint_is_attached_to_every_group_of_its_name_in_classification_json() -> None:
    """Подсказка показывается в таблице страницы уточнения: она лежит в строке группы."""
    from dataclasses import replace  # noqa: PLC0415

    from green.application.name_hints import NameHint  # noqa: PLC0415
    from green.infrastructure.reports.artifacts import classification_payload  # noqa: PLC0415

    report = replace(
        REPORT,
        groups=(
            _group("ПЕШ.переход", "assumed_geometry:contour", ObjectClass.CONTOUR, 7),
            _group("ПЕШ.переход", "assumed_geometry:point", ObjectClass.IGNORE, 2),
            _group("Газон", "name_rule", ObjectClass.LAWN, 4),
        ),
    )
    hint = NameHint("ПЕШ.переход", 9, {"contour": 9}, "ignore", 0.9, "qwen3:8b")
    groups = classification_payload(report, (hint,))["groups"]
    assert groups[0]["llm_hint"] == {"suggestion": "ignore", "confidence": 0.9, "model": "qwen3:8b"}
    assert groups[1]["llm_hint"]["suggestion"] == "ignore"
    assert "llm_hint" not in groups[2]


def test_classification_json_without_hints_has_no_hint_fields() -> None:
    from green.infrastructure.reports.artifacts import classification_payload  # noqa: PLC0415

    assert all("llm_hint" not in g for g in classification_payload(REPORT)["groups"])
