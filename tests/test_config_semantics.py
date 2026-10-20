"""Классы объектов из словарей конфигурации, которые решают, какая норма применяется.

Аудит Берзарина 16.10.2026 (docs/research/jury-audit-2026-10-16): дорожный знак получал
правило осветительной опоры (4 м), лестница и стела - правило подпорной стенки (3 м).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from shapely.geometry import LineString, Point, box

from green.domain.objects import Feature, ObjectClass, SourceRef
from green.infrastructure.config.repositories import YamlLayerMapSource

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

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


# Входные DXF сторонних авторов (17.10.2026): имена слоёв без правил пилота.
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
        ("GROUND", ObjectClass.LAWN),  # у Воронов - земля под озеленение (их тесты: type lawn)
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


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Ревью 17.10.2026: фраза не должна перебивать пометку сноса.
        ("Край проезжей части_демонтаж", ObjectClass.IGNORE),
        ("Край дороги (демонтаж)", ObjectClass.IGNORE),
        ("кабель связи демонтаж", ObjectClass.IGNORE),
        # Чужие границы - не граница работ.
        ("Граница территории ОКН", ObjectClass.CONTOUR),
        ("Граница объекта культурного наследия", ObjectClass.CONTOUR),
        ("Граница проекта планировки", ObjectClass.CONTOUR),
        # Подписи и выноски границы работ - оформление, только рамка/border - граница.
        ("Подписи границы работ", ObjectClass.IGNORE),
        ("Выноски граница работ", ObjectClass.IGNORE),
    ],
)
def test_review_regressions_in_the_vocabulary(name: str, expected: ObjectClass) -> None:
    inferred = LAYER_MAP.vocabulary.infer(None, name)
    assert inferred is not None, name
    assert inferred.object_class is expected, (name, inferred)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Сторонние входы без грунта (17.10.2026): водоём - не земля и не линия покрытия.
        ("ВОДОЕМ", ObjectClass.OBSTACLE),
        ("OSM_HYDROGRAPHY", ObjectClass.OBSTACLE),
        ("POND", ObjectClass.OBSTACLE),
        ("WATER_BODY", ObjectClass.OBSTACLE),
        # GreenCAD: тестовая копия границы работ, не газон (их README).
        ("GC_TEST_GREEN_ZONE", ObjectClass.IGNORE),
        # Детали 3D-зданий и разметка - не границы покрытий.
        ("WINDOWS", ObjectClass.IGNORE),
        ("ROAD_MARKINGS", ObjectClass.IGNORE),
        ("PARKING_MARKINGS", ObjectClass.IGNORE),
        ("CANOPIES", ObjectClass.OBSTACLE),
        ("TRANSFORMER_SUBSTATION", ObjectClass.BUILDING),
        ("PLAYGROUND_SPORTS", ObjectClass.SIDEWALK),
        ("PLAYGROUND", ObjectClass.SIDEWALK),
    ],
)
def test_foreign_site_names_without_soil(name: str, expected: ObjectClass) -> None:
    found, evidence = LAYER_MAP.decide(_feature(name, None))
    if evidence.method != "name_rule":
        inferred = LAYER_MAP.vocabulary.infer(None, name)
        found = inferred.object_class if inferred else ObjectClass.UNKNOWN
    assert found is expected, name


@pytest.mark.parametrize(
    ("layer", "geometry", "radius", "expected"),
    [
        # OSM: «существующее озеленение» - площади зелени (газон), а круги - кроны.
        ("OSM_GREEN_EXISTING", box(0, 0, 30, 20), None, ObjectClass.LAWN),
        ("GREEN_EXISTING", Point(5, 5).buffer(3.0), 3.0, ObjectClass.EXISTING_TREE),
        ("OSM_RAILWAY", LineString([(0, 0), (50, 0)]), None, ObjectClass.RAILWAY),
    ],
)
def test_osm_green_and_railway_layers(
    layer: str, geometry: BaseGeometry, radius: float | None, expected: ObjectClass
) -> None:
    feature = Feature(SourceRef("f", "x", "1"), layer, geometry, circle_radius_m=radius)
    found, evidence = LAYER_MAP.decide(feature)
    if evidence.method != "name_rule":
        inferred = LAYER_MAP.vocabulary.infer(None, layer)
        found = inferred.object_class if inferred else ObjectClass.UNKNOWN
    assert found is expected, layer


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # сторонний вход: слой «ЛИСТВЕННИЦА ЕВРОПЕЙСКАЯ» брал слово оформления «лист» началом слова.
        ("ЛИСТВЕННИЦА ЕВРОПЕЙСКАЯ", ObjectClass.EXISTING_TREE),
        ("Лиственница сибирская", ObjectClass.EXISTING_TREE),
        ("Лист 1", ObjectClass.IGNORE),
        ("Листы оформления", ObjectClass.IGNORE),
    ],
)
def test_larch_is_not_a_sheet(name: str, expected: ObjectClass) -> None:
    inferred = LAYER_MAP.vocabulary.infer(None, name)
    assert inferred is not None, name
    assert inferred.object_class is expected, (name, inferred)


@pytest.mark.parametrize(
    "block",
    [
        "17.Наташинский_ГЕО_ЦВЕТ$0$цвет_output[1-7]_edge001",
        "17.Наташинский_ГЕО_ЦВЕТ$0$цвет_output[3]_edge003",
        "цвет_output[1-7]_3ДЖКХ-25-00694kl",
        "output[1-4]_edge001",
        # Блоки легенды внутри листа (2-я Прядильная, 20 тыс. объектов на слое 0, 18.10.2026).
        "output[1-4]_edge001$0$LEG21",
        "output[5-7]_edge005$0$LEG21_3",
    ],
)
def test_colour_sheet_regulation_lines_are_annotation(block: str) -> None:
    """Наташинский: листы линий градрегулирования цветной съёмки («цвет_output[..]_edgeN», 382
    тыс. объектов на слое 0) правило «output[..]_edge» не ловило из-за приставки «цвет_» -
    они шли «контуром по геометрии» и делили газон."""
    found, evidence = LAYER_MAP.decide(_feature("17.Наташинский_ГЕО_ЦВЕТ$0$_Внешние ссылки", block))
    assert evidence.method == "name_rule"
    assert found is ObjectClass.IGNORE


@pytest.mark.parametrize(
    "layer", ["Доп подземка$0$Level 3", "Доп подземка$0$Level 17", "Доп подземка$0$Level 51"]
)
def test_levels_of_an_underground_survey_xref_are_networks(layer: str) -> None:
    """Харьковская, 18.10.2026: внешняя ссылка «Доп подземка» из MicroStation - слои Level N
    без смысла, а сами линии - подземные сети. По геометрии они были «контуром» без отступов;
    вид сети неизвестен, поэтому - сеть неизвестного вида с её отступами."""
    found, evidence = LAYER_MAP.decide(_feature(layer, "Доп подземка"))
    assert found is ObjectClass.UTILITY_UNKNOWN
    assert evidence.method == "name_rule"


def test_levels_of_a_topographic_xref_stay_unresolved() -> None:
    found, _ = LAYER_MAP.decide(_feature("Доп топо$0$Level 41", "Доп топо"))
    assert found is not ObjectClass.UTILITY_UNKNOWN


@pytest.mark.parametrize(
    ("layer", "block"),
    [
        ("xref196484$0$!Project_traffic line 1.14.1", "*U658"),  # «зебра», Песчаный
        ("ПЕШ.переход Сущ", "*U438"),  # Наташинский
        ("ПЕШ.переход", None),
    ],
)
def test_pedestrian_crossing_marking_is_annotation(layer: str, block: str | None) -> None:
    """Разметка пешеходного перехода лежит на проезжей части: ограничение даёт покрытие."""
    found, evidence = LAYER_MAP.decide(_feature(layer, block))
    assert found is ObjectClass.IGNORE
    assert evidence.method == "name_rule"


def test_underground_crossing_is_still_a_structure() -> None:
    found, _ = LAYER_MAP.decide(_feature("Подземный переход", None))
    assert found is ObjectClass.STRUCTURE
