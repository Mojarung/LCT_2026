"""Доказательство неизменности исходных данных: отпечатки DXF-тегов каждой сущности."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from ezdxf.lldxf.tagwriter import TagCollector

from green.application.results import IntegrityReport, SourceSnapshot
from green.infrastructure.cad.documents import RESULT_PREFIX, load_document

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.document import Drawing

REPORT_LIMIT = 100


class EzdxfIntegrityChecker:
    def snapshot(self, source: Path) -> SourceSnapshot:
        return SourceSnapshot(fingerprints(load_document(source)[0]))

    def check(self, before: SourceSnapshot, result: Path) -> IntegrityReport:
        """Сверяет отпечатки исходника (сняты писателем до правок) с сохранённым результатом."""
        after = fingerprints(load_document(result)[0])
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
        )

    def verify_files(self, source: Path, result: Path) -> IntegrityReport:
        return self.check(self.snapshot(source), result)


def fingerprints(doc: Drawing) -> dict[str, str]:
    """Отпечатки всех сущностей вне слоёв и блоков результата (включая содержимое блоков)."""
    digests: dict[str, str] = {}
    for block in doc.blocks:
        if block.name.upper().startswith(RESULT_PREFIX):
            continue
        for entity in block:
            block_name = entity.dxf.name if entity.dxftype() == "INSERT" else ""
            if _is_result(entity.dxf.get("layer", "0"), block_name):
                continue
            collector = TagCollector(dxfversion=doc.dxfversion)
            entity.export_dxf(collector)
            digests[entity.dxf.handle] = hashlib.blake2b(
                repr(collector.tags).encode(), digest_size=16
            ).hexdigest()
    return digests


def _is_result(layer: str, block_name: str) -> bool:
    return layer.upper().startswith(RESULT_PREFIX) or block_name.upper().startswith(RESULT_PREFIX)
