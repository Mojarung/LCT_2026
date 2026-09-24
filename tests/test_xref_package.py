"""Unknown package names and reference transforms must retain the same geometry."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import ezdxf
import pytest
from ezdxf import xref
from ezdxf.entities import XRecord
from fastapi.testclient import TestClient
from test_pipeline_synthetic import ROOT, _street

from green.application.errors import InputError
from green.application.input_quality import require_complete_geometry
from green.application.semantic_names import local_name
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.infrastructure.cad.documents import load_document
from green.infrastructure.cad.merge import EzdxfDrawingMerger, _save_package
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.cad.xref_package import expanded_entity_counts
from green.interfaces.api.app import API_PREFIX, create_app

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.document import Drawing


def _line(path: Path, *, unit: int = 6, start: float = 0, end: float = 10) -> Drawing:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = unit
    doc.layers.add("arbitrary pipe")
    doc.modelspace().add_line((start, 0), (end, 0), dxfattribs={"layer": "arbitrary pipe"})
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)
    return doc


def _host(path: Path, filename: str, *, scale: float = 1, angle: float = 0) -> Drawing:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    xref.attach(
        doc,
        block_name="arbitrary reference",
        filename=filename,
        insert=(100, 200),
        scale=scale,
        rotation=angle,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)
    return doc


@pytest.mark.parametrize("scale", [0.001, 1, 2, -1])
@pytest.mark.parametrize("angle", [0, 37, 90])
def test_xref_uses_existing_matrix_exactly_once(tmp_path: Path, scale: float, angle: float) -> None:
    asset, host = tmp_path / "network.dxf", tmp_path / "site.dxf"
    # Header says mm, but the existing insertion is the coordinate contract.
    _line(asset, unit=4)
    _host(host, ".\\NETWORK.dwg", scale=scale, angle=angle)
    target = tmp_path / "combined.dxf"
    result = EzdxfDrawingMerger().merge([host, asset], target)
    scene = EzdxfSceneReader().read(target)
    require_complete_geometry(scene)
    assert len(scene.features) == 1
    expected = [
        (100, 200),
        (
            100 + 10 * scale * math.cos(math.radians(angle)),
            200 + 10 * scale * math.sin(math.radians(angle)),
        ),
    ]
    for actual, point in zip(scene.features[0].geometry.coords, expected, strict=True):
        assert actual == pytest.approx(point)
    assert result.assembly is not None
    assert [i.role for i in result.assembly.inputs] == ["base", "xref_asset"]
    assert result.assembly.references[0].action == "embedded"
    assert len(ezdxf.readfile(target).modelspace()) == 1


def test_insertion_base_and_multiple_instances_are_preserved(tmp_path: Path) -> None:
    asset, host = tmp_path / "network.dxf", tmp_path / "site.dxf"
    doc = _line(asset, start=50, end=60)
    doc.header["$INSBASE"] = (50, 0, 0)
    doc.saveas(asset)
    doc = _host(host, "network.dxf")
    doc.modelspace().add_blockref("arbitrary reference", (500, 600))
    doc.saveas(host)
    target = tmp_path / "combined.dxf"
    EzdxfDrawingMerger().merge([host, asset], target)
    scene = EzdxfSceneReader().read(target)
    assert {tuple(f.geometry.coords[0]) for f in scene.features} == {(100, 200), (500, 600)}
    assert {tuple(f.geometry.coords[-1]) for f in scene.features} == {(110, 200), (510, 600)}


def test_nested_references_and_extra_order_do_not_duplicate_geometry(tmp_path: Path) -> None:
    leaf, child, host = [tmp_path / f"{name}.dxf" for name in ("leaf", "child", "host")]
    _line(leaf)
    _host(child, "leaf.dxf", scale=2, angle=90)
    _host(host, "child.dxf", scale=3)
    target = tmp_path / "combined.dxf"
    EzdxfDrawingMerger().merge([host, leaf, child], target)
    scene = EzdxfSceneReader().read(target)
    require_complete_geometry(scene)
    assert len(scene.features) == 1
    assert list(scene.features[0].geometry.coords) == pytest.approx([(400, 800), (400, 860)])


@pytest.mark.parametrize("nested", [False, True])
def test_overlays_obey_root_and_nested_visibility(tmp_path: Path, *, nested: bool) -> None:
    leaf, child, host = [tmp_path / f"{name}.dxf" for name in ("leaf", "child", "host")]
    _line(leaf)
    doc = _line(child, end=20)
    xref.attach(doc, block_name="overlay", filename="leaf.dxf", overlay=True)
    doc.saveas(child)
    _host(host, "child.dxf")
    sources = [host, child, leaf] if nested else [child, leaf]
    target = tmp_path / "combined.dxf"
    result = EzdxfDrawingMerger().merge(sources, target)
    scene = EzdxfSceneReader().read(target)
    require_complete_geometry(scene)
    assert len(scene.features) == (1 if nested else 2)
    assert result.assembly is not None
    assert any(r.action == "excluded_nested_overlay" for r in result.assembly.references) == nested


def test_missing_nested_overlay_is_not_required_by_parent(tmp_path: Path) -> None:
    child, host = tmp_path / "child.dxf", tmp_path / "host.dxf"
    doc = _line(child)
    xref.attach(doc, block_name="unseen", filename="not-provided.dxf", overlay=True)
    doc.saveas(child)
    _host(host, "child.dxf")
    target = tmp_path / "combined.dxf"
    EzdxfDrawingMerger().merge([host, child], target)
    scene = EzdxfSceneReader().read(target)
    require_complete_geometry(scene)
    assert len(scene.features) == 1


def test_package_does_not_open_unlisted_files(tmp_path: Path) -> None:
    asset, host, unrelated = [tmp_path / f"{name}.dxf" for name in ("secret", "host", "other")]
    _line(asset)
    _line(unrelated)
    _host(host, str(asset))
    with pytest.raises(InputError, match="не предоставлен"):
        EzdxfDrawingMerger().merge([host, unrelated], tmp_path / "combined.dxf")


@pytest.mark.parametrize("precise_path", [False, True])
def test_same_basename_requires_an_unambiguous_supplied_path(
    tmp_path: Path, *, precise_path: bool
) -> None:
    first, second, host = (
        tmp_path / "one/network.dxf",
        tmp_path / "two/network.dxf",
        tmp_path / "host.dxf",
    )
    _line(first, end=10)
    _line(second, end=20)
    _host(host, "one/network.dwg" if precise_path else "network.dwg")
    target = tmp_path / "combined.dxf"
    if not precise_path:
        with pytest.raises(InputError, match="одноимённых"):
            EzdxfDrawingMerger().merge([host, first, second], target)
        return
    result = EzdxfDrawingMerger().merge([host, first, second], target)
    assert result.assembly is not None
    assert [i.role for i in result.assembly.inputs] == ["base", "xref_asset", "overlay"]
    assert sorted(f.geometry.length for f in EzdxfSceneReader().read(target).features) == [10, 20]


def test_upload_names_survive_changed_disk_names_and_unicode_form(tmp_path: Path) -> None:
    asset, host = tmp_path / "extra_1.dxf", tmp_path / "input.dxf"
    _line(asset)
    _host(host, ".\\СЕТИ\\МАЙ.dwg")
    target = tmp_path / "combined.dxf"
    result = EzdxfDrawingMerger().merge(
        [host, asset], target, source_names=("пакет/основа.dwg", "пакет/сети/май.dwg")
    )
    assert len(EzdxfSceneReader().read(target).features) == 1
    assert result.assembly.references[0].source == "пакет/сети/май.dwg"


def test_reference_cycle_is_explicitly_rejected(tmp_path: Path) -> None:
    first, second = tmp_path / "one.dxf", tmp_path / "two.dxf"
    _host(first, "two.dxf")
    _host(second, "one.dxf")
    with pytest.raises(InputError, match="цикл"):
        EzdxfDrawingMerger().merge([first, second], tmp_path / "combined.dxf")


def test_xref_in_an_ordinary_wrapper_is_resolved(tmp_path: Path) -> None:
    asset, host = tmp_path / "asset.dxf", tmp_path / "host.dxf"
    _line(asset)
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    xref.define(doc, block_name="data", filename="asset.dxf")
    wrapper = doc.blocks.new("symbol")
    wrapper.add_blockref("data", (10, 20))
    doc.modelspace().add_blockref("symbol", (100, 200))
    doc.saveas(host)
    target = tmp_path / "combined.dxf"
    EzdxfDrawingMerger().merge([host, asset], target)
    scene = EzdxfSceneReader().read(target)
    assert list(scene.features[0].geometry.coords) == [(110, 220), (120, 220)]


def test_upload_runs_with_resolved_xref_and_records_assembly(tmp_path: Path) -> None:
    source, asset = tmp_path / "site.dxf", tmp_path / "networks.dxf"
    _street(source)
    doc = ezdxf.readfile(source)
    xref.attach(doc, block_name="unknown name", filename="networks.dwg")
    doc.saveas(source)
    _line(asset, end=10)
    settings = Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs")
    with TestClient(create_app(build_container(settings))) as client:
        response = client.post(
            f"{API_PREFIX}/runs",
            files=[
                ("file", ("site.dxf", source.read_bytes(), "image/vnd.dxf")),
                ("extra", ("networks.dxf", asset.read_bytes(), "image/vnd.dxf")),
            ],
            data={
                "overrides": (
                    '{"placement_solver":"greedy", '
                    '"block_classes":{"unknown name":"utility.water"}}'
                )
            },
        )
        assert response.status_code == 202, response.text
        run = client.get(response.headers["Location"]).json()
        assert run["state"] == "succeeded", run
        url = next(a["url"] for a in run["artifacts"] if a["name"] == "assembly.json")
        assembly = client.get(url).json()
        assert assembly["references"][0]["source"] == "networks.dxf"
        assert run["summary"]["integrity_ok"]


def test_shared_reference_is_loaded_at_each_insertion_but_not_as_extra_overlay(
    tmp_path: Path,
) -> None:
    leaf, child, host = [tmp_path / f"{name}.dxf" for name in ("leaf", "child", "host")]
    _line(leaf)
    _host(child, "leaf.dxf")
    doc = _host(host, "child.dxf")
    xref.attach(doc, block_name="also leaf", filename="leaf.dxf", insert=(10, 20))
    doc.saveas(host)
    target = tmp_path / "combined.dxf"
    EzdxfDrawingMerger().merge([host, leaf, child], target)
    scene = EzdxfSceneReader().read(target)
    assert len(scene.features) == 2
    assert {tuple(f.geometry.coords[0]) for f in scene.features} == {(200, 400), (10, 20)}


def test_independent_overlay_with_embedded_reference_normalises_once(tmp_path: Path) -> None:
    leaf, child, host = [tmp_path / f"{name}.dxf" for name in ("leaf", "child", "host")]
    _line(leaf, end=10000, unit=0)  # XREF coordinates have an explicit parent matrix.
    doc = _host(child, "leaf.dxf", scale=2)
    doc.header["$INSUNITS"] = 4
    doc.saveas(child)
    _line(host, end=1)
    target = tmp_path / "combined.dxf"
    EzdxfDrawingMerger().merge([host, leaf, child], target)
    scene = EzdxfSceneReader().read(target)
    assert sorted(f.geometry.length for f in scene.features) == pytest.approx([1, 20])
    long = max(scene.features, key=lambda f: f.geometry.length)
    assert list(long.geometry.coords) == pytest.approx([(0.1, 0.2), (20.1, 0.2)])


def test_loss_inside_imported_block_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaf, host = tmp_path / "leaf.dxf", tmp_path / "host.dxf"
    doc = _line(leaf)
    block = doc.blocks.new("nested detail")
    block.add_line((0, 0), (5, 0))
    doc.modelspace().add_blockref(block.name, (0, 0))
    doc.saveas(leaf)
    _host(host, "leaf.dxf")
    execute = xref.Loader.execute

    def broken_import(loader, xref_prefix: str = "") -> None:  # noqa: ANN001 - fault injection
        execute(loader, xref_prefix)
        for block in loader.tdoc.blocks:
            if "nested detail" in block.name:
                for entity in list(block.query("LINE")):
                    block.delete_entity(entity)

    monkeypatch.setattr(xref.Loader, "execute", broken_import)
    target = tmp_path / "combined.dxf"
    target.write_bytes(b"previous successful result")
    with pytest.raises(InputError, match="потеряны"):
        EzdxfDrawingMerger().merge([host, leaf], target)
    assert target.read_bytes() == b"previous successful result"


def test_expanded_inventory_counts_array_instances_and_attached_values() -> None:
    doc = ezdxf.new("R2018")
    block = doc.blocks.new("repeat")
    block.add_line((0, 0), (5, 0))
    insert = doc.modelspace().add_blockref(
        block.name,
        (0, 0),
        dxfattribs={"row_count": 2, "column_count": 3, "row_spacing": 10, "column_spacing": 10},
    )
    insert.add_attrib("ID", "pipe")
    assert expanded_entity_counts(doc.modelspace()) == {"INSERT": 1, "LINE": 6, "ATTRIB": 6}


def test_closed_extra_cycle_is_not_silently_ignored(tmp_path: Path) -> None:
    host, one, two = [tmp_path / f"{name}.dxf" for name in ("host", "one", "two")]
    _line(host)
    _host(one, "two.dxf")
    _host(two, "one.dxf")
    with pytest.raises(InputError, match="цикл"):
        EzdxfDrawingMerger().merge([host, one, two], tmp_path / "combined.dxf")


def _kit_boundary(path: Path, references: list[tuple[str, str]], *, insert: tuple = (0, 0)) -> None:
    """Файл границ работ комплекта: ссылается на подоснову и сети их исходными CAD-именами."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    doc.layers.add("Граница работ")
    doc.modelspace().add_lwpolyline(
        [(0, -5), (40, -5), (40, 5), (0, 5)], close=True, dxfattribs={"layer": "Граница работ"}
    )
    for block_name, filename in references:
        xref.attach(doc, block_name=block_name, filename=filename, insert=insert)
    doc.saveas(path)


