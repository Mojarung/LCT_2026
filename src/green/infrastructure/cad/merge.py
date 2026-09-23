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

from green.application.errors import InputError
from green.application.ports import MergeResult
from green.infrastructure.cad.documents import load_document
from green.infrastructure.cad.integrity import require_exportable_document
from green.infrastructure.cad.units import decide_units, measure

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
    def merge(self, sources: Sequence[Path], target: Path, *, unit: str = "auto") -> MergeResult:
        if len(sources) < _MIN_SOURCES:
            raise InputError("Склейка: нужно не меньше двух чертежей")
        base, notes = load_document(sources[0])
        require_exportable_document(base, sources[0].name)
        notes = list(notes)
        counts = [len(base.modelspace())]
        base_unit = decide_units(base, unit).unit_m
        base_box = _extents(base)
        for path in sources[1:]:
            doc, doc_notes = load_document(path)
            require_exportable_document(doc, path.name)
            notes += doc_notes
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
            raise InputError(
                f"Склейка: ожидалось {sum(counts)} сущностей, получено {merged} - часть сущностей "
                "не перенесена. Расчёт на неполном комплекте остановлен."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        base.saveas(target)
        return MergeResult(path=target, notes=tuple(notes))


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
