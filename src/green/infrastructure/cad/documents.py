"""Загрузка DXF с откатом в режим восстановления для повреждённых файлов."""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import TYPE_CHECKING

import ezdxf
from ezdxf import recover

from green.application.errors import InputError

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.document import Drawing

RESULT_PREFIX = "GREEN_"
APPID = "LCT_GREEN"

type Loaded = tuple[Drawing, list[str]]


class DocumentCache:
    """Передаёт загруженный чертёж от читателя писателю: одна загрузка большого DXF вместо двух.

    Ключ учитывает время изменения и размер файла, поэтому изменённый файл перечитывается.
    Писатель забирает документ из кэша (take), дальше документ меняется только у него.
    """

    def __init__(self, capacity: int = 2) -> None:
        self._capacity = capacity
        self._lock = threading.Lock()
        self._items: OrderedDict[tuple[str, int, int], Loaded] = OrderedDict()

    def load(self, path: Path) -> Loaded:
        key = _key(path)
        with self._lock:
            cached = self._items.get(key)
        if cached is not None:
            return cached
        loaded = load_document(path)
        with self._lock:
            self._items[key] = loaded
            while len(self._items) > self._capacity:
                self._items.popitem(last=False)
        return loaded

    def take(self, path: Path) -> Loaded:
        with self._lock:
            cached = self._items.pop(_key(path), None)
        return cached if cached is not None else load_document(path)


def _key(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return str(path.resolve()), stat.st_mtime_ns, stat.st_size


def load_document(path: Path) -> tuple[Drawing, list[str]]:
    try:
        return ezdxf.readfile(path), []
    except ezdxf.DXFStructureError:
        pass
    except OSError as error:
        raise InputError(f"Не удалось открыть {path.name}: {error}") from error
    try:
        doc, auditor = recover.readfile(path)
    except ezdxf.DXFStructureError as error:
        raise InputError(f"{path.name} не является корректным DXF: {error}") from error
    fixes = len(auditor.fixes) + len(auditor.errors)
    return doc, [f"{path.name} прочитан в режиме восстановления, исправлено записей: {fixes}"]