def test_catalogue_names_resolve_boundary_references_and_keep_the_base_once(
    tmp_path: Path,
) -> None:
    """Кустанайская: границы ссылаются на «00.1_10004141_Топография», файл каталога назван
    «00-1-10004141-topografiya.dxf». Основа загружена как основа, сети внедрены один раз."""
    base = tmp_path / "00-1-10004141-topografiya.dxf"
    nets = tmp_path / "00-2-10004141-seti.dxf"
    bounds = tmp_path / "01-10004141-granitsy-rabot.dxf"
    _line(base, start=0, end=10)
    _line(nets, start=20, end=30)
    _kit_boundary(
        bounds,
        [
            ("00.1_10004141_Топография", r"..\..\00.1_10004141_Топография.dwg"),
            ("00.2_10004141_Сети", "00.2_10004141_Сети.dwg"),
        ],
    )

    result = EzdxfDrawingMerger().merge([base, nets, bounds], tmp_path / "merged.dxf")

    scene = EzdxfSceneReader().read(result.path)
    require_complete_geometry(scene)
    # Слои внедрённой ссылки названы как в AutoCAD: «00.2_10004141_Сети$0$arbitrary pipe».
    pipes = sorted(
        round(f.geometry.bounds[0])
        for f in scene.features
        if local_name(f.layer) == "arbitrary pipe"
    )
    assert pipes == [0, 20]
    actions = {binding.block: binding.action for binding in result.assembly.references}
    assert actions == {
        "00.1_10004141_Топография": "provided_as_input",
        "00.2_10004141_Сети": "embedded",
    }


