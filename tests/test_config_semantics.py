"""Классы объектов из словарей конфигурации, которые решают, какая норма применяется.

Аудит Берзарина 16.10.2026 (docs/research/jury-audit-2026-10-16): дорожный знак получал
правило осветительной опоры (4 м), лестница и стела - правило подпорной стенки (3 м).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import LineString

from green.domain.objects import Feature, ObjectClass, SourceRef
from green.infrastructure.config.repositories import YamlLayerMapSource

ROOT = Path(__file__).resolve().parents[1]
LAYER_MAP = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()


def test_road_sign_is_an_obstacle_not_a_light_pole() -> None:
    entry = LAYER_MAP.symbols.get("DORZN1")
    assert entry is not None
    assert entry.object_class is ObjectClass.OBSTACLE


@pytest.mark.parametrize("name", ["Лестница", "Ступени", "Пандус", "Стела навигации"])
def test_stairs_and_stelae_are_obstacles_not_retaining_walls(name: str) -> None:
    found = LAYER_MAP.vocabulary.infer(None, name)
    assert found is not None
    assert found.object_class is ObjectClass.OBSTACLE


@pytest.mark.parametrize("name", ["Подпорная стенка", "Парапет"])
def test_retaining_walls_keep_the_retaining_wall_rule(name: str) -> None:
    found = LAYER_MAP.vocabulary.infer(None, name)
    assert found is not None
    assert found.object_class is ObjectClass.STRUCTURE


def _feature(layer: str, block: str | None) -> Feature:
    return Feature(SourceRef("f", "x", "1"), layer, LineString([(0, 0), (5, 0)]), block=block)


@pytest.mark.parametrize(
    ("layer", "block"),
    [
        # Чекпоинт 16.10.2026, п. 2, и перепись прогонов 19 улиц: линии этих листов на слое 0
        # выводились «контуром по геометрии» (39 тыс. объектов) и делили газон на части.
        ("0_геоподоснова", "output[19-22]_3_ДЖКХ-25_01840kl"),  # красные линии, Берзарина
        ("0", "output[1-4]_edge001"),  # лист линий градостроительного регулирования
        ("0", "output[1-4]_edge001$0$RL 2.8.3"),  # знак линии регулирования
        ("0", "output[5-7]_edge005$0$RL 3.13"),
    ],
)
def test_red_lines_and_regulation_lines_are_not_surfaces(layer: str, block: str) -> None:
    found, evidence = LAYER_MAP.decide(_feature(layer, block))
    assert found is ObjectClass.IGNORE
    assert evidence.method == "name_rule"


def test_topographic_sheet_block_is_not_caught_by_the_red_line_rule() -> None:
    """Негативный контроль: лист топоплана (tp) правилом красных линий не снимается."""
    _, evidence = LAYER_MAP.decide(_feature("0", "output[1-12]_3_ДЖКХ-24_03233tp"))
    reasons = [LAYER_MAP.rules[i].reason for i in evidence.matched_rules]
    assert not any("красн" in reason for reason in reasons)


# Выгрузка паспорта ОГХ / ЕГКО (чертёж жюри 236287, 08.10.2026): английские имена слоёв без
# единого русского слова. Жюри не смогло запустить чертёж без JSON поверх профиля - классы
# этих слоёв теперь в словаре, JSON не нужен.
@pytest.mark.parametrize(
    ("layer", "expected"),
    [
        ("BOUND", ObjectClass.WORK_BOUNDARY),
        ("DOROGA", ObjectClass.CURB),
        ("DOM", ObjectClass.BUILDING),
        ("EGKO_BUILDINGS", ObjectClass.BUILDING),
        ("Жилое", ObjectClass.BUILDING),
        ("ZABOR", ObjectClass.FENCE),
        ("LAWN", ObjectClass.LAWN),
        ("EGKO_ROADS", ObjectClass.ROAD),
        ("2.Резиновая крошка", ObjectClass.SIDEWALK),
        ("2.Плитка", ObjectClass.SIDEWALK),
        ("2.Песчано-гравийная смесь", ObjectClass.SIDEWALK),
        ("PLANT_NUM_TXT", ObjectClass.IGNORE),
        ("план|DOM", ObjectClass.BUILDING),  # слой привязанного XREF
    ],
)
def test_ogh_passport_layers_need_no_overrides(layer: str, expected: ObjectClass) -> None:
    found, evidence = LAYER_MAP.decide(_feature(layer, None))
    assert found is expected
    assert evidence.method == "name_rule"


@pytest.mark.parametrize("layer", ["DOMINO", "ogh_BOUND_old", "BOUNDARY_TEXT", "RANDOM"])
def test_ogh_names_match_whole_words_only(layer: str) -> None:
    found, _ = LAYER_MAP.decide(_feature(layer, None))
    assert found not in {ObjectClass.BUILDING, ObjectClass.WORK_BOUNDARY}


@pytest.mark.parametrize(
    ("block", "layer"),
    [
        # Чертёж жюри 236287: скалодром на слое МАФ стал зданием по слову wall (22 786 линий с
        # отступом 5 м), стойка велопарковки - опорой освещения по слову «стойка».
        ("WALL BOULDERING CUBE XL", "МАФы"),
        ("Стойка велопарковка", "МАФы"),
        ("Стойки велопарковки", "Благоустройство"),
    ],
)
def test_playground_and_bike_rack_blocks_are_obstacles(block: str, layer: str) -> None:
    found = LAYER_MAP.vocabulary.infer(block, layer)
    assert found is not None
    assert found.object_class is ObjectClass.OBSTACLE


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Стойка светильника", ObjectClass.POLE), ("Wall of building", ObjectClass.BUILDING)],
)
def test_pole_and_wall_words_still_work_elsewhere(name: str, expected: ObjectClass) -> None:
    found = LAYER_MAP.vocabulary.infer(name)
    assert found is not None
    assert found.object_class is expected


# Входные DXF других команд финала (other/*, 17.10.2026): имена слоёв без правил пилота.
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ГРАНИЦА_ПРОЕКТА", ObjectClass.WORK_BOUNDARY),
        ("РАМКА_ГРАНИЦА_УЧАСТКА", ObjectClass.WORK_BOUNDARY),
        ("TERRITORY_BOUNDARY", ObjectClass.WORK_BOUNDARY),
        ("SITE_BORDER", ObjectClass.WORK_BOUNDARY),
        ("КАБЕЛЬ_СВЯЗИ", ObjectClass.UTILITY_TELECOM),
        ("CABLE_COMM_N", ObjectClass.UTILITY_TELECOM),
        ("КРАЙ_ДОРОГИ", ObjectClass.CURB),
    ],
)
def test_foreign_layer_names(name: str, expected: ObjectClass) -> None:
    found, evidence = LAYER_MAP.decide(_feature(name, None))
    if evidence.method != "name_rule":
        inferred = LAYER_MAP.vocabulary.infer(None, name)
        assert inferred is not None, name
        found = inferred.object_class
    assert found is expected


@pytest.mark.parametrize("name", ["Рамка", "Рамка листа", "SHEET_BORDER", "Кабель силовой"])
def test_frames_and_power_cables_keep_their_classes(name: str) -> None:
    found, evidence = LAYER_MAP.decide(_feature(name, None))
    if evidence.method != "name_rule":
        inferred = LAYER_MAP.vocabulary.infer(None, name)
        found = inferred.object_class if inferred else ObjectClass.UNKNOWN
    expected = ObjectClass.UTILITY_POWER if "Кабель" in name else ObjectClass.IGNORE
    assert found is expected, name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Синтетические участки Воронов: граница слоем BOUNDARY, кабель связи ELECTR_CABLE_COMM.
        ("BOUNDARY", ObjectClass.WORK_BOUNDARY),
        ("ELECTR_CABLE_COMM", ObjectClass.UTILITY_TELECOM),
        ("ELECTR_CABLE", ObjectClass.UTILITY_POWER),
    ],
)
def test_bare_english_boundary_and_comm_cable(name: str, expected: ObjectClass) -> None:
    found, evidence = LAYER_MAP.decide(_feature(name, None))
    if evidence.method != "name_rule":
        inferred = LAYER_MAP.vocabulary.infer(None, name)
        assert inferred is not None, name
        found = inferred.object_class
    assert found is expected
