"""Окружение участка из OpenStreetMap через Overpass API.

Запрос - прямоугольник чертежа, пересчитанный в долготу и широту; ответ - дома, отдельные
деревья и дороги с геометрией (`out geom`), они пересчитываются обратно в систему чертежа
(`drawing_crs` из config/geo_layers.yaml, МСК-Москва). Данные OpenStreetMap - ODbL, источник
указывается в ответе и в 3D-виде.

Сеть на стенде «при необходимости», поэтому любая ошибка сети, тайм-аут или кривой ответ -
`ContextUnavailableError`: 3D-вид остаётся без окружения, прогон это не задевает.
"""

from __future__ import annotations

import gzip
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any

import pyproj
import yaml

from green.application.city_context import (
    CityContext,
    ContextArea,
    ContextBuilding,
    ContextRoad,
    ContextUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from green.application.city_context import Extent, Point
    from green.application.ports import CityContextSource

# Основной сервер и зеркало Mail.ru: очередь Overpass бывает длинной, и запрос идёт дальше
# по списку, если сервер не ответил.
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
SOURCE = "© участники OpenStreetMap, ODbL"
USER_AGENT = "green-lct2026/1.0 (3D context for street greening plans)"

# Ширина проезжей части по классу дороги, метры: типовые профили московских улиц.
ROAD_WIDTH_M = {
    "motorway": 22.0,
    "trunk": 18.0,
    "primary": 14.0,
    "secondary": 11.0,
    "tertiary": 9.0,
    "unclassified": 6.5,
    "residential": 6.5,
    "living_street": 6.0,
    "service": 4.5,
    "pedestrian": 5.0,
    "footway": 2.0,
}
# Зелёные зоны: (ключ, значения) тегов OpenStreetMap.
GREEN_TAGS = {
    "landuse": ("grass", "forest", "meadow", "recreation_ground", "village_green"),
    "leisure": ("park", "garden"),
    "natural": ("wood", "scrub"),
}
# Стоянки под открытым небом: подземные и многоэтажные в 3D не видны.
HIDDEN_PARKING = frozenset({"underground", "multi-storey", "rooftop"})
_LEVELS = re.compile(r"\d+")
_STOREY_M = 3.0
# Замкнутый контур дома в ответе Overpass: три вершины и повтор первой.
_RING_POINTS = 4
_LINE_POINTS = 2


def drawing_crs(geo_layers: Path) -> str:
    """Система координат чертежа из config/geo_layers.yaml."""
    data = yaml.safe_load(geo_layers.read_text(encoding="utf-8"))
    return str(data["drawing_crs"])


def overpass_query(south: float, west: float, north: float, east: float, timeout_s: int) -> str:
    bbox = f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}"
    roads = "|".join(ROAD_WIDTH_M)
    parts = [
        f'way["building"]({bbox});',
        f'node["natural"="tree"]({bbox});',
        f'way["highway"~"^({roads})$"]({bbox});',
        *(f'way["{key}"~"^({"|".join(values)})$"]({bbox});' for key, values in GREEN_TAGS.items()),
        f'way["amenity"="parking"]({bbox});',
    ]
    return f"[out:json][timeout:{timeout_s}];({''.join(parts)});out geom qt;"


def levels_of(tags: dict[str, Any]) -> int | None:
    for key in ("building:levels", "levels"):
        match = _LEVELS.search(str(tags.get(key, "")))
        if match:
            return max(1, min(int(match.group()), 100))
    height = _LEVELS.search(str(tags.get("height", "")))
    if height:
        return max(1, round(int(height.group()) / _STOREY_M))
    return None


def _green_kind(tags: dict[str, Any]) -> str | None:
    for key, values in GREEN_TAGS.items():
        if tags.get(key) in values:
            return f"{key}={tags[key]}"
    return None


def is_open_parking(tags: dict[str, Any]) -> bool:
    return tags.get("amenity") == "parking" and tags.get("parking") not in HIDDEN_PARKING