def test_base_reference_with_an_offset_is_rejected(tmp_path: Path) -> None:
    """Основа уже лежит в своих координатах: ссылка со сдвигом означала бы второе положение."""
    base = tmp_path / "00-1-x-topografiya.dxf"
    bounds = tmp_path / "01-x-granitsy-rabot.dxf"
    _line(base)
    _kit_boundary(bounds, [("00.1_X_Топография", "00.1_X_Топография.dwg")], insert=(10, 0))

    with pytest.raises(InputError, match="XREF"):
        EzdxfDrawingMerger().merge([base, bounds], tmp_path / "merged.dxf")


@pytest.mark.parametrize("declared", [True, False])
def test_reference_absent_from_customer_data_is_a_named_gap_only_when_declared(
    tmp_path: Path, *, declared: bool
) -> None:
    """Файла наружного освещения нет во всём архиве заказчика: каталог это проверил и объявил.

    Объявленная ссылка не останавливает сборку, а попадает в заметки прогона; та же ссылка
    без объявления по-прежнему ошибка - комплект просто не полон."""
    base, nets = tmp_path / "base.dxf", tmp_path / "nets.dxf"
    _line(nets, start=20, end=30)
    doc = _line(base)
    xref.attach(doc, block_name="НО", filename=r".\НО наташинский пр.dwg", overlay=True)
    doc.saveas(base)
    names = ("Исходные данные/АПОТ.dwg", "Исходные данные/tp.dwg")
    absent = [("Исходные данные/АПОТ.dwg", r".\НО наташинский пр.dwg")] if declared else []

    merge = EzdxfDrawingMerger().merge
    if not declared:
        with pytest.raises(InputError, match="не предоставлен"):
            merge([base, nets], tmp_path / "m.dxf", source_names=names, absent_references=absent)
        return
    result = merge([base, nets], tmp_path / "m.dxf", source_names=names, absent_references=absent)

    scene = EzdxfSceneReader().read(result.path)
    require_complete_geometry(scene)
    assert len(scene.features) == 2
    assert any("нет в исходных данных заказчика" in note for note in result.notes)
    assert [(b.block, b.action) for b in result.assembly.references] == [("НО", "absent_in_source")]


