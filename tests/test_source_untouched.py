"""Обработка не добавляет в исходный документ ничего своего.

ezdxf при отрисовке MULTILEADER (её вызывает `ezdxf.bbox.extents`) создаёт в документе блок
стрелки. На генплане Берзарина так в исходнике появлялась сущность SOLID, которой в файле
заказчика нет (docs/notes/22-source-document-untouched.md). Чтение и измерение чертежа обязаны
оставлять документ как есть, а писатель обязан заметить, если это не так.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import pytest
from ezdxf.math import Vec2
from ezdxf.render import mleader
from test_pipeline_synthetic import ROOT, _street

from green.application.errors import InputError
from green.application.use_case import PENDING_DXF, PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.infrastructure.cad.documents import DocumentCache
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.cad.units import measure

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.document import Drawing


def _with_leader(path: Path, *, container_only: bool) -> None:
    """Улица, к которой добавлена выноска MULTILEADER: в блоке-знаке и в самой модели.

    container_only: вся улица уезжает в блок, в модели остаётся одна вставка. Так выглядит генплан
    с привязанными XREF, на нём ошибка и проявилась.
    """
    _street(path)
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    sign = doc.blocks.new("SIGN_WITH_LEADER")
    sign.add_circle((0, 0), 0.5)
    _leader(sign)
    _leader(msp)
    msp.add_blockref("SIGN_WITH_LEADER", (30, 30))
    if container_only:
        shell = doc.blocks.new("XREF_LIKE")
        for entity in list(msp):
            msp.move_to_layout(entity, shell)
        msp.add_blockref("XREF_LIKE", (0, 0))
    _drop_arrow_blocks(doc)
    doc.saveas(path)


def _leader(layout: object) -> None:
    builder = layout.add_multileader_mtext("Standard")  # type: ignore[attr-defined]
    builder.set_content("липа")
    builder.add_leader_line(mleader.ConnectionSide.left, [Vec2(-30, -20)])
    builder.build(insert=Vec2(1, 1))


def _drop_arrow_blocks(doc: Drawing) -> None:
    """Построитель выноски сам создаёт блок стрелки. В файлах заказчика его нет: убираем."""
    for block in list(doc.blocks):
        if block.name.startswith("_") and not block.name.startswith("*"):
            doc.blocks.delete_block(block.name, safe=False)


def _state(doc: Drawing) -> tuple[int, frozenset[str]]:
    return len(doc.entitydb), frozenset(block.name for block in doc.blocks)


@pytest.mark.parametrize("container_only", [False, True])
def test_reading_and_measuring_leave_the_document_as_loaded(
    tmp_path: Path, *, container_only: bool
) -> None:
    source = tmp_path / "leader.dxf"
    _with_leader(source, container_only=container_only)
    cache = DocumentCache()
    doc, _ = cache.load(source)
    before = _state(doc)
    assert measure(doc) is not None
    scene = EzdxfSceneReader(documents=cache).read(source)
    assert len(scene.features) > 100
    assert _state(doc) == before


@pytest.mark.parametrize("container_only", [False, True])
def test_result_holds_no_blocks_the_source_did_not_have(
    tmp_path: Path, *, container_only: bool
) -> None:
    source = tmp_path / "leader.dxf"
    _with_leader(source, container_only=container_only)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load("strict", {"max_rejections": 50})
    report = container.use_case.execute(
        PlanRequest("leader", source, tmp_path / "out", "strict", params)
    )
    assert report.integrity.ok
    assert len(report.plan.placements) >= 10
    had = {block.name for block in ezdxf.readfile(source).blocks}
    got = {block.name for block in ezdxf.readfile(report.output_dxf).blocks}
    assert {name for name in got - had if not name.upper().startswith("GREEN_")} == set()


def test_writer_reports_entities_added_by_processing(tmp_path: Path) -> None:
    """Если обработка всё же добавила сущность вне слоёв результата, целостность не сходится."""
    source = tmp_path / "street.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    original_read = container.reader.read
    params = container.profiles.load("strict", {"max_rejections": 50})
    request = PlanRequest("careless", source, tmp_path / "out", "strict", params)
    previous = container.use_case.execute(request).output_dxf.read_bytes()

    def careless_read(path: Path, *, unit: str = "auto"):  # noqa: ANN202 - Scene из читателя
        scene = original_read(path, unit=unit)
        doc, _ = container.documents.load(path)
        doc.modelspace().add_line((0, 0), (1, 1), dxfattribs={"layer": "Бортовой камень"})
        return scene

    container.use_case._reader = type("Careless", (), {"read": staticmethod(careless_read)})()  # noqa: SLF001
    with pytest.raises(InputError, match="добавлено вне результата 1"):
        container.use_case.execute(request)
    assert (tmp_path / "out" / "result.dxf").read_bytes() == previous
    integrity = container.integrity.verify_files(source, tmp_path / "out" / PENDING_DXF)
    assert not integrity.ok
    assert len(integrity.added_outside_result_layers) == 1
