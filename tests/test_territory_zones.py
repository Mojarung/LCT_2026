"""Особо охраняемые и природные территории из слоёв ГИС (ТЗ, п. 2: «иные зоны охраны»).

369-ПП, приложение 2, п. 5.2: инвазивные виды группы III (дуб красный, дёрен белый) не
высаживаются на особо охраняемых зелёных и природных территориях, а на иных территориях
зелёного фонда допускаются с условием (п. 5.3). Раньше тип территории задавал только профиль
- один на весь чертёж. Теперь посадка внутри слоя ООПТ или природного комплекса получает свой
тип территории, и вид группы III там не ставится.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
import shapely
from shapely.geometry import box
from test_pipeline_synthetic import ROOT

from green.application.assortment.context import site_context
from green.application.assortment.filters import species_verdict
from green.application.params import PlanParams
from green.application.places import forget_places, place_map, with_places
from green.application.validation import validate_plan
from green.domain.norms import PlantingType
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import LifeForm, Placement, Plan, Species, Verdict
from green.infrastructure.config.repositories import YamlRuleBookSource
from green.infrastructure.gis.layers import YamlGisLayerSource

if TYPE_CHECKING:
    from pathlib import Path

BOOK = YamlRuleBookSource(ROOT / "config" / "acts.yaml", ROOT / "config" / "rules.yaml").load()
RED_OAK = Species(
    "quercus_rubra", "дуб красный", "Quercus rubra", 8.0, life_form=LifeForm.TREE_LARGE
)


def _feature(cls: ObjectClass, geometry: object, name: str) -> Feature:
    return Feature(SourceRef("12345678", "00000000", name), name, geometry, object_class=cls)  # type: ignore[arg-type]


def _placement(number: int, x: float, y: float) -> Placement:
    return Placement(
        f"P{number:05d}", number, PlantingType.TREE, RED_OAK, x, y, Verdict.ALLOWED, ()
    )


FEATURES = (
    _feature(ObjectClass.TERRITORY_PROTECTED, box(0, 0, 50, 50), "оопт"),
    _feature(ObjectClass.TERRITORY_NATURAL, box(100, 0, 150, 50), "пк"),
)


def _placed() -> Plan:
    forget_places()
    plan = Plan(
        placements=(_placement(1, 10, 10), _placement(2, 120, 10), _placement(3, 300, 10)),
        rejections=(),
    )
    return with_places(plan, place_map(FEATURES))


def test_places_inside_protected_and_natural_zones_get_their_territory() -> None:
    plan = _placed()

    assert [p.territory for p in plan.placements] == ["protected_green", "natural", ""]


def test_invasive_group_three_is_refused_inside_the_zone_and_allowed_outside() -> None:
    plan = _placed()
    params = PlanParams()

    inside = species_verdict(RED_OAK, site_context(plan.placements[0]), BOOK, params)
    natural = species_verdict(RED_OAK, site_context(plan.placements[1]), BOOK, params)
    outside = species_verdict(RED_OAK, site_context(plan.placements[2]), BOOK, params)

    assert not inside.allowed
    assert inside.blocking is not None
    assert "особо охраняемая зелёная территория" in inside.blocking.text
    assert inside.blocking.rule_id == "R-INV-QUERUB-001"
    assert not natural.allowed
    assert outside.allowed


def test_profile_territory_still_applies_where_no_zone_is_drawn() -> None:
    plan = _placed()
    params = PlanParams(territory="natural")

    outside = species_verdict(RED_OAK, site_context(plan.placements[2]), BOOK, params)

    assert not outside.allowed


def test_zone_territory_is_kept_by_a_moved_placement_only_after_recount() -> None:
    plan = _placed()
    moved = replace(plan.placements[0], x=300.0, place="", territory="")

    again = with_places(replace(plan, placements=(moved,)), place_map(FEATURES))

    assert again.placements[0].territory == ""


def test_independent_check_refuses_group_three_inside_the_zone() -> None:
    """Проверка плана (validation) не верит подбору: дуб красный в ООПТ - нарушение."""
    plan = _placed()
    inside = replace(plan, placements=(plan.placements[0],))

    result = validate_plan(
        inside,
        list(FEATURES),
        [],
        BOOK,
        PlanParams(require_soil=False, require_utility_data=False, require_work_boundary=False),
    )

    assert any(issue.code == "species_rule" for issue in result.issues)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ООПТ_Москва.geojson", ObjectClass.TERRITORY_NATURAL),
        ("природный_комплекс.geojson", ObjectClass.TERRITORY_NATURAL),
        ("особо_охраняемые_зелёные_территории.geojson", ObjectClass.TERRITORY_PROTECTED),
        ("ООЗТ.geojson", ObjectClass.TERRITORY_PROTECTED),
    ],
)
def test_gis_layer_of_protected_and_natural_territories_is_recognised(
    tmp_path: Path, name: str, expected: ObjectClass
) -> None:
    path = tmp_path / name
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": shapely.geometry.mapping(box(0, 0, 10, 10)),
                        "properties": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    (feature,) = YamlGisLayerSource(ROOT / "config" / "geo_layers.yaml").read([path]).features

    assert feature.object_class is expected
