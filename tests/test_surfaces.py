"""Карта покрытий: где грунт, а где твёрдое покрытие площадок и дорожек."""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, box

from green.application.surfaces import Material, build_surface_map, label_material
from green.domain.objects import Feature, ObjectClass, SourceRef, TextLabel


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("А", Material.PAVED),
        ("ГАЗОН", Material.SOIL),
        ("ДЕТ.ПЛ.", Material.PAVED),
        ("СПОРТ ПЛ.", Material.PAVED),
        ("СПЕЦ.ПОКРЫТИЕ", Material.PAVED),
        ("СПЕЦ.ПОКР.", Material.PAVED),
        ("Газон рулонный", Material.SOIL),
        # «ж.б.» у трубы - не бетонное покрытие: короткие обозначения фразами не ищутся.
        ("d=400ж.б.", None),
        ("каб.", None),
    ],
)
def test_labels_name_the_material(text: str, expected: Material | None) -> None:
    assert label_material(text) is expected


def test_a_playground_inside_a_lawn_is_paved_not_soil() -> None:
    """Харьковская, 23.09.2026: контур «Граница площадки» был в ignore, подпись «ДЕТ.ПЛ.» не
    распознавалась, и грунт газона затекал на детскую площадку со спецпокрытием."""
    ref = SourceRef("f", "x", "1")
    lawn = box(0, 0, 40, 40)
    playground = box(10, 10, 20, 20)
    features = [
        Feature(ref, "Граница улицы", lawn.exterior, object_class=ObjectClass.PAVEMENT_EDGE),
        Feature(
            ref, "Граница площадки", playground.exterior, object_class=ObjectClass.PAVEMENT_EDGE
        ),
    ]
    labels = [
        TextLabel(ref, "Леса и газоны", 30.0, 30.0, "ГАЗОН"),
        TextLabel(ref, "Пояснительные подписи", 15.0, 15.0, "ДЕТ.ПЛ."),
    ]
    surface = build_surface_map(features, labels, lawn, 0.5)
    assert surface is not None
    inside, outside = shapely.points(np.array([(15.0, 12.0), (30.0, 5.0)]))
    assert surface.material(np.array([inside]))[0] == Material.PAVED
    assert surface.material(np.array([outside]))[0] == Material.SOIL


def test_a_paved_hatch_seeds_its_own_area() -> None:
    """Штриховка тротуара без подписи - тоже знание о покрытии: её середина - твёрдое."""
    ref = SourceRef("f", "x", "1")
    site = box(0, 0, 40, 40)
    walk = box(0, 18, 40, 22)
    features = [
        Feature(ref, "Граница улицы", site.exterior, object_class=ObjectClass.PAVEMENT_EDGE),
        Feature(ref, "ДВ_ПП_ДО_Тип9_Устройство_трот", walk, object_class=ObjectClass.SIDEWALK),
        Feature(
            ref, "край", LineString([(0, 18), (40, 18)]), object_class=ObjectClass.PAVEMENT_EDGE
        ),
        Feature(
            ref, "край", LineString([(0, 22), (40, 22)]), object_class=ObjectClass.PAVEMENT_EDGE
        ),
    ]
    labels = [TextLabel(ref, "Леса и газоны", 5.0, 5.0, "ГАЗОН")]
    surface = build_surface_map(features, labels, site, 0.5)
    assert surface is not None
    assert surface.material(np.array([shapely.Point(30.0, 20.0)]))[0] == Material.PAVED
