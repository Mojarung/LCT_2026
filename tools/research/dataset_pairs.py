"""Сколько улиц пилота дают пару «как было -> как стало» для сравнения с проектировщиком.

Считает по содержимому внутреннего архива, ничего не распаковывая. Решение принимается по
папке верхнего уровня внутри улицы, а не по имени файла: «Исходные данные» (в любом
написании) - вход, «Проектное решение» - ответ проектировщика, «Архив» и «Портфолио»
не учитываются.

Порядок проверок важен. Внутри «Исходных данных» лежат папки «Генплан …» и «… дендроплан»,
поэтому классификатор, который ищет слово «генплан» раньше слова «исходные», относит вход к
ответу: так первый проход дал 11 улиц вместо 14.

Запуск: uv run python tools/research/dataset_pairs.py [путь/к/архиву.zip]
"""

from __future__ import annotations

import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

DEFAULT = Path("dataset/Датасет/Пилотный проект 20 улиц.zip")
STREET = re.compile(r"^(\d{1,2})[.\s_)]+(.+)$")
BEFORE = re.compile(r"исходн|исходый|изыскан", re.IGNORECASE)
AFTER = re.compile(r"проектн", re.IGNORECASE)
ARCHIVED = re.compile(r"архив|портфолио", re.IGNORECASE)
PLANTING = re.compile(r"посадочн|озелен", re.IGNORECASE)
# Дендроплан значит разное в зависимости от папки: в исходных данных это существующие
# насаждения (вход), в проектном решении - проектные. «Благоустройство» может содержать
# озеленение, а может и нет, поэтому оба идут отдельными уровнями, а не в основной счёт.
WEAKER = re.compile(r"дендро|благоустр", re.IGNORECASE)
DRAWING = (".dwg", ".dxf")
MAX_STREET = 20


def decode(name: str) -> str:
    """Имена в архиве в cp866, zipfile отдаёт их разобранными как cp437."""
    try:
        return name.encode("cp437").decode("cp866")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def street_of(parts: list[str]) -> tuple[int, str] | None:
    for index, part in enumerate(parts[:-1]):
        match = STREET.match(part)
        if match and int(match.group(1)) <= MAX_STREET and len(parts) > index + 2:
            return index, match.group(2).strip()
    return None


def collect(archive: Path) -> dict[int, dict[str, object]]:
    rows: defaultdict[int, dict[str, object]] = defaultdict(
        lambda: {"name": "", "base": 0, "plan_dwg": set(), "weaker": set(), "plan_pdf": set()}
    )
    with zipfile.ZipFile(archive) as book:
        for info in book.infolist():
            if info.is_dir():
                continue
            parts = decode(info.filename).replace("\\", "/").split("/")
            found = street_of(parts)
            if found is None:
                continue
            index, name = found
            number = int(parts[index].split(".")[0].strip(" _)"))
            row = rows[number]
            row["name"] = name[:32]
            top, leaf = parts[index + 1], parts[-1]
            if ARCHIVED.search(top):
                continue
            drawing = leaf.lower().endswith(DRAWING)
            if BEFORE.search(top) and drawing:
                row["base"] = int(row["base"]) + 1
            elif AFTER.search(top):
                named = PLANTING.search(leaf) or WEAKER.search(leaf)
                key = (
                    None
                    if not named
                    else ("plan_dwg" if PLANTING.search(leaf) else "weaker")
                    if drawing
                    else "plan_pdf"
                )
                if key is not None:
                    bucket = row[key]
                    assert isinstance(bucket, set)  # noqa: S101
                    bucket.add(leaf)
    return dict(rows)


def main() -> int:
    archive = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not archive.exists():
        sys.stdout.write(f"нет архива {archive}\n")
        return 1
    rows = collect(archive)
    header = f"{'№':>3} {'улица':<32} {'подосн':>7} {'посадочн':>9} {'дендро/благ':>12} {'pdf':>4}"
    sys.stdout.write(header + "\n")
    strict: list[int] = []
    weaker: list[int] = []
    pdf_only: list[int] = []
    for number in range(1, MAX_STREET + 1):
        row = rows.get(number)
        if row is None:
            sys.stdout.write(f"{number:>3} {'(не найдена)':<32}\n")
            continue
        plan, weak, pdf = row["plan_dwg"], row["weaker"], row["plan_pdf"]
        assert isinstance(plan, set)  # noqa: S101
        assert isinstance(weak, set)  # noqa: S101
        assert isinstance(pdf, set)  # noqa: S101
        sys.stdout.write(
            f"{number:>3} {str(row['name']):<32} {row['base']:>7} {len(plan):>9} "
            f"{len(weak):>12} {len(pdf):>4}\n"
        )
        if not row["base"]:
            continue
        if plan:
            strict.append(number)
        elif weak:
            weaker.append(number)
        elif pdf:
            pdf_only.append(number)
    sys.stdout.write(f"\nподоснова + посадочный план или озеленение: {len(strict)} -> {strict}\n")
    sys.stdout.write(f"вместо посадочного дендроплан или благоустройство: {weaker}\n")
    sys.stdout.write(f"план только в PDF: {pdf_only}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
