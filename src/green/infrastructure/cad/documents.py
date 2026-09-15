"""Загрузка DXF с откатом в режим восстановления для повреждённых файлов."""

from __future__ import annotations

import io
import re
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING

import ezdxf
from ezdxf import recover

from green.application.errors import InputError

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.audit import Auditor
    from ezdxf.document import Drawing

RESULT_PREFIX = "GREEN_"
APPID = "LCT_GREEN"
_BAD_UNICODE_ESCAPE = re.compile(rb"\\U\+(?![0-9A-Fa-f]{4})")
_GROUP_CODE = re.compile(rb"^\s*-?\d{1,4}\s*$")

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
    doc: Drawing | None = None
    try:
        doc = ezdxf.readfile(path)
    except ezdxf.DXFStructureError, ValueError:
        pass
    except OSError as error:
        raise InputError(f"Не удалось открыть {path.name}: {error}") from error
    if doc is not None:
        # Строгий загрузчик не проверяет ссылки. DXF от конвертеров (LibreDWG) содержат висячие
        # handle, например у материалов ByLayer, и без аудита ezdxf падает при сохранении.
        auditor = doc.audit()
        fixes = len(auditor.fixes)
        if not fixes and not auditor.errors:
            return doc, []
        note = f"{path.name}: аудит исправил записей: {fixes}, ошибок: {len(auditor.errors)}"
        return doc, [note]
    notes: list[str] = []
    try:
        doc, auditor = recover.readfile(path)
    except ezdxf.DXFStructureError, ValueError:
        # LibreDWG режет длинные строки посреди «\U+XXXX» (ValueError) и оставляет сырые
        # переводы строк (DXFStructureError, пары «код-значение» съезжают): чиним и читаем снова.
        doc, auditor, note = _recover_repaired(path)
        notes.append(note)
    fixes = len(auditor.fixes) + len(auditor.errors)
    notes.append(f"{path.name} прочитан в режиме восстановления, исправлено записей: {fixes}")
    return doc, notes


def _recover_repaired(path: Path) -> tuple[Drawing, Auditor, str]:
    """Ремонт строк, которые LibreDWG режет посреди escape-последовательности и перевода строки."""
    data, joined = _join_broken_values(path.read_bytes())
    data, replaced = _BAD_UNICODE_ESCAPE.subn(b"?", data)
    try:
        doc, auditor = recover.read(io.BytesIO(data))
    except (ezdxf.DXFStructureError, ValueError) as error:
        raise InputError(f"{path.name} не является корректным DXF: {error}") from error
    note = (
        f"{path.name}: восстановлено разорванных строковых значений {joined}, "
        f"заменено некорректных последовательностей \\U+ {replaced}"
    )
    return doc, auditor, note


def _join_broken_values(data: bytes) -> tuple[bytes, int]:
    """DXF чередует строку кода группы и строку значения. Если на месте кода стоит не число,
    это хвост предыдущего значения с сырым переводом строки: он приклеивается обратно."""
    lines = data.split(b"\n")
    out: list[bytes] = []
    joined = 0
    expect_code = True
    for line in lines:
        if not expect_code:
            out.append(line)
            expect_code = True
        elif not line.strip():
            # Пустой хвост после последнего перевода строки (CRLF в конце файла) не значение.
            out.append(line)
        elif _GROUP_CODE.match(line) or not out:
            out.append(line)
            expect_code = False
        else:
            out[-1] = out[-1].rstrip(b"\r") + b" " + line.strip()
            joined += 1
    return b"\n".join(out), joined
