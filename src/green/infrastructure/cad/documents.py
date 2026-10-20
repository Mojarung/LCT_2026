"""Загрузка DXF с откатом в режим восстановления для повреждённых файлов."""

from __future__ import annotations

import io
import itertools
import re
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING

import ezdxf
from ezdxf import recover
from ezdxf.audit import AuditError, ErrorEntry
from ezdxf.entities import DXFTagStorage

from green.application.errors import InputError
from green.infrastructure.cad import acis_index
from green.infrastructure.cad.structure import require_complete_container

if TYPE_CHECKING:
    from ezdxf.audit import Auditor
    from ezdxf.document import Drawing
    from ezdxf.entities import DXFEntity

acis_index.install()  # поиск ACIS по индексу, а не перебором (acis_index.py)

RESULT_PREFIX = "GREEN_"
APPID = "LCT_GREEN"
_BAD_UNICODE_ESCAPE = re.compile(rb"\\U\+(?![0-9A-Fa-f]{4})")
_GROUP_CODE = re.compile(rb"^\s*-?\d{1,4}\s*$")
_LONE_CR = re.compile(rb"\r(?!\n)")
_REMOVED_ACAD_TABLE = re.compile(r"ACAD_TABLE\(#([0-9A-Fa-f]+)\)")
_SPATIAL_REPAIRS = frozenset(
    {
        AuditError.REMOVED_INVALID_GRAPHIC_ENTITY,
        AuditError.REMOVED_ENTITY_WITH_INVALID_OWNER_HANDLE,
        AuditError.UNDEFINED_BLOCK,
        AuditError.UNDEFINED_BLOCK_NAME,
        AuditError.INVALID_BLOCK_REFERENCE_CYCLE,
        AuditError.INVALID_INTEGER_VALUE,
        AuditError.INVALID_FLOATING_POINT_VALUE,
        AuditError.INVALID_LAYER_NAME,
        AuditError.INVALID_EXTRUSION_VECTOR,
        AuditError.INVALID_MAJOR_AXIS,
        AuditError.INVALID_VERTEX_COUNT,
        AuditError.INVALID_MLINE_VERTEX,
        AuditError.INVALID_MLINESTYLE_ELEMENT_COUNT,
        AuditError.INVALID_SPLINE_DEFINITION,
        AuditError.INVALID_SPLINE_CONTROL_POINT_COUNT,
        AuditError.INVALID_SPLINE_FIT_POINT_COUNT,
        AuditError.INVALID_SPLINE_KNOT_VALUE_COUNT,
        AuditError.INVALID_SPLINE_WEIGHT_COUNT,
        AuditError.INVALID_CREASE_VALUE_COUNT,
        AuditError.INVALID_ELLIPSE_RATIO,
        AuditError.INVALID_HATCH_BOUNDARY_PATH,
        AuditError.TAG_ATTRIBUTE_MISSING,
        AuditError.INVALID_MESH_DATA,
    }
)

type Loaded = tuple[Drawing, list[str]]

_CYCLE_BLOCK = re.compile(r'block "([^"]+)"')


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

    def put(self, path: Path, loaded: Loaded) -> None:
        """Документ, уже прочитанный с этого файла (склейка перечитывает записанный комплект для
        проверки): чтение и запись берут его отсюда, а не разбирают файл ещё раз."""
        key = _key(path)
        with self._lock:
            self._items[key] = loaded
            self._loaded_handles[id(loaded[0])] = frozenset(loaded[0].entitydb.keys())
            while len(self._items) > self._capacity:
                _, (evicted, _) = self._items.popitem(last=False)
                self._loaded_handles.pop(id(evicted), None)

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


