"""Слой функционального зонирования: вид территории по словам атрибутов, место посадки в плане."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import shapely
from shapely.geometry import box
from test_pipeline_synthetic import ROOT, _street

from green.application.placement import MODE_LABELS
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.domain.objects import ObjectClass
from green.infrastructure.gis.layers import YamlGisLayerSource

if TYPE_CHECKING:
    from pathlib import Path

    from green.domain.planting import Plan

CONFIG = ROOT / "config" / "geo_layers.yaml"


def _layer(path: Path, *zones: tuple[shapely.Polygon, str]) -> Path:
    data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": shapely.geometry.mapping(zone),
                "properties": {"NAME": name},
            }
            for zone, name in zones
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_zone_kind_comes_from_attribute_words(tmp_path: Path) -> None:
    path = _layer(
        tmp_path / "функциональное_зонирование.geojson",
        (box(0, 0, 10, 10), "Жилая застройка, дворовая территория"),
        (box(20, 0, 30, 10), "Сквер"),
        (box(40, 0, 50, 10), "Улично-дорожная сеть"),
        (box(60, 0, 70, 10), "Промзона"),
    )
    layers = YamlGisLayerSource(CONFIG).read([path])
    classes = [f.object_class for f in layers.features]
    assert classes == [
        ObjectClass.TERRITORY_YARD,
        ObjectClass.TERRITORY_SQUARE,
        ObjectClass.TERRITORY_STREET,
    ]


@pytest.fixture(scope="module")
def yard_plan(tmp_path_factory: pytest.TempPathFactory) -> Plan:
    work = tmp_path_factory.mktemp("zoning")
    source = work / "street.dxf"
    _street(source)
    layer = _layer(work / "зонирование.geojson", (box(-10, -10, 130, 70), "Дворовая территория"))
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=work / "runs"))
    params = container.profiles.load("strict", {"max_rejections": 50})
    report = container.use_case.execute(
        PlanRequest("zoning", source, work / "out", "strict", params, gis_layers=(layer,))
    )
    return report.plan


def test_every_planting_in_the_yard_zone_is_placed_in_the_yard(yard_plan: Plan) -> None:
    assert yard_plan.placements
    assert {p.place for p in yard_plan.placements} == {"yard"}


def test_no_alley_in_a_yard(yard_plan: Plan) -> None:
    assert not [p for p in yard_plan.placements if MODE_LABELS["alley"] in p.notes]


def test_species_follow_the_yard_category(yard_plan: Plan) -> None:
    assert all(p.species.categories.get("yards") != "minus" for p in yard_plan.placements)
    quality = yard_plan.quality
    assert quality is not None
    category = next(t for t in quality.terms if t.key == "category")
    assert "дворов" in category.note


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Зона парковки", None),
        ("Паркинг", None),
        ("Детский сад", None),
        ("Нежилая застройка", None),
        ("ГБУ Жилищник района", None),
        ("Жилая застройка", ObjectClass.TERRITORY_YARD),
        ("Парк Победы", ObjectClass.TERRITORY_PARK),
        ("Сад Эрмитаж", ObjectClass.TERRITORY_PARK),
        ("Бульвар", ObjectClass.TERRITORY_SQUARE),
    ],
)
def test_zone_words_do_not_catch_look_alikes(
    tmp_path: Path, name: str, expected: ObjectClass | None
) -> None:
    path = _layer(tmp_path / "функциональное_зонирование.geojson", (box(0, 0, 10, 10), name))
    classes = [f.object_class for f in YamlGisLayerSource(CONFIG).read([path]).features]
    assert classes == ([expected] if expected else [])
