"""Поиск данных ACIS по дескриптору сущности через индекс, а не перебором.

ezdxf 1.4.4 (sections/acdsdata.py, AcDsDataSection.find_acis_record) на каждое обращение к
`sab` у REGION и 3DSOLID перебирает все записи ACDSDATA: на чертеже с тысячами областей это
N^2. Профиль Камчатской 17.10.2026 - 78 с из 288 прогона уходило на этот перебор при раскрытии
вставок и сверке целостности. Индекс «дескриптор -> первая запись» строится по разделу один раз
и перестраивается, когда список записей меняется (добавление, удаление); ответ тот же, что у
перебора: первая подходящая запись.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ezdxf.sections import acdsdata

if TYPE_CHECKING:
    from ezdxf.sections.acdsdata import AcDsDataSection, AcDsRecord

_INDEX = "_green_acis_index"


def _find_acis_record(self: AcDsDataSection, handle: str) -> AcDsRecord | None:
    entities = self.entities
    cached = getattr(self, _INDEX, None)
    if cached is None or cached[0] is not entities or cached[1] != len(entities):
        index: dict[str, AcDsRecord] = {}
        for record in self.acdsrecords:
            if acdsdata.is_acis_data(record):
                index.setdefault(acdsdata.acis_entity_handle(record), record)
        cached = (entities, len(entities), index)
        setattr(self, _INDEX, cached)
    return cached[2].get(handle)


def _new_acis_data(self: AcDsDataSection, handle: str, sab_data: bytes) -> None:
    """Новая запись дописывается и в индекс: запись результата не перестраивает его N раз."""
    cached = getattr(self, _INDEX, None)
    fresh = cached is not None and cached[0] is self.entities and cached[1] == len(self.entities)
    _NEW(self, handle, sab_data)
    if fresh:
        cached[2].setdefault(handle, self.entities[-1])
        setattr(self, _INDEX, (self.entities, len(self.entities), cached[2]))


_NEW = acdsdata.AcDsDataSection.new_acis_data


def install() -> None:
    """Подменить поиск в ezdxf; повторный вызов ничего не меняет."""
    acdsdata.AcDsDataSection.find_acis_record = _find_acis_record
    acdsdata.AcDsDataSection.new_acis_data = _new_acis_data
