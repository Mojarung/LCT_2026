"""Собрать каталог улиц пилотного проекта: DWG из архива -> DXF на диске.

Архив «Пилотный проект 20 улиц.zip» (11,4 ГБ) распакован быть не может и не должен:
из него по каждой улице достаётся только комплект подосновы, конвертируется в DXF и
кладётся в `dataset/streets/`. Рядом пишется `catalog.json` - его читает сервис, чтобы
показать список улиц. Датасета на стенде жюри нет, поэтому отсутствие каталога - это
нормальное состояние, а не ошибка.

    uv run python tools/prepare_streets.py --list          посмотреть, что будет выбрано
    uv run python tools/prepare_streets.py                 собрать всё
    uv run python tools/prepare_streets.py --only 16 --only 8

Выбор файлов - по именам, потому что ничего другого в архиве нет: у двадцати улиц
двадцать разных способов назвать геоподоснову. Поэтому решение каждой улицы попадает в
каталог вместе с оценкой, а `--list` показывает его до того, как начнётся конвертация.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

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

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}


def slugify(name: str) -> str:
    """Имя папки улицы -> короткий латинский идентификатор для путей и адресов."""
    text = "".join(TRANSLIT.get(char, char) for char in name.lower())
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return re.sub(r"-{2,}", "-", text)[:60]


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


def build_converter():
    """Тот же конвертер, что у сервиса: второй реализации быть не должно.

    На Windows LibreDWG лежит распакованным в `tools/libredwg` и в PATH не попадает,
    поэтому путь ищется и там, а не только по имени.
    """
    binary = os.environ.get("GREEN_LIBREDWG_BINARY", "")
    if not binary:
        local = ROOT / "tools" / "libredwg" / ("dwg2dxf.exe" if os.name == "nt" else "dwg2dxf")
        if local.exists():
            binary = str(local)
    options = [LibreDwgConverter(binary=binary)] if binary else [LibreDwgConverter()]
    options.append(OdaFileConverter())
    for converter in options:
        if converter.available():
            return converter
    message = "не найден ни dwg2dxf (LibreDWG), ни ODAFileConverter"
    raise SystemExit(message)


def convert_one(job: tuple[str, str, str]) -> tuple[str, str, str]:
    """Достать один DWG из архива и положить рядом его DXF. Работает в своём процессе."""
    member, slug, role = job
    converter = build_converter()
    target_dir = OUT / slug
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(member).stem
    target = target_dir / f"{slugify(stem) or 'source'}.dxf"
    if target.exists():
        return slug, target.name, "уже был"

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
            return slug, Path(member).name, f"ошибка: {error}"
        shutil.move(str(produced), target)
    return slug, target.name, role


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="показать выбор и выйти")
    parser.add_argument("--only", action="append", type=int, help="номера улиц")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

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
            print(f"    [{pick.role:<12}] {pick.size / 1024 / 1024:6.1f} МБ  {Path(pick.path).name}")
    if args.list:
        return

    jobs = [
        (pick.path, street.slug, pick.role)
        for street in streets
        for pick in street.picks
    ]
    print(f"\nконвертирую {len(jobs)} файлов в {OUT}")
    done: dict[str, list[str]] = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for slug, name, role in pool.map(convert_one, jobs):
            print(f"  {slug:<32} {name:<44} {role}")
            if not role.startswith("ошибка"):
                done.setdefault(slug, []).append(name)

    catalog = []
    for street in streets:
        files = done.get(street.slug, [])
        if not files:
            continue
        main_name = f"{slugify(Path(street.picks[0].path).stem) or 'source'}.dxf"
        catalog.append(
            {
                "slug": street.slug,
                "number": street.number,
                "title": re.sub(r"^\d+\.\s*", "", street.title).strip(),
                "main": main_name,
                "files": sorted(files),
            }
        )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nкаталог: {OUT / 'catalog.json'}, улиц {len(catalog)}")


if __name__ == "__main__":
    main()
