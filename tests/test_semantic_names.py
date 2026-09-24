"""Имена файлов комплекта: каталог переименовал их латиницей, внешние ссылки помнят исходные."""

from __future__ import annotations

import pytest

from green.application.semantic_names import slug_key


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("00.1_10004141_Топография", "00-1-10004141-topografiya"),
        ("00-1-10004141-topografiya", "00-1-10004141-topografiya"),
        ("Шаблоны значков", "shablony-znachkov"),
        ("output[1-12]_3_ДЖКХ-24_03233tp", "output-1-12-3-dzhkh-24-03233tp"),
        ("  Улица   Берзарина  ", "ulitsa-berzarina"),
        ("Щёлковское ш.", "schelkovskoe-sh"),
    ],
)
def test_slug_key_matches_the_street_catalogue(name: str, slug: str) -> None:
    assert slug_key(name) == slug
