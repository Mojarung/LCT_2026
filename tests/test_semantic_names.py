"""Имена файлов комплекта: каталог переименовал их латиницей, внешние ссылки помнят исходные."""

from __future__ import annotations

import pytest

from green.application.semantic_names import base_name, slug_key


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


@pytest.mark.parametrize(
    ("block", "base"),
    [
        ("DEREVO_935", "DEREVO"),
        ("output[1]_tp$0$DEREVO_935", "DEREVO"),
        ("host|KUST1_162", "KUST1"),
        ("AFIS_1_3", "AFIS"),
        ("AFIS_1", "AFIS"),
        ("SM_1_2", "SM"),
        ("RL 2.8.1_12", "RL 2.8.1"),
        ("LEG12", "LEG12"),
        ("DEREVO", "DEREVO"),
    ],
)
def test_base_name_drops_only_the_instance_number(block: str, base: str) -> None:
    assert base_name(block) == base
