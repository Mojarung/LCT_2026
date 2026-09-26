"""Доказательство неизменности исходных данных: отпечатки DXF-тегов каждой сущности."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from ezdxf.lldxf.tagwriter import TagCollector

from green.application.errors import InputError
from green.application.results import IntegrityReport, SourceSnapshot
from green.infrastructure.cad.documents import RESULT_PREFIX, load_document
from green.infrastructure.cad.export_validation import check_written_plan

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from ezdxf.document import Drawing
    from ezdxf.lldxf.types import DXFTag

    from green.application.results import PlanExportReport
    from green.domain.planting import Plan

REPORT_LIMIT = 100
_TEXT_CHUNK = 3
_TEXT_TAIL = 1
_SURROGATE_LOW = 0xDC80
_SURROGATE_HIGH = 0xDCFF


class EzdxfIntegrityChecker:
    def __init__(self) -> None:
        # Результат, загруженный проверкой целостности: сверка плана берёт его же, а не читает
        # файл второй раз (на улице в 200 МБ одно чтение - минуты). Ключ - путь и время записи.
        self._loaded: tuple[Path, int, Drawing] | None = None

    def _result(self, result: Path) -> Drawing:
        stamp = result.stat().st_mtime_ns
        loaded, self._loaded = self._loaded, None
        if loaded is not None and loaded[0] == result and loaded[1] == stamp:
            return loaded[2]
        doc, _ = load_document(result)
        self._loaded = (result, stamp, doc)
        return doc

    def snapshot(self, source: Path) -> SourceSnapshot:
        digests, unexportable = fingerprints(load_document(source)[0])
        return SourceSnapshot(digests, unexportable)

    def check(self, before: SourceSnapshot, result: Path) -> IntegrityReport:
        """Сверяет отпечатки исходника (сняты писателем до правок) с сохранённым результатом."""
        doc = self._result(result)
        after, _ = fingerprints(doc)
        digests = before.digests
        changed = sorted(h for h, digest in digests.items() if h in after and after[h] != digest)
        missing = sorted(h for h in digests if h not in after)
        generated = _result_handles(doc)
        added = sorted(h for h in after if h not in digests and h not in generated)
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

    def check_plan(self, result: Path, plan: Plan, *, unit_m: float) -> PlanExportReport:
        return check_written_plan(result, plan, unit_m=unit_m, doc=self._result(result))


def require_exportable_document(doc: Drawing, name: str) -> None:
    """Catch data loss before an intermediate save can erase its evidence."""
    missing = []
    count = 0
    for block in doc.blocks:
        for entity in block:
            collector = TagCollector(dxfversion=doc.dxfversion, optional=False)
            if entity.preprocess_export(collector):
                continue
            count += 1
            if len(missing) < REPORT_LIMIT:
                missing.append(
                    f"{entity.dxftype()} {entity.dxf.handle}, слой {entity.dxf.get('layer', '0')!r}"
                )
    if count:
        raise InputError(
            f"{name}: {count} исходных сущностей невозможно сохранить: "
            + "; ".join(missing[:10])
            + ". Нужен DXF с полными данными; склейка не должна скрывать их потерю."
        )


def fingerprints(doc: Drawing) -> tuple[dict[str, str], int]:
    """Отпечатки всех исходных сущностей, включая исходные имена GREEN_*.

    Теги собираются так же, как их пишет файловый писатель ezdxf: необязательные теги со
    значением по умолчанию опускаются (optional=False), иначе DXF от конвертеров, где такие
    теги записаны явно, после пересохранения выглядит изменённым. Сущности, которые ezdxf не
    экспортирует (REGION без ACIS-данных), считаются отдельно и в отпечатки не входят.
    """
    digests: dict[str, str] = {}
    unexportable = 0
    for block in doc.blocks:
        for entity in block:
            collector = TagCollector(dxfversion=doc.dxfversion, optional=False)
            if not entity.preprocess_export(collector):
                unexportable += 1
                continue
            entity.export_dxf(collector)
            digests[entity.dxf.handle] = hashlib.blake2b(
                repr(_canonical(entity.dxftype(), collector.tags)).encode(), digest_size=16
            ).hexdigest()
    return digests, unexportable


def _result_handles(doc: Drawing) -> set[str]:
    """New result entities may be added; an original handle is always protected.

    An arbitrary source can already have GREEN_* layers or blocks. Naming alone
    must never exempt those original entities from changed/missing checks.
    """
    handles = set()
    for block in doc.blocks:
        own_block = block.name.upper().startswith(RESULT_PREFIX)
        for entity in block:
            name = entity.dxf.name if entity.dxftype() == "INSERT" else ""
            if own_block or _is_result(entity.dxf.get("layer", "0"), name):
                handles.add(entity.dxf.handle)
    return handles


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