# Штриховок, многострочного текста и прозрачности в DXF R12 нет: результат R12-чертежа пишется в
# R2000. ezdxf переводит загруженный документ без потерь, и отпечатки исходных сущностей снимаются
# уже в форме R2000 - и при записи, и при сверке (`green verify`), иначе сравнивались бы разные
# записи одной сущности.
RESULT_MIN_VERSION = "AC1015"
R12_NOTE = (
    "Чертёж в формате DXF R12: результат записан в DXF R2000 (штриховки газонов и зон, "
    "многострочный текст в R12 не существуют). Исходные сущности перенесены без изменений, "
    "сверка целостности идёт в форме R2000."
)


def upgrade_for_result(doc: Drawing) -> bool:
    """Переводит документ старше R2000 в R2000 до записи и сверки; True - если переводил."""
    if doc.dxfversion >= RESULT_MIN_VERSION:
        return False
    doc.dxfversion = RESULT_MIN_VERSION
    return True


def entity_layer(entity: DXFEntity) -> str:
    """Слой сущности; у неизвестной ezdxf сущности (ARCALIGNEDTEXT и т.п.) атрибута нет - «0»."""
    return str(entity.dxf.get("layer", "0")) if entity.dxf.is_supported("layer") else "0"


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
        require_complete_container(path)
        doc = ezdxf.readfile(path)
        if _misdeclared_cyrillic(doc):
            doc = _as_cp1251(ezdxf.readfile(path, encoding=CP1251))
            return _strict(path, doc, [_cp_note(path)])
        return _strict(path, doc, [])
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
    _require_safe_audit(path, auditor)
    notes.extend(_cycle_notes(path, auditor))
    fixes = len(auditor.fixes) + len(auditor.errors)
    notes.append(f"{path.name} прочитан в режиме восстановления, исправлено записей: {fixes}")
    return doc, notes


def _strict(path: Path, doc: Drawing, notes: list[str]) -> tuple[Drawing, list[str]]:
    # Строгий загрузчик не проверяет ссылки. DXF от конвертеров (LibreDWG) содержат висячие
    # handle, например у материалов ByLayer, и без аудита ezdxf падает при сохранении.
    # LibreDWG can emit a bare ACAD_TABLE tag with no content or owner.
    # A table with block references, cells or other payload must still block:
    # absence of a proxy graphic alone does not prove that it is empty.
    empty_tables = {
        entity.dxf.handle.upper()
        for entity in doc.entitydb.values()
        if entity.dxftype() == "ACAD_TABLE"
        and isinstance(entity, DXFTagStorage)
        and entity.dxf.get("owner") is None
        and not entity.proxy_graphic
        and all(tag.code in {0, 5} for tag in entity.xtags)
    }
    auditor = doc.audit()
    _require_safe_audit(path, auditor, empty_tables=empty_tables)
    notes.extend(_cycle_notes(path, auditor))
    fixes = len(auditor.fixes)
    if fixes or auditor.errors:
        notes.append(f"{path.name}: аудит исправил записей: {fixes}, ошибок: {len(auditor.errors)}")
    removed_tables = empty_tables - set(doc.entitydb)
    if removed_tables:
        notes.append(
            f"{path.name}: удалены пустые записи ACAD_TABLE без содержимого: "
            f"{len(removed_tables)}. "
            "Таблицы с данными или геометрией этим исключением не покрываются."
        )
    return doc, notes


