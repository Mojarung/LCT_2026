"""Слои ГИС: GeoJSON и SHP, классы по конфигу, пересчёт координат, зоны в плане.

ТЗ, п. 1: на входе - данные публичных кадастров, функциональное зонирование, элементы
городской среды (data.mos.ru), охранные зоны. Пересчёт WGS 84 -> МСК-Москва проверен на
Кустанайской: точка посадки (16 046,25; -5 738,63) - это 37,75284 в. д., 55,61520 с. ш.
"""

from __future__ import annotations

import json
import zipfile
from typing import TYPE_CHECKING

import shapefile
import shapely
from shapely.geometry import Polygon, box
from test_pipeline_synthetic import ROOT, _street

from green.application.gis_alignment import alignment_notes
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import Verdict
from green.infrastructure.gis.layers import YamlGisLayerSource

if TYPE_CHECKING:
    from pathlib import Path

CONFIG = ROOT / "config" / "geo_layers.yaml"
KUSTANAY_LONLAT = (37.75284, 55.61520)
KUSTANAY_LOCAL = (16046.25, -5738.63)
WGS84_WKT = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
)


def _collection(*features: dict, crs: str | None = None) -> dict:
    data: dict = {"type": "FeatureCollection", "features": list(features)}
    if crs:
        data["crs"] = {"type": "name", "properties": {"name": crs}}
    return data


def _feature(geometry: Polygon, **properties: object) -> dict:
    return {
        "type": "Feature",
        "geometry": shapely.geometry.mapping(geometry),
        "properties": properties,
    }


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_local_layer_keeps_coordinates_and_takes_the_class_from_the_file_name(
    tmp_path: Path,
) -> None:
    zone = box(10, 20, 30, 40)
    path = _write(tmp_path / "охранная_зона_газопровода.geojson", _collection(_feature(zone)))

    layers = YamlGisLayerSource(CONFIG).read([path])

    (feature,) = layers.features
    assert feature.object_class is ObjectClass.ZONE_GAS
    assert feature.geometry.equals(zone)
    assert feature.geometry_error_m == 0.0
    assert "в системе чертежа" in layers.notes[0]


def test_wgs84_layer_is_moved_into_the_drawing_system_with_its_error(tmp_path: Path) -> None:
    lon, lat = KUSTANAY_LONLAT
    square = box(lon - 0.00005, lat - 0.00005, lon + 0.00005, lat + 0.00005)
    path = _write(tmp_path / "здания.geojson", _collection(_feature(square)))

    (feature,) = YamlGisLayerSource(CONFIG).read([path]).features

    centre = feature.geometry.centroid
    assert feature.object_class is ObjectClass.BUILDING
    assert abs(centre.x - KUSTANAY_LOCAL[0]) < 1.0
    assert abs(centre.y - KUSTANAY_LOCAL[1]) < 1.0
    assert feature.geometry_error_m == 1.0  # погрешность пересчёта уходит в запас проверок


def test_declared_crs_and_green_class_attribute_win(tmp_path: Path) -> None:
    """crs GeoJSON (EPSG:3857) пересчитывается; класс из атрибута green_class, ignore - в
    сведения, объект без класса - в предупреждения."""
    x, y = 4_201_900.0, 7_470_000.0  # Москва в Web Mercator
    path = _write(
        tmp_path / "data.geojson",
        _collection(
            _feature(box(x, y, x + 20, y + 20), green_class="zone.power_line"),
            _feature(box(x + 50, y, x + 60, y + 10), green_class="ignore"),
            _feature(box(x + 80, y, x + 90, y + 10), kind="неизвестно"),
            crs="EPSG:3857",
        ),
    )

    layers = YamlGisLayerSource(CONFIG).read([path])

    assert [f.object_class for f in layers.features] == [ObjectClass.ZONE_POWER]
    assert layers.features[0].geometry.bounds[0] < 100_000  # уже метры МСК, не Меркатор
    assert "пересчитан" in layers.notes[0]
    assert any("без класса" in w for w in layers.warnings)


def test_shapefile_in_a_zip_with_prj_is_read_and_moved(tmp_path: Path) -> None:
    lon, lat = KUSTANAY_LONLAT
    base = tmp_path / "охранные_зоны_ЛЭП"
    with shapefile.Writer(str(base), shapeType=shapefile.POLYGON, encoding="utf-8") as writer:
        writer.field("name", "C")
        ring = [(lon, lat), (lon + 0.0002, lat), (lon + 0.0002, lat + 0.0001), (lon, lat + 0.0001)]
        writer.poly([[*ring, ring[0]]])
        writer.record("ВЛ 0,4 кВ")
    base.with_suffix(".prj").write_text(WGS84_WKT, encoding="utf-8")
    archive = tmp_path / "охранные_зоны_ЛЭП.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for suffix in (".shp", ".shx", ".dbf", ".prj"):
            bundle.write(base.with_suffix(suffix), base.with_suffix(suffix).name)

    (feature,) = YamlGisLayerSource(CONFIG).read([archive]).features

    assert feature.object_class is ObjectClass.ZONE_POWER
    assert abs(feature.geometry.bounds[0] - KUSTANAY_LOCAL[0]) < 1.0


def _building(geometry: Polygon, handle: str) -> Feature:
    return Feature(
        ref=SourceRef(file_sha8="0" * 8, xref_hash8="0" * 8, handle=handle),
        layer="Здания",
        geometry=geometry,
        object_class=ObjectClass.BUILDING,
    )


def test_alignment_reports_the_building_shift_and_warns_when_it_is_large() -> None:
    drawing = [_building(box(i * 40, 0, i * 40 + 20, 12), f"b{i}") for i in range(5)]
    near = [_building(box(i * 40 + 0.4, 0.3, i * 40 + 20.4, 12.3), f"g{i}") for i in range(5)]
    far = [_building(box(i * 40 + 8, 6, i * 40 + 28, 18), f"f{i}") for i in range(5)]

    notes, warnings = alignment_notes(near, drawing)
    assert notes
    assert not warnings
    assert "0,50 м" in notes[0]

    notes, warnings = alignment_notes(far, drawing)
    assert not notes
    assert "проверьте систему координат" in warnings[0]


def test_gas_zone_from_a_layer_puts_plantings_inside_it_under_approval(tmp_path: Path) -> None:
    """Посадка, яма которой заходит в зону газопровода из слоя, не проходит как «допускается»:
    нужна письменная санкция эксплуатационной организации (ПП РФ N 878, п. 16)."""
    source = tmp_path / "street.dxf"
    _street(source)
    zone = box(0, 0, 45, 60)
    layer = _write(tmp_path / "охранная_зона_газопровода.geojson", _collection(_feature(zone)))
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load(
        "strict",
        {"shrub_rows": False, "understory": False, "shrub_fill": False, "curb_hedges": False},
    )

    report = container.use_case.execute(
        PlanRequest("gis", source, tmp_path / "out", "strict", params, gis_layers=(layer,))
    )

    plan = report.plan
    reach = zone.buffer(params.planting_radius_m)
    inside = [p for p in plan.placements if reach.contains(shapely.Point(p.x, p.y))]
    assert all(p.verdict is not Verdict.ALLOWED for p in inside)
    rules = {c.rule_id for p in plan.placements for c in p.checks} | {
        c.rule_id for r in plan.rejections for c in r.blocking
    }
    assert "R-GASAREA-TREE-001" in rules
    assert any("охранная_зона_газопровода" in note for note in report.load_notes)
