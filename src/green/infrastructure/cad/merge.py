"""Склейка комплекта DXF в один документ: первый файл - основа, остальные догружаются в модель.

Заказчик подаёт на вход не один чертёж, а комплект: генплан в одном DXF, геоподоснова в другом,
файлов может быть несколько (docs/notes/15-organizers-qa.md, вопросы 3 и 4). Проектировщик
делает то же вручную: накладывает чертежи по координатам и получает рабочий генплан.

Имена ресурсов. Одноимённые слои разных файлов должны остаться одним слоем: по имени слоя
работает классификатор. Это даёт политика KEEP. Но при KEEP одноимённые блоки с разным
содержимым получили бы геометрию первого файла. Поэтому, если имена пользовательских блоков
пересекаются, включается NUM_PREFIX: конфликтующий ресурс получает префикс «$0$», который
классификатор слоёв и читатель блоков уже понимают (так выглядят внедрённые XREF).
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from ezdxf import transform, xref
from ezdxf.entities import Region

from green.application.errors import InputError
from green.application.ports import MergeResult
from green.infrastructure.cad.acis_sidecar import load_region_sidecar, sidecar_path
from green.infrastructure.cad.documents import load_document
from green.infrastructure.cad.integrity import require_exportable_document
from green.infrastructure.cad.units import decide_units, measure
from green.infrastructure.cad.xref_package import DrawingPackage, expanded_entity_counts

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ezdxf.document import Drawing

_MIN_SOURCES = 2
# Файл комплекта, у которого с основой общая меньше половины меньшего из двух габаритов, скорее
# всего другой лист или другой объект: склейка пройдёт, а посадок не будет.
_MIN_OVERLAP = 0.5

type Box = tuple[float, float, float, float]


def _extents(doc: Drawing) -> Box | None:
    """Рамка точек привязки чертежа. `ezdxf.bbox` не годится: он меняет документ."""
    spread = measure(doc)
    return None if spread is None else spread.bounds


def _overlap(first: Box, second: Box) -> float:
    """Доля общей площади от меньшего из двух габаритов."""
    width = min(first[2], second[2]) - max(first[0], second[0])
    height = min(first[3], second[3]) - max(first[1], second[1])
    if width < 0 or height < 0:
        return 0.0
    smaller = min((b[2] - b[0]) * (b[3] - b[1]) for b in (first, second))
    if smaller <= 0:
        # Файл из одной линии или одной вставки даёт рамку нулевой площади: она либо лежит
        # внутри второй рамки, либо нет.
        return 1.0
    return (width * height) / smaller


def _area(box: Box | None) -> float:
    return 0.0 if box is None else max(box[2] - box[0], 0.0) * max(box[3] - box[1], 0.0)


def _union(first: Box | None, second: Box | None) -> Box | None:
    if first is None:
        return second
    if second is None:
        return first
    return (
        min(first[0], second[0]),
        min(first[1], second[1]),
        max(first[2], second[2]),
        max(first[3], second[3]),
    )


def _user_blocks(doc: Drawing) -> set[str]:
    return {block.name for block in doc.blocks if not block.name.startswith("*")}


class EzdxfDrawingMerger:
    def merge(
        self,
        sources: Sequence[Path],
        target: Path,
        *,
        unit: str = "auto",
        source_names: Sequence[str] = (),
    ) -> MergeResult:
        if len(sources) < _MIN_SOURCES:
            raise InputError("Склейка: нужно не меньше двух чертежей")
        if target.resolve() in {source.resolve() for source in sources}:
            raise InputError("Склейка не может перезаписать один из исходных файлов")
        package = DrawingPackage.load(sources, source_names)
        sat_by_sab = _collect_region_sidecars(sources, package.documents)
        package.resolve()
        base = package.documents[0]
        notes = package.notes
        assembly = package.report()
        for binding in assembly.references:
            notes.append(
                f"XREF {binding.block}: {binding.action}, {binding.source or binding.reference}; "
                "масштаб и положение заданы исходной вставкой"
            )
        counts = [len(base.modelspace())]
        base_unit = decide_units(base, unit).unit_m
        base_box = _extents(base)
        for index in package.roots[1:]:
            path, doc = sources[index], package.documents[index]
            counts.append(len(doc.modelspace()))
            factor = decide_units(doc, unit).unit_m / base_unit
            if factor != 1.0:
                _normalise(doc, factor, path.name)
                notes.append(
                    f"Склейка: координаты {path.name} переведены в единицы основы, "
                    f"коэффициент {factor:g}"
                )
            box = _extents(doc)
            # Сверяемся с тем, что уже набралось, а не только с основой. Комплект улицы -
            # это несколько планшетов Мосгеотреста, каждый на свой кусок: с основой такой
            # планшет может не пересекаться вовсе, а с уже склеенным - обязан, иначе он
            # действительно про другой объект. Вырожденный габарит основы (генплан, у
            # которого вся геометрия во внешних ссылках) проверку не проходит вообще.
            if box is not None and base_box is not None and _area(base_box) > 0:
                shared = _overlap(base_box, box)
                if shared < _MIN_OVERLAP:
                    notes.append(
                        f"Склейка: габариты {path.name} и уже склеенного комплекта "
                        f"перекрываются на {shared:.0%} - возможно, это разные листы или "
                        "разные объекты"
                    )
            base_box = _union(base_box, box)
            _load_overlay(base, doc, path.name, notes)
        merged = len(base.modelspace())
        listed = ", ".join(
            f"{sources[index].name}: {count}"
            for index, count in zip(package.roots, counts, strict=True)
        )
        notes.append(f"Склейка комплекта: {listed}; в объединённом чертеже {merged} сущностей")
        if merged != sum(counts):
            raise InputError(
                f"Склейка: ожидалось {sum(counts)} сущностей, получено {merged} - часть сущностей "
                "не перенесена. Расчёт на неполном комплекте остановлен."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        _save_package(base, target)
        _propagate_region_sidecars(sat_by_sab, target)
        return MergeResult(path=target, notes=tuple(notes), assembly=assembly)


def _collect_region_sidecars(
    sources: Sequence[Path], documents: Sequence[Drawing]
) -> dict[str, str]:
    sat_by_sab: dict[str, str] = {}
    for source, doc in zip(sources, documents, strict=True):
        path = sidecar_path(source)
        if not path.exists():
            continue
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        load_region_sidecar(source, digest, doc)
        payload = json.loads(path.read_text(encoding="utf-8"))
        for entry in payload["regions"].values():
            sab_digest = entry["sab_sha256"]
            sat = entry["sat"]
            if sab_digest in sat_by_sab and sat_by_sab[sab_digest] != sat:
                raise InputError("Склейка: одинаковый SAB получил разные SAT-контуры")
            sat_by_sab[sab_digest] = sat
    return sat_by_sab


def _propagate_region_sidecars(sat_by_sab: dict[str, str], target: Path) -> None:
    """Follow SAB content through ezdxf handle remapping when drawings are merged."""
    if not sat_by_sab:
        sidecar_path(target).unlink(missing_ok=True)
        return
    merged, _ = load_document(target)
    regions = [entity for entity in merged.entitydb.values() if isinstance(entity, Region)]
    mapped = {}
    used: set[str] = set()
    for region in regions:
        if not region.sab:
            continue
        digest = hashlib.sha256(region.sab).hexdigest()
        sat = sat_by_sab.get(digest)
        if sat is not None:
            mapped[region.dxf.handle] = {"sab_sha256": digest, "sat": sat}
            used.add(digest)
    if used != sat_by_sab.keys():
        raise InputError("Склейка: один или несколько ACIS REGION потеряны или изменены")
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    payload = {
        "schema": 1,
        "engine": "acadrust",
        "engine_version": "0.5.5",
        "dxf_sha256": digest,
        "source_regions": len(regions),
        "regions": mapped,
    }
    sidecar_path(target).write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    load_region_sidecar(target, digest, merged)


def _load_overlay(base: Drawing, doc: Drawing, name: str, notes: list[str]) -> None:
    if doc.dxfversion > base.dxfversion:
        raise InputError(f"Склейка: {name} имеет более новую версию DXF, чем основа")
    clash = sorted(_user_blocks(base) & _user_blocks(doc))
    policy = xref.ConflictPolicy.NUM_PREFIX if clash else xref.ConflictPolicy.KEEP
    if clash:
        notes.append(
            f"Склейка: в {name} {len(clash)} блоков с именами, которые уже есть "
            "в основе; совпавшие ресурсы этого файла получили префикс «$0$»"
        )
    expected = expanded_entity_counts(base.modelspace()) + expanded_entity_counts(doc.modelspace())
    xref.load_modelspace(doc, base, conflict_policy=policy)
    if expanded_entity_counts(base.modelspace()) != expected:
        raise InputError(f"Склейка: при импорте {name} потеряны/заменены вложенные сущности")


def _save_package(doc: Drawing, target: Path) -> None:
    require_exportable_document(doc, target.name)
    expected = expanded_entity_counts(doc.modelspace())
    pending = target.with_name(f".{target.name}.pending")
    doc.saveas(pending)
    written, _ = load_document(pending)
    if expanded_entity_counts(written.modelspace()) != expected:
        raise InputError("Склейка: записанный DXF потерял часть структуры объектов")
    pending.replace(target)


def _normalise(doc: Drawing, factor: float, name: str) -> None:
    if factor < transform.MIN_SCALING_FACTOR:
        raise InputError(f"Склейка: слишком малый коэффициент единиц {factor:g} для {name}")
    # Only modelspace entities. INSERT scales its block contents exactly once;
    # transforming block definitions as well would double-scale nested geometry.
    errors = transform.scale_uniform(doc.modelspace(), factor)
    if errors:
        raise InputError(
            f"Склейка: не удалось пересчитать единицы {name}: " + "; ".join(errors.messages()[:5])
        )
