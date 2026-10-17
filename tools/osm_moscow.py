# ruff: noqa: INP001, T201, PLR2004 - консольный инструмент подготовки данных
"""Нарезать OpenStreetMap Москвы на квадраты для 3D-вида без интернета.

Город вокруг съёмки (GET /runs/{id}/context) сервис берёт сначала из этих квадратов, и только
если их нет - из Overpass. На стенде жюри сети может не быть, поэтому квадраты кладутся в
образ (data/osm/moscow, Dockerfile). Источник - выгрузка BBBike «Moscow» (OSM PBF, ODbL):
прямоугольник 37,32-37,88 в. д., 55,57-55,92 с. ш., Москва в МКАД с запасом.

Из выгрузки берутся только дома, дороги, отдельные деревья и зелёные зоны - то же, что
спрашивает Overpass (green.infrastructure.gis.osm), координаты сразу в системе чертежа
(drawing_crs из config/geo_layers.yaml), квадраты по 1 км в этой системе, gzip JSON. Объект,
задевающий несколько квадратов, лежит в каждом с одним id; сервис убирает повторы.

    curl -L -o dataset/osm_src/Moscow.osm.pbf \\
        https://download.bbbike.org/osm/bbbike/Moscow/Moscow.osm.pbf
    uv run --with osmium python tools/osm_moscow.py dataset/osm_src/Moscow.osm.pbf data/osm/moscow
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import osmium
import pyproj

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from green.infrastructure.gis.osm import (  # noqa: E402 - путь к пакету добавлен выше
    GREEN_TAGS,
    ROAD_WIDTH_M,
    drawing_crs,
    is_open_parking,
    levels_of,
)

TILE_M = 1000


class Collector(osmium.SimpleHandler):
    def __init__(self, transformer: pyproj.Transformer) -> None:
        super().__init__()
        self._to = transformer
        self.items: list[tuple[str, dict[str, object], list[tuple[float, float]]]] = []

    def _xy(self, nodes: osmium.osm.WayNodeList) -> list[tuple[float, float]] | None:
        try:
            lons = [n.lon for n in nodes]
            lats = [n.lat for n in nodes]
        except osmium.InvalidLocationError:
            return None
        xs, ys = self._to.transform(lons, lats)
        return [(round(float(x), 2), round(float(y), 2)) for x, y in zip(xs, ys, strict=True)]

    def node(self, n: osmium.osm.Node) -> None:
        if n.tags.get("natural") == "tree" and n.location.valid():
            x, y = self._to.transform(n.location.lon, n.location.lat)
            self.items.append(("tree", {"id": f"n{n.id}"}, [(round(x, 2), round(y, 2))]))

    def way(self, w: osmium.osm.Way) -> None:
        tags = dict(w.tags)
        closed = len(w.nodes) >= 4 and w.nodes[0].ref == w.nodes[-1].ref
        green = next(
            (f"{k}={tags[k]}" for k, values in GREEN_TAGS.items() if tags.get(k) in values), None
        )
        kind: str | None = None
        props: dict[str, object] = {"id": f"w{w.id}"}
        if "building" in tags and closed:
            kind = "building"
            props |= {"levels": levels_of(tags), "kind": tags["building"]}
        elif green and closed:
            kind = "green"
            props |= {"kind": green}
        elif is_open_parking(tags) and closed:
            kind = "parking"
            props |= {"kind": "parking"}
        elif tags.get("highway") in ROAD_WIDTH_M and len(w.nodes) >= 2:
            kind = "road"
            props |= {"kind": tags["highway"], "width_m": ROAD_WIDTH_M[tags["highway"]]}
        if kind is None:
            return
        points = self._xy(w.nodes)
        if points:
            if kind != "road":
                points = points[:-1]
            self.items.append((kind, props, points))


def tiles_of(points: list[tuple[float, float]]) -> list[tuple[int, int]]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [
        (ix, iy)
        for ix in range(int(min(xs) // TILE_M), int(max(xs) // TILE_M) + 1)
        for iy in range(int(min(ys) // TILE_M), int(max(ys) // TILE_M) + 1)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pbf", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    crs = drawing_crs(ROOT / "config" / "geo_layers.yaml")
    transformer = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    collector = Collector(transformer)
    collector.apply_file(str(args.pbf), locations=True)
    tiles: dict[tuple[int, int], dict[str, list[object]]] = defaultdict(
        lambda: {"buildings": [], "trees": [], "roads": [], "greens": [], "parkings": []}
    )
    counts: dict[str, int] = defaultdict(int)
    for kind, props, points in collector.items:
        counts[kind] += 1
        for key in tiles_of(points):
            tile = tiles[key]
            if kind == "tree":
                tile["trees"].append({"id": props["id"], "xy": list(points[0])})
            elif kind == "road":
                tile["roads"].append({**props, "line": [list(p) for p in points]})
            elif kind == "green":
                tile["greens"].append({**props, "ring": [list(p) for p in points]})
            elif kind == "parking":
                tile["parkings"].append({**props, "ring": [list(p) for p in points]})
            else:
                tile["buildings"].append({**props, "ring": [list(p) for p in points]})
    args.out.mkdir(parents=True, exist_ok=True)
    total = 0
    for (ix, iy), tile in tiles.items():
        path = args.out / f"{ix}_{iy}.json.gz"
        path.write_bytes(gzip.compress(json.dumps(tile, separators=(",", ":")).encode(), 9))
        total += path.stat().st_size
    index = {
        "version": 1,
        "tile_m": TILE_M,
        "crs": crs,
        "source": "© участники OpenStreetMap, ODbL; выгрузка BBBike Moscow",
        "pbf": args.pbf.name,
        "pbf_mtime": time.strftime("%Y-%m-%d", time.gmtime(args.pbf.stat().st_mtime)),
        "tiles": sorted(f"{ix}_{iy}" for ix, iy in tiles),
        "counts": dict(counts),
    }
    (args.out / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    print(
        f"{len(tiles)} квадратов, {total / 1e6:.1f} МБ, {dict(counts)}, "
        f"{time.perf_counter() - started:.0f} с"
    )


if __name__ == "__main__":
    main()
