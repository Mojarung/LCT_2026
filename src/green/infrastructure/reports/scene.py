"""Сцена для трёхмерного вида: объёмы зданий, точки посадок и облик видов (scene.json).

Браузер строит из этого файла объёмную картинку участка: здания выдавливаются на высоту из
подписей чертежа, деревья и кусты ставятся в точки плана с высотой и кроной вида. Файл
самодостаточен: за видами не нужно ходить в plan.json, за зданиями - в basemap.geojson.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import shapely

if TYPE_CHECKING:
    from numpy.typing import NDArray
    from shapely.geometry import Polygon

    from green.application.volumes import BuildingVolume, Volumes
    from green.domain.planting import Placement, Plan, Species

SCENE_VERSION = 1
CRS_NOTE = "координаты чертежа в метрах, не WGS84"
# Сколько застройки показывать вокруг посадок. Улица из каталога - это несколько планшетов,
# до километра в поперечнике: вид на весь комплект теряет сам план. 200 м - квартал по обе
# стороны улицы, этого хватает, чтобы посадки читались на фоне своих домов.
SCENE_MARGIN_M = 200.0
DIGITS = 2  # сантиметр, как у подосновы: точнее геоподоснова не бывает

type Extent = tuple[float, float, float, float]


def scene_payload(plan: Plan, volumes: Volumes | None) -> dict[str, Any]:
    """Содержимое scene.json.

    counts.buildings - сколько объёмов попало в выгрузку, counts.cropped - сколько отрезано
    охватом сцены; вместе это все объёмы прогона, то есть from_labels + from_neighbors +
    from_letters + assumed. Остальные числа - баланс граней из `Volumes`.
    """
    extent = _extent(plan, volumes)
    kept, cropped = _crop(volumes.buildings if volumes is not None else (), extent)
    return {
        "version": SCENE_VERSION,
        "crs_note": CRS_NOTE,
        "extent": [round(value, DIGITS) for value in extent],
        "counts": _counts(volumes, len(kept), cropped),
        "buildings": [_building(volume) for volume in kept],
        "plants": [_plant(placement) for placement in plan.placements],
        "species": {p.species.code: _look(p.species) for p in plan.placements},
    }


def _extent(plan: Plan, volumes: Volumes | None) -> Extent:
    """Охват сцены: посадки с запасом, а без посадок - вся застройка прогона."""
    if plan.placements:
        xs = [p.x for p in plan.placements]
        ys = [p.y for p in plan.placements]
        margin = SCENE_MARGIN_M
        return (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)
    bbox = volumes.bbox if volumes is not None else None
    return bbox if bbox is not None else (0.0, 0.0, 0.0, 0.0)


def _crop(
    buildings: tuple[BuildingVolume, ...], extent: Extent
) -> tuple[list[BuildingVolume], int]:
    """Объёмы, задевающие охват; остальные только считаются."""
    if not buildings:
        return [], 0
    footprints = np.array([b.footprint for b in buildings], dtype=object)
    inside = shapely.intersects(footprints, shapely.box(*extent))
    kept = [volume for volume, hit in zip(buildings, inside, strict=True) if hit]
    return kept, len(buildings) - len(kept)


def _counts(volumes: Volumes | None, kept: int, cropped: int) -> dict[str, int]:
    fields = (
        "faces",
        "from_labels",
        "from_neighbors",
        "from_letters",
        "assumed",
        "voids",
        "slivers",
        "open_lines",
    )
    balance = {name: getattr(volumes, name) if volumes is not None else 0 for name in fields}
    return {"buildings": kept, **balance, "cropped": cropped}


def _building(volume: BuildingVolume) -> dict[str, Any]:
    return {
        "rings": _rings(volume.footprint),
        "height_m": round(volume.height_m, DIGITS),
        "floors": volume.floors,
        "floors_source": volume.floors_source,
        "kind": volume.kind,
        "wall": volume.wall,
        "use": volume.use,
        "labels": list(volume.labels),
    }


def _rings(footprint: Polygon) -> list[list[list[float]]]:
    """Наружное кольцо против часовой стрелки первым, дыры по часовой - за ним.

    Кольца замкнуты, как в GeoJSON: последняя точка равна первой. Повтор точки, возникший
    от округления до сантиметра, выбрасывается - триангуляция на нём спотыкается.
    """
    oriented = shapely.orient_polygons(footprint)
    rings = [oriented.exterior, *oriented.interiors]
    return [_ring(shapely.get_coordinates(ring)) for ring in rings]


def _ring(coords: NDArray[np.float64]) -> list[list[float]]:
    rounded = np.round(coords, DIGITS)
    moved = np.r_[True, np.any(np.diff(rounded, axis=0) != 0, axis=1)]
    return rounded[moved].tolist()


def _plant(placement: Placement) -> dict[str, Any]:
    info = placement.assortment
    return {
        "id": placement.placement_id,
        "x": round(placement.x, DIGITS),
        "y": round(placement.y, DIGITS),
        "type": placement.planting_type.value,
        "code": placement.species.code,
        "structure": info.structure_kind if info is not None else None,
    }


def _look(species: Species) -> dict[str, Any]:
    """Облик вида для сцены: форма, высота, крона через 10 лет и взрослая, хвоя, темп роста."""
    return {
        "name_ru": species.name_ru,
        "name_lat": species.name_lat,
        "life_form": species.life_form.value,
        "height_m": species.height_m,
        "crown_diameter_m": species.crown_diameter_m,
        "crown_mature_m": species.crown_mature_m,
        "evergreen": species.evergreen,
        "conifer": species.is_conifer,
        "growth": species.growth,
        "genus": species.genus,
        "family": species.family,
    }
