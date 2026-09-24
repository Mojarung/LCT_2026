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

from typing import TYPE_CHECKING

from ezdxf import transform, xref
from ezdxf.entities import Dictionary, DXFEntity, is_graphic_entity

from green.application.errors import InputError
from green.application.ports import MergeResult
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
# Не объекты: определения блоков и элементы таблиц. В словаре им быть нельзя.
_NOT_OBJECTS = frozenset(
    {"BLOCK", "ENDBLK", "BLOCK_RECORD", "LAYER", "LTYPE", "STYLE", "DIMSTYLE", "UCS", "VIEW",
     "VPORT", "APPID"}
)  # fmt: skip

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
        absent_references: Sequence[tuple[str, str]] = (),
    ) -> MergeResult:
        if len(sources) < _MIN_SOURCES:
            raise InputError("Склейка: нужно не меньше двух чертежей")
        if target.resolve() in {source.resolve() for source in sources}:
            raise InputError("Склейка не может перезаписать один из исходных файлов")
        package = DrawingPackage.load(sources, source_names, absent_references)
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
        dropped = _save_package(base, target)
        if dropped:
            notes.append(
                f"Склейка: удалено {dropped} устаревших записей словарей (ассоциативные связи "
                "и поля, которые ezdxf не переносит между файлами); геометрия не затронута"
            )
        return MergeResult(path=target, notes=tuple(notes), assembly=assembly)


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


def _save_package(doc: Drawing, target: Path) -> int:
    """Записать склейку и проверить её обратным чтением; число удалённых записей словарей."""
    require_exportable_document(doc, target.name)
    dropped = _drop_stale_dictionary_entries(doc)
    expected = expanded_entity_counts(doc.modelspace())
    pending = target.with_name(f".{target.name}.pending")
    doc.saveas(pending)
    written, _ = load_document(pending)
    if expanded_entity_counts(written.modelspace()) != expected:
        raise InputError("Склейка: записанный DXF потерял часть структуры объектов")
    pending.replace(target)
    return dropped


def _drop_stale_dictionary_entries(doc: Drawing) -> int:
    """Убрать из словарей записи, которые указывают не на объекты.

    Словарь хранит только объекты секции OBJECTS. Когда ezdxf при внедрении ссылки не может
    скопировать объект словаря (ACAD_ASSOCNETWORK, FIELD, прокси: «copy process ignored»), в
    словаре остаётся старый handle исходного файла, а в собранном он занят чужой сущностью:
    полилинией или определением блока (Харьковская, 25.09.2026). Аудит при чтении «отбирает»
    такой блок словарю и падает. Сама запись - остаток ассоциативных связей, не геометрия.
    """
    dropped = 0
    for dictionary in doc.objects:
        if not isinstance(dictionary, Dictionary):
            continue
        for key, value in list(dictionary.items()):
            if isinstance(value, DXFEntity) and (
                is_graphic_entity(value) or value.dxftype() in _NOT_OBJECTS
            ):
                dictionary.discard(key)
                dropped += 1
    return dropped


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
