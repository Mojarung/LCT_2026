"""Собрать каталог улиц пилотного проекта: DWG из архива -> DXF на диске.

Архив «Пилотный проект 20 улиц.zip» (11,4 ГБ) распакован быть не может и не должен:
из него по каждой улице достаётся только комплект подосновы, конвертируется в DXF и
кладётся в `dataset/streets/`. Рядом пишется `catalog.json` - его читает сервис, чтобы
показать список улиц. Датасета на стенде жюри нет, поэтому отсутствие каталога - это
нормальное состояние, а не ошибка.

    uv run python tools/prepare_streets.py --list          посмотреть, что будет выбрано
    uv run python tools/prepare_streets.py                 собрать всё
    uv run python tools/prepare_streets.py --only 16 --only 8
    uv run python tools/prepare_streets.py --converter oda --out dataset/streets_dxf_oda

Конвертер по умолчанию, как у сервиса, - ODA File Converter, если он установлен: LibreDWG
теряет данные ACIS у каждой области REGION (сверка 25.09.2026, CLAUDE.md).

Выбор файлов - по именам, потому что ничего другого в архиве нет: у двадцати улиц
двадцать разных способов назвать геоподоснову. Поэтому решение каждой улицы попадает в
каталог вместе с оценкой, а `--list` показывает его до того, как начнётся конвертация.
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import shutil
import sys
import tempfile
import unicodedata
import zipfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from green.application.semantic_names import slug_key  # noqa: E402
from green.infrastructure.convert.libredwg import LibreDwgConverter  # noqa: E402
from green.infrastructure.convert.oda import OdaFileConverter  # noqa: E402

ZIP = ROOT / "dataset" / "Датасет" / "Пилотный проект 20 улиц.zip"
OUT = ROOT / "dataset" / "streets_dxf"
TOP = "Пилотный проект 20 улиц"

#: Папка входных данных называется у всех по-разному, вплоть до опечаток в падеже.
SOURCE_DIR = re.compile(r"исходн|генеральный план редформат", re.I)

#: Признаки геоподосновы в имени файла. Ничего надёжнее имени в архиве нет.
PREFER = (
    (re.compile(r"гео(?![а-я])|топограф", re.I), 6),
    (re.compile(r"(?<![а-я])гп(?![а-я])|генплан|генеральн\w+ план", re.I), 4),
    (re.compile(r"апот", re.I), 1),
)
#: Проектное решение, дендроплан и организация движения - это ответ или чужой слой, не вход.
REJECT = re.compile(
    r"дендро|посадочн|озелен|проектн\w+ решени|благоустройств|"
    r"(?<![а-я])одд(?![а-я])|(?<![а-я])иот\d*(?![а-я])|портфолио|архив|удал\w+ деревь",
    re.I,
)
#: Выгрузки Мосгеотреста по видам сетей: тепло, водопровод, кабели, прочее.
UTILITY = re.compile(r"(?<![а-я])(tp|up|kl|pp)(?![a-z])|коммуникац|сети", re.I)
#: Границы работ отдельным файлом (`output[1-3]_brd.dwg`, «01_Границы работ.dwg»). Без них
#: алгоритму нечем ограничить участок, и он засаживает всю подоснову вместе с чужими дворами.
BOUNDARY = re.compile(r"(?<![a-z])brd(?![a-z])|границ\w*\s*работ", re.I)
#: Потолок на комплект: планшетов на улицу бывает до трёх, видов сетей четыре, плюс границы.
MAX_FILES = 16
# Единицы улицы, когда заголовок основы с геометрией спорит (решение 25.09.2026: заголовку
# верим, пока геометрия ему явно не противоречит; противоречие снимается только явно).
UNIT_OVERRIDES = {
    "2-peschanyy-pereulok": (
        "m",
        "заголовок генплана - миллиметры от шаблона, а геометрия метровая: топооснова 1:500 "
        "вставлена в масштабе 1, координатные кресты через 50 единиц, текст высотой около 1",
    ),
}


def slugify(name: str) -> str:
    """Имя папки улицы -> короткий латинский идентификатор для путей и адресов.

    Тот же ключ, по которому сборка комплекта находит файл внешней ссылки: второй
    транслитерации быть не должно.
    """
    return slug_key(name)[:60]


def entry_name(info: zipfile.ZipInfo) -> str:
    """Имя записи с учётом того, что половина архива записана в cp866."""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp866")
    except UnicodeError:
        return info.filename


@dataclass
class Candidate:
    path: str
    size: int
    score: int
    role: str


@dataclass
class Street:
    number: int
    title: str
    slug: str
    picks: list[Candidate] = field(default_factory=list)
    note: str = ""


def score_of(name: str) -> int:
    if REJECT.search(name):
        return -10
    score = 0
    for pattern, weight in PREFER:
        if pattern.search(name):
            score += weight
    return score


def sheet_of(name: str) -> str:
    """Планшет Мосгеотреста, к которому относится выгрузка.

    Имя выглядит как `output_1-3__3_ДЖКХ-25_02794tp`: последние буквы - вид сети, остальное -
    номер планшета. Убираем вид, и все выгрузки одного планшета сходятся в один ключ.
    """
    return UTILITY.sub("", Path(name).stem.lower()).strip("_- ")


def pick_files(files: list[tuple[str, int]]) -> tuple[list[Candidate], str]:
    """Выбрать комплект подосновы: основной чертёж плюс выгрузки сетей.

    Сети лежат отдельными файлами (`...tp.dwg`, `...up.dwg`), и без них на плане нет
    половины ограничений. Берём по одному файлу на пару «планшет + вид»: в архиве каждая
    выгрузка лежит в двух-трёх копиях, но **планшетов на улицу бывает несколько**, и они
    покрывают разные её куски. Дедупликация по одному лишь виду давала комплект, где
    топография взята с одного планшета, а сети с другого: половина улицы оставалась без
    сетей, и алгоритм засаживал её сплошняком (Песчаный переулок, `docs/notes/26`).
    """
    scored = [Candidate(path=p, size=s, score=score_of(Path(p).name), role="") for p, s in files]
    usable = [c for c in scored if c.score > -10]
    if not usable:
        return [], "в исходных данных только проектные решения"

    # Файл в сотню килобайт - не подоснова, а обёртка со ссылками на внешние чертежи:
    # геометрия лежит в них, а у нас xref не разворачивается. Имя у такой обёртки при этом
    # самое подходящее («Собранная ГЕО»), поэтому отсеивает её только размер.
    weighty = [c for c in usable if c.size >= 1_000_000]
    main = max(weighty or usable, key=lambda c: (c.score, c.size))
    main.role = "подоснова"
    picks = [main]

    seen: set[tuple[str, str]] = set()
    for cand in sorted(usable, key=lambda c: -c.size):
        if cand is main or cand.size == 0:
            continue
        name = Path(cand.path).name
        # Границы работ в архиве лежат и пустыми файлами на 0 байт, и рабочими на полсотни
        # килобайт под тем же именем: пустые отсеяны размером выше.
        if BOUNDARY.search(name) and not UTILITY.search(name):
            key = (sheet_of(name), "brd")
            if key in seen:
                continue
            seen.add(key)
            cand.role = "границы работ"
            picks.append(cand)
            if len(picks) >= MAX_FILES:
                break
            continue
        match = UTILITY.search(name)
        if not match:
            continue
        kind = (match.group(1) or match.group(0)).lower()
        key = (sheet_of(name), kind)
        if key in seen:
            continue
        seen.add(key)
        cand.role = f"сети {kind}"
        picks.append(cand)
        if len(picks) >= MAX_FILES:
            break
    return picks, ""


def survey() -> list[Street]:
    """Пройти оглавление архива и решить по каждой улице, что брать."""
    by_street: dict[str, list[tuple[str, int]]] = {}
    with zipfile.ZipFile(ZIP) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = entry_name(info)
            parts = name.split("/")
            if len(parts) < 4 or parts[0] != TOP or not name.lower().endswith(".dwg"):
                continue
            if not SOURCE_DIR.search(parts[2]):
                continue
            by_street.setdefault(parts[1], []).append((name, info.file_size))

    streets: list[Street] = []
    for title, files in by_street.items():
        number = int(match.group(1)) if (match := re.match(r"(\d+)", title)) else 0
        picks, note = pick_files(files)
        streets.append(
            Street(number=number, title=title, slug=slugify(title), picks=picks, note=note)
        )
    return sorted(streets, key=lambda s: s.number)


def oda_binary() -> str:
    """ODA File Converter: GREEN_ODA_BINARY, иначе стандартная установка Windows, иначе PATH."""
    binary = os.environ.get("GREEN_ODA_BINARY", "")
    if binary:
        return binary
    installed = sorted(Path("C:/Program Files/ODA").glob("ODAFileConverter*/ODAFileConverter.exe"))
    return str(installed[-1]) if installed else "ODAFileConverter"


def build_converter(kind: str = "auto"):
    """Тот же конвертер, что у сервиса: второй реализации быть не должно.

    На Windows LibreDWG лежит распакованным в `tools/libredwg` и в PATH не попадает,
    поэтому путь ищется и там, а не только по имени.
    """
    binary = os.environ.get("GREEN_LIBREDWG_BINARY", "")
    if not binary:
        local = ROOT / "tools" / "libredwg" / ("dwg2dxf.exe" if os.name == "nt" else "dwg2dxf")
        if local.exists():
            binary = str(local)
    libredwg = LibreDwgConverter(binary=binary) if binary else LibreDwgConverter()
    oda = OdaFileConverter(binary=oda_binary())
    options = {"auto": [oda, libredwg], "libredwg": [libredwg], "oda": [oda]}[kind]
    for converter in options:
        if converter.available():
            return converter
    message = f"конвертер {kind} не найден: ни ODAFileConverter, ни dwg2dxf (LibreDWG)"
    raise SystemExit(message)


def convert_one(job: tuple[str, str, str, str, str, str]) -> tuple[str, str, str]:
    """Достать один DWG из архива и положить рядом его DXF. Работает в своём процессе."""
    member, slug, role, kind, out, name = job
    converter = build_converter(kind)
    target_dir = Path(out) / slug
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name
    if target.exists():
        return member, name, "уже был"

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        source = work / Path(member).name
        with zipfile.ZipFile(ZIP) as archive:
            info = next(i for i in archive.infolist() if entry_name(i) == member)
            with archive.open(info) as src, source.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1 << 20)
        try:
            produced = converter.to_dxf(source, work)
        except Exception as error:  # noqa: BLE001 - причина уходит в отчёт, улица не падает
            return member, name, f"ошибка: {error}"
        shutil.move(str(produced), target)
    return member, name, role


# ---------------------------------------------------------------- внешние ссылки

DRAWINGS = (".dwg", ".dxf")
XREF_FLAG = 4
OVERLAY_FLAG = 8


def xrefs(path: Path) -> list[tuple[str, str, bool]]:
    """Внешние ссылки DXF: (имя блока, путь, overlay).

    Секция BLOCKS читается построчно, без ezdxf: подоснова весит сотни мегабайт, а нужны
    только заголовки блоков. DXF 2007+ в UTF-8, более старые - в кодировке чертежа (cp1251).
    """
    found: list[tuple[str, str, bool]] = []
    section = rtype = None
    record: dict[str, str] = {}
    with path.open("rb") as handle:
        lines = iter(handle)
        for code_line in lines:
            raw = next(lines, b"").rstrip(b"\r\n")
            try:
                value = raw.decode("utf-8")
            except UnicodeDecodeError:
                value = raw.decode("cp1251", errors="replace")
            code = code_line.strip()
            if code == b"0":
                flags = int(record.get("70", "0") or 0)
                # AutoCAD ставит overlay оба флага, ezdxf - только флаг overlay.
                if rtype == "BLOCK" and flags & (XREF_FLAG | OVERLAY_FLAG):
                    found.append(
                        (record.get("2", ""), record.get("1", ""), bool(flags & OVERLAY_FLAG))
                    )
                rtype, record = value, {}
                if value == "ENDSEC" and section == "BLOCKS":
                    break
                continue
            if rtype == "SECTION" and code == b"2":
                section = value
            elif section == "BLOCKS" and code in (b"1", b"2", b"70"):
                record.setdefault(code.decode(), value)
    return found


def _member_key(path: str) -> str:
    stem, suffix = posixpath.splitext(unicodedata.normalize("NFC", path).casefold())
    return stem + ".dwg" if suffix in DRAWINGS else stem + suffix


def _shared_folders(first: str, second: str) -> int:
    count = 0
    for a, b in zip(first.split("/")[:-1], second.split("/")[:-1], strict=False):
        if a != b:
            break
        count += 1
    return count


def resolve_reference(
    host: str, reference: str, members: dict[str, zipfile.ZipInfo]
) -> tuple[str | None, str]:
    """Файл внешней ссылки в архиве улицы: (путь в архиве или None, как найден).

    Как AutoCAD: сначала путь от папки основного чертежа, затем имя файла среди чертежей
    улицы (ключ имени, как у каталога). Из копий в разных папках берётся ближайшая к
    основному чертежу; одинаковые по содержимому копии - одна и та же ссылка. Остальное
    не угадывается: «неоднозначно» или «нет в архиве».
    """
    path = reference.replace("\\", "/").strip()
    keys = {_member_key(member): member for member in members}
    if path and not re.match(r"^([A-Za-z]:|/)", path):
        candidate = posixpath.normpath(posixpath.join(posixpath.dirname(host), path))
        if (found := keys.get(_member_key(candidate))) is not None:
            return found, "по пути"
    stem = slug_key(PurePosixPath(path).stem)
    same = [member for member in members if slug_key(PurePosixPath(member).stem) == stem]
    if len(same) > 1:
        nearest = max(_shared_folders(member, host) for member in same)
        same = [member for member in same if _shared_folders(member, host) == nearest]
    if len({(members[m].file_size, members[m].CRC) for m in same}) == 1:
        return same[0], "по имени"
    return None, "неоднозначно" if same else "нет в архиве"


def _sheet_key(name: str) -> tuple[str, str] | None:
    """Пара «планшет + вид» выгрузки сетей или границ работ, как в pick_files."""
    base = Path(name).name
    if BOUNDARY.search(base) and not UTILITY.search(base):
        return sheet_of(base), "brd"
    if match := UTILITY.search(base):
        return sheet_of(base), (match.group(1) or match.group(0)).lower()
    return None


@dataclass
class Kit:
    """Комплект улицы: основной чертёж, всё, на что он ссылается, и выгрузки из отбора."""

    street: Street
    members: dict[str, zipfile.ZipInfo]
    files: dict[str, str] = field(default_factory=dict)  # путь в архиве -> имя в каталоге
    roles: dict[str, str] = field(default_factory=dict)
    missing: list[dict[str, object]] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    queued: list[str] = field(default_factory=list)

    def add(self, member: str, role: str) -> None:
        info = self.members[member]
        if any(
            (self.members[known].file_size, self.members[known].CRC) == (info.file_size, info.CRC)
            for known in self.files
        ):
            return  # тот же файл уже в комплекте, пусть и из другой папки
        name = f"{slugify(Path(member).stem) or 'source'}.dxf"
        taken = set(self.files.values())
        suffix = 2
        while name in taken:
            name = f"{slugify(Path(member).stem) or 'source'}-{suffix}.dxf"
            suffix += 1
        self.files[member] = name
        self.roles[member] = role
        self.queued.append(member)

    def add_uncovered_picks(self) -> None:
        """Выгрузки из отбора, чьей пары «планшет + вид» ещё нет среди ссылок комплекта."""
        covered = {_sheet_key(member) for member in self.files} - {None}
        for pick in self.street.picks[1:]:
            if _sheet_key(pick.path) not in covered and pick.path in self.members:
                self.add(pick.path, pick.role)

    def follow(self, host: str, dxf: Path) -> None:
        for block, reference, overlay in xrefs(dxf):
            member, how = resolve_reference(host, reference, self.members)
            if member is not None:
                if member not in self.files:
                    self.add(member, "ссылка")
                continue
            self.missing.append(
                {
                    "host": self.files[host],
                    "block": block,
                    "reference": reference,
                    "overlay": overlay,
                    "why": how,
                }
            )


def drawing_members(archive: zipfile.ZipFile) -> dict[str, dict[str, zipfile.ZipInfo]]:
    """Все DWG/DXF каждой улицы по имени её папки, без служебных заголовков tar."""
    found: dict[str, dict[str, zipfile.ZipInfo]] = {}
    for info in archive.infolist():
        name = entry_name(info)
        parts = name.split("/")
        if info.is_dir() or len(parts) < 3 or parts[0] != TOP or "PaxHeader" in parts:
            continue
        if name.lower().endswith(DRAWINGS) and info.file_size > 0:
            found.setdefault(parts[1], {})[name] = info
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="показать выбор и выйти")
    parser.add_argument("--only", action="append", type=int, help="номера улиц")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--converter", choices=("auto", "libredwg", "oda"), default="auto")
    parser.add_argument("--out", type=Path, default=OUT, help="папка каталога улиц")
    args = parser.parse_args()
    out = args.out if args.out.is_absolute() else ROOT / args.out

    if not ZIP.exists():
        raise SystemExit(f"нет архива: {ZIP}")

    streets = survey()
    if args.only:
        streets = [s for s in streets if s.number in set(args.only)]

    for street in streets:
        head = f"{street.number:>2}. {street.title}"
        if not street.picks:
            print(f"{head}\n    пропуск: {street.note}")
            continue
        print(head)
        for pick in street.picks:
            print(
                f"    [{pick.role:<12}] {pick.size / 1024 / 1024:6.1f} МБ  {Path(pick.path).name}"
            )
    if args.list:
        return

    with zipfile.ZipFile(ZIP) as archive:
        members = drawing_members(archive)
    kits = [Kit(street, members.get(street.title, {})) for street in streets if street.picks]
    for kit in kits:
        kit.add(kit.street.picks[0].path, kit.street.picks[0].role)
    owner = {member: kit for kit in kits for member in kit.members}
    print(f"\nконвертирую в {out} ({build_converter(args.converter).name}), по ссылкам волнами")
    picks_added = False
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        while True:
            jobs = [
                (
                    member,
                    kit.street.slug,
                    kit.roles[member],
                    args.converter,
                    str(out),
                    kit.files[member],
                )
                for kit in kits
                for member in kit.queued
            ]
            for kit in kits:
                kit.queued = []
            if not jobs:
                if picks_added:
                    break
                # Сначала основной чертёж и его ссылки, потом выгрузки из отбора, которых
                # ссылки не покрыли: иначе одна сеть из двух копий архива попадёт дважды.
                for kit in kits:
                    kit.add_uncovered_picks()
                picks_added = True
                continue
            for member, name, status in pool.map(convert_one, jobs):
                kit = owner[member]
                print(f"  {kit.street.slug:<32} {name:<48} {status}")
                if status.startswith("ошибка"):
                    kit.failed[member] = status
                    continue
                kit.follow(member, out / kit.street.slug / name)

    catalog = []
    for kit in kits:
        done = [member for member in kit.files if member not in kit.failed]
        if kit.street.picks[0].path not in done:
            continue
        catalog.append(
            {
                "slug": kit.street.slug,
                "number": kit.street.number,
                "title": re.sub(r"^\d+\.\s*", "", kit.street.title).strip(),
                "main": kit.files[kit.street.picks[0].path],
                "files": sorted(kit.files[member] for member in done),
                # Путь в архиве от папки улицы: по нему сборка комплекта находит файл
                # внешней ссылки так же, как AutoCAD, а не по угаданному имени.
                "sources": {kit.files[m]: "/".join(m.split("/")[2:]) for m in done},
                "roles": {kit.files[m]: kit.roles[m] for m in done},
                "missing_xrefs": kit.missing,
                "failed": {kit.files[m]: kit.failed[m] for m in kit.failed},
            }
        )
        if kit.street.slug in UNIT_OVERRIDES:
            unit, reason = UNIT_OVERRIDES[kit.street.slug]
            catalog[-1] |= {"drawing_unit": unit, "drawing_unit_reason": reason}
        print(
            f"{kit.street.number:>2}. {kit.street.slug}: файлов {len(done)}, "
            f"по ссылкам {sum(1 for m in done if kit.roles[m] == 'ссылка')}, "
            f"ссылок без файла {len(kit.missing)}, ошибок конвертации {len(kit.failed)}"
        )
    out.mkdir(parents=True, exist_ok=True)
    (out / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nкаталог: {out / 'catalog.json'}, улиц {len(catalog)}")


if __name__ == "__main__":
    main()
