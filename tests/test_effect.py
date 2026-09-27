"""Баланс озеленения и эффект «было - стало»: деревья, кроны, борта, ярус, газон, шум, виды."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, MultiPoint, Point, box
from test_quality import LAWN, LIME, SPIREA, _place

from green.application.effect import street_effect
from green.application.params import PlanParams
from green.application.placement import MODE_LABELS
from green.application.ports import InventoryCounts
from green.application.quality import Site, site_of
from green.application.surfaces import SurfaceMap
from green.application.tree_strips import STRIP_SOURCE
from green.domain.norms import LawnKind
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import Lawn, Plan

PARAMS = PlanParams()
HEDGE = MODE_LABELS["curb_hedge"]
ALLEY = MODE_LABELS["alley"]


def _site(*trunks: tuple[float, float], shrubs: tuple[tuple[float, float], ...] = ()) -> Site:
    features = [
        Feature(
            SourceRef("f", "x", "b"),
            "граница",
            box(0.0, -20.0, 200.0, 20.0),
            object_class=ObjectClass.WORK_BOUNDARY,
        ),
        Feature(
            SourceRef("f", "x", "c"),
            "борт",
            LineString([(0.0, 0.0), (200.0, 0.0)]),
            object_class=ObjectClass.CURB,
        ),
    ]
    features += [
        Feature(
            SourceRef("f", "x", f"t{i}"),
            "деревья",
            Point(xy),
            object_class=ObjectClass.EXISTING_TREE,
            symbol=f"s{i}",
        )
        for i, xy in enumerate(trunks)
    ]
    features += [
        Feature(
            SourceRef("f", "x", f"k{i}"),
            "кусты",
            Point(xy),
            object_class=ObjectClass.EXISTING_SHRUB,
        )
        for i, xy in enumerate(shrubs)
    ]
    return site_of(features)


def _plan(*placements, lawns: tuple[Lawn, ...] = ()) -> Plan:  # noqa: ANN002
    return Plan(placements=tuple(placements), rejections=(), lawns=lawns)


def _m(effect, key: str):  # noqa: ANN001, ANN202
    return next(m for m in effect.measures if m.key == key)


def test_empty_plan_after_equals_before() -> None:
    effect = street_effect(_plan(), _site((50.0, 5.0)), PARAMS)
    for m in effect.measures:
        if m.before is not None:
            assert m.after == m.before, m.key
    assert _m(effect, "trees").before == 1


def test_new_crown_over_an_existing_one_adds_no_shade() -> None:
    site = _site((100.0, 5.0))
    effect = street_effect(_plan(_place(1, 100.5, 5.0, LIME, note=LAWN)), site, PARAMS)
    shade = _m(effect, "canopy_m2")
    assert shade.after == pytest.approx(shade.before, abs=1.0)
    assert _m(effect, "trees").after == 2


def test_shrub_at_the_curb_adds_curb_under_greenery() -> None:
    site = _site()
    effect = street_effect(_plan(_place(1, 50.0, 1.0, SPIREA, note=HEDGE)), site, PARAMS)
    curb = _m(effect, "curb_green_m")
    assert curb.before == 0
    assert curb.after > 0


def test_shrub_under_an_existing_tree_is_a_second_tier() -> None:
    site = _site((100.0, 8.0))
    effect = street_effect(_plan(_place(1, 101.0, 11.5, SPIREA, note=LAWN)), site, PARAMS)
    tiers = _m(effect, "tiers_trees")
    assert (tiers.before, tiers.after) == (0, 1)


def test_wide_belt_along_the_curb_is_a_noise_screen() -> None:
    # Полоса 12 м зелени вдоль 50 м борта: кроны 8,5 м в два ряда с шагом 4 м.
    trunks = [(x, y) for x in range(20, 71, 4) for y in (4.0, 9.0)]
    effect = street_effect(_plan(), _site(*trunks), PARAMS)
    band = next(b for b in effect.noise if b.width == "10-15")
    assert band.curb_before_m == pytest.approx(band.curb_after_m)
    assert 40.0 <= band.curb_before_m <= 70.0  # noqa: PLR2004 - 50 м борта с краями крон
    assert band.dba == "4-5"
    assert _m(effect, "noise_curb_m").before == pytest.approx(
        sum(b.curb_before_m for b in effect.noise)
    )


def test_no_belt_no_noise_screen() -> None:
    effect = street_effect(_plan(_place(1, 50.0, 3.0, LIME, note=ALLEY)), _site(), PARAMS)
    assert _m(effect, "noise_curb_m").after == 0


def test_planting_kinds_with_hedge_length_and_lawns() -> None:
    hedge = [_place(i, 10.0 + i, 1.0, SPIREA, note=HEDGE) for i in range(1, 11)]
    trees = [_place(20 + i, 30.0 + 6 * i, 3.0, LIME, note=ALLEY) for i in range(3)]
    lawn = Lawn("l1", 1, LawnKind.NEW, box(100.0, 5.0, 110.0, 15.0), ("R-LAWN",))
    kept = Lawn("l2", 2, LawnKind.KEPT, box(120.0, 5.0, 130.0, 10.0), ("R-LAWN",))
    effect = street_effect(_plan(*hedge, *trees, lawns=(lawn, kept)), _site(), PARAMS)
    kinds = {k.key: k for k in effect.kinds}
    assert kinds["curb_hedge"].count == 10
    assert kinds["curb_hedge"].length_m == pytest.approx(10.0)
    assert kinds["alley"].count == 3
    assert kinds["lawn_new"].area_m2 == pytest.approx(100.0)
    assert effect.area_m2 == pytest.approx(200.0 * 40.0)
    assert effect.curb_m == pytest.approx(200.0)
    lawn_m2 = _m(effect, "lawn_m2")
    assert (lawn_m2.before, lawn_m2.after) == (pytest.approx(50.0), pytest.approx(150.0))


def test_inventory_gives_the_balance_of_the_survey() -> None:
    """Итог перечётки по 770-ПП: было - все деревья, включая вырубку; стало - без вырубки и
    с новыми; кусты перечётки - в строку кустарников."""
    inventory = InventoryCounts(
        matched={"lime": 40, "spirea": 10},
        unmatched={"Самосев": 5, "Кизильник куст": 3},
        rows_removed=2,
        removed=7,
    )
    effect = street_effect(
        _plan(_place(1, 50.0, 5.0, LIME, note=LAWN)),
        _site((10.0, 5.0)),
        PARAMS,
        inventory,
        catalog=(LIME, SPIREA),
    )
    trees = _m(effect, "trees")
    assert (trees.before, trees.after) == (52, 46)
    assert "перечётной ведомости" in trees.note
    assert "к вырубке 7" in trees.note
    shrubs = _m(effect, "shrubs")
    assert shrubs.before == 13


def test_no_boundary_means_no_data_not_zero() -> None:
    features = [
        Feature(
            SourceRef("f", "x", "c"),
            "борт",
            LineString([(0, 0), (200, 0)]),
            object_class=ObjectClass.CURB,
        ),
        Feature(
            SourceRef("f", "x", "t"),
            "деревья",
            Point(50, 5),
            object_class=ObjectClass.EXISTING_TREE,
            symbol="s",
        ),
    ]
    effect = street_effect(_plan(_place(1, 50.0, 9.0, LIME, note=LAWN)), site_of(features), PARAMS)
    for key in ("trees", "canopy_m2", "curb_green_m", "tiers_trees", "noise_curb_m"):
        m = _m(effect, key)
        assert (m.before, m.after) == (None, None), key
    assert "граница работ" in _m(effect, "trees").note


def test_tree_strips_only_give_no_count() -> None:
    features = [
        Feature(
            SourceRef("f", "x", "b"),
            "граница",
            box(0, -20, 200, 20),
            object_class=ObjectClass.WORK_BOUNDARY,
        ),
        Feature(
            SourceRef("f", "x", "s"),
            "полоса",
            MultiPoint([(20.0 + i, 5.0) for i in range(10)]),
            object_class=ObjectClass.EXISTING_TREE,
            source_entity_type=STRIP_SOURCE,
        ),
    ]
    effect = street_effect(_plan(), site_of(features), PARAMS)
    trees = _m(effect, "trees")
    assert trees.before is None
    assert "не определяется" in trees.note
    assert _m(effect, "canopy_m2").before > 0


def test_no_curbs_no_noise_data() -> None:
    features = [
        Feature(
            SourceRef("f", "x", "b"),
            "граница",
            box(0, -20, 200, 20),
            object_class=ObjectClass.WORK_BOUNDARY,
        ),
    ]
    effect = street_effect(_plan(), site_of(features), PARAMS)
    assert _m(effect, "noise_curb_m").before is None
    assert _m(effect, "curb_green_m").before is None


def test_existing_shrub_under_a_new_crown_is_a_tier_after() -> None:
    site = _site(shrubs=((101.0, 10.0),))
    effect = street_effect(_plan(_place(1, 100.0, 10.0, LIME, note=LAWN)), site, PARAMS)
    tiers = _m(effect, "tiers_trees")
    assert (tiers.before, tiers.after) == (0, 1)


def test_per_km_measures_against_mgsn() -> None:
    effect = street_effect(
        _plan(*[_place(i, 5.0 * i, 5.0, LIME, note=ALLEY) for i in range(1, 11)]),
        _site(),
        replace(PARAMS, street_length_m=100.0),
    )
    per_km = _m(effect, "trees_per_km")
    assert per_km.after == pytest.approx(100.0)
    assert per_km.kind == "norm"


def _strokes_site(*trunks: tuple[float, float]) -> Site:
    """Деревья разобранными знаками: по чертежу число деревьев не определяется."""
    features = [
        Feature(
            SourceRef("f", "x", "b"),
            "граница",
            box(0.0, -20.0, 200.0, 20.0),
            object_class=ObjectClass.WORK_BOUNDARY,
        )
    ]
    features += [
        Feature(
            SourceRef("f", "x", f"a{i}"),
            "деревья",
            LineString([(x, y), (x + 0.1, y)]),
            object_class=ObjectClass.EXISTING_TREE,
            source_entity_type="ARC",
        )
        for i, (x, y) in enumerate(trunks)
    ]
    return site_of(features)


def test_marks_give_no_tree_count_but_give_crowns() -> None:
    effect = street_effect(
        _plan(_place(1, 150.0, 5.0, LIME, note=LAWN)), _strokes_site((20.0, 5.0)), PARAMS
    )
    trees = _m(effect, "trees")
    assert trees.before is None
    assert trees.after is None
    assert "не определяется" in trees.note
    assert _m(effect, "canopy_m2").before > 0
    assert _m(effect, "trees_per_km").before is None


def _surface(paved_below: bool) -> SurfaceMap:  # noqa: FBT001 - вариант карты для теста
    soil = box(-50.0, 0.0, 250.0, 50.0)
    below = box(-50.0, -50.0, 250.0, 0.0)
    return SurfaceMap(
        grid=np.zeros((1, 1), dtype=np.int8),
        origin=(0.0, 0.0),
        cell=1.0,
        seeds_paved=1,
        seeds_soil=1,
        soil_area=shapely.union(soil, below) if not paved_below else soil,
        paved_area=below if paved_below else None,
    )


def test_noise_counts_curbs_with_pavement_on_one_side() -> None:
    trunks = [(x, y) for x in range(20, 71, 4) for y in (4.0, 9.0)]
    site = _site(*trunks)
    road = street_effect(_plan(), site, PARAMS, surface=_surface(paved_below=True))
    park = street_effect(_plan(), site, PARAMS, surface=_surface(paved_below=False))
    assert _m(road, "noise_curb_m").before > 40.0  # noqa: PLR2004 - полоса вдоль 50 м борта
    assert _m(park, "noise_curb_m").before == 0


def test_incremental_noise_equals_a_fresh_count() -> None:
    """Правка пересчитывает шумозащиту только у бортов рядом с изменёнными посадками; итог тот
    же, что у счёта с нуля."""
    from green.application import effect as module

    trunks = [(x, y) for x in range(20, 71, 4) for y in (4.0, 9.0)]
    site = _site(*trunks)
    belt = [
        _place(i, 100.0 + 4 * (i % 10), 4.0 + 5 * (i // 10), LIME, note=LAWN) for i in range(20)
    ]
    first = _plan(*belt)
    second = _plan(*belt[1:], _place(99, 150.0, 9.0, LIME, note=LAWN))
    module.clear_caches()
    street_effect(first, site, PARAMS)
    stepped = street_effect(second, site, PARAMS)
    module.clear_caches()
    fresh = street_effect(second, site, PARAMS)
    assert [(b.curb_before_m, b.curb_after_m) for b in stepped.noise] == [
        (b.curb_before_m, b.curb_after_m) for b in fresh.noise
    ]
    assert _m(stepped, "curb_green_m").after == pytest.approx(_m(fresh, "curb_green_m").after)
