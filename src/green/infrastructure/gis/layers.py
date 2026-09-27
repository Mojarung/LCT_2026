"""Чтение слоёв ГИС (GeoJSON, SHP) в объекты подосновы в координатах чертежа.

Класс объекта задаёт config/geo_layers.yaml: по имени файла, по атрибуту или прямо атрибутом
green_class. Координаты: явная система слоя (crs GeoJSON, .prj SHP) или долгота и широта
пересчитываются в систему чертежа (МСК-Москва); метровые значения без системы координат
считаются уже местными. Погрешность пересчёта уходит в запас проверок расстояний, как
погрешность геометрии чертежа.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import pyproj
import shapefile
import shapely
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator
from shapely.geometry import shape

from green.application.errors import InputError
from green.application.ports import GisLayers
from green.application.wording import counted
from green.domain.objects import NO_XREF, Feature, ObjectClass, SourceRef

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from shapely.geometry.base import BaseGeometry

FROM_ATTRIBUTE = "from_attribute"
GEOJSON_SUFFIXES = frozenset({".geojson", ".json"})
SHAPE_SUFFIXES = frozenset({".zip", ".shp"})
SUFFIXES = GEOJSON_SUFFIXES | SHAPE_SUFFIXES
_LONLAT_LIMIT = (180.0, 90.0)
_LONLAT_SPAN = 1.0


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    file: str | None = None
    attribute: str | None = None
    value: str | None = None
    # Регулярное выражение по любому значению атрибутов: у слоёв зонирования имя поля с видом
    # территории у каждого источника своё (NAME, VID, TYPE, «Наименование»).
    any_value: str | None = None
    object_class: str
    note: str = ""

    @field_validator("file", "value", "any_value")
    @classmethod
    def _regex(cls, value: str | None) -> str | None:
        if value is not None:
            re.compile(value)
        return value

    @field_validator("object_class")
    @classmethod
    def _class(cls, value: str) -> str:
        if value != FROM_ATTRIBUTE:
            ObjectClass(value)
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1]
    drawing_crs: str
    transform_error_m: float = Field(ge=0, le=100)
    rules: tuple[_Rule, ...]


@dataclass(frozen=True, slots=True)
class _Record:
    geometry: BaseGeometry
    properties: Mapping[str, Any]


class YamlGisLayerSource:
    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self, paths: Sequence[Path]) -> GisLayers:
        config = _Config.model_validate(yaml.safe_load(self._path.read_text(encoding="utf-8")))
        target = pyproj.CRS.from_user_input(config.drawing_crs)
        features: list[Feature] = []
        notes: list[str] = []
        warnings: list[str] = []
        for path in paths:
            layer = _read_layer(path, config, target)
            features += layer.features
            notes += layer.notes
            warnings += layer.warnings
        return GisLayers(tuple(features), tuple(notes), tuple(warnings))


def _read_layer(path: Path, config: _Config, target: pyproj.CRS) -> GisLayers:
    name = path.name
    suffix = path.suffix.lower()
    if suffix not in SUFFIXES:
        raise InputError(
            f"Слой ГИС {name}: ожидается GeoJSON (.geojson, .json) или SHP (.zip, .shp)"
        )
    records, source_crs = _geojson(path) if suffix in GEOJSON_SUFFIXES else _shapefile(path)
    if not records:
        return GisLayers(warnings=(f"Слой ГИС {name}: объектов нет",))
    crs, how = _source_crs(records, source_crs)
    error = 0.0
    if crs is not None:
        transformer = pyproj.Transformer.from_crs(crs, target, always_xy=True)

        def move(xy: np.ndarray) -> np.ndarray:
            x, y = transformer.transform(xy[:, 0], xy[:, 1])
            return np.column_stack([x, y])

        records = [_Record(shapely.transform(r.geometry, move), r.properties) for r in records]
        error = config.transform_error_m
    sha8 = hashlib.blake2b(path.read_bytes(), digest_size=4).hexdigest()
    features: list[Feature] = []
    counts: Counter[str] = Counter()
    skipped = 0
    rule_notes: set[str] = set()
    for index, record in enumerate(records):
        rule, object_class = _classify(name, record.properties, config.rules)
        if object_class is None:
            skipped += 1
            continue
        if rule is not None and rule.note:
            rule_notes.add(rule.note)
        counts[object_class.value] += 1
        if object_class is ObjectClass.IGNORE:
            continue
        features.append(
            Feature(
                ref=SourceRef(file_sha8=sha8, xref_hash8=NO_XREF, handle=f"gis{index}"),
                layer=f"ГИС {name}",
                geometry=record.geometry,
                object_class=object_class,
                geometry_error_m=error,
                source_entity_type="gis",
            )
        )
    classes = ", ".join(f"{cls} {n}" for cls, n in sorted(counts.items()))
    total = counted(len(records), "объект", "объекта", "объектов")
    notes = [f"Слой ГИС {name}: {total}, {how}; классы: {classes or 'нет'}"]
    notes += sorted(f"Слой ГИС {name}: {note}" for note in rule_notes)
    warnings = []
    if skipped:
        warnings.append(
            f"Слой ГИС {name}: {counted(skipped, 'объект', 'объекта', 'объектов')} без класса "
            "(нет правила в config/geo_layers.yaml и атрибута green_class) в расчёт не вошли"
        )
    return GisLayers(tuple(features), tuple(notes), tuple(warnings))


def _classify(
    name: str, properties: Mapping[str, Any], rules: Sequence[_Rule]
) -> tuple[_Rule | None, ObjectClass | None]:
    for rule in rules:
        if rule.file is not None and not re.search(rule.file, name):
            continue
        if rule.any_value is not None and not any(
            re.search(rule.any_value, str(value)) for value in properties.values()
        ):
            continue
        if rule.attribute is not None:
            if properties.get(rule.attribute) in (None, ""):
                continue
            if rule.value is not None and not re.search(
                rule.value, str(properties[rule.attribute])
            ):
                continue
        if rule.object_class != FROM_ATTRIBUTE:
            return rule, ObjectClass(rule.object_class)
        try:
            return rule, ObjectClass(str(properties[rule.attribute or ""]))
        except ValueError:
            continue
    return None, None


def _source_crs(
    records: Sequence[_Record], declared: pyproj.CRS | None
) -> tuple[pyproj.CRS | None, str]:
    """Система координат слоя и описание для журнала; None - слой уже в системе чертежа."""
    if declared is not None and (declared.is_geographic or declared.to_epsg() is not None):
        return declared, f"пересчитан из {declared.name} в систему чертежа"
    bounds = shapely.total_bounds([r.geometry for r in records])
    # Долгота и широта: значения в пределах градусов и охват слоя не больше градуса - улица
    # в Москве занимает сотые доли градуса. Местный слой в метрах с малыми значениями (объект
    # у начала координат чертежа) охватывает десятки метров и сюда не попадает.
    lonlat = (
        all(abs(v) <= _LONLAT_LIMIT[0] for v in bounds[0::2])
        and all(abs(v) <= _LONLAT_LIMIT[1] for v in bounds[1::2])
        and bounds[2] - bounds[0] <= _LONLAT_SPAN
        and bounds[3] - bounds[1] <= _LONLAT_SPAN
    )
    if lonlat:
        return pyproj.CRS.from_epsg(
            4326
        ), "в долготе и широте (WGS 84), пересчитан в систему чертежа"
    if declared is not None:
        return None, f"система {declared.name} без кода EPSG принята за систему чертежа"
    return None, "в метрах без системы координат, принят в системе чертежа"


def _geojson(path: Path) -> tuple[list[_Record], pyproj.CRS | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise InputError(f"Слой ГИС {path.name}: не GeoJSON ({error})") from error
    crs = None
    name = ((data.get("crs") or {}).get("properties") or {}).get("name")
    if name:
        crs = pyproj.CRS.from_user_input(name)
    return [_Record(shape(f["geometry"]), f.get("properties") or {}) for f in _features(data)], crs


def _features(data: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    kind = data.get("type")
    if kind == "FeatureCollection":
        yield from (f for f in data.get("features", []) if f.get("geometry"))
    elif kind == "Feature" and data.get("geometry"):
        yield data
    elif kind:
        yield {"type": "Feature", "geometry": data, "properties": {}}


def _shapefile(path: Path) -> tuple[list[_Record], pyproj.CRS | None]:
    if path.suffix.lower() == ".shp":
        return _read_shp(path)
    with tempfile.TemporaryDirectory() as folder:
        with zipfile.ZipFile(path) as archive:
            archive.extractall(folder)
        shapes = sorted(Path(folder).rglob("*.shp"))
        if not shapes:
            raise InputError(f"Слой ГИС {path.name}: в архиве нет .shp")
        records: list[_Record] = []
        crs = None
        for shp in shapes:
            part, part_crs = _read_shp(shp)
            records += part
            crs = crs or part_crs
        return records, crs


def _read_shp(path: Path) -> tuple[list[_Record], pyproj.CRS | None]:
    prj = path.with_suffix(".prj")
    crs = (
        pyproj.CRS.from_wkt(prj.read_text(encoding="utf-8", errors="replace"))
        if prj.is_file()
        else None
    )
    records = []
    reader = shapefile.Reader(str(path), encoding="utf-8", encodingErrors="replace")
    try:
        fields = [f[0] for f in reader.fields[1:]]
        for item in reader.iterShapeRecords():
            figure = item.shape
            if figure is None or figure.shapeType == shapefile.NULL:
                continue
            values = list(item.record or ())
            records.append(
                _Record(shape(figure.__geo_interface__), dict(zip(fields, values, strict=False)))
            )
    finally:
        reader.close()
    return records, crs