def test_stale_dictionary_entry_pointing_at_a_block_is_dropped_before_saving(
    tmp_path: Path,
) -> None:
    """Харьковская: ezdxf не переносит ассоциативные связи между файлами и оставляет в словаре
    старый handle, а в склейке он занят определением блока. Аудит при чтении «отбирал» блок
    словарю и падал. Такая запись удаляется при записи склейки, геометрия цела."""
    doc = ezdxf.new("R2018")
    block = doc.blocks.new("output[1-8]_pp")
    block.add_line((0, 0), (1, 0))
    doc.modelspace().add_blockref("output[1-8]_pp", (0, 0))
    polyline = doc.modelspace().add_lwpolyline([(0, 0), (5, 0), (5, 5)])
    extension = polyline.new_extension_dict().dictionary
    extension._data["ACAD_ASSOCNETWORK"] = block.block  # noqa: SLF001 - так её оставляет копия
    target = tmp_path / "merged.dxf"

    dropped = _save_package(doc, target)

    assert dropped == 1
    written, _ = load_document(target)
    assert len(written.modelspace()) == 2
    assert written.blocks.get("output[1-8]_pp").block.dxf.name == "output[1-8]_pp"


@pytest.mark.parametrize("form", ["handle", "foreign"])
@pytest.mark.parametrize("victim", ["block", "polyline"])
def test_dictionary_entry_left_from_the_source_file_is_dropped_before_saving(
    tmp_path: Path, form: str, victim: str
) -> None:
    """Харьковская, второй заход: копия словаря из файла ссылки хранит ссылку исходного
    файла - строку handle или объект чужого документа. В склейке этот handle занят
    определением блока или полилинией; аудит при чтении отдавал их словарю: блок ронял
    чтение, у полилинии молча менялся владелец."""
    doc = ezdxf.new("R2018")
    block = doc.blocks.new("output[1-8]_pp")
    block.add_line((0, 0), (1, 0))
    msp = doc.modelspace()
    msp.add_blockref("output[1-8]_pp", (0, 0))
    other = msp.add_lwpolyline([(10, 0), (15, 0)])
    polyline = msp.add_lwpolyline([(0, 0), (5, 0), (5, 5)])
    taken = block.block.dxf.handle if victim == "block" else other.dxf.handle
    stale = taken if form == "handle" else XRecord.new(handle=taken)
    polyline.new_extension_dict().dictionary._data["ACAD_ASSOCNETWORK"] = stale  # noqa: SLF001
    target = tmp_path / "merged.dxf"

    dropped = _save_package(doc, target)

    assert dropped == 1
    written, _ = load_document(target)
    owner = written.modelspace().block_record_handle
    assert [e.dxf.owner for e in written.modelspace()] == [owner] * 3
    written_block = written.blocks.get("output[1-8]_pp")
    assert written_block.block.dxf.owner == written_block.block_record_handle
