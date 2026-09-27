"""Классификатор слоёв на именах из генплана Берзарина и выгрузок Геотреста."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from shapely.geometry import LineString, Point

from green.application.classification import classification_report
from green.application.errors import ConfigurationError
from green.domain.objects import Feature, ObjectClass, Scene, SourceRef
from green.infrastructure.config.repositories import YamlLayerMapSource

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

LAYER_MAP = YamlLayerMapSource(
    Path(__file__).resolve().parents[1] / "config" / "layer_map.yaml"
).load()
DESIGNER = "link-улица Берзарина_Покрытия — Новые$0$"
GEOTREST = "output[1-12]_3_ДЖКХ-24_03233"


@pytest.mark.parametrize(
    ("layer", "expected"),
    [
        (f"{DESIGNER}ДВ_ПП_Газон_У за счет АБ_ПЧ", ObjectClass.UNKNOWN),
        (f"{DESIGNER}ДВ_ПП_Газон_Р", ObjectClass.UNKNOWN),
        (f"{DESIGNER}ДВ_ПП_Тип4_У_ПЧ за счет Газона", ObjectClass.ROAD),
        (f"{DESIGNER}ДВ_ПП_Тип2_Р_покрытия_ПЧ_Местные", ObjectClass.ROAD),
        (f"{DESIGNER}ДВ_ПП_Тип6_У_ТР_3м за счет Газона", ObjectClass.SIDEWALK),
        (f"{DESIGNER}ДВ_ПП_Тип5_Р ТР", ObjectClass.SIDEWALK),
        (f"{DESIGNER}ДВ_ПП_Ремонт плитки_1", ObjectClass.SIDEWALK),
        ("link_улица Берзарина_Люки$0$_ГП_В1 колодцы_сущ.", ObjectClass.UTILITY_ACCESS),
        (f"{GEOTREST}tp$0$Железные дороги", ObjectClass.RAILWAY),
        (f"{GEOTREST}tp$0$Бортовой камень", ObjectClass.CURB),
        (f"{GEOTREST}up$0$Кабель электрический", ObjectClass.UTILITY_POWER),
        (f"{GEOTREST}up$0$Топливопровод", ObjectClass.UTILITY_UNKNOWN),
        (f"{GEOTREST}tp$0$Крыльца", ObjectClass.OBSTACLE),
        (f"{GEOTREST}tp$0$Фонтаны", ObjectClass.OBSTACLE),
        (f"{GEOTREST}tp$0$Памятники", ObjectClass.OBSTACLE),
        ("3-я Парковая|Топо_Береговая линия", ObjectClass.OBSTACLE),
        (f"{GEOTREST}tp$0$Вентиляторы", ObjectClass.STRUCTURE),
        (f"{GEOTREST}kl$0$Красные линии", ObjectClass.IGNORE),
        # Слои топоплана, которых не было в словаре (перепись слоёв 19 улиц, 25.09.2026).
        (f"{GEOTREST}tp$0$Граница площадки", ObjectClass.PAVEMENT_EDGE),
        (f"{GEOTREST}tp$0$Топографические объекты", ObjectClass.OBSTACLE),
        (f"{GEOTREST}tp$0$Грунты", ObjectClass.OBSTACLE),
        (f"{GEOTREST}tp$0$Указатель подз коммуникаций", ObjectClass.OBSTACLE),
        (f"{GEOTREST}tp$0$Подъемные краны", ObjectClass.OBSTACLE),
        (f"{GEOTREST}tp$0$Платформы ЖД", ObjectClass.STRUCTURE),
        (f"{GEOTREST}up$0$Водосточный коллектор", ObjectClass.UTILITY_STORM),
        (f"{GEOTREST}tp$0$Территории", ObjectClass.IGNORE),
        # Контур площадки со своим покрытием - граница покрытий, а не мусор (Харьковская).
        (f"{GEOTREST}tp$2$Граница площадки", ObjectClass.PAVEMENT_EDGE),
        ("ДВ_ПП_ДО_Тип2_Ремонт_покрытия_ПЧ_Местные", ObjectClass.ROAD),
        ("ДВ_ПП_ДО_Тип4_Устройство_уширений_местные", ObjectClass.ROAD),
        ("ДВ_ПП_ДО_Тип5_Замена_покрытия_трот_более_2м", ObjectClass.SIDEWALK),
        ("ДВ_ПП_ДО_Тип5а_Капремонт_трот", ObjectClass.SIDEWALK),
        ("ДВ_ПП_ДО_Тип9_Устройство_трот_менее_2м", ObjectClass.SIDEWALK),
        ("ДВ_ПП_ДО_Тип_Устройство_площадки", ObjectClass.SIDEWALK),
    ],
)
def test_layer_classes(layer: str, expected: ObjectClass) -> None:
    feature = Feature(
        ref=SourceRef("00000000", "00000000", "1"),
        layer=layer,
        geometry=LineString([(0, 0), (1, 1)]),
    )
    assert LAYER_MAP.classify(feature) is expected


@pytest.mark.parametrize(
    ("geometry", "radius", "expected"),
    [
        (Point(0, 0).buffer(0.25), 0.25, ObjectClass.EXISTING_TREE),
        (Point(0, 0).buffer(0.25), None, ObjectClass.EXISTING_TREE),
        (LineString([(0, 0), (7, 0)]), None, ObjectClass.LAWN),
    ],
)
def test_tree_strip_layer_by_geometry(
    geometry: BaseGeometry, radius: float | None, expected: ObjectClass
) -> None:
    """Залитый ствол полосы (REGION до 0,5 м) - дерево, как кружок; пунктир - контур грунта."""
    feature = Feature(
        ref=SourceRef("00000000", "00000000", "1"),
        layer=f"{GEOTREST}tp$0$Полоса деревьев",
        geometry=geometry,
        circle_radius_m=radius,
    )
    assert LAYER_MAP.classify(feature) is expected


def test_ignore_rule_without_a_reason_does_not_load(tmp_path: Path) -> None:
    """Игнор слоя - решение, которое надо объяснить: без причины карта слоёв не читается."""
    path = tmp_path / "layer_map.yaml"
    path.write_text(
        'version: 1\nrules:\n  - {pattern: "Рамк", object_class: ignore}\n', encoding="utf-8"
    )

    with pytest.raises(ConfigurationError, match="reason"):
        YamlLayerMapSource(path, tmp_path / "no-symbols.yaml").load()


def test_report_names_the_reason_of_every_ignored_layer() -> None:
    frame = Feature(
        ref=SourceRef("00000000", "00000000", "1"),
        layer=f"{GEOTREST}tp$0$Рамка",
        geometry=LineString([(0, 0), (1, 1)]),
    )
    scene = Scene("s.dxf", "0" * 64, "AC1032", (frame,))

    report = classification_report(scene, LAYER_MAP)

    ignored = [r for r in report.rules if r.object_class is ObjectClass.IGNORE]
    assert ignored
    assert all(r.reason for r in ignored)
