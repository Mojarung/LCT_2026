"""Черновик записей ассортимента из паспортов пилотных улиц.

Вход: dataset/catalog/species_from_passports.csv (выгрузка разделов «Ассортимент» и
«Пиковая декоративность» семи паспортов). Выход в stdout: сколько строк прочитано,
сколько сопоставлено с config/species.yaml, и YAML-черновик для видов, которых в
каталоге ещё нет. Черновик не записывается в каталог автоматически: латинских имён в
паспортах нет, а экологию и ограничения проставляет человек по справочнику.

Колонка «высота» в паспорте - проектная высота саженца (см), а не взрослая высота вида,
поэтому в height_m она не попадает: печатается отдельной строкой комментария.

Запуск: uv run python tools/build_species_catalog.py
"""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "dataset" / "catalog" / "species_from_passports.csv"
CATALOG_PATH = ROOT / "config" / "species.yaml"

MONTHS = (
    ("янв", 1),
    ("фев", 2),
    ("мар", 3),
    ("апр", 4),
    ("ма[йея]", 5),
    ("июн", 6),
    ("июл", 7),
    ("авг", 8),
    ("сен", 9),
    ("окт", 10),
    ("ноя", 11),
    ("дек", 12),
)
_MONTH_RE = re.compile("|".join(f"(?P<m{number}>{stem})" for stem, number in MONTHS))
_RANGE_RE = re.compile(r"с\s+(\w+)\s+по\s+(\w+)|(\w+)\s*[-–—]\s*(\w+)")
_YEAR_ROUND = re.compile(r"круглый год|весь год|круглогодичн")
_SORT = re.compile(r"[\"'«][^\"'»]*[\"'»]|\([^)]*\)")
# «с3», «С7,5-С10», «Р9», «Крупномер», «на штамбе» - тара и форма поставки, не признак вида
_TRADE = re.compile(r"\b[сррc]\d[\d,.–—-]*\b|\bкрупномер\w*\b|\bна штамбе\b|\bр\d+\b")

TRAITS = (
    ("gas_tolerance: 2", re.compile(r"газо|пыле|дым")),
    ("salt_tolerance: 2", re.compile(r"реагент|солеустойч|засолен")),
    ("light: shade", re.compile(r"тенев|теневынослив")),
    ("compaction_tolerance: 2", re.compile(r"уплотн|вытапт")),
    ("fluff: true", re.compile(r"пух|пылит")),
    ("thorny: true", re.compile(r"колюч|шип")),
)


def street_id(street: str) -> str:
    """«10. Старый Гай ул» и «10_Старый_Гай_ул» - одна улица пилота: ключ - её номер."""
    match = re.match(r"\s*(\d+)", street)
    return match.group(1) if match else normalize(street)


def normalize(name: str) -> str:
    """«Клен остролистный 'Друммонди'» -> «клен остролистныи» (без сорта, ё и й сведены)."""
    folded = _SORT.sub("", name).casefold().replace("ё", "е").replace("й", "и")
    words = re.findall(r"[а-яa-z]+", _TRADE.sub("", folded))
    return " ".join(words[:2])


def month_of(word: str) -> int | None:
    match = _MONTH_RE.match(word.casefold())
    if match is None or match.lastgroup is None:
        return None
    return int(match.lastgroup.removeprefix("m"))


def months_of(text: str) -> set[int]:
    """Месяцы пиковой декоративности из свободного текста паспорта."""
    if not text:
        return set()
    lowered = text.casefold()
    if _YEAR_ROUND.search(lowered):
        return set(range(1, 13))
    months: set[int] = set()
    for match in _RANGE_RE.finditer(lowered):
        first, second = (match.group(1), match.group(2))
        if first is None:
            first, second = match.group(3), match.group(4)
        start, end = month_of(first or ""), month_of(second or "")
        if start is None or end is None:
            continue
        months |= set(range(start, end + 1)) if start <= end else set(range(start, 13)) | set(
            range(1, end + 1)
        )
    if not months:
        months = {
            number
            for match in _MONTH_RE.finditer(lowered)
            if (number := month_of(match.group(0))) is not None
        }
    return months


def known_names() -> set[str]:
    """Русские имена из каталога в нормализованном виде - чтобы не плодить дубликаты."""
    text = CATALOG_PATH.read_text(encoding="utf-8")
    return {normalize(m) for m in re.findall(r"name_ru:\s*([^,}\n]+)", text)}


