"""Карта покрытий: где грунт, а где твёрдое покрытие площадок и дорожек."""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, box

from green.application import surfaces
from green.application.surfaces import Material, build_surface_map, label_material
from green.domain.objects import ClassificationEvidence, Feature, ObjectClass, SourceRef, TextLabel


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


def test_functional_ground_playground_excludes_both_planting_kinds() -> None:
    ref = SourceRef("f", "x", "ground-playground")
    lawn = box(0, 0, 60, 40)
    playground = box(10, 10, 30, 25)
    features = [
        Feature(ref, "Леса и газоны", lawn, object_class=ObjectClass.LAWN),
        Feature(
            ref, "Граница площадки", playground.exterior, object_class=ObjectClass.PAVEMENT_EDGE
        ),
    ]
    labels = [
        TextLabel(
            ref,
            "Пояснительные подписи",
            15,
            15,
            "ДЕТ.ПЛ.",
            surface_role="ignore",
            surface_evidence=ClassificationEvidence("annotation_label"),
        ),
        TextLabel(ref, "Подписи", 25, 20, "ГРУНТ"),
        TextLabel(ref, "Подписи", 45, 20, "ГАЗОН"),
    ]
    surface = build_surface_map(features, labels, lawn, 0.5, inference_mode="hybrid")
    assert surface is not None
    inside = np.array([shapely.Point(20, 17)], dtype=object)
    outside = np.array([shapely.Point(45, 20)], dtype=object)
    assert surface.material(inside)[0] == Material.PAVED
    assert not surface.fits_soil(inside, 1.6)[0]  # дерево
    assert not surface.fits_soil(inside, 0.4)[0]  # кустарник
    assert surface.fits_soil(outside, 1.6)[0]
    assert surface.functional_reason(inside[0]) == "функциональная площадка: ДЕТ.ПЛ."


def test_functional_label_does_not_exclude_a_large_lawn() -> None:
    ref = SourceRef("f", "x", "large-lawn")
    lawn = box(0, 0, 100, 50)
    surface = build_surface_map(
        [Feature(ref, "Газон", lawn, object_class=ObjectClass.LAWN)],
        [TextLabel(ref, "Подписи", 10, 10, "ДЕТ.ПЛ."), TextLabel(ref, "Подписи", 50, 25, "ГАЗОН")],
        lawn,
        0.5,
    )
    assert surface is not None
    assert surface.material(np.array([shapely.Point(50, 25)], dtype=object))[0] == Material.SOIL


def test_functional_label_excludes_a_small_inferred_soil_component() -> None:
    ref = SourceRef("f", "x", "open-ground")
    extent = box(0, 0, 100, 100)
    surface = build_surface_map(
        [],
        [
            TextLabel(ref, "Пояснительные", 52, 50, "СПОРТ ПЛ.", surface_role="ignore"),
            TextLabel(ref, "Материал покрытия", 50, 50, "ГРУНТ"),
        ],
        extent,
        0.5,
        inference_mode="hybrid",
    )
    assert surface is not None
    inside = np.array([shapely.Point(55, 50)], dtype=object)
    assert surface.material(inside)[0] == Material.PAVED
    assert not surface.fits_soil(inside, 0.4)[0]


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


def test_objects_far_from_the_site_do_not_reach_the_surface_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Понтрягина, 28.09.2026: склейка граней по всему комплекту 424 МБ съедала память. Объекты
    дальше NEAR_EXTENT_M от границы работ в сетку не попадают - их и не склеиваем."""
    ref = SourceRef("f", "x", "1")
    site = box(0, 0, 40, 40)
    near = [
        Feature(ref, "Граница улицы", site.exterior, object_class=ObjectClass.PAVEMENT_EDGE),
        Feature(ref, "борт", LineString([(0, 20), (40, 20)]), object_class=ObjectClass.CURB),
    ]
    far = [
        Feature(
            ref, "борт", LineString([(1000 + i, 0), (1000 + i, 500)]), object_class=ObjectClass.CURB
        )
        for i in range(50)
    ]
    labels = [TextLabel(ref, "Леса и газоны", 5.0, 5.0, "ГАЗОН")]
    seen: list[int] = []
    original = surfaces._barrier_lines  # noqa: SLF001 - считаем, сколько объектов дошло
    monkeypatch.setattr(
        surfaces, "_barrier_lines", lambda fs: (seen.append(len(fs)), original(fs))[1]
    )
    with_far = build_surface_map([*near, *far], labels, site, 0.5)
    assert max(seen) == len(near)
    alone = build_surface_map(near, labels, site, 0.5)
    assert with_far is not None
    assert alone is not None
    assert (with_far.grid == alone.grid).all()
