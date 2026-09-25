"""A HATCH can borrow a REGION only after a unique, bounded sibling match."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import pytest
from ezdxf.acis import api
from ezdxf.render import MeshBuilder

from green.application.input_quality import require_complete_geometry
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path

    from green.domain.objects import Scene


def _scene(tmp_path: Path, *, regions: int = 1, shift: float = 0.0) -> Scene:
    doc = ezdxf.new("R2018")
    doc.units = 6
    block = doc.blocks.new("symbol")
    for _ in range(regions):
        mesh = MeshBuilder()
        mesh.add_face([(shift, 0, 0), (shift + 1, 0, 0), (shift + 1, 1, 0), (shift, 1, 0)])
        region = block.add_region(dxfattribs={"layer": "ground"})
        api.export_dxf(region, [api.body_from_mesh(mesh)])
    hatch = block.add_hatch(dxfattribs={"layer": "ground"})
    hatch.paths.add_polyline_path(
        [(0, 0, 0.005), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, -0.005, 0), (0, 0, 0)],
        is_closed=False,
    )
    doc.modelspace().add_blockref("symbol", (10, 20))
    source = tmp_path / "scene.dxf"
    doc.saveas(source)
    return EzdxfSceneReader().read(source)


def test_unique_matching_region_recovers_invalid_hatch(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    require_complete_geometry(scene)
    region, hatch = scene.features
    assert (region.source_entity_type, hatch.source_entity_type) == ("REGION", "HATCH")
    assert hatch.geometry.equals(region.geometry)
    assert hatch.ref != region.ref
    assert hatch.geometry_error_m is not None
    assert hatch.geometry_error_m > 0
    assert any("HATCH восстановлены" in warning for warning in scene.warnings)


@pytest.mark.parametrize(("regions", "shift"), [(2, 0.0), (1, 2.0)])
def test_ambiguous_or_distant_region_cannot_recover_hatch(
    tmp_path: Path, regions: int, shift: float
) -> None:
    scene = _scene(tmp_path, regions=regions, shift=shift)
    require_complete_geometry(scene)
    hatch = next(feature for feature in scene.features if feature.source_entity_type == "HATCH")
    assert hatch.uncertain_footprint
    assert hatch.geometry.area > 0
    assert not scene.read_diagnostics.geometry_gaps
