"""scene.json: контракт файла, по которому браузер строит объёмную сцену участка.

Имена полей здесь закреплены намеренно: фронт читает их напрямую, и переименование в
выгрузке без правки фронта дало бы пустую сцену без единой ошибки.
"""

from __future__ import annotations

from pathlib import Path

import orjson
import pytest
from shapely.geometry import LinearRing, Polygon, box

from green.application.volumes import BuildingVolume, Volumes
from green.domain.norms import PlantingType
from green.domain.planting import AssortmentInfo, Placement, Plan, Verdict
from green.infrastructure.config.repositories import YamlSpeciesCatalog
from green.infrastructure.reports.scene import SCENE_MARGIN_M, scene_payload

CATALOG = YamlSpeciesCatalog(Path(__file__).resolve().parents[1] / "config" / "species.yaml")
COUNT_KEYS = {
    "buildings",
    "faces",
    "from_labels",
    "from_neighbors",
    "from_letters",
    "assumed",
    "voids",
    "slivers",
    "open_lines",
    "closed_cuts",
    "cropped",
}
SPECIES_KEYS = {
    "name_ru",
    "name_lat",
    "life_form",
    "height_m",
    "crown_diameter_m",
    "crown_mature_m",
    "evergreen",
    "conifer",
    "growth",
    "genus",
    "family",
}


def _placement(pid: str, code: str, x: float, y: float, structure: str | None) -> Placement:
    species = CATALOG.get(code)
    return Placement(
        placement_id=pid,
        number=1,
        planting_type=PlantingType.TREE if species.is_tree else PlantingType.SHRUB,
        species=species,
        x=x,
        y=y,
        verdict=Verdict.ALLOWED,
        checks=(),
        assortment=AssortmentInfo(
            status="assigned", percent=70, factors={}, structure_kind=structure
        )
        if structure
        else None,
    )


def _volume(footprint: Polygon, floors: int = 5) -> BuildingVolume:
    return BuildingVolume(
        footprint=footprint,
        height_m=16.2,
        floors=floors,
        floors_source="label",
        kind="building",
        wall="brick",
        use="residential",
        labels=("К-", str(floors)),
    )


# Наружное кольцо по часовой, дыра против: выгрузка обязана развернуть оба.
YARD = Polygon(
    [(0, 0), (0, 40.004), (40, 40), (40, 0)], holes=[[(10, 10), (30, 10), (30, 30), (10, 30)]]
)
PLAN = Plan(
    placements=(
        _placement("P1", "tilia_cordata", 50.0, 50.0, "row"),
        _placement("P2", "picea_abies", 60.0, 55.0, None),
    ),
    rejections=(),
)
VOLUMES = Volumes(
    buildings=(_volume(YARD), _volume(box(5000, 5000, 5010, 5010), 2)),
    faces=4,
    from_labels=2,
    voids=1,
    slivers=1,
    open_lines=3,
)


def test_scene_has_the_contract_keys_and_survives_json() -> None:
    scene = orjson.loads(orjson.dumps(scene_payload(PLAN, VOLUMES)))

    assert set(scene) == {
        "version",
        "crs_note",
        "extent",
        "counts",
        "buildings",
        "plants",
        "species",
    }
    assert scene["version"] == 1
    assert set(scene["counts"]) == COUNT_KEYS
    assert set(scene["buildings"][0]) == {
        "rings",
        "height_m",
        "floors",
        "floors_source",
        "kind",
        "wall",
        "use",
        "labels",
    }
    assert set(scene["plants"][0]) == {"id", "number", "x", "y", "type", "code", "structure"}
    assert set(scene["species"]["tilia_cordata"]) == SPECIES_KEYS


def test_extent_is_the_plantings_with_a_margin_and_far_buildings_are_cropped() -> None:
    scene = scene_payload(PLAN, VOLUMES)

    margin = SCENE_MARGIN_M
    assert scene["extent"] == [50 - margin, 50 - margin, 60 + margin, 55 + margin]
    assert len(scene["buildings"]) == 1
    counts = scene["counts"]
    assert (counts["buildings"], counts["cropped"]) == (1, 1)
    assert counts["buildings"] + counts["cropped"] == len(VOLUMES.buildings)
    assert (counts["faces"], counts["voids"], counts["open_lines"]) == (4, 1, 3)


def test_rings_are_ccw_outside_cw_inside_and_rounded_to_a_centimetre() -> None:
    (building,) = scene_payload(PLAN, VOLUMES)["buildings"]
    exterior, hole = building["rings"]

    assert LinearRing(exterior).is_ccw
    assert not LinearRing(hole).is_ccw
    assert exterior[0] == exterior[-1], "кольцо замкнуто, как в GeoJSON"
    assert [0.0, 40.0] in exterior
    assert building["labels"] == ["К-", "5"]


def test_plants_carry_species_and_structure_and_species_only_those_used() -> None:
    scene = scene_payload(PLAN, VOLUMES)

    linden, spruce = scene["plants"]
    assert linden == {
        "id": "P1",
        "number": linden["number"],
        "x": 50.0,
        "y": 50.0,
        "type": "tree",
        "code": "tilia_cordata",
        "structure": "row",
    }
    assert isinstance(linden["number"], int)
    assert spruce["structure"] is None
    assert set(scene["species"]) == {"tilia_cordata", "picea_abies"}
    assert scene["species"]["picea_abies"]["conifer"] is True
    assert scene["species"]["tilia_cordata"]["conifer"] is False
    assert scene["species"]["tilia_cordata"]["height_m"] == pytest.approx(
        CATALOG.get("tilia_cordata").height_m
    )


def test_without_volumes_the_scene_is_still_written_with_no_buildings() -> None:
    scene = scene_payload(PLAN, None)

    assert scene["buildings"] == []
    assert set(scene["counts"]) == COUNT_KEYS
    assert all(value == 0 for value in scene["counts"].values())
    assert len(scene["plants"]) == 2


def test_without_plantings_the_extent_is_the_buildings() -> None:
    scene = scene_payload(Plan(placements=(), rejections=()), VOLUMES)

    assert scene["extent"] == [0.0, 0.0, 5010.0, 5010.0]
    assert scene["counts"]["cropped"] == 0
    assert scene["plants"] == []
    assert scene["species"] == {}
