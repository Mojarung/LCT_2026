"""Unknown CAD conventions cannot be replaced with pilot-street scale assumptions."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import pytest

from green.application.errors import InputError
from green.application.use_case import to_dxf
from green.infrastructure.cad.merge import EzdxfDrawingMerger
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.cad.units import decide_units

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("code", "factor"), [(1, 0.0254), (2, 0.3048), (4, 0.001), (5, 0.01), (7, 1000), (14, 0.1)]
)
def test_declared_units_work_for_a_small_unfamiliar_drawing(code: int, factor: float) -> None:
    doc = ezdxf.new("R2018")
    doc.units = code
    doc.modelspace().add_line((0, 0), (7 / factor, 0))
    assert decide_units(doc).unit_m == pytest.approx(factor)


def test_missing_units_require_an_explicit_scale() -> None:
    doc = ezdxf.new("R2018")
    doc.units = 0
    doc.modelspace().add_line((0, 0), (1000, 0))
    with pytest.raises(InputError, match="drawing_unit"):
        decide_units(doc)
    assert decide_units(doc, "m").unit_m == 1


@pytest.mark.parametrize(
    ("base_code", "base_factor", "other_code", "other_factor"),
    [(6, 1.0, 4, 0.001), (4, 0.001, 6, 1.0), (2, 0.3048, 5, 0.01)],
)
def test_merge_normalises_each_source_before_overlay(
    tmp_path: Path, base_code: int, base_factor: float, other_code: int, other_factor: float
) -> None:
    paths = []
    original = []
    for n, (code, factor) in enumerate([(base_code, base_factor), (other_code, other_factor)]):
        doc = ezdxf.new("R2018")
        doc.units = code
        doc.layers.add(f"opaque_{n}")
        # Block transform is intentional: normalising both block and INSERT would double-scale it.
        block = doc.blocks.new(f"symbol_{n}")
        block.add_line((0, 0), (10 / factor, 0))
        doc.modelspace().add_blockref(
            f"symbol_{n}", (100 / factor, 200 / factor), dxfattribs={"layer": f"opaque_{n}"}
        )
        path = tmp_path / f"source{n}.dxf"
        doc.saveas(path)
        paths.append(path)
        original.append(path.read_bytes())
    result = EzdxfDrawingMerger().merge(paths, tmp_path / "merged.dxf")
    scene = EzdxfSceneReader().read(result.path)
    assert len(scene.features) == 2
    for feature in scene.features:
        assert feature.geometry.bounds == pytest.approx((100, 200, 110, 200))
    assert [p.read_bytes() for p in paths] == original


class FakeConverter:
    name = "fake"

    def available(self) -> bool:
        return True

    def to_dxf(self, source: Path, work_dir: Path) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        target = work_dir / (source.stem + ".dxf")
        target.write_bytes(source.read_bytes())
        return target


def test_same_basename_in_different_input_folders_does_not_overwrite_conversion(
    tmp_path: Path,
) -> None:
    sources = []
    for folder, data in [("topography", b"first file"), ("utilities", b"second file")]:
        path = tmp_path / folder / "sheet.dwg"
        path.parent.mkdir()
        path.write_bytes(data)
        sources.append(path)
    first, _ = to_dxf([FakeConverter()], sources[0], tmp_path / "out")
    second, _ = to_dxf([FakeConverter()], sources[1], tmp_path / "out")
    assert first != second
    assert first.read_bytes() == b"first file"
    assert second.read_bytes() == b"second file"
