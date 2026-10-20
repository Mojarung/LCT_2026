"""Чужие чертежи: прогон идёт и показывает план на любом входе, который можно прочитать.

Жюри проверяет сервис на своих файлах (20.10.2026): старый формат R12, кириллица в cp1251 под
чужой кодовой страницей, нет границы работ, блок вставляет сам себя, вырожденные объекты,
сеть-многогранник, внешняя ссылка без файла, DWG с расширением .dxf. Каждый случай - короткий
прогон по улице 60 x 40 м; что сервис исправил сам, называет журнал прогона.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import ezdxf
import pytest
import shapely

from green.application.errors import InputError
from green.application.use_case import PlanRequest, drawing_kind, to_dxf
from green.application.work_area import INFERRED_LAYER, with_work_area
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.infrastructure.cad.documents import load_document

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.document import Drawing
    from ezdxf.layouts import BaseLayout

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
FAST = {
    "placement_solver": "greedy",
    "shrub_rows": False,
    "understory": False,
    "shrub_fill": False,
    "max_rejections": 20,
}


def _poly(space: BaseLayout, points: list[tuple[float, float]], layer: str) -> None:
    if space.doc.dxfversion == "AC1009":
        space.add_polyline2d(points, close=True, dxfattribs={"layer": layer})
    else:
        space.add_lwpolyline(points, close=True, dxfattribs={"layer": layer})


def _street(space: BaseLayout, *, boundary: bool = True) -> None:
    """Проезжая часть внизу, борт по y=12, газон выше, водопровод по y=25, дом вверху."""
    if boundary:
        _poly(space, [(0, 0), (60, 0), (60, 40), (0, 40)], "Граница заказа")
    for x in range(60):
        space.add_line((x, 12), (x + 0.7, 12), dxfattribs={"layer": "Бортовой камень"})
    _poly(space, [(0, 12), (60, 12), (60, 35), (0, 35)], "Леса и газоны")
    space.add_text("ГАЗОН", height=2.5, dxfattribs={"layer": "Леса и газоны"}).set_placement(
        (30, 20)
    )
    space.add_text("А", height=2.5, dxfattribs={"layer": "Граница улицы"}).set_placement((30, 6))
    space.add_line((0, 25), (60, 25), dxfattribs={"layer": "Водопровод"})
    space.add_text("d=300ст.", height=2.5, dxfattribs={"layer": "Водопровод"}).set_placement(
        (30, 25.5)
    )
    _poly(space, [(0, 35), (60, 35), (60, 40), (0, 40)], "Здания")


def _new(version: str = "R2018") -> Drawing:
    doc = ezdxf.new(version)
    if version != "R12":
        doc.units = 6
    return doc


def _run(tmp_path: Path, source: Path, **overrides: object) -> dict[str, object]:
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load("strict", {**FAST, **overrides})
    out = tmp_path / "out"
    report = container.use_case.execute(PlanRequest("t", source, out, "strict", params))
    container.artifacts.save(out, report)
    return {"report": report, "out": out}


def _trees(report: object) -> int:
    return sum(p.species.is_tree for p in report.plan.placements)  # ty: ignore[unresolved-attribute]


def test_r12_drawing_is_written_as_r2000_with_every_source_entity_intact(tmp_path: Path) -> None:
    doc = _new("R12")
    _street(doc.modelspace())
    source = tmp_path / "r12.dxf"
    doc.saveas(source)
    run = _run(tmp_path, source)
    report = run["report"]
    assert report.integrity.ok  # ty: ignore[unresolved-attribute]
    assert _trees(report) > 0
    assert any("DXF R12" in w for w in report.warnings)  # ty: ignore[unresolved-attribute]
    assert ezdxf.readfile(run["out"] / "result.dxf").dxfversion == "AC1015"  # ty: ignore[unsupported-operator]


def test_cyrillic_cp1251_under_a_western_codepage_is_read_as_cyrillic(tmp_path: Path) -> None:
    doc = _new("R2000")
    _street(doc.modelspace())
    source = tmp_path / "cp.dxf"
    doc.saveas(source, encoding="cp1251")  # заголовок остаётся ANSI_1252
    assert ezdxf.readfile(source).encoding == "cp1252"
    loaded, notes = load_document(source)
    assert "Граница заказа" in {e.dxf.layer for e in loaded.modelspace()}
    assert any("cp1251" in n for n in notes)
    report = _run(tmp_path, source)["report"]
    assert _trees(report) > 0
    assert report.integrity.ok  # ty: ignore[unresolved-attribute]


def test_drawing_without_a_work_boundary_gets_one_from_its_extent(tmp_path: Path) -> None:
    doc = _new()
    _street(doc.modelspace(), boundary=False)
    source = tmp_path / "open.dxf"
    doc.saveas(source)
    report = _run(tmp_path, source)["report"]
    assert _trees(report) > 0
    assert any("замкнутой границы работ в чертеже нет" in w for w in report.warnings)  # ty: ignore[unresolved-attribute]
    blocked = _run(tmp_path / "strict", source, infer_work_boundary=False)["report"]
    assert _trees(blocked) == 0


def test_block_inserting_itself_does_not_stop_the_run(tmp_path: Path) -> None:
    doc = _new()
    _street(doc.modelspace())
    loop = doc.blocks.new("LOOP")
    loop.add_circle((0, 0), 0.5)
    loop.add_blockref("LOOP", (3, 0))
    doc.modelspace().add_blockref("LOOP", (5, 38))
    source = tmp_path / "loop.dxf"
    doc.saveas(source)
    report = _run(tmp_path, source)["report"]
    assert report.integrity.ok  # ty: ignore[unresolved-attribute]
    assert any("цикл ссылок" in w for w in report.warnings)  # ty: ignore[unresolved-attribute]


def test_degenerate_objects_are_points_and_a_polyface_has_a_footprint(tmp_path: Path) -> None:
    doc = _new()
    msp = doc.modelspace()
    _street(msp)
    msp.add_circle((10, 30), 0.0, dxfattribs={"layer": "Колодцы"})
    msp.add_arc((20, 30), 2.0, 10, 10, dxfattribs={"layer": "Бортовой камень"})
    msp.add_polyface().append_face([(40, 14), (44, 14), (44, 18)])
    source = tmp_path / "degenerate.dxf"
    doc.saveas(source)
    report = _run(tmp_path, source)["report"]
    warnings = report.warnings  # ty: ignore[unresolved-attribute]
    assert any("прочитаны точкой: CIRCLE: 1, ARC: 1" in w for w in warnings)
    assert not any("прочитан не полностью" in w for w in warnings)


def test_missing_external_reference_is_a_warning_unless_input_is_strict(tmp_path: Path) -> None:
    doc = _new()
    _street(doc.modelspace())
    doc.blocks.new("XREF_NET", dxfattribs={"flags": 4, "xref_path": "C:/nowhere/net.dwg"})
    doc.modelspace().add_blockref("XREF_NET", (0, 0))
    source = tmp_path / "xref.dxf"
    doc.saveas(source)
    report = _run(tmp_path, source)["report"]
    assert _trees(report) > 0
    assert any(
        w.startswith("Чертёж прочитан не полностью: не найдена 1 внешняя ссылка")
        and "strict_input=true" in w
        for w in report.warnings  # ty: ignore[unresolved-attribute]
    )
    with pytest.raises(InputError, match="внешняя ссылка"):
        _run(tmp_path / "strict", source, strict_input=True)


def test_drawing_kind_is_decided_by_content_not_by_extension(tmp_path: Path) -> None:
    dwg = tmp_path / "plan.dxf"
    dwg.write_bytes(b"AC1032\x00\x00\x00\x00\x00\x00\x01")
    text = tmp_path / "plan.dwg"
    _new().saveas(text)
    binary = tmp_path / "bin.dwg"
    _new().saveas(binary, fmt="bin")
    garbage = tmp_path / "x.dwg"
    garbage.write_bytes(b"\x89PNG....")
    assert drawing_kind(dwg) == ".dwg"
    assert drawing_kind(text) == ".dxf"
    assert drawing_kind(binary) == ".dxf"
    assert drawing_kind(garbage) is None


@pytest.mark.parametrize(
    ("data", "message"),
    [(b"", "пуст"), (b"hello, this is not a drawing\n", "не DXF")],
)
def test_empty_or_foreign_file_names_the_problem(tmp_path: Path, data: bytes, message: str) -> None:
    path = tmp_path / "bad.dxf"
    path.write_bytes(data)
    with pytest.raises(InputError, match=message):
        load_document(path)


def _feature(geometry: object, cls: ObjectClass, handle: str) -> Feature:
    return Feature(SourceRef("f", "x", handle), "layer", geometry, object_class=cls)  # ty: ignore[invalid-argument-type]


def test_work_area_is_the_hull_of_site_objects_without_far_strays() -> None:
    site = [
        _feature(shapely.box(x, y, x + 1, y + 1), ObjectClass.BUILDING, f"b{x}{y}")
        for x in range(0, 100, 10)
        for y in range(0, 50, 10)
    ]
    stray = _feature(shapely.Point(50_000, 50_000).buffer(1), ObjectClass.BUILDING, "far")
    frame = _feature(shapely.box(-500, -500, 500, 500).boundary, ObjectClass.IGNORE, "frame")
    features, note = with_work_area([*site, stray, frame])
    added = [f for f in features if f.layer == INFERRED_LAYER]
    assert len(added) == 1
    area = shapely.Polygon(added[0].geometry.coords)
    assert area.bounds == pytest.approx((0, 0, 91, 41))
    assert note is not None
    assert "0,37 га" in note


def test_open_drawn_boundary_is_closed_by_its_hull_and_a_closed_one_is_kept() -> None:
    open_line = shapely.LineString([(0, 0), (100, 0), (100, 50), (0, 50)])
    features, note = with_work_area([_feature(open_line, ObjectClass.WORK_BOUNDARY, "wb")])
    assert note is not None
    assert "незамкнутой границе" in note
    assert shapely.Polygon(features[-1].geometry.coords).area == pytest.approx(5000)
    closed = shapely.box(0, 0, 100, 50).boundary
    kept, none = with_work_area([_feature(closed, ObjectClass.WORK_BOUNDARY, "wb")])
    assert none is None
    assert len(kept) == 1


def test_dwg_saved_as_dxf_is_sent_to_the_converter(tmp_path: Path) -> None:
    class Converter:
        name = "fake"

        def __init__(self) -> None:
            self.seen: list[str] = []

        def available(self) -> bool:
            return True

        def to_dxf(self, source: Path, workdir: Path) -> Path:
            self.seen.append(source.suffix)
            target = workdir / f"{source.stem}.dxf"
            shutil.copyfile(text, target)
            return target

    text = tmp_path / "real.dxf"
    _new().saveas(text)
    disguised = tmp_path / "plan.dxf"
    disguised.write_bytes(b"AC1032" + b"\x00" * 64)
    converter = Converter()
    path, name = to_dxf([converter], disguised, tmp_path / "work")
    assert name == "fake"
    assert converter.seen == [".dwg"]
    assert path.suffix == ".dxf"


def test_french_latin1_text_is_not_mistaken_for_cyrillic(tmp_path: Path) -> None:
    """Ревью 20.10.2026: буквы Latin-1 среди обычной латиницы - французский, а не кириллица."""
    doc = _new("R2000")
    for i in range(10):
        doc.modelspace().add_text(
            f"Bâtiment élevé à côté de la façade {i}", dxfattribs={"layer": "Façade"}
        )
    source = tmp_path / "fr.dxf"
    doc.saveas(source)
    loaded, notes = load_document(source)
    assert loaded.encoding == "cp1252"
    assert not any("cp1251" in n for n in notes)
    assert "Façade" in {e.dxf.layer for e in loaded.modelspace()}
