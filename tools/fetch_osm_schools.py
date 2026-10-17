"""Здания школ и детских садов Москвы из OpenStreetMap для правила 10 м (743-ПП, табл. 3.6.1).

В топоплане Мосгеотреста назначения здания нет (docs/notes/21-slopes-and-schools.md): школа -
такое же «Н», как магазин. Выгрузка OSM даёт контуры зданий школ и детсадов: здания с
building=school|kindergarten и все здания внутри территорий amenity=school|kindergarten.
Здание внутри территории берётся, только если оно не меньше 300 м² и его центр внутри
территории. Сервис берёт из контуров только здания чертежа, совпавшие с ними (application/schools.py).
Данные OSM - ODbL, © участники OpenStreetMap.

    uv run python tools/fetch_osm_schools.py [--raw сохранённый ответ Overpass]
Итог: config/gis/osm_schools_moscow.geojson.
"""
# ruff: noqa: INP001, T201, S310
from __future__ import annotations

import argparse
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "config" / "gis" / "osm_schools_moscow.geojson"
QUERY = """[out:json][timeout:300];
area["name"="Москва"]["admin_level"="4"]->.msk;
(
  way["building"~"^(school|kindergarten)$"](area.msk);
  way["amenity"~"^(school|kindergarten)$"]["building"](area.msk);
)->.direct;
way["amenity"~"^(school|kindergarten)$"](area.msk)->.grounds;
.grounds map_to_area ->.ga;
way["building"](area.ga)->.inside;
(.direct; .inside; .grounds;);
out tags geom;"""
# Здание внутри территории школы - школьное, только если оно не мелкое (сараи, ТП, гаражи -
# ревью 17.10.2026: 1389 контуров меньше 100 м²) и его центр внутри территории (Overpass
# (area) берёт и дома у забора, у которых одна вершина внутри).
MIN_INSIDE_M2 = 300.0
_M_PER_DEG = 111_320.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path)
    args = parser.parse_args()
    if args.raw:
        data = json.loads(args.raw.read_text(encoding="utf-8"))
    else:
        body = urllib.parse.urlencode({"data": QUERY}).encode()
        request = urllib.request.Request(
            "https://overpass-api.de/api/interpreter", body,
            {"User-Agent": "green-lct2026/1.0"})
        with urllib.request.urlopen(request, timeout=600) as response:
            data = json.loads(response.read().decode("utf-8"))
    from shapely.geometry import Polygon  # noqa: PLC0415 - инструмент, не сервис

    grounds, buildings = [], []
    for element in data["elements"]:
        geometry = element.get("geometry") or []
        ring = [(round(p["lon"], 6), round(p["lat"], 6)) for p in geometry]
        if len(ring) < 4 or ring[0] != ring[-1]:
            continue
        tags = element.get("tags", {})
        amenity, building = tags.get("amenity", ""), tags.get("building", "")
        if amenity in {"school", "kindergarten"} and not building:
            grounds.append(Polygon(ring))
        elif building:
            direct = building in {"school", "kindergarten"} or amenity in {"school", "kindergarten"}
            kind = "kindergarten" if "kindergarten" in (building, amenity) else "school"
            buildings.append((element["id"], ring, direct, kind))
    features = []
    for way, ring, direct, kind in buildings:
        polygon = Polygon(ring)
        if not direct:
            lat = polygon.centroid.y
            area = polygon.area * _M_PER_DEG**2 * math.cos(math.radians(lat))
            point = polygon.representative_point()
            if area < MIN_INSIDE_M2 or not any(g.contains(point) for g in grounds):
                continue
        features.append({
            "type": "Feature",
            "properties": {"green_class": "school", "osm_way": way, "kind": kind,
                           "tagged": direct},
            "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]},
        })
    collection = {
        "type": "FeatureCollection",
        # Явная система координат: вся Москва шире градуса, без неё слой не узнать за WGS 84.
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "source": "OpenStreetMap (ODbL), Overpass API, "
        + data.get("osm3s", {}).get("timestamp_osm_base", ""),
        "features": features,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(collection, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"зданий {len(features)} -> {OUT} ({OUT.stat().st_size / 1e6:.1f} МБ)")


if __name__ == "__main__":
    main()
