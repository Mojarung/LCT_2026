"""Коды «Классификаторов для информационного моделирования» (Москва, 2024) в именах слоёв.

Классификатор прислало жюри: часть 1 «Топографическая ситуация» (ТС) и часть 2
«Планировочная организация земельного участка» (ПО ЗУ). Все строки обеих частей лежат в
config/im_classifier.yaml; слой с кодом получает класс сервиса раньше вывода по словам.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from green.domain.objects import ObjectClass
from green.infrastructure.config.repositories import YamlLayerMapSource

if TYPE_CHECKING:
    from green.application.name_semantics import Vocabulary

CONFIG = Path(__file__).parents[1] / "config"


@pytest.fixture(scope="module")
def vocabulary() -> Vocabulary:
    return YamlLayerMapSource(CONFIG / "layer_map.yaml").load().vocabulary


def test_every_classifier_row_is_in_config() -> None:
    data = yaml.safe_load((CONFIG / "im_classifier.yaml").read_text(encoding="utf-8"))
    codes, unmapped = data["codes"], data["unmapped"]
    assert not set(codes) & set(unmapped)
    # 1 998 строк таблиц, один код в PDF повторён дважды.
    assert len(codes) + len(unmapped) == 1997
    assert {ObjectClass(entry["class"]) for entry in codes.values()}


@pytest.mark.parametrize(
    ("layer", "expected"),
    [
        ("ТС 22 00 01 01", ObjectClass.EXISTING_TREE),  # дерево отдельно стоящее
        ("ТС_22_00_02_01", ObjectClass.EXISTING_SHRUB),  # куст
        ("ТС-09-10-02", ObjectClass.CURB),  # бортовой камень
        ("ТС091002", ObjectClass.CURB),  # слитно
        ("ТС 17 10 01 Газопровод", ObjectClass.UTILITY_GAS),
        ("ПО ЗУ 25 10 01", ObjectClass.UTILITY_GAS),
        ("ПОЗУ_27_10_01", ObjectClass.UTILITY_POWER),
        ("ТС 14 00 01", ObjectClass.UTILITY_ACCESS),  # точка водопровода - колодец
    ],
)
def test_layer_code_decides_class(
    vocabulary: Vocabulary, layer: str, expected: ObjectClass
) -> None:
    found = vocabulary.infer(None, layer)
    assert found is not None
    assert found.kind == "classifier"
    assert found.object_class is expected


@pytest.mark.parametrize("layer", ["ТС-16", "ТС 2Ду100", "ПОСТ 12 10 01", "ТСЖ 22 00 01"])
def test_short_or_foreign_codes_do_not_match(vocabulary: Vocabulary, layer: str) -> None:
    found = vocabulary.coded(layer)
    assert found is None


def test_pilot_layer_names_have_no_classifier_codes(vocabulary: Vocabulary) -> None:
    """Слои 20 улиц пилота кодов не содержат: их классы от классификатора не меняются."""
    names = json.loads((CONFIG / "name_model.json").read_text(encoding="utf-8"))["names"]
    assert names
    assert [name for name in names if vocabulary.coded(name)] == []
