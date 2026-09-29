"""Неверный параметр профиля объясняется по-русски: поле, что не так, что пришло.

Текст уходит человеку как есть (detail ответа 422, строка ошибки в CLI), поэтому сырой
вывод pydantic по-английски со ссылкой на errors.pydantic.dev здесь - дефект, а не деталь.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from test_pipeline_synthetic import ROOT

from green.application.errors import ConfigurationError, InputError
from green.infrastructure.config.repositories import YamlProfileSource, YamlSpeciesCatalog

if TYPE_CHECKING:
    from pathlib import Path

PROFILES = YamlProfileSource(ROOT / "config" / "profiles")
PREFIX = "Параметры профиля 'strict' некорректны: "
ENGLISH = re.compile(
    r"pydantic|Input should|Extra inputs|should be|valid (?:number|integer)|validation error"
    r"|For further",
    re.IGNORECASE,
)


def _refusal(overrides: dict[str, object], profile: str = "strict") -> str:
    with pytest.raises(InputError) as caught:
        PROFILES.load(profile, overrides)
    return str(caught.value)


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        pytest.param(
            {"bogus": 1}, "bogus: такого параметра нет (получено 1)", id="extra_forbidden"
        ),
        pytest.param(
            {"spacing_m": -3},
            "spacing_m: должно быть не меньше 0.3 (получено -3)",
            id="greater_than_equal",
        ),
        pytest.param(
            {"spacing_m": 100},
            "spacing_m: должно быть не больше 50 (получено 100)",
            id="less_than_equal",
        ),
        pytest.param(
            {"spacing_m": "abc"},
            'spacing_m: должно быть числом (получено "abc")',
            id="float_parsing",
        ),
        pytest.param(
            {"max_rejections": "x"},
            'max_rejections: должно быть целым числом (получено "x")',
            id="int_parsing",
        ),
        pytest.param(
            {"placement_solver": "fast"},
            'placement_solver: допустимые значения greedy, milp, portfolio (получено "fast")',
            id="literal_error",
        ),
        pytest.param(
            {"territory": "park"},
            "territory: допустимые значения green_fund, protected_green, natural,"
            ' outside_green_fund (получено "park")',
            id="enum",
        ),
        pytest.param(
            # int_parsing_size: целое больше предела разбора - тип, которого нет в словаре.
            {"given_assortment": {"tilia_cordata": 1e30}},
            'given_assortment["tilia_cordata"]: значение не подходит (получено 1e+30)',
            id="unknown_type",
        ),
    ],
)
def test_each_error_type_names_the_field_the_problem_and_the_value(
    overrides: dict[str, object], detail: str
) -> None:
    text = _refusal(overrides)

    assert text == PREFIX + detail
    assert not ENGLISH.search(text)


def test_every_bad_field_is_listed_in_one_message() -> None:
    """Пример жюри: два неверных поля - оба в одном ответе, без английского текста."""
    text = _refusal({"spacing_m": -3, "bogus": 1})

    assert text == PREFIX + (
        "spacing_m: должно быть не меньше 0.3 (получено -3);"
        " bogus: такого параметра нет (получено 1)"
    )
    assert not ENGLISH.search(text)


def test_consequence_of_a_bad_item_is_not_reported_as_a_second_error() -> None:
    """Неверный элемент списка pydantic ещё раз считает пустым списком («нужен хотя бы
    один элемент») - человеку это путает: он прислал один элемент."""
    text = _refusal({"modes": ["x"]})

    assert text == PREFIX + 'modes[0]: допустимые значения alley, lawn, fill (получено "x")'


def test_bad_profile_file_is_explained_the_same_way(tmp_path: Path) -> None:
    (tmp_path / "broken.yaml").write_text("spacing_m: -3\nbogus: 1\n", encoding="utf-8")

    with pytest.raises(InputError) as caught:
        YamlProfileSource(tmp_path).load("broken")

    assert str(caught.value) == (
        "Параметры профиля 'broken' некорректны: spacing_m: должно быть не меньше 0.3"
        " (получено -3); bogus: такого параметра нет (получено 1)"
    )


def test_broken_config_file_is_explained_in_russian(tmp_path: Path) -> None:
    """Файлы config/ правит команда, но и их ошибка доходит до человека (500 с detail)."""
    path = tmp_path / "species.yaml"
    path.write_text("species:\n  - code: x\n    crown_diameter_m: много\n", encoding="utf-8")

    with pytest.raises(ConfigurationError) as caught:
        YamlSpeciesCatalog(path).all()

    text = str(caught.value)
    assert text.startswith("species.yaml: ")
    assert 'species[0]["crown_diameter_m"]: должно быть числом (получено "много")' in text
    assert 'species[0]["name_ru"]: обязательное поле не задано' in text
    assert not ENGLISH.search(text)
