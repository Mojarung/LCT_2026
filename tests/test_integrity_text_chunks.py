"""Отпечаток длинного MTEXT переживает пересохранение, даже если буква разорвана между кусками.

LibreDWG пишет длинный текст кусками по 250 байт и рвёт двухбайтовую кириллическую букву между
куском с кодом 3 и следующим. ezdxf читает половинки как суррогаты, при записи склеивает их в
букву и нарезает текст заново. На посадочном плане Берзарина из-за этого «менялись» 4 сущности
из 311 432 (docs/notes/24-audit.md).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import ezdxf

from green.infrastructure.cad.documents import load_document
from green.infrastructure.cad.integrity import EzdxfIntegrityChecker

if TYPE_CHECKING:
    from pathlib import Path

LONG_TEXT = "ДАННЫЙ ПЛАН ВЫДАН ГБУ Мосгоргеотрест " * 12
CHUNK_TAIL = re.compile(rb"(\r?\n  3\r?\n)([^\r\n]+)(\r?\n  [13]\r?\n)([^\r\n]+)")


def _split_a_letter_between_chunks(path: Path) -> None:
    """Первый байт следующего куска переносится в конец предыдущего: буква рвётся пополам."""
    raw = path.read_bytes()
    match = CHUNK_TAIL.search(raw)
    assert match is not None, "в файле нет MTEXT, нарезанного на куски"
    head, first, separator, second = match.groups()
    assert second[0] >= 0x80, "следующий кусок должен начинаться с двухбайтовой буквы"
    broken = head + first + second[:1] + separator + second[1:]
    path.write_bytes(raw[: match.start()] + broken + raw[match.end() :])


def test_letter_split_between_text_chunks_is_not_a_change(tmp_path: Path) -> None:
    source = tmp_path / "source.dxf"
    drawing = ezdxf.new("R2018")
    drawing.modelspace().add_mtext(LONG_TEXT)
    drawing.modelspace().add_line((0, 0), (1, 1))
    drawing.saveas(source)
    _split_a_letter_between_chunks(source)
    loaded, _ = load_document(source)
    text = loaded.modelspace().query("MTEXT").first.text
    assert any(0xDC80 <= ord(ch) <= 0xDCFF for ch in text), "разрыв буквы не воспроизведён"

    checker = EzdxfIntegrityChecker()
    snapshot = checker.snapshot(source)
    resaved = tmp_path / "resaved.dxf"
    load_document(source)[0].saveas(resaved)
    report = checker.check(snapshot, resaved)

    assert report.ok
    assert report.changed == ()


def test_changed_text_is_still_reported(tmp_path: Path) -> None:
    source = tmp_path / "source.dxf"
    drawing = ezdxf.new("R2018")
    drawing.modelspace().add_mtext(LONG_TEXT)
    drawing.saveas(source)
    checker = EzdxfIntegrityChecker()
    snapshot = checker.snapshot(source)

    edited = ezdxf.readfile(source)
    mtext = edited.modelspace().query("MTEXT").first
    mtext.text = mtext.text.replace("Мосгоргеотрест", "Мосгоргеотрест!", 1)
    result = tmp_path / "edited.dxf"
    edited.saveas(result)

    report = checker.check(snapshot, result)
    assert not report.ok
    assert len(report.changed) == 1
