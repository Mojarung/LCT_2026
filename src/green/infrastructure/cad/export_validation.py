"""Read the saved DXF and compare new plantings with the certified plan.

The check uses actual INSERT coordinates, transforms, symbol geometry, attributes,
layer and XDATA. Counting entities alone cannot detect a wrong scale or species.
Lawns are compared by identity, kind and the area of the written hatch boundaries.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import TYPE_CHECKING

from ezdxf.entities import Hatch, Insert
from ezdxf.entities.boundary_paths import PolylinePath
from ezdxf.lldxf.const import BOUNDARY_PATH_EXTERNAL
from ezdxf.lldxf.encoding import decode_dxf_unicode
from shapely.geometry import Polygon

from green.application.barriers import BARRIER_NOTE
from green.application.results import PlanExportReport
from green.domain.planting import Verdict
from green.infrastructure.cad.documents import APPID, load_document

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.document import Drawing

    from green.domain.planting import Placement, Plan

_LAYERS = frozenset(
    {
        "GREEN_TREES",
        "GREEN_TREES_APPROVAL",
        "GREEN_TREES_BARRIER",
        "GREEN_SHRUBS",
        "GREEN_SHRUBS_APPROVAL",
    }
)
_LAWN_LAYER = "GREEN_LAWN"
_TOLERANCE_M = 1e-6
# Площадь участка в XDATA и координаты штриховки - те же числа плана; допуск - на округление.
_AREA_TOLERANCE_M2 = 0.01
_XDATA_STRING = 1000
_IDENTITY_FIELDS = 2


def check_written_plan(result: Path, plan: Plan, *, unit_m: float) -> PlanExportReport:
    doc, _ = load_document(result)
    expected = {p.placement_id: p for p in plan.placements}
    counts: Counter[str] = Counter()
    issues = []
    found = 0
    for entity in doc.modelspace():
        layer = entity.dxf.get("layer", "0")
        planting_block = entity.dxftype() == "INSERT" and entity.dxf.name.upper().startswith(
            ("GREEN_TREE_", "GREEN_SHRUB_")
        )
        if layer not in _LAYERS and not planting_block:
            continue
        found += 1
        if not isinstance(entity, Insert) or not entity.has_xdata(APPID):
            issues.append(f"{entity.dxf.handle}: planting has no INSERT or identity XDATA")
            continue
        tags = entity.get_xdata(APPID)
        strings = [t.value for t in tags if t.code == _XDATA_STRING]
        identity = strings[0] if strings else ""
        counts[identity] += 1
        placement = expected.get(identity)
        if placement is None:
            issues.append(f"{identity}: unexpected planting")
            continue
        if len(strings) < _IDENTITY_FIELDS or strings[1] != placement.verdict.value:
            issues.append(f"{identity}: incorrect verdict XDATA")
        issues.extend(_compare(doc, entity, placement, unit_m))
    issues.extend(
        f"{identity}: expected one planting, found {counts[identity]}"
        for identity in expected
        if counts[identity] != 1
    )
    lawn_issues, found_lawns = _check_lawns(doc, plan, unit_m)
    issues.extend(lawn_issues)
    return PlanExportReport(
        len(plan.placements),
        found,
        tuple(issues),
        expected_lawns=len(plan.lawns),
        found_lawns=found_lawns,
    )


def _check_lawns(doc: Drawing, plan: Plan, unit: float) -> tuple[list[str], int]:
    """Every lawn is written once or in parts, with its kind and exactly its area."""
    expected = {lawn.lawn_id: lawn for lawn in plan.lawns}
    areas: defaultdict[str, float] = defaultdict(float)
    issues = []
    hatches = [e for e in doc.modelspace() if e.dxf.get("layer", "0") == _LAWN_LAYER]
    for entity in hatches:
        if not isinstance(entity, Hatch) or not entity.has_xdata(APPID):
            issues.append(f"{entity.dxf.handle}: lawn has no HATCH or identity XDATA")
            continue
        strings = [t.value for t in entity.get_xdata(APPID) if t.code == _XDATA_STRING]
        identity = strings[0] if strings else ""
        lawn = expected.get(identity)
        if lawn is None:
            issues.append(f"{identity}: unexpected lawn")
            continue
        if len(strings) < _IDENTITY_FIELDS or strings[1] != lawn.kind.value:
            issues.append(f"{identity}: incorrect lawn kind XDATA")
        area = _hatch_area(entity)
        if area is None:
            issues.append(f"{identity}: lawn boundary is not a closed polyline")
            continue
        areas[identity] += area * unit * unit
    for identity, lawn in expected.items():
        if identity not in areas:
            issues.append(f"{identity}: lawn is missing")
        elif not math.isclose(areas[identity], lawn.area_m2, abs_tol=_AREA_TOLERANCE_M2):
            issues.append(f"{identity}: lawn area differs from certified plan")
    return issues, len(hatches)


def _hatch_area(hatch: Hatch) -> float | None:
    """Area of one external polyline boundary minus its holes, in drawing units."""
    shells, holes = [], []
    for path in hatch.paths:
        if not isinstance(path, PolylinePath) or any(v[2] for v in path.vertices):
            return None
        ring = [(v[0], v[1]) for v in path.vertices]
        (shells if path.path_type_flags & BOUNDARY_PATH_EXTERNAL else holes).append(ring)
    if len(shells) != 1:
        return None
    return float(Polygon(shells[0], holes).area)


def _compare(doc: Drawing, insert: Insert, placement: Placement, unit: float) -> list[str]:
    identity = placement.placement_id
    issues = []
    location = insert.dxf.insert
    if not _near(location.x * unit, placement.x) or not _near(location.y * unit, placement.y):
        issues.append(f"{identity}: coordinates differ from certified plan")
    if any(not _near(insert.dxf.get(axis, 1) * unit, 1) for axis in ("xscale", "yscale", "zscale")):
        issues.append(f"{identity}: incorrect INSERT scale")
    kind = "SHRUB" if placement.species.is_shrub else "TREE"
    block_name = f"GREEN_{kind}_{placement.species.code.upper()}"
    if insert.dxf.name != block_name:
        issues.append(f"{identity}: incorrect species block")
    if insert.dxf.layer != _expected_layer(placement):
        issues.append(f"{identity}: incorrect planting layer")
    attrs = {decode_dxf_unicode(a.dxf.tag): decode_dxf_unicode(a.dxf.text) for a in insert.attribs}
    if attrs.get("SPECIES") != placement.species.name_ru or attrs.get("NUM") != str(
        placement.number
    ):
        issues.append(f"{identity}: incorrect species/number attributes")
    block = doc.blocks.get(insert.dxf.name)
    circles = list(block.query("CIRCLE")) if block is not None else []
    if len(circles) != 1:
        issues.append(f"{identity}: missing or ambiguous crown symbol")
    else:
        circle = circles[0]
        center = insert.matrix44().transform(circle.dxf.center)
        if not _near(center.x * unit, placement.x) or not _near(center.y * unit, placement.y):
            issues.append(f"{identity}: symbol centre displaced from planting")
        if not _near(circle.dxf.radius * 2, placement.species.crown_diameter_m):
            issues.append(f"{identity}: crown symbol size differs from species")
    return issues


def _expected_layer(placement: Placement) -> str:
    stem = "GREEN_SHRUBS" if placement.species.is_shrub else "GREEN_TREES"
    if placement.verdict is Verdict.NEEDS_APPROVAL:
        return stem + "_APPROVAL"
    if not placement.species.is_shrub and BARRIER_NOTE in placement.notes:
        return stem + "_BARRIER"
    return stem


def _near(actual: float, expected: float) -> bool:
    return math.isfinite(actual) and math.isclose(actual, expected, rel_tol=0, abs_tol=_TOLERANCE_M)
