"""Lost spatial entities must not become apparently empty planting space."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import pytest
from ezdxf.acis import api as acis
from ezdxf.render import forms
from test_pipeline_synthetic import ROOT, _street

from green.application.errors import InputError
from green.application.input_quality import require_complete_geometry
from green.application.results import SourceSnapshot
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.infrastructure.cad.documents import load_document
from green.infrastructure.cad.integrity import EzdxfIntegrityChecker, fingerprints
from green.infrastructure.cad.merge import EzdxfDrawingMerger
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path


def _inject_empty_region(path: Path, *, layer: str = "Газопровод") -> None:
    # ezdxf refuses to export empty ACIS; reproduce the converter's actual tags.
    # DXF 2007+ всегда в UTF-8: кодировка ОС по умолчанию (cp1251 на Windows) портит имя слоя.
    data = path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    marker = "  2\nENTITIES\n"
    assert marker in data
    tags = (
        "  0\nREGION\n  5\nAFF123\n100\nAcDbEntity\n"
        f"  8\n{layer}\n100\nAcDbModelerGeometry\n 70\n1\n100\nAcDbRegion\n"
    )
    path.write_bytes(data.replace(marker, marker + tags, 1).encode("utf-8"))


@pytest.mark.parametrize("layer", ["Газопровод", "0", "arbitrary", "Грунты"])
def test_empty_region_is_an_actionable_gap_regardless_of_layer(tmp_path: Path, layer: str) -> None:
    path = tmp_path / "lost.dxf"
    doc = ezdxf.new("R2018")
    if layer != "0":
        doc.layers.add(layer)
    doc.modelspace().add_line((0, 0), (1, 1))
    doc.saveas(path)
    _inject_empty_region(path, layer=layer)
    scene = EzdxfSceneReader().read(path, unit="m")
    with pytest.raises(InputError, match="REGION"):
        require_complete_geometry(scene)
    gaps = scene.read_diagnostics.geometry_gaps
    assert len(gaps) == 1
    assert (gaps[0].entity_type, gaps[0].layer, gaps[0].count) == ("REGION", layer, 1)
    assert gaps[0].reason == "missing-acis-data"
    assert gaps[0].source_refs[0].endswith(":AFF123")


@pytest.mark.parametrize("kind", ["region", "3dsolid", "body"])
def test_unread_acis_is_blocking_even_if_payload_is_present(tmp_path: Path, kind: str) -> None:
    doc = ezdxf.new("R2018")
    entity = getattr(doc.modelspace(), f"add_{kind}")()
    acis.export_dxf(entity, [acis.body_from_mesh(forms.cube())])
    path = tmp_path / "solid.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit="m")
    with pytest.raises(InputError, match=kind.upper()):
        require_complete_geometry(scene)


def test_spatial_gap_inside_rotated_block_is_not_annotation(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    block = doc.blocks.new("unknown geometry")
    mesh = block.add_mesh()
    with mesh.edit_data() as data:
        data.vertices = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)]
        data.faces = [(0, 1, 2, 3)]
    doc.modelspace().add_blockref(block.name, (200, 100), dxfattribs={"rotation": 30})
    path = tmp_path / "mesh.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit="m")
    with pytest.raises(InputError, match="MESH"):
        require_complete_geometry(scene)
    assert scene.read_diagnostics.geometry_gaps[0].block == block.name


def test_mask_inside_rotated_block_is_an_accounted_underlay(tmp_path: Path) -> None:
    """Маска WIPEOUT - картинка поверх чертежа, не объект: учёт её называет, прогон идёт."""
    doc = ezdxf.new("R2018")
    block = doc.blocks.new("unknown geometry")
    block.add_wipeout([(0, 0), (10, 0), (10, 10), (0, 10)])
    doc.modelspace().add_blockref(block.name, (200, 100), dxfattribs={"rotation": 30})
    path = tmp_path / "mask.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit="m")
    require_complete_geometry(scene)
    assert scene.read_diagnostics.outcomes["skipped:WIPEOUT:underlay"] == 1


def test_image_cannot_silently_become_available_land(tmp_path: Path) -> None:
    """Растр - подложка (решение 25.09.2026): прогон не останавливает, но и земли не даёт:
    объектов из картинки нет, а учёт и предупреждение называют её."""
    doc = ezdxf.new("R2018")
    image = doc.add_image_def(filename="missing-survey.png", size_in_pixel=(100, 100))
    doc.modelspace().add_image(image, insert=(0, 0), size_in_units=(20, 20))
    path = tmp_path / "raster.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit="m")
    require_complete_geometry(scene)
    assert scene.features == ()
    assert scene.read_diagnostics.outcomes["skipped:IMAGE:underlay"] == 1
    assert any("IMAGE" in warning for warning in scene.warnings)


def test_failure_to_interpret_a_spatial_curve_is_reported(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.modelspace().add_xline((0, 0), (1, 0))
    path = tmp_path / "unbounded.dxf"
    doc.saveas(path)
    with pytest.raises(InputError, match="XLINE"):
        require_complete_geometry(EzdxfSceneReader().read(path, unit="m"))


@pytest.mark.parametrize("profile", ["strict", "no_utilities"])
def test_partial_input_does_not_publish_plan(tmp_path: Path, profile: str) -> None:
    path = tmp_path / "street.dxf"
    _street(path)
    _inject_empty_region(path)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load(profile, {})
    with pytest.raises(InputError, match="REGION"):
        container.use_case.execute(PlanRequest("lost", path, tmp_path / "out", profile, params))
    assert not (tmp_path / "out/result.dxf").exists()


def test_nonexportable_entity_is_not_a_successful_integrity_check(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.modelspace().add_line((0, 0), (1, 1))
    # Put it in an unused block: the scene walker won't visit it, but saving loses it.
    doc.blocks.new("unused source objects").add_region()
    digests, unexportable = fingerprints(doc)
    assert unexportable == 1
    saved = tmp_path / "saved.dxf"
    doc.saveas(saved)
    report = EzdxfIntegrityChecker().check(SourceSnapshot(digests, unexportable), saved)
    assert not report.ok
    assert report.unexportable == 1


@pytest.mark.parametrize("broken_index", [0, 1])
def test_merge_cannot_erase_evidence_of_missing_source_geometry(
    tmp_path: Path, broken_index: int
) -> None:
    paths = [tmp_path / f"part-{n}.dxf" for n in range(2)]
    for path in paths:
        doc = ezdxf.new("R2018")
        doc.modelspace().add_line((0, 0), (1, 1))
        doc.saveas(path)
    _inject_empty_region(paths[broken_index])
    target = tmp_path / "merged.dxf"
    with pytest.raises(InputError, match="REGION"):
        EzdxfDrawingMerger().merge(paths, target)
    assert not target.exists()


def test_gap_counts_are_complete_but_handle_examples_are_bounded(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    for x in range(100):
        doc.modelspace().add_xline((x, 0), (0, 1))
    path = tmp_path / "many.dxf"
    doc.saveas(path)
    gaps = EzdxfSceneReader().read(path, unit="m").read_diagnostics.geometry_gaps
    assert len(gaps) == 1
    assert gaps[0].count == 100
    assert len(gaps[0].source_refs) == 5


def test_annotation_skips_remain_distinct_from_missing_geometry(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.modelspace().add_leader([(0, 0), (5, 5)])
    doc.modelspace().add_text("annotation")
    path = tmp_path / "notes.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit="m")
    assert scene.read_diagnostics.skipped_by_type == {"LEADER": 1}
    assert not scene.read_diagnostics.geometry_gaps
    require_complete_geometry(scene)


@pytest.mark.parametrize("nested", [False, True])
def test_audit_cannot_delete_a_missing_block_before_completeness_check(
    tmp_path: Path, *, nested: bool
) -> None:
    doc = ezdxf.new("R2018")
    space = doc.blocks.new("wrapper") if nested else doc.modelspace()
    space.add_blockref("not_defined", (0, 0))
    if nested:
        doc.modelspace().add_blockref("wrapper", (0, 0))
    path = tmp_path / "missing-block.dxf"
    doc.saveas(path)
    with pytest.raises(InputError, match="аудит DXF"):
        load_document(path)