def _require_safe_audit(
    path: Path, auditor: Auditor, *, empty_tables: set[str] | None = None
) -> None:
    # ezdxf can delete an INSERT with a missing definition before the walker ever
    # sees it, or repair a hatch/curve into different geometry. A warning is not
    # enough to certify clearance against that altered scene.
    def unsafe(fix: ErrorEntry) -> bool:
        if fix.code not in _SPATIAL_REPAIRS:
            return False
        if fix.code not in {
            AuditError.REMOVED_INVALID_GRAPHIC_ENTITY,
            AuditError.REMOVED_ENTITY_WITH_INVALID_OWNER_HANDLE,
        }:
            return True
        match = _REMOVED_ACAD_TABLE.search(fix.message)
        return match is None or match.group(1).upper() not in (empty_tables or set())

    # Блок, вставляющий сам себя: геометрия не потеряна, обход прерывает цикл на повторе имени
    # блока (reader, insert:cycle). Остальные неисправленные ошибки останавливают чтение.
    errors = [e for e in auditor.errors if e.code != AuditError.INVALID_BLOCK_REFERENCE_CYCLE]
    problems = [*errors, *(f for f in auditor.fixes if unsafe(f))]
    if problems:
        detail = "; ".join(f"{entry.code}: {entry.message}" for entry in problems[:10])
        raise InputError(
            f"{path.name}: аудит DXF обнаружил потерю/изменение геометрии или "
            f"неисправленные ошибки: {detail}. Нужен исправленный исходник."
        )


CP1251 = "cp1251"
_LATIN_LETTERS = re.compile("[À-ÿ]")
_CYRILLIC = re.compile("[Ѐ-ӿ]")
_ASCII_LETTERS = re.compile("[A-Za-z]")
_CODEPAGE_SAMPLE = 5_000  # объектов модели для проверки кодировки
_MOJIBAKE_MIN = 20  # букв Latin-1 - меньше не повод перечитывать
_FIXED_SHARE = 0.8  # после перекодировки кириллицей становятся почти все такие буквы


def _misdeclared_cyrillic(doc: Drawing) -> bool:
    """Кириллица в cp1251 под заголовком другой кодовой страницы (ANSI_1252 у экспорта из
    западных программ): имена слоёв и подписи читаются как «Ãðàíèöà». DXF 2007+ - UTF-8."""
    if doc.dxfversion >= "AC1021" or doc.encoding == CP1251:
        return False
    sample = [layer.dxf.name for layer in doc.layers]
    for entity in itertools.islice(doc.modelspace(), _CODEPAGE_SAMPLE):
        sample.append(entity.dxf.get("layer", ""))
        if entity.dxftype() in {"TEXT", "MTEXT"}:
            sample.append(str(entity.dxf.get("text", "")))
    text = "".join(sample)
    latin = len(_LATIN_LETTERS.findall(text))
    # Французское «Façade» тоже даёт буквы Latin-1, но среди обычных латинских они редки; у
    # кириллицы, прочитанной как cp1252, обычных латинских букв почти нет (ревью 20.10.2026).
    ascii_letters = len(_ASCII_LETTERS.findall(text))
    if latin < _MOJIBAKE_MIN or latin < ascii_letters or len(_CYRILLIC.findall(text)) >= latin:
        return False
    try:
        fixed = text.encode(doc.encoding, errors="ignore").decode(CP1251, errors="ignore")
    except LookupError:
        return False
    return len(_CYRILLIC.findall(fixed)) >= _FIXED_SHARE * latin


def _as_cp1251(doc: Drawing) -> Drawing:
    doc.encoding = CP1251  # и результат пишется той же кодовой страницей
    return doc


def _cp_note(path: Path) -> str:
    return (
        f"{path.name}: кодовая страница в заголовке не совпадает с текстом - имена слоёв и "
        "подписи в cp1251 (кириллица); чертёж прочитан как cp1251, результат записан в ней же."
    )


def _cycle_notes(path: Path, auditor: Auditor) -> list[str]:
    cycles = [e for e in auditor.errors if e.code == AuditError.INVALID_BLOCK_REFERENCE_CYCLE]
    if not cycles:
        return []
    found = {m.group(1) for e in cycles if (m := _CYCLE_BLOCK.search(e.message))}
    names = sorted(n for n in found if not n.startswith("*")) or sorted(found)
    return [
        (
            f"{path.name}: блоки вставляют сами себя (цикл ссылок): {', '.join(names[:10])}. "
            "Повторная вставка того же блока внутри себя не разбирается, объекты одного "
            "прохода учтены; исходник не меняется."
        )
    ]


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
