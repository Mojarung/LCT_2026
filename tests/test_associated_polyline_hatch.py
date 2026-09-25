"""An associated HATCH can verify fitted POLYLINE geometry inside a block."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import pytest

from green.application.errors import InputError
from green.application.input_quality import require_complete_geometry
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path

    from green.domain.objects import Scene


def _scene(
    tmp_path: Path,
    *,
    shift: float = 0.0,
    associate: bool = True,
    rotation: float = 0.0,
    scale: float = 1.0,
) -> Scene:
    doc = ezdxf.new("R2018")
    doc.units = 6
    block = doc.blocks.new("symbol")
    polyline = block.add_polyline2d(
        [(0, 0), (1, 0), (1, 1), (0, 1)],
        close=True,
        dxfattribs={"layer": "boundary"},
    )
    polyline.dxf.flags |= 2  # CAD curve-fit generated vertices
    hatch = block.add_hatch(dxfattribs={"layer": "boundary"})
    path = hatch.paths.add_polyline_path(
        [(shift, 0), (shift + 1, 0), (shift + 1, 1), (shift, 1)],
    )
    if associate:
        path.source_boundary_objects = [polyline.dxf.handle]
        hatch.dxf.associative = 1
    doc.modelspace().add_blockref(
        "symbol", (10, 20), dxfattribs={"rotation": rotation, "xscale": scale, "yscale": scale}
    )
    source = tmp_path / "scene.dxf"
    doc.saveas(source)
    return EzdxfSceneReader().read(source)


@pytest.mark.parametrize(("rotation", "scale"), [(0.0, 1.0), (37.0, 2.0), (171.0, 0.5)])
def test_matching_associated_hatch_bounds_fitted_polyline(
    tmp_path: Path, rotation: float, scale: float
) -> None:
    scene = _scene(tmp_path, rotation=rotation, scale=scale)
    require_complete_geometry(scene)
    polyline = next(
        feature for feature in scene.features if feature.source_entity_type == "POLYLINE"
    )
    assert polyline.geometry_error_m is not None
    assert not scene.read_diagnostics.geometry_gaps
    assert any("POLYLINE сверены" in warning for warning in scene.warnings)


def test_stale_association_keeps_the_gap(tmp_path: Path) -> None:
    scene = _scene(tmp_path, shift=0.1)
    with pytest.raises(InputError, match="approximation-error-not-bounded"):
        require_complete_geometry(scene)
    assert scene.read_diagnostics.geometry_gaps[0].entity_type == "POLYLINE"


def test_missing_association_keeps_the_gap(tmp_path: Path) -> None:
    scene = _scene(tmp_path, associate=False)
    with pytest.raises(InputError, match="approximation-error-not-bounded"):
        require_complete_geometry(scene)
    assert scene.read_diagnostics.geometry_gaps[0].entity_type == "POLYLINE"
