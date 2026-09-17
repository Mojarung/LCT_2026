"""Загрузка DXF с откатом в режим восстановления для повреждённых файлов."""

from __future__ import annotations

import io
import re
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING

import ezdxf
from ezdxf import recover

from green.application.errors import InputError

if TYPE_CHECKING:
    from ezdxf.document import Drawing

RESULT_PREFIX = "GREEN_"
APPID = "LCT_GREEN"
_BAD_UNICODE_ESCAPE = re.compile(rb"\\U\+(?![0-9A-Fa-f]{4})")
_GROUP_CODE = re.compile(rb"^\s*-?\d{1,4}\s*$")
_LONE_CR = re.compile(rb"\r(?!\n)")

type Loaded = tuple[Drawing, list[str]]


class DocumentCache:
    """Передаёт загруженный чертёж от читателя писателю: одна загрузка большого DXF вместо двух.

    Ключ учитывает время изменения и размер файла, поэтому изменённый файл перечитывается.
    Писатель забирает документ из кэша (take), дальше документ меняется только у него.

    Кэш помнит handle всех сущностей сразу после загрузки. Всё, что появилось в документе
    между загрузкой и записью, добавила обработка, а не заказчик: писатель исключает такие
    сущности из отпечатков исходника, и проверка целостности называет их добавленными.
    """

    def __init__(self, capacity: int = 2) -> None:
        self._capacity = capacity
        self._lock = threading.Lock()
        self._items: OrderedDict[tuple[str, int, int], Loaded] = OrderedDict()
        self._loaded_handles: dict[int, frozenset[str]] = {}

    def load(self, path: Path) -> Loaded:
        key = _key(path)
        with self._lock:
            cached = self._items.get(key)
        if cached is not None:
            return cached
        loaded = load_document(path)
        handles = frozenset(loaded[0].entitydb.keys())
        with self._lock:
            self._items[key] = loaded
            self._loaded_handles[id(loaded[0])] = handles
            while len(self._items) > self._capacity:
                _, (evicted, _) = self._items.popitem(last=False)
                self._loaded_handles.pop(id(evicted), None)
        return loaded

    def take(self, path: Path) -> Loaded:
        with self._lock:
            cached = self._items.pop(_key(path), None)
        return cached if cached is not None else load_document(path)

    def added_since_load(self, doc: Drawing) -> frozenset[str]:
        """Handle сущностей, которых не было в документе сразу после загрузки."""
        with self._lock:
            loaded = self._loaded_handles.pop(id(doc), None)
        if loaded is None:
            return frozenset()
        return frozenset(doc.entitydb.keys()) - loaded


def _key(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return str(path.resolve()), stat.st_mtime_ns, stat.st_size


def load_document(path: Path) -> tuple[Drawing, list[str]]:
    """Загрузка с нарастающей терпимостью. Всё, что сделано с файлом, попадает в заметки.

    1. Строгий загрузчик ezdxf: он в два раза быстрее режима восстановления.
    2. Ремонт строк (дефекты LibreDWG) и снова строгий загрузчик, уже на отремонтированных байтах.
    3. Режим восстановления ezdxf на тех же байтах.

    Раньше после шага 1 шёл режим восстановления на исходном файле: на генплане Берзарина он
    16,9 с разбирал файл и падал на разорванной строке, после чего всё равно начинался ремонт
    (docs/notes/23-load-time.md).
    """
    try:
        return _strict(path, ezdxf.readfile(path), [])
    except ezdxf.DXFStructureError, ValueError:
        pass
    except OSError as error:
        raise InputError(f"Не удалось открыть {path.name}: {error}") from error
    data, notes = _repaired_bytes(path)
    if notes:
        doc = _read_strict(data)
        if doc is not None:
            return _strict(path, doc, notes)
    try:
        doc, auditor = recover.read(io.BytesIO(data))
    except (ezdxf.DXFStructureError, ValueError) as error:
        raise InputError(f"{path.name} не является корректным DXF: {error}") from error
    fixes = len(auditor.fixes) + len(auditor.errors)
    notes.append(f"{path.name} прочитан в режиме восстановления, исправлено записей: {fixes}")
    return doc, notes


def _strict(path: Path, doc: Drawing, notes: list[str]) -> tuple[Drawing, list[str]]:
    # Строгий загрузчик не проверяет ссылки. DXF от конвертеров (LibreDWG) содержат висячие
    # handle, например у материалов ByLayer, и без аудита ezdxf падает при сохранении.
    auditor = doc.audit()
    fixes = len(auditor.fixes)
    if fixes or auditor.errors:
        notes.append(f"{path.name}: аудит исправил записей: {fixes}, ошибок: {len(auditor.errors)}")
    return doc, notes


def _repaired_bytes(path: Path) -> tuple[bytes, list[str]]:
    """Ремонт строк, которые LibreDWG режет посреди escape-последовательности и перевода строки."""
    data, joined = _join_broken_values(path.read_bytes())
    data, replaced = _BAD_UNICODE_ESCAPE.subn(b"?", data)
    # Одиночный CR внутри значения: текстовый режим Python считает его переводом строки, и пары
    # «код-значение» у строгого загрузчика съезжают. Режим восстановления делит только по LF.
    data, lone = _LONE_CR.subn(b"", data)
    if not (joined or replaced or lone):
        return data, []
    note = (
        f"{path.name}: восстановлено разорванных строковых значений {joined}, "
        f"заменено некорректных последовательностей \\U+ {replaced}"
    )
    if lone:
        note += f", убрано одиночных возвратов каретки {lone}"
    return data, [note]


def _read_strict(data: bytes) -> Drawing | None:
    """Строгий загрузчик читает файл, а не байты: кодировку он определяет по заголовку сам."""
    with tempfile.TemporaryDirectory(prefix="green_dxf_") as folder:
        repaired = Path(folder) / "repaired.dxf"
        repaired.write_bytes(data)
        try:
            return ezdxf.readfile(repaired)
        except ezdxf.DXFStructureError, ValueError:
            return None


def _join_broken_values(data: bytes) -> tuple[bytes, int]:
    """DXF чередует строку кода группы и строку значения. Если на месте кода стоит не число,
    это хвост предыдущего значения с сырым переводом строки: он приклеивается обратно."""
    lines = data.split(b"\n")
    last = len(lines) - 1
    out: list[bytes] = []
    joined = 0
    expect_code = True
    for position, line in enumerate(lines):
        if not expect_code:
            out.append(line)
            expect_code = True
        elif position == last and not line.strip():
            # Пустой хвост после последнего перевода строки (CRLF в конце файла) не значение.
            out.append(line)
        elif _GROUP_CODE.match(line) or not out:
            out.append(line)
            expect_code = False
        else:
            tail = line.strip()
            out[-1] = out[-1].rstrip(b"\r") + (b" " + tail if tail else b"")
            joined += 1
    return b"\n".join(out), joined
