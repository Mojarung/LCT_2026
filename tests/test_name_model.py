"""Класс по похожему имени слоя (третья ступень): уверенно - класс, сомнительно - ничего."""

from __future__ import annotations

from pathlib import Path

from green.application.name_model import NameModel, name_key
from green.domain.objects import ObjectClass
from green.infrastructure.config.repositories import YamlLayerMapSource

C = ObjectClass
MODEL = NameModel(
    names=(
        "Водопровод",
        "Водопровод сущ",
        "Сети_Водопровод",
        "Канализация",
        "Канализация бытовая",
        "Бортовой камень",
        "Борт",
        "Газон",
        "Газон новый",
    ),
    classes=(
        C.UTILITY_WATER,
        C.UTILITY_WATER,
        C.UTILITY_WATER,
        C.UTILITY_SEWER,
        C.UTILITY_SEWER,
        C.CURB,
        C.CURB,
        C.LAWN,
        C.LAWN,
    ),
)


def test_similar_name_gets_the_class_of_its_neighbours() -> None:
    guess = MODEL.guess("ИС_Водопровод_проект", None)
    assert guess is not None
    assert guess.object_class is C.UTILITY_WATER
    assert guess.method.startswith("model:utility.water")


def test_model_never_widens_the_planting_zone() -> None:
    """Газон и граница работ - только по правилам и словам (правило безопасности greenai)."""
    assert MODEL.guess("Газон новый рулонный", None) is None


def test_unfamiliar_name_gets_nothing() -> None:
    assert MODEL.guess("Xyzzy слой 77", None) is None


def test_empty_model_proposes_nothing() -> None:
    assert NameModel().guess("Водопровод", None) is None
    assert not NameModel()


def test_key_uses_local_layer_and_base_block_names() -> None:
    assert name_key("host|Водопровод", "output[1]_tp$0$KOLODEC_12") == "Водопровод KOLODEC"
    assert name_key("Водопровод", "*U123") == "Водопровод"


def test_shipped_layer_map_carries_the_pilot_names() -> None:
    root = Path(__file__).resolve().parents[1]
    layer_map = YamlLayerMapSource(root / "config/layer_map.yaml").load()
    assert len(layer_map.names.names) > 1000
    assert all(c not in {C.LAWN, C.WORK_BOUNDARY} for c in layer_map.names.classes)