def _closed(ring: tuple[Point, ...]) -> tuple[Point, ...] | None:
    """Замкнутый контур без повтора первой вершины, или None."""
    return ring[:-1] if len(ring) >= _RING_POINTS and ring[0] == ring[-1] else None


def parse_overpass(payload: dict[str, Any], to_drawing: pyproj.Transformer) -> CityContext:
    """Ответ Overpass -> окружение в метрах чертежа."""
    buildings: list[ContextBuilding] = []
    trees: list[Point] = []
    roads: list[ContextRoad] = []
    greens: list[ContextArea] = []
    parkings: list[ContextArea] = []

    def points(geometry: list[dict[str, float]]) -> tuple[Point, ...]:
        xs, ys = to_drawing.transform([p["lon"] for p in geometry], [p["lat"] for p in geometry])
        return tuple((float(x), float(y)) for x, y in zip(xs, ys, strict=True))

    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        if element.get("type") == "node" and tags.get("natural") == "tree":
            x, y = to_drawing.transform(element["lon"], element["lat"])
            trees.append((float(x), float(y)))
            continue
        geometry = element.get("geometry")
        if element.get("type") != "way" or not geometry:
            continue
        shape = points(geometry)
        green = _green_kind(tags)
        if "building" in tags and (ring := _closed(shape)):
            buildings.append(
                ContextBuilding(ring=ring, levels=levels_of(tags), kind=str(tags["building"]))
            )
        elif green and (ring := _closed(shape)):
            greens.append(ContextArea(ring=ring, kind=green))
        elif is_open_parking(tags) and (ring := _closed(shape)):
            parkings.append(ContextArea(ring=ring, kind="parking"))
        elif tags.get("highway") in ROAD_WIDTH_M and len(shape) >= _LINE_POINTS:
            road = str(tags["highway"])
            roads.append(ContextRoad(line=shape, width_m=ROAD_WIDTH_M[road], kind=road))
    return CityContext(
        extent=(0.0, 0.0, 0.0, 0.0),
        buildings=tuple(buildings),
        trees=tuple(trees),
        roads=tuple(roads),
        greens=tuple(greens),
        parkings=tuple(parkings),
        source=SOURCE,
    )


class OverpassContextSource:
    """Окружение из OpenStreetMap: запрос в Overpass, пересчёт в систему чертежа."""

    def __init__(self, crs: str, urls: Sequence[str] = OVERPASS_URLS, timeout_s: int = 90) -> None:
        target = pyproj.CRS.from_user_input(crs)
        self._to_drawing = pyproj.Transformer.from_crs("EPSG:4326", target, always_xy=True)
        self._to_wgs = pyproj.Transformer.from_crs(target, "EPSG:4326", always_xy=True)
        self._urls = tuple(urls)
        self._timeout_s = timeout_s

    def around(self, extent: Extent) -> CityContext:
        min_x, min_y, max_x, max_y = extent
        lons, lats = self._to_wgs.transform(
            [min_x, max_x, max_x, min_x], [min_y, min_y, max_y, max_y]
        )
        query = overpass_query(min(lats), min(lons), max(lats), max(lons), self._timeout_s)
        payload = self._fetch(query)
        context = parse_overpass(payload, self._to_drawing)
        return CityContext(
            extent=extent,
            buildings=context.buildings,
            trees=context.trees,
            roads=context.roads,
            greens=context.greens,
            parkings=context.parkings,
            source=context.source,
        )

    def _fetch(self, query: str) -> dict[str, Any]:
        errors: list[str] = []
        for url in self._urls:
            request = urllib.request.Request(  # noqa: S310 - адреса Overpass из настроек, https
                url,
                data=urllib.parse.urlencode({"data": query}).encode(),
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self._timeout_s + 5) as response:  # noqa: S310
                    return json.loads(response.read())
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
                errors.append(f"{urllib.parse.urlsplit(url).netloc}: {error}")
        msg = "OpenStreetMap недоступен: " + "; ".join(errors)
        raise ContextUnavailableError(msg)


