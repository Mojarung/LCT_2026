"""Вывод класса незнакомого слоя по словам имени (задача 14, config/vocabulary.yaml).

Имена - настоящие незнакомые слои переписи 19 улиц пилота (25.09.2026), ожидаемый класс решён
по картинке слоя и подписям рядом. Грамматика проекта: новое стоит до «за счёт», «на месте»,
«за», «на» и первым в паре заливок «ГЗН-АБ ТР» (проверено подписями съёмки внутри заливок).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from green.domain.objects import ObjectClass
from green.infrastructure.config.repositories import YamlLayerMapSource

ROOT = Path(__file__).resolve().parents[1]
WORDS = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load().vocabulary

C = ObjectClass


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Газон нового оформления - всегда газон (слова пользователя 25.09.2026).
        ("ДВ_ГП_П_Газон_Рулонный", C.LAWN),
        ("ДВ_ГП_П_Газон", C.LAWN),
        ("ДВ_ПП_Газон_Р", C.LAWN),
        ("ОЗ_Цветник тип 4 Теневой цветник", C.LAWN),
        ("!Project_hatch road grass", C.LAWN),
        ("ГП_контр_газон_нов", C.LAWN),
        # Проектная грамматика: новое - до разделителя и первым в паре заливок.
        ("ДВ_ПП_Газон_У за счет АБ_ПЧ", C.LAWN),
        ("ДВ_ПП_П_Газон новый на ПР Ч", C.LAWN),
        ("ДВ_ПП_Тип4_ПЧ за газон", C.ROAD),
        ("ДВ_ПП_ДО_Тип3_Устройство_уширений_магистральные_на месте газона", C.ROAD),
        ("ДВ_ПП_ДО_Тип7_Устройство_трот_менее_3м_газон уничтож", C.SIDEWALK),
        ("_АБ ТР-ГЗН (2 и более метров)", C.SIDEWALK),
        ("_ГЗН-АБ ТР", C.LAWN),
        ("_ЩМА ПЧ-АБ ТР", C.ROAD),
        ("ДВ_ГП_П_Борт_БР_на_тротуаре_15см", C.CURB),
        # Покрытия проектировщиков.
        ("ДВ_ПП_ДО_Тип2_Ремонт_покрытия_ПЧ_Местные", C.ROAD),
        ("ДВ_ПП_ДО_Тип6_Устройство_трот_более_2м", C.SIDEWALK),
        ("ДВ_ПП_ДО_Ремонт гранитной плитки", C.SIDEWALK),
        ("!Project_hatch road sidewalk - Тип 5", C.SIDEWALK),
        ("!Project_hatch road - Тип 2", C.ROAD),
        ("_Тип 5 (рем. ТР из а.б)", C.SIDEWALK),
        ("_Тип 2 (рем. мз а.б)", C.ROAD),
        ("ДВ_ГП_П_ДО_Кромка_Укр_Обочины", C.ROAD),
        ("дорожная одежда", C.ROAD),
        ("ДВ_ПП_ДО_Тип7а_Устройство_детских и спорт", C.SIDEWALK),
        ("!Project_crushed stone - Тип 9", C.SIDEWALK),
        # Борта, ограды, сооружения, препятствия.
        ("ГП1 (300х150)", C.CURB),
        ("ДВ_АКР_БР100.30.15", C.CURB),
        ("ДВ_ГП_П_ПО_Ограничивающее", C.FENCE),
        ("!!Взлёт_ПОС_Ограждение", C.FENCE),
        ("A-HATCH-WALL", C.BUILDING),
        ("ДВ_ГП_П_Воздуховоды", C.STRUCTURE),
        ("ДВ_ГП_П_Стела", C.STRUCTURE),
        ("!Project_road stairs", C.STRUCTURE),
        ("!Project_construction retaining wall", C.STRUCTURE),
        ("ДВ_ГП_П_МАФ", C.OBSTACLE),
        # Сети, опоры, колодцы.
        ("ЭН_РКЛ_удс в трубе", C.UTILITY_POWER),
        ("ЭН_КЛ земля_Моссвет_ВБШв 4х16", C.UTILITY_POWER),
        ("_ЭС_зеземление", C.UTILITY_POWER),
        ("ИОТ2_1х63", C.UTILITY_POWER),
        ("СИП 2А", C.POWER_LINE_OVERHEAD),
        ("ЭН_ВЛ_сущ", C.POWER_LINE_OVERHEAD),
        ("М_СПАЙКИ", C.UTILITY_TELECOM),
        ("ДВ_ГП_П_Водоотводные_лотки", C.UTILITY_STORM),
        ("ЭН_ГНБ_трубы", C.UTILITY_UNKNOWN),
        ("ИОС_опора КО вылет 4м.", C.POLE),
        ("ДВ_ГП_П_НО_Светильник_КОНТРАСТ", C.POLE),
        ("!_ГП_колодец_ТР_водосток", C.UTILITY_ACCESS),
        # Граница работ, контур.
        ("_ГП_граница благоустройства", C.WORK_BOUNDARY),
        ("ДВ_АКР_Граница_работ", C.WORK_BOUNDARY),
        ("ГП_контр_тип6", C.CONTOUR),
        # Снимаемое проектом и оформление в расчёт не идут.
        ("ЭН_ВЛИ демонтаж", C.IGNORE),
        ("ЭН_ВЛ_Дем", C.IGNORE),
        ("_Разборка", C.IGNORE),
        ("ДВ_ГП_П_ОФР_Текст", C.IGNORE),
        ("PDF _усиление", C.IGNORE),
        ("ДВ_(0) Не печать", C.IGNORE),
        ("ГП_PIKETS", C.IGNORE),
        ("ЭН_освещенность", C.IGNORE),
        ("C-ROAD-TEXT", C.IGNORE),
        ("!!!_Условные обозначения на ЛИСТ", C.IGNORE),
        ("ДВ_Xref_Спутник", C.IGNORE),
        ("Defpoints", C.IGNORE),
        # Деревья: существующее остаётся препятствием, посадки проектировщика - его ответ.
        ("СУЩ_Деревья", C.EXISTING_TREE),
        ("Деревья", C.EXISTING_TREE),
        ("ГП_Деревья", C.IGNORE),
        ("Вырубка_деревьев", C.IGNORE),
        ("Кустарники_проект", C.IGNORE),
    ],
)
def test_pilot_names_are_inferred(name: str, expected: ObjectClass) -> None:
    found = WORDS.infer(name)
    assert found is not None
    assert found.object_class is expected, found


@pytest.mark.parametrize("name", ["0", "Layer1", "Level 41", "Штриховка", "ДВ_ГП_П_ПС", "L26"])
def test_names_without_words_leave_the_decision_to_geometry(name: str) -> None:
    assert WORDS.infer(name) is None


def test_block_name_is_more_specific_than_its_layer() -> None:
    found = WORDS.infer("Урна_Город", "Деревья")
    assert found is not None
    assert found.object_class is ObjectClass.OBSTACLE


def test_xref_namespace_is_not_a_meaning() -> None:
    """Имя файла внешней ссылки - пространство имён: «Газон|L26» не газон."""
    assert WORDS.infer("Газон|L26") is None
    assert WORDS.infer("Газон$0$L26") is None


def test_negation_removes_the_word_it_negates() -> None:
    found = WORDS.infer("Тротуар без газона")
    assert found is not None
    assert found.object_class is ObjectClass.SIDEWALK


def test_evidence_names_the_word() -> None:
    found = WORDS.infer("ДВ_ГП_П_Газон_Рулонный")
    assert found is not None
    assert found.method == "inferred_name:газон"
