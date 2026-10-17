"""Город вокруг съёмки для 3D-вида: отбор окружения и разбор ответа Overpass."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pyproj
import pytest

from green.application.city_context import (
    CityContext,
    CityContextService,
    ContextBuilding,
    ContextRoad,
    ContextUnavailableError,
    ring_extent,
    without_survey,
)
from green.application.errors import NotFoundError
from green.infrastructure.gis.osm import (
    OverpassContextSource,
    overpass_query,
    parse_overpass,
)

if TYPE_CHECKING:
    from pathlib import Path

MSK = (
    "+proj=tmerc +lat_0=55.66666666667 +lon_0=37.5 +k=1 +x_0=16.098 +y_0=14.512 "
    "+ellps=bessel +towgs84=316.151,78.924,589.65,-1.57273,2.69209,2.34693,8.4507 "
    "+units=m +no_defs"
)


def square(x: float, y: float, size: float) -> tuple[tuple[float, float], ...]:
    return ((x, y), (x + size, y), (x + size, y + size), (x, y + size))


def test_house_of_the_drawing_wins_over_the_map() -> None:
    context = CityContext(
        extent=(0, 0, 1000, 1000),
        buildings=(
            ContextBuilding(ring=square(10, 10, 20), levels=9, kind="apartments"),
            ContextBuilding(ring=square(600, 600, 20), levels=None, kind="yes"),
            ContextBuilding(ring=square(800, 800, 1), levels=1, kind="kiosk"),
        ),
        trees=((50, 50), (700, 700)),
        roads=(ContextRoad(line=((0, 0), (900, 0)), width_m=6.5, kind="residential"),),
    )
    drawing = [list(square(15, 15, 10))]
    kept = without_survey(context, (0, 0, 100, 100), drawing)
    assert [b.ring[0] for b in kept.buildings] == [(600, 600)]
    assert kept.trees == ((700, 700),)
    assert kept.roads == context.roads
    assert "домов карты, совпавших с домами чертежа: 2" in kept.notes[-1]


def test_ring_extent_widens_survey_on_every_side() -> None:
    assert ring_extent((0, 0, 10, 20), 5) == (-5, -5, 15, 25)


def test_overpass_answer_lands_in_drawing_metres() -> None:
    to_drawing = pyproj.Transformer.from_crs("EPSG:4326", MSK, always_xy=True)
    to_wgs = pyproj.Transformer.from_crs(MSK, "EPSG:4326", always_xy=True)
    corners = [(16000, -5200), (16020, -5200), (16020, -5185), (16000, -5185), (16000, -5200)]
    lonlat = [to_wgs.transform(x, y) for x, y in corners]
    tree_lon, tree_lat = to_wgs.transform(16050, -5150)
    road = [to_wgs.transform(x, y) for x, y in [(15900, -5300), (16100, -5300)]]
    payload = {
        "elements": [
            {
                "type": "way",
                "tags": {"building": "apartments", "building:levels": "17"},
                "geometry": [{"lon": lon, "lat": lat} for lon, lat in lonlat],
            },
            {"type": "node", "tags": {"natural": "tree"}, "lon": tree_lon, "lat": tree_lat},
            {
                "type": "way",
                "tags": {"highway": "secondary"},
                "geometry": [{"lon": lon, "lat": lat} for lon, lat in road],
            },
            {"type": "way", "tags": {"highway": "path"}, "geometry": []},
            {
                "type": "way",
                "tags": {"amenity": "parking"},
                "geometry": [{"lon": lon, "lat": lat} for lon, lat in lonlat],
            },
            {
                "type": "way",
                "tags": {"amenity": "parking", "parking": "underground"},
                "geometry": [{"lon": lon, "lat": lat} for lon, lat in lonlat],
            },
            {
                "type": "way",
                "tags": {"leisure": "park"},
                "geometry": [{"lon": lon, "lat": lat} for lon, lat in lonlat],
            },
        ]
    }
    context = parse_overpass(payload, to_drawing)
    (house,) = context.buildings
    assert house.levels == 17
    assert len(house.ring) == 4
    assert house.ring[0] == pytest.approx((16000, -5200), abs=0.01)
    assert context.trees[0] == pytest.approx((16050, -5150), abs=0.01)
    (street,) = context.roads
    assert street.width_m == 11
    (park,) = context.greens
    assert park.kind == "leisure=park"
    # Подземная стоянка в 3D не видна, открытая - да.
    assert len(context.parkings) == 1
    assert "OpenStreetMap" in context.source


def test_query_asks_buildings_trees_and_roads_in_bbox() -> None:
    query = overpass_query(55.6, 37.7, 55.62, 37.76, 25)
    assert "[out:json][timeout:25]" in query
    assert 'way["building"](55.600000,37.700000,55.620000,37.760000)' in query
    assert 'node["natural"="tree"]' in query
    assert "out geom" in query
    assert 'way["leisure"~"^(park|garden)$"]' in query


def test_no_network_is_an_unavailable_context_not_a_crash() -> None:
    source = OverpassContextSource(
        MSK, urls=["http://127.0.0.1:9/overpass", "http://127.0.0.1:9/mirror"], timeout_s=5
    )
    with pytest.raises(ContextUnavailableError, match=r"127.0.0.1:9.*127.0.0.1:9"):
        source.around((16000, -5200, 16100, -5100))


class _Store:
    def __init__(self, root: Path) -> None:
        self.root = root

    def run_dir(self, run_id: str) -> Path:
        return self.root / run_id

    def artifact(self, run_id: str, name: str) -> Path:
        return self.root / run_id / "output" / name


class _Source:
    def __init__(self) -> None:
        self.calls = 0

    def around(self, extent: tuple[float, float, float, float]) -> CityContext:
        self.calls += 1
        return CityContext(
            extent=extent,
            buildings=(ContextBuilding(ring=square(500, 500, 30), levels=12, kind="yes"),),
            source="test",
        )


def test_service_asks_the_map_once_and_keeps_the_answer(tmp_path: Path) -> None:
    run = tmp_path / "r1" / "output"
    run.mkdir(parents=True)
    scene = {"extent": [0, 0, 100, 100], "buildings": [{"rings": [list(square(5, 5, 10))]}]}
    (run / "scene.json").write_text(json.dumps(scene), encoding="utf-8")
    source = _Source()
    service = CityContextService(source, _Store(tmp_path))  # type: ignore[arg-type]
    first = json.loads(service.for_run("r1"))
    second = json.loads(service.for_run("r1"))
    assert first == second
    assert source.calls == 1
    assert first["buildings"][0]["levels"] == 12
    assert first["source"] == "test"


def test_service_without_source_or_scene_explains_why(tmp_path: Path) -> None:
    (tmp_path / "r2" / "output").mkdir(parents=True)
    off = CityContextService(None, _Store(tmp_path))  # type: ignore[arg-type]
    with pytest.raises(ContextUnavailableError, match="выключено"):
        off.for_run("r2")
    on = CityContextService(_Source(), _Store(tmp_path))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError, match=r"scene.json"):
        on.for_run("r2")


def _tiles(root: Path) -> Path:
    import gzip  # noqa: PLC0415 - нужен только этому помощнику

    house = {"id": "w1", "ring": [[990, 10], [1010, 10], [1010, 20], [990, 20]], "levels": 9}
    tile = {
        "buildings": [{**house, "kind": "apartments"}],
        "roads": [{"id": "w2", "line": [[0, 0], [1500, 0]], "width_m": 6.5, "kind": "service"}],
        "greens": [],
        "trees": [{"id": "n3", "xy": [500, 500]}],
    }
    for key in ("0_0", "1_0"):
        (root / f"{key}.json.gz").write_bytes(gzip.compress(json.dumps(tile).encode()))
    index = {
        "version": 1,
        "tile_m": 1000,
        "crs": MSK,
        "source": "osm-test",
        "tiles": ["0_0", "1_0"],
    }
    (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return root


def test_tiles_on_disk_give_the_city_without_network(tmp_path: Path) -> None:
    from green.infrastructure.gis.osm import TileContextSource  # noqa: PLC0415

    source = TileContextSource(_tiles(tmp_path))
    context = source.around((0, -100, 1900, 900))
    # Дом и дорога лежат в двух квадратах, но в окружении - по одному разу.
    assert len(context.buildings) == 1
    assert len(context.roads) == 1
    assert context.trees == ((500, 500),)
    assert context.source == "osm-test"
    with pytest.raises(ContextUnavailableError, match="вне выгрузки"):
        source.around((50000, 50000, 51000, 51000))


def test_chain_falls_back_to_the_next_source(tmp_path: Path) -> None:
    from green.infrastructure.gis.osm import (  # noqa: PLC0415
        ChainedContextSource,
        TileContextSource,
    )

    chain = ChainedContextSource([TileContextSource(_tiles(tmp_path)), _Source()])
    assert chain.around((50000, 50000, 51000, 51000)).source == "test"
    assert chain.around((0, 0, 900, 900)).source == "osm-test"
