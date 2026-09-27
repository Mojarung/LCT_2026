"""A reference to grass in a work description does not establish present soil."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Point, box

from green.application.classification import classification_report, classify_scene
from green.application.params import PlanParams
from green.application.surfaces import Material, build_surface_map
from green.domain.objects import Feature, ObjectClass, Scene, SourceRef
from green.infrastructure.config.repositories import YamlLayerMapSource

RULES = YamlLayerMapSource(Path(__file__).resolve().parents[1] / "config/layer_map.yaml").load()

# Real naming patterns plus unseen negation/removal formulations. The desired
# answer is review, not an invented interpretation of the construction phase.
AMBIGUOUS = (
    "ДВ_ПП_Тип7_ТРОТ за ГАЗОН",
    "ДВ_ПП_Тип4_ПЧ за газон",
    "ДВ_АКР_Лестница за газон",
    "ДВ_ПП_ДО_Тип3_Устройство_уширений_магистральные_на месте газона",
    "ДВ_ПП_ДО_Тип7_Устройство_трот_менее_3м_газон уничтож",
    "ДВ_ПП_П_Газон новый на ПР Ч",
    "ДВ_ПП_Газон_Восстановление",
    "ДВ_ПП_Газон_У за счет ПЧ",
    "ДВ_ПП_Газон_Р",
    "ДВ_ГП_П_Газон_Рулонный",
    "Газон под демонтаж",
    "Не газон",
    "Газон проектируемый",
    "Устройство газона",
)


def raw(layer: str, *, block: str | None = None) -> Scene:
    return Scene(
        "sample.dxf",
        "sha",
        "AC1032",
        (Feature(SourceRef("12345678", "00000000", "A"), layer, box(0, 0, 20, 20), block),),
    )


# Режим проверки тиммейта: стадию проекта выбирает человек, до этого - уточнение.
VERIFIED = PlanParams(infer_unknown=False)
# Стадия «по проекту» (вопрос 2 пользователя, 25.09.2026): новое покрытие - до «за», «за
# счёт», «на месте»; снимаемое и отрицаемое грунтом не становится.
NOT_SOIL_IN_PROJECT = {
    "ДВ_ПП_Тип7_ТРОТ за ГАЗОН": ObjectClass.SIDEWALK,
    "ДВ_ПП_Тип4_ПЧ за газон": ObjectClass.ROAD,
    "ДВ_АКР_Лестница за газон": ObjectClass.STRUCTURE,
    "ДВ_ПП_ДО_Тип3_Устройство_уширений_магистральные_на месте газона": ObjectClass.ROAD,
    "ДВ_ПП_ДО_Тип7_Устройство_трот_менее_3м_газон уничтож": ObjectClass.SIDEWALK,
    "Газон под демонтаж": ObjectClass.IGNORE,
    "Не газон": ObjectClass.CONTOUR,
}
NEW_LAWN_IN_PROJECT = tuple(name for name in AMBIGUOUS if name not in NOT_SOIL_IN_PROJECT)


def _soil_at_centre(scene: Scene) -> bool:
    surface = build_surface_map(scene.features, scene.labels, box(0, 0, 20, 20), 0.5)
    return (
        surface is not None
        and surface.material(np.array([Point(10, 10)], dtype=object))[0] == Material.SOIL
    )


@pytest.mark.parametrize("layer", AMBIGUOUS)
def test_work_and_transition_names_cannot_establish_soil_in_verified_mode(layer: str) -> None:
    scene, _ = classify_scene(raw(layer), RULES, VERIFIED)
    report = classification_report(scene, RULES, VERIFIED)
    assert scene.features[0].object_class is not ObjectClass.LAWN
    assert not report.ready
    assert not _soil_at_centre(scene)


@pytest.mark.parametrize(("layer", "expected"), NOT_SOIL_IN_PROJECT.items())
def test_project_stage_takes_the_new_material_and_never_soil_for_it(
    layer: str, expected: ObjectClass
) -> None:
    scene, _ = classify_scene(raw(layer), RULES, PlanParams())
    assert scene.features[0].object_class is expected
    assert classification_report(scene, RULES, PlanParams()).ready
    assert not _soil_at_centre(scene)


@pytest.mark.parametrize("layer", NEW_LAWN_IN_PROJECT)
def test_new_lawn_of_the_project_is_planting_ground(layer: str) -> None:
    """Газон проектировщика - грунт посадки: сажаем по проекту (решение пользователя)."""
    scene, _ = classify_scene(raw(layer), RULES, PlanParams())
    assert scene.features[0].object_class is ObjectClass.LAWN
    assert scene.features[0].classification.method.startswith("inferred_name:")
    assert _soil_at_centre(scene)


@pytest.mark.parametrize("layer", ["Газон", "ДВ_ГП_СУЩ_ГАЗОН", "Леса и газоны", "Газон Сохранение"])
def test_plain_existing_material_names_still_work(layer: str) -> None:
    scene, _ = classify_scene(raw(layer), RULES)
    assert scene.features[0].object_class is ObjectClass.LAWN


def test_explicit_per_input_assignment_resolves_phase_and_keeps_name_evidence() -> None:
    layer = "ДВ_ПП_Газон_У за счет ПЧ"
    scene, _ = classify_scene(raw(layer), RULES, PlanParams(layer_classes={layer: "lawn"}))
    report = classification_report(scene, RULES)
    assert report.ready
    assert scene.features[0].classification.method == "explicit_layer"
    assert scene.features[0].classification.matched_rules


def test_xref_filename_is_not_a_construction_phase() -> None:
    scene, _ = classify_scene(raw("Проектируемый газон|Газон"), RULES)
    assert scene.features[0].object_class is ObjectClass.LAWN


def test_named_parent_block_can_disqualify_positive_lawn() -> None:
    scene, _ = classify_scene(raw("Газон", block="Демонтаж покрытий"), RULES, VERIFIED)
    assert scene.features[0].object_class is ObjectClass.UNKNOWN
    assert scene.features[0].classification.method == "material_context"
    # По проекту снимаемое не становится грунтом: блок «Демонтаж покрытий» - снос.
    scene, _ = classify_scene(raw("Газон", block="Демонтаж покрытий"), RULES, PlanParams())
    assert scene.features[0].object_class is ObjectClass.IGNORE
    assert scene.features[0].classification.method.startswith("inferred_removed:")
