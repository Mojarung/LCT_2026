"""Каталог улиц пилотного проекта, подготовленный на диске.

Читает `catalog.json`, который пишет `tools/prepare_streets.py`: распаковывать 11-гигабайтный
архив в рантайме нечем и незачем, поэтому улицы конвертируются заранее. Каталога может не
быть вовсе - на стенде жюри датасет не монтируется, и это не ошибка, а пустой список.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import orjson

from green.application.ports import StreetSource

if TYPE_CHECKING:
    from pathlib import Path

LOGGER = logging.getLogger(__name__)

CATALOG_NAME = "catalog.json"
_MB = 1024 * 1024


class JsonStreetCatalog:
    """Улицы из `catalog.json`. Файл перечитывается, когда меняется его отметка времени."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._cached: tuple[StreetSource, ...] = ()
        self._stamp: float | None = None

    def all(self) -> tuple[StreetSource, ...]:
        catalog = self._root / CATALOG_NAME
        try:
            stamp = catalog.stat().st_mtime
        except OSError:
            self._cached, self._stamp = (), None
            return ()
        if stamp != self._stamp:
            self._cached = self._read(catalog)
            self._stamp = stamp
        return self._cached

    def get(self, slug: str) -> StreetSource | None:
        return next((street for street in self.all() if street.slug == slug), None)

    def _read(self, catalog: Path) -> tuple[StreetSource, ...]:
        try:
            rows = orjson.loads(catalog.read_bytes())
        except OSError, orjson.JSONDecodeError:
            LOGGER.warning("Каталог улиц не прочитан: %s", catalog)
            return ()

        streets: list[StreetSource] = []
        for row in rows:
            folder = self._root / str(row.get("slug", ""))
            main = folder / str(row.get("main", ""))
            # Улица без основного файла в списке не нужна: запускать по ней нечего, а строка
            # в выпадающем списке, которая падает при выборе, хуже отсутствия строки.
            if not main.is_file():
                LOGGER.warning("Улица %s пропущена: нет %s", row.get("slug"), main)
                continue
            extra = tuple(
                folder / name
                for name in row.get("files", [])
                if name != main.name and (folder / name).is_file()
            )
            size = main.stat().st_size + sum(path.stat().st_size for path in extra)
            streets.append(
                StreetSource(
                    slug=str(row["slug"]),
                    number=int(row.get("number", 0)),
                    title=str(row.get("title", row["slug"])),
                    main=main,
                    extra=extra,
                    size_mb=round(size / _MB, 1),
                )
            )
        return tuple(sorted(streets, key=lambda street: street.number))


__all__ = ["JsonStreetCatalog"]
