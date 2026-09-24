"""ACIS geometry kept outside entity tags must be part of the source fingerprint."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import pytest
from ezdxf.acis import api
from ezdxf.render import MeshBuilder

from green.infrastructure.cad.integrity import EzdxfIntegrityChecker

if TYPE_CHECKING:
    from pathlib import Path


def _body(width: int) -> api.Body:
    mesh = MeshBuilder()
    mesh.add_face([(0, 0, 0), (width, 0, 0), (width, 3, 0), (0, 3, 0)])
    return api.body_from_mesh(mesh)


@pytest.mark.parametrize("version", ["R2010", "R2018"])
def test_region_payload_change_breaks_integrity(tmp_path: Path, version: str) -> None:
    original = tmp_path / "original.dxf"
    unchanged = tmp_path / "unchanged.dxf"
    changed = tmp_path / "changed.dxf"
    doc = ezdxf.new(version)
    region = doc.modelspace().add_region()
    api.export_dxf(region, [_body(4)])
    handle = region.dxf.handle
    doc.saveas(original)

    loaded = ezdxf.readfile(original)
    loaded.saveas(unchanged)
    checker = EzdxfIntegrityChecker()
    assert checker.verify_files(original, unchanged).ok

    mutated = ezdxf.readfile(original)
    api.export_dxf(mutated.entitydb[handle], [_body(8)])
    mutated.saveas(changed)
    result = checker.verify_files(original, changed)
    assert not result.ok
    assert result.changed == (handle,)
