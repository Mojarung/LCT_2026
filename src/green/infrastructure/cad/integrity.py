"""Доказательство неизменности исходных данных: отпечатки DXF-тегов каждой сущности."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from ezdxf.lldxf.tagwriter import TagCollector

from green.application.results import IntegrityReport, SourceSnapshot
from green.infrastructure.cad.documents import RESULT_PREFIX, load_document

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from ezdxf.document import Drawing
    from ezdxf.lldxf.types import DXFTag

REPORT_LIMIT = 100
_TEXT_CHUNK = 3
_TEXT_TAIL = 1
_SURROGATE_LOW = 0xDC80
_SURROGATE_HIGH = 0xDCFF


class EzdxfIntegrityChecker:
    def snapshot(self, source: Path) -> SourceSnapshot:
        digests, unexportable = fingerprints(load_document(source)[0])
        return SourceSnapshot(digests, unexportable)

    def check(self, before: SourceSnapshot, result: Path) -> IntegrityReport:
        """Сверяет отпечатки исходника (сняты писателем до правок) с сохранённым результатом."""
        after, _ = fingerprints(load_document(result)[0])
        digests = before.digests
        changed = sorted(h for h, digest in digests.items() if h in after and after[h] != digest)
        missing = sorted(h for h in digests if h not in after)
        added = sorted(h for h in after if h not in digests)
        return IntegrityReport(
            source_entities=len(digests),
            unchanged=len(digests) - len(changed) - len(missing),
            changed=tuple(changed[:REPORT_LIMIT]),
            missing=tuple(missing[:REPORT_LIMIT]),
            added_outside_result_layers=tuple(added[:REPORT_LIMIT]),
            unexportable=before.unexportable,
        )

    def verify_files(self, source: Path, result: Path) -> IntegrityReport:
        return self.check(self.snapshot(source), result)


def fingerprints(doc: Drawing) -> tuple[dict[str, str], int]:
    """Отпечатки всех сущностей вне слоёв и блоков результата (включая содержимое блоков).

    Теги собираются так же, как их пишет файловый писатель ezdxf: необязательные теги со
    значением по умолчанию опускаются (optional=False), иначе DXF от конвертеров, где такие
    теги записаны явно, после пересохранения выглядит изменённым. Сущности, которые ezdxf не
    экспортирует (REGION без ACIS-данных), считаются отдельно и в отпечатки не входят.
    """
    digests: dict[str, str] = {}
    unexportable = 0
    for block in doc.blocks:
        if block.name.upper().startswith(RESULT_PREFIX):
            continue
        for entity in block:
            block_name = entity.dxf.name if entity.dxftype() == "INSERT" else ""
            if _is_result(entity.dxf.get("layer", "0"), block_name):
                continue
            collector = TagCollector(dxfversion=doc.dxfversion, optional=False)
            if not entity.preprocess_export(collector):
                unexportable += 1
                continue
            entity.export_dxf(collector)
            digests[entity.dxf.handle] = hashlib.blake2b(
                repr(_canonical(entity.dxftype(), collector.tags)).encode(), digest_size=16
            ).hexdigest()
    return digests, unexportable


def _canonical(kind: str, tags: Iterable[DXFTag]) -> list[tuple[int, object]]:
    """Теги в виде, который не меняется от пересохранения самого по себе.

    Длинный текст MTEXT лежит в DXF кусками по 250 знаков: коды 3 и замыкающий 1. LibreDWG режет
    по байтам и рвёт двухбайтовую букву между кусками. ezdxf читает половинки как суррогаты,
    при записи склеивает байты обратно в букву и нарезает текст заново. Содержимое то же, а теги
    другие: на посадочном плане Берзарина так «менялись» 4 сущности из 311 432
    (docs/notes/24-audit.md). Поэтому куски склеиваются, суррогаты сводятся к буквам.
    """
    items: list[tuple[int, object]] = []
    chunks: list[str] = []
    for tag in tags:
        code, value = tag.code, tag.value
        if kind == "MTEXT" and code == _TEXT_CHUNK and isinstance(value, str):
            chunks.append(value)
            continue
        if kind == "MTEXT" and code == _TEXT_TAIL and isinstance(value, str):
            value, chunks = "".join([*chunks, value]), []
        items.append((code, _whole_characters(value) if isinstance(value, str) else value))
    if chunks:
        items.append((_TEXT_CHUNK, _whole_characters("".join(chunks))))
    return items


def _whole_characters(value: str) -> str:
    """Суррогаты от чтения с surrogateescape обратно в байты и в буквы, если байты это UTF-8."""
    if value.isascii() or not any(_SURROGATE_LOW <= ord(ch) <= _SURROGATE_HIGH for ch in value):
        return value
    return value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def _is_result(layer: str, block_name: str) -> bool:
    return layer.upper().startswith(RESULT_PREFIX) or block_name.upper().startswith(RESULT_PREFIX)
