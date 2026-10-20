"""Газоны за границей работ: пустой план объясняется, а не выглядит сбоем (чертёж жюри СПОЗУ К2)."""

from __future__ import annotations

from shapely.geometry import Polygon, box

from green.application.constraints import lawns_outside_note
from green.domain.objects import NO_XREF, Feature, ObjectClass, SourceRef


def _feature(geometry: Polygon, kind: ObjectClass, layer: str, handle: str) -> Feature:
    return Feature(
        ref=SourceRef(file_sha8="00000000", xref_hash8=NO_XREF, handle=handle),
        layer=layer,
        geometry=geometry,
        object_class=kind,
    )


def test_lawns_beyond_the_boundary_are_reported_with_a_rerun_hint() -> None:
    boundary = box(0, 0, 100, 100)
    lawn = _feature(box(120, 0, 160, 40), ObjectClass.LAWN, "ГП газон", "1")
    edge = _feature(boundary.exterior, ObjectClass.WORK_BOUNDARY, "ГП Граница работ", "2")

    note = lawns_outside_note([lawn, edge], boundary)

    assert note is not None
    assert "снаружи 1 600 м²" in note
    assert '"ГП Граница работ": "ignore"' in note


def test_lawns_inside_the_boundary_say_nothing() -> None:
    boundary = box(0, 0, 100, 100)
    lawn = _feature(box(10, 10, 60, 60), ObjectClass.LAWN, "ГП газон", "1")
    far = _feature(box(120, 0, 160, 40), ObjectClass.LAWN, "ГП газон", "3")

    assert lawns_outside_note([lawn, far], boundary) is None
    assert lawns_outside_note([lawn], None) is None
