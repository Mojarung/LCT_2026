"""Классификатор слоёв на именах из генплана Берзарина и выгрузок Геотреста."""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import LineString

from green.domain.objects import Feature, ObjectClass, SourceRef
from green.infrastructure.config.repositories import YamlLayerMapSource

LAYER_MAP = YamlLayerMapSource(
    Path(__file__).resolve().parents[1] / "config" / "layer_map.yaml"
).load()
DESIGNER = "link-улица Берзарина_Покрытия — Новые$0$"
GEOTREST = "output[1-12]_3_ДЖКХ-24_03233"


@pytest.mark.parametrize(
    ("layer", "expected"),
    [
        (f"{DESIGNER}ДВ_ПП_Газон_У за счет АБ_ПЧ", ObjectClass.LAWN),
        (f"{DESIGNER}ДВ_ПП_Газон_Р", ObjectClass.LAWN),
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
