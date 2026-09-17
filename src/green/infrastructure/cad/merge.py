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

from ezdxf import xref

from green.application.errors import InputError
from green.application.ports import MergeResult
from green.infrastructure.cad.documents import load_document
from green.infrastructure.cad.units import measure

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


def _user_blocks(doc: Drawing) -> set[str]:
    return {block.name for block in doc.blocks if not block.name.startswith("*")}


class EzdxfDrawingMerger:
    def merge(self, sources: Sequence[Path], target: Path) -> MergeResult:
        if len(sources) < _MIN_SOURCES:
            raise InputError("Склейка: нужно не меньше двух чертежей")
        base, notes = load_document(sources[0])
        notes = list(notes)
        counts = [len(base.modelspace())]
        units = {sources[0].name: base.header.get("$INSUNITS", 0)}
        base_box = _extents(base)
        for path in sources[1:]:
            doc, doc_notes = load_document(path)
            notes += doc_notes
            counts.append(len(doc.modelspace()))
            units[path.name] = doc.header.get("$INSUNITS", 0)
            box = _extents(doc)
            if base_box is not None and box is not None:
                shared = _overlap(base_box, box)
                if shared < _MIN_OVERLAP:
                    notes.append(
                        f"Склейка: габариты {path.name} и основы {sources[0].name} "
                        f"перекрываются на {shared:.0%} - возможно, это разные листы или "
                        "разные объекты"
                    )
            clash = sorted(_user_blocks(base) & _user_blocks(doc))
            policy = xref.ConflictPolicy.NUM_PREFIX if clash else xref.ConflictPolicy.KEEP
            if clash:
                notes.append(
                    f"Склейка: в {path.name} {len(clash)} блоков с именами, которые уже есть "
                    "в основе; совпавшие ресурсы этого файла получили префикс «$0$»"
                )
            xref.load_modelspace(doc, base, conflict_policy=policy)
        merged = len(base.modelspace())
        listed = ", ".join(f"{p.name}: {n}" for p, n in zip(sources, counts, strict=True))
        notes.append(f"Склейка комплекта: {listed}; в объединённом чертеже {merged} сущностей")
        if merged != sum(counts):
            notes.append(
                f"Склейка: ожидалось {sum(counts)} сущностей, получено {merged} - часть сущностей "
                "ezdxf не переносит между документами"
            )
        if len(set(units.values())) > 1:
            notes.append(
                "Склейка: у файлов разные единицы чертежа ($INSUNITS): "
                + ", ".join(f"{name}: {value}" for name, value in units.items())
                + ". Координаты не пересчитывались"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        base.saveas(target)
        return MergeResult(path=target, notes=tuple(notes))
