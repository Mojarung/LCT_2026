"""Жизненная форма каталога совпадает со «Справочником пород» ДПиООС из датасета пилота.

Справочник - лист шаблона перечётной ведомости: заказчик сам делит породы на деревья и
кустарники. Вид, записанный в каталоге иначе, попадает не в тот план (ирга колосистая
стояла деревом, хотя у заказчика она кустарник).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from green.domain.planting import TREE_FORMS
from green.infrastructure.config.repositories import YamlSpeciesCatalog

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "research" / "city_species_dictionary.py"


def _tool():  # noqa: ANN202 - модуль инструмента грузится по пути
    spec = importlib.util.spec_from_file_location("city_species_dictionary", TOOL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not _tool().WORKBOOK.exists(), reason="датасет не распакован")
def test_catalog_life_forms_follow_the_city_dictionary() -> None:
    tool = _tool()
    dictionary = tool.load_dictionary()
    catalog = YamlSpeciesCatalog(ROOT / "config" / "species.yaml")
    matched = 0
    for species in catalog.all():
        row = dictionary.get(tool._norm(species.name_ru))  # noqa: SLF001 - нормализация инструмента
        if row is None:
            continue
        matched += 1
        expected = "дерево" if species.life_form in TREE_FORMS else "кустарник"
        assert row[1] == expected, (species.code, row)
    assert matched >= 40


@pytest.mark.skipif(not _tool().WORKBOOK.exists(), reason="датасет не распакован")
def test_invasive_species_have_no_value_code_in_the_city_dictionary() -> None:
    """Сверка с 369-ПП по данным заказчика: у инвазивных пород код ценности не проставлен."""
    tool = _tool()
    dictionary = tool.load_dictionary()
    catalog = YamlSpeciesCatalog(ROOT / "config" / "species.yaml")
    for species in catalog.all():
        row = dictionary.get(tool._norm(species.name_ru))  # noqa: SLF001
        if row is not None and species.invasive_group is not None:
            assert row[2] is None, (species.code, row)
