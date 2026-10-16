"""Поиск данных ACIS по дескриптору сущности за постоянное время.

ezdxf 1.4.4 ищет запись ACDSDATA перебором всех записей на каждое обращение к `sab`
(sections/acdsdata.py, find_acis_record): на чертеже с тысячами REGION это N^2. Профиль
Камчатской 17.10.2026: 78 с из 288 прогона - этот перебор при раскрытии вставок и сверке
целостности. Индекс по дескриптору даёт тот же ответ, перебор не повторяется.
"""

from __future__ import annotations

import io

import ezdxf
from ezdxf.sections import acdsdata

from green.infrastructure.cad import documents  # noqa: F401 - ставит индекс поиска ACIS


def _doc_with_solids(count: int) -> ezdxf.document.Drawing:
    doc = ezdxf.new("R2018")
    for i in range(count):
        doc.modelspace().add_3dsolid().sab = b"ACIS BinaryFile" + i.to_bytes(4, "little")
    stream = io.StringIO()
    doc.write(stream)
    return ezdxf.read(io.StringIO(stream.getvalue()))


def test_each_solid_gets_its_own_acis_data() -> None:
    doc = _doc_with_solids(40)
    payloads = [solid.sab for solid in doc.modelspace().query("3DSOLID")]
    assert payloads == [b"ACIS BinaryFile" + i.to_bytes(4, "little") for i in range(40)]


def test_lookup_does_not_rescan_all_records(monkeypatch) -> None:  # noqa: ANN001
    doc = _doc_with_solids(200)
    calls = 0
    original = acdsdata.acis_entity_handle

    def counted(record):  # noqa: ANN001, ANN202
        nonlocal calls
        calls += 1
        return original(record)

    monkeypatch.setattr(acdsdata, "acis_entity_handle", counted)
    for solid in doc.modelspace().query("3DSOLID"):
        assert solid.sab
    assert calls <= 2 * 200  # перебор на каждое обращение дал бы ~200 * 100


def test_new_and_deleted_records_are_seen() -> None:
    doc = _doc_with_solids(5)
    section = doc.acdsdata
    first = doc.modelspace().query("3DSOLID").first
    assert section.get_acis_data(first.dxf.handle)
    section.new_acis_data("ABC", b"ACIS BinaryFileNEW")
    assert section.get_acis_data("ABC") == b"ACIS BinaryFileNEW"
    section.del_acis_data("ABC")
    assert section.get_acis_data("ABC") == b""