def main() -> int:
    if not CSV_PATH.exists():
        sys.stdout.write(f"нет файла {CSV_PATH}\n")
        return 1
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as stream:  # выгрузка идёт с BOM
        reader = csv.DictReader(stream)
        missing = {"street", "name", "count", "peak"} - set(reader.fieldnames or ())
        if missing:
            sys.stdout.write(f"в CSV нет колонок: {', '.join(sorted(missing))}\n")
            return 1
        rows = list(reader)

    streets: defaultdict[str, set[str]] = defaultdict(set)
    counts: defaultdict[str, int] = defaultdict(int)
    months: defaultdict[str, set[int]] = defaultdict(set)
    traits: defaultdict[str, set[str]] = defaultdict(set)
    heights: defaultdict[str, set[str]] = defaultdict(set)
    display: dict[str, str] = {}
    skipped = 0

    for row in rows:
        key = normalize(row.get("name") or "")
        if not key:
            skipped += 1
            continue
        display.setdefault(key, (row.get("name") or "").strip())
        streets[key].add(street_id(row.get("street") or ""))
        try:
            counts[key] += int(float(row.get("count") or 0))
        except ValueError:
            skipped += 1
        months[key] |= months_of(row.get("peak") or "")
        text = f"{row.get('traits') or ''} {row.get('function') or ''}"
        traits[key] |= {flag for flag, pattern in TRAITS if pattern.search(text.casefold())}
        if height := (row.get("height") or "").strip():
            heights[key].add(height)

    known = known_names()
    fresh = sorted(set(streets) - known, key=lambda k: (-len(streets[k]), -counts[k], k))
    sys.stdout.write(
        f"строк прочитано: {len(rows)}; видов после склейки: {len(streets)}; "
        f"уже в каталоге: {len(set(streets) & known)}; новых: {len(fresh)}; "
        f"строк без имени или количества: {skipped}\n\n"
    )
    sys.stdout.write("# черновик: латинское имя, семейство и экологию заполнить вручную\n")
    for key in fresh:
        sys.stdout.write(
            f"  # {display[key]}: улиц {len(streets[key])}, штук {counts[key]}, "
            f"посадочная высота (см) {sorted(heights[key]) or '-'}\n"
            f"  - {{code: TODO, name_ru: {display[key]}, name_lat: TODO, genus: TODO,\n"
            f"     family: TODO, life_form: TODO, height_m: TODO, crown_diameter_m: TODO,\n"
            f"     crown_mature_m: TODO, hardiness_zone: TODO, salt_tolerance: TODO,\n"
            f"     decor_months: {sorted(months[key])}, "
            f"pilot_streets: {len(streets[key])}, pilot_count: {counts[key]},\n"
            f"     {', '.join(sorted(traits[key])) or '# признаков в тексте нет'}\n"
            f"     status: draft, sources: {{hardiness_zone: TODO, salt_tolerance: TODO}}}}\n"
        )
    sys.stdout.write("\n# уже в каталоге - перенести pilot_streets/pilot_count руками:\n")
    for key in sorted(set(streets) & known):
        sys.stdout.write(
            f"  # {display[key]}: pilot_streets: {len(streets[key])}, "
            f"pilot_count: {counts[key]}, decor_months: {sorted(months[key])}\n"
        )

    # Сводка по роду: устойчива к сортам и торговым названиям, из неё берётся pilot_streets.
    genus_streets: defaultdict[str, set[str]] = defaultdict(set)
    genus_counts: defaultdict[str, int] = defaultdict(int)
    genus_names: defaultdict[str, set[str]] = defaultdict(set)
    for key in streets:
        genus = key.split()[0]
        genus_streets[genus] |= streets[key]
        genus_counts[genus] += counts[key]
        genus_names[genus].add(key)
    sys.stdout.write("\n# род: в скольких паспортах встречается, штук, какие записи склеены\n")
    for genus in sorted(genus_streets, key=lambda g: (-len(genus_streets[genus]), g)):
        sys.stdout.write(
            f"  # {genus}: улиц {len(genus_streets[genus])}, штук {genus_counts[genus]}, "
            f"записей {len(genus_names[genus])}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
