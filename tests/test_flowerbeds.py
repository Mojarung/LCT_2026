"""Цветники из многолетников на газоне плана (п. 3 ТЗ: травянистые покрытия, элементы скверов).

Цветник - часть газона у тротуара: шириной не меньше flowerbed_min_width_m, площадью около
flowerbed_area_m2, не ближе flowerbed_spacing_m к другому. Смесь и плотность - цветники
принятого проекта Куликовской (config/rules.yaml, flowerbed_mixes): под кронами теневая, на
открытом месте солнечная.
"""

from __future__ import annotations

import itertools
from dataclasses import replace

import shapely
from shapely.geometry import box
from test_pipeline_synthetic import ROOT

from green.application.constraints import work_boundary
from green.application.lawns import WARNING_PREFIX, plan_lawns
from green.application.params import PlanParams
from green.application.surfaces import build_surface_map
from green.domain.norms import LawnKind, PlantingType
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import LifeForm, Placement, Plan, Species, Verdict
from green.infrastructure.config.repositories import YamlRuleBookSource

BOOK = YamlRuleBookSource(ROOT / "config" / "acts.yaml", ROOT / "config" / "rules.yaml").load()
TREE = Species(
    "tree", "липа", "Tilia cordata", 6.0, life_form=LifeForm.TREE_MEDIUM, crown_mature_m=12.0
)
# Газон 400 x 8 м вдоль тротуара 400 x 3 м, всё в границе работ.
BOUNDARY = box(0, 0, 400, 20)
LAWN = box(0, 3, 400, 11)
WALK = box(0, 0, 400, 3)


def _feature(cls: ObjectClass, geometry: object, name: str) -> Feature:
    return Feature(SourceRef("12345678", "00000000", name), name, geometry, object_class=cls)  # type: ignore[arg-type]


def _tree(number: int, x: float, y: float) -> Placement:
    return Placement(f"P{number:05d}", number, PlantingType.TREE, TREE, x, y, Verdict.ALLOWED, ())


def _plan(
    params: PlanParams | None = None,
    *,
    lawn: object = LAWN,
    trees: tuple[Placement, ...] = (),
    book: object = BOOK,
) -> Plan:
    features = [
        _feature(ObjectClass.WORK_BOUNDARY, BOUNDARY, "boundary"),
        _feature(ObjectClass.LAWN, lawn, "lawn"),
        _feature(ObjectClass.SIDEWALK, WALK, "walk"),
    ]
    surface = build_surface_map(features, [], work_boundary(features), 0.5)
    assert surface is not None
    return plan_lawns(
        Plan(placements=trees, rejections=()),
        features=features,
        labels=[],
        surface=surface,
        rulebook=book,  # type: ignore[arg-type]
        params=params or PlanParams(),
    )


def _beds(plan: Plan) -> list:
    return [g for g in plan.lawns if g.kind is LawnKind.FLOWERBED]


def test_flowerbeds_sit_on_the_lawn_by_the_walk_and_keep_their_spacing() -> None:
    plan = _plan()

    beds = _beds(plan)
    # 400 м газона, шаг 150 м: три цветника, не два и не четыре.
    assert len(beds) == 3
    centers = shapely.centroid([b.geometry for b in beds])
    xs = sorted(shapely.get_x(centers))
    assert min(b - a for a, b in itertools.pairwise(xs)) >= 150
    for bed in beds:
        assert LAWN.buffer(1e-6).covers(bed.geometry)
        assert bed.geometry.distance(WALK) <= 3.0
        assert 0.8 * 60 <= bed.area_m2 <= 1.3 * 60
        assert "R-LAWN-FLOWER-001" in bed.rule_ids


def test_flowerbed_is_carved_out_of_its_lawn() -> None:
    plan = _plan()

    assert _beds(plan)
    beds = shapely.union_all([b.geometry for b in _beds(plan)])
    lawns = [g for g in plan.lawns if g.kind is not LawnKind.FLOWERBED]
    assert all(g.geometry.intersection(beds).area < 1e-6 for g in lawns)
    total = sum(g.area_m2 for g in plan.lawns)
    assert abs(total - LAWN.area) < 1.0
    assert [g.number for g in plan.lawns] == list(range(1, len(plan.lawns) + 1))
    assert len({g.lawn_id for g in plan.lawns}) == len(plan.lawns)


def test_plants_follow_the_sunny_mix_density_and_shares() -> None:
    bed = _beds(_plan())[0]

    assert bed.mix == "солнечный цветник: злаки и многолетники"
    counts = {name: count for name, _lat, count in bed.plants}
    assert set(counts) == {
        "Молиния голубая",
        "Щучка дернистая",
        "Котовник Фассена",
        "Очиток видный",
        "Астра бордюрная",
    }
    # 9 шт./м², котовник - четверть смеси.
    assert abs(sum(counts.values()) - 9 * bed.area_m2) <= len(counts)
    assert counts["Котовник Фассена"] == round(9 * bed.area_m2 * 0.25)


def test_flowerbed_under_crowns_takes_the_shade_mix() -> None:
    # Ряд лип с кронами 12 м над всей полосой газона.
    trees = tuple(_tree(i, 6.0 + 8 * i, 7.0) for i in range(50))
    plan = _plan(trees=trees)

    beds = _beds(plan)
    assert beds
    assert {b.mix for b in beds} == {"теневой цветник: многолетники под кронами"}
    assert {name for name, _, _ in beds[0].plants} == {
        "Бруннера сибирская",
        "Герань крупнокорневищная",
        "Манжетка мягкая",
    }


def test_narrow_lawn_gets_no_flowerbed() -> None:
    plan = _plan(lawn=box(0, 3, 400, 5))

    assert not _beds(plan)
    assert plan.lawns


def test_lawn_away_from_the_walk_gets_no_flowerbed() -> None:
    plan = _plan(lawn=box(0, 8, 400, 16))

    assert not _beds(plan)


def test_flowerbeds_are_switched_off_by_the_profile() -> None:
    plan = _plan(PlanParams(flowerbeds=False))

    assert not _beds(plan)
    assert abs(sum(g.area_m2 for g in plan.lawns) - LAWN.area) < 1.0


def test_without_its_rule_no_flowerbed_and_a_warning() -> None:
    book = replace(
        BOOK, lawn_rules=tuple(r for r in BOOK.lawn_rules if r.kind is not LawnKind.FLOWERBED)
    )
    plan = _plan(book=book)

    assert not _beds(plan)
    assert any(w.startswith(WARNING_PREFIX) and "цветник" in w for w in plan.warnings)
