"""The ACIS bridge may add verified data without rewriting other DXF sections."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import ezdxf
import pytest
from ezdxf.acis import api
from ezdxf.render import MeshBuilder

from green.application.errors import ConversionError, InputError
from green.infrastructure.cad.acis_sidecar import load_region_sidecar, sidecar_path
from green.infrastructure.cad.merge import EzdxfDrawingMerger
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.convert.hybrid import _splice_acds

if TYPE_CHECKING:
    from pathlib import Path


def test_splice_preserves_every_other_base_byte() -> None:
    base = b"  0\r\nSECTION\r\n  2\r\nENTITIES\r\n  0\r\nENDSEC\r\n  0\r\nEOF\r\n"
    acds = b"  0\r\nSECTION\r\n  2\r\nACDSDATA\r\n  0\r\nACDSRECORD\r\n  0\r\nENDSEC\r\n"
    rich = b"  0\r\nSECTION\r\n  2\r\nHEADER\r\n  0\r\nENDSEC\r\n" + acds + b"  0\r\nEOF\r\n"
    combined = _splice_acds(base, rich)
    assert combined.replace(acds, b"") == base
    assert combined.count(acds) == 1


def test_splice_replaces_existing_acds_without_touching_other_sections() -> None:
    base = (
        b"0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nSECTION\n2\nACDSDATA\n1\nold\n0\nENDSEC\n0\nEOF\n"
    )
    rich = b"0\nSECTION\n2\nACDSDATA\n1\nnew\n0\nENDSEC\n0\nEOF\n"
    assert _splice_acds(base, rich) == base.replace(b"1\nold", b"1\nnew")


@pytest.mark.parametrize("rich", [b"0\nEOF\n", b"0\nSECTION\n2\nACDSDATA\n0\nEOF\n"])
def test_splice_rejects_missing_or_unclosed_acds(rich: bytes) -> None:
    with pytest.raises(ConversionError, match="ACDSDATA"):
        _splice_acds(b"0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n", rich)


def test_sidecar_is_bound_to_dxf_and_region_sab(tmp_path: Path) -> None:
    path = tmp_path / "test.dxf"
    doc = ezdxf.new("R2018")
    region = doc.modelspace().add_region()
    region.sab = b"sample sab"
    doc.saveas(path)
    loaded = ezdxf.readfile(path)
    region = loaded.modelspace().query("REGION")[0]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    payload = {
        "schema": 1,
        "engine": "acadrust",
        "engine_version": "0.5.5",
        "dxf_sha256": digest,
        "source_regions": 1,
        "regions": {
            region.dxf.handle: {
                "sab_sha256": hashlib.sha256(region.sab).hexdigest(),
                "sat": "700 0 1 0\ncoedge $-1 $-1 $-1 $-1 $-1 $-1 forward 0 $-1 #\n",
            }
        },
    }
    sidecar_path(path).write_text(json.dumps(payload), encoding="utf-8")
    result = load_region_sidecar(path, digest, loaded)
    assert result[region.dxf.handle][1].endswith("forward $-1 #")

    with pytest.raises(InputError, match="не соответствует DXF"):
        load_region_sidecar(path, "0" * 64, loaded)
    payload["regions"][region.dxf.handle]["sab_sha256"] = "0" * 64
    sidecar_path(path).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(InputError, match="REGION"):
        load_region_sidecar(path, digest, loaded)


def test_merge_carries_recovered_region_mapping(tmp_path: Path) -> None:
    base = tmp_path / "base.dxf"
    overlay = tmp_path / "overlay.dxf"
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    region = doc.modelspace().add_region()
    region.sab = b"sample sab"
    doc.saveas(base)
    digest = hashlib.sha256(base.read_bytes()).hexdigest()
    sidecar_path(base).write_text(
        json.dumps(
            {
                "schema": 1,
                "engine": "acadrust",
                "engine_version": "0.5.5",
                "dxf_sha256": digest,
                "source_regions": 1,
                "regions": {
                    region.dxf.handle: {
                        "sab_sha256": hashlib.sha256(region.sab).hexdigest(),
                        "sat": "700 0 1 0\n",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    extra = ezdxf.new("R2018")
    extra.header["$INSUNITS"] = 6
    extra.modelspace().add_line((0, 0), (1, 1))
    extra.saveas(overlay)
    target = tmp_path / "merged.dxf"
    EzdxfDrawingMerger().merge([base, overlay], target, unit="m")
    merged = ezdxf.readfile(target)
    mapped = load_region_sidecar(target, hashlib.sha256(target.read_bytes()).hexdigest(), merged)
    assert set(mapped) == {merged.modelspace().query("REGION")[0].dxf.handle}


@pytest.mark.parametrize("deviation", [0.001, 0.1])
def test_associative_open_hatch_uses_only_matching_region(tmp_path: Path, deviation: float) -> None:
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6
    mesh = MeshBuilder()
    mesh.add_face([(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)])
    region = doc.modelspace().add_region()
    api.export_dxf(region, [api.body_from_mesh(mesh)])
    hatch = doc.modelspace().add_hatch()
    hatch.dxf.associative = 1
    boundary = hatch.paths.add_polyline_path(
        [(deviation, deviation), (2, 0), (2, 2), (0, 2), (0, 0)], is_closed=False
    )
    boundary.source_boundary_objects.append(region.dxf.handle)
    source = tmp_path / "source.dxf"
    doc.saveas(source)
    scene = EzdxfSceneReader().read(source)
    hatch_features = [
        feature for feature in scene.features if feature.source_entity_type == "HATCH"
    ]
    assert len(hatch_features) == (1 if deviation < 0.002 else 0)
    assert sum(gap.count for gap in scene.read_diagnostics.geometry_gaps) == (
        0 if deviation < 0.002 else 1
    )