class TileContextSource:
    """Окружение из квадратов OpenStreetMap на диске (tools/osm_moscow.py): без сети.

    Квадраты - в системе чертежа, по `tile_m` метров; объект, задевающий несколько квадратов,
    лежит в каждом, повторы убираются по id. Нет ни одного квадрата для участка (улица вне
    выгрузки) - `ContextUnavailableError`, и сервис может спросить Overpass.
    """

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
        self._tile_m = float(index["tile_m"])
        self._tiles = set(index["tiles"])
        self._source = str(index["source"])

    def around(self, extent: Extent) -> CityContext:
        min_x, min_y, max_x, max_y = extent
        keys = [
            f"{ix}_{iy}"
            for ix in range(int(min_x // self._tile_m), int(max_x // self._tile_m) + 1)
            for iy in range(int(min_y // self._tile_m), int(max_y // self._tile_m) + 1)
        ]
        present = [key for key in keys if key in self._tiles]
        if not present:
            msg = "Участок вне выгрузки OpenStreetMap на диске"
            raise ContextUnavailableError(msg)
        found = _TileItems(extent)
        for key in present:
            found.add(json.loads(gzip.decompress((self._dir / f"{key}.json.gz").read_bytes())))
        return CityContext(
            extent=extent,
            buildings=tuple(found.buildings),
            trees=tuple(found.trees),
            roads=tuple(found.roads),
            greens=tuple(found.greens),
            parkings=tuple(found.parkings),
            source=self._source,
        )


class _TileItems:
    """Объекты квадратов в прямоугольнике участка, без повторов по id."""

    def __init__(self, extent: Extent) -> None:
        self._extent = extent
        self._seen: set[str] = set()
        self.buildings: list[ContextBuilding] = []
        self.trees: list[Point] = []
        self.roads: list[ContextRoad] = []
        self.greens: list[ContextArea] = []
        self.parkings: list[ContextArea] = []

    def _new(self, item: dict[str, Any], points: list[list[float]]) -> bool:
        if item["id"] in self._seen:
            return False
        min_x, min_y, max_x, max_y = self._extent
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        if max(xs) < min_x or min(xs) > max_x or max(ys) < min_y or min(ys) > max_y:
            return False
        self._seen.add(item["id"])
        return True

    def add(self, tile: dict[str, list[dict[str, Any]]]) -> None:
        for item in tile["buildings"]:
            if self._new(item, item["ring"]):
                self.buildings.append(
                    ContextBuilding(
                        ring=_pts(item["ring"]), levels=item["levels"], kind=item["kind"]
                    )
                )
        for item in tile["roads"]:
            if self._new(item, item["line"]):
                self.roads.append(
                    ContextRoad(line=_pts(item["line"]), width_m=item["width_m"], kind=item["kind"])
                )
        for name, target in (("greens", self.greens), ("parkings", self.parkings)):
            for item in tile.get(name, []):
                if self._new(item, item["ring"]):
                    target.append(ContextArea(ring=_pts(item["ring"]), kind=item["kind"]))
        for item in tile["trees"]:
            if self._new(item, [item["xy"]]):
                self.trees.append((item["xy"][0], item["xy"][1]))


def _pts(points: list[list[float]]) -> tuple[Point, ...]:
    return tuple((p[0], p[1]) for p in points)


class ChainedContextSource:
    """Источники по очереди: квадраты на диске, потом Overpass. Ошибки складываются в одну."""

    def __init__(self, sources: Sequence[CityContextSource]) -> None:
        self._sources = tuple(sources)

    def around(self, extent: Extent) -> CityContext:
        errors: list[str] = []
        for source in self._sources:
            try:
                return source.around(extent)
            except ContextUnavailableError as error:
                errors.append(str(error))
        raise ContextUnavailableError("; ".join(errors) or "Окружение выключено")
