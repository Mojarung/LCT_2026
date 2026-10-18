"""Тень зданий над местом посадки и светолюбие вида (ТЗ, п. 2: плотность застройки и условия
посадки).

Вид в каталоге несёт потребность в свете (light: sun - светолюбив, semi - терпит
полутень). Тень над местом считается по объёмам зданий (application/volumes) и солнцу над
Москвой в два дня сезона вегетации: доля светлых часов, когда место в тени дома.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from shapely.geometry import box

from green.application.assortment.context import site_context
from green.application.assortment.filters import species_verdict
from green.application.insolation import ShadeMap, sun_position, with_shade
from green.application.params import PlanParams
from green.application.volumes import BuildingVolume
from green.domain.norms import PlantingType, RuleBook
from green.domain.planting import LifeForm, Placement, Plan, Species, Verdict

HOUSE = BuildingVolume(
    box(0, 0, 40, 20), height_m=30.0, floors=10, floors_source="label", kind="building"
)
SUN = Species("sun", "липа", "Tilia cordata", 6.0, life_form=LifeForm.TREE_MEDIUM, light="sun")
SEMI = Species(
    "semi", "клён", "Acer platanoides", 6.0, life_form=LifeForm.TREE_MEDIUM, light="semi"
)


def _placement(x: float, y: float, species: Species = SUN) -> Placement:
    return Placement("P00001", 1, PlantingType.TREE, species, x, y, Verdict.ALLOWED, ())


def test_sun_over_moscow_at_summer_noon_is_high_in_the_south() -> None:
    # 22 июня, 12:30 по Москве: солнце около 57-58 градусов, азимут около 180.
    sun = sun_position(173, 12.5)
    assert sun.elevation == pytest.approx(57.7, abs=1.0)
    assert sun.azimuth == pytest.approx(180, abs=6)


def test_north_side_of_a_tall_house_is_in_shade_south_side_is_not() -> None:
    shade = ShadeMap((HOUSE,))

    north, south, far = shade.share(np.array([[20.0, 24.0], [20.0, -6.0], [20.0, 400.0]]))

    assert north > 0.6
    assert south < 0.2
    assert far == 0.0


def test_without_buildings_nothing_is_shaded() -> None:
    assert ShadeMap(()).share(np.array([[0.0, 0.0]])).tolist() == [0.0]


def test_with_shade_fills_only_places_without_it() -> None:
    plan = Plan(
        placements=(_placement(20, 24), replace(_placement(20, -6), placement_id="P2", shade=0.9)),
        rejections=(),
    )

    shaded = with_shade(plan, ShadeMap((HOUSE,)))

    assert shaded.placements[0].shade is not None
    assert shaded.placements[0].shade > 0.6
    assert shaded.placements[1].shade == 0.9


def test_sun_loving_species_is_not_planted_in_deep_shade_semi_is() -> None:
    book = RuleBook(acts={}, distance_rules=(), fingerprint="")
    params = PlanParams()
    deep = replace(_placement(20, 24), shade=0.8)
    open_ = replace(_placement(20, -6), shade=0.1)

    refused = species_verdict(SUN, site_context(deep), book, params)
    assert not refused.allowed
    assert refused.blocking is not None
    assert "тени зданий" in refused.blocking.text
    assert species_verdict(SEMI, site_context(deep), book, params).allowed
    assert species_verdict(SUN, site_context(open_), book, params).allowed
    # Тень не посчитана (нет объёмов зданий) - ограничения нет.
    assert species_verdict(SUN, site_context(_placement(20, 24)), book, params).allowed
