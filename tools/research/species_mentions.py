"""Где в таблицах датасета встречаются породы: паспорта объектов, ведомости ассортимента, перечётки.

Для каждого шаблона печатает файл, раздел («Исходные данные» - существующие деревья,
«Проектное решение» - посадки проектировщика), лист и текст ячейки. Нужен, чтобы вид в
каталоге опирался на практику пилота, а не только на справочник.

    uv run python tools/research/species_mentions.py "карагана" "лох " "вяз мелколист"
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import openpyxl
import xlrd

ROOT = Path(__file__).resolve().parents[2]
STREETS = ROOT / "dataset" / "Датасет" / "Пилотный проект 20 улиц"


def _cells(path: Path) -> list[tuple[str, str]]:
    if path.suffix.lower() == ".xlsx":
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        return [
            (sheet.title, str(value))
            for sheet in book.worksheets
            for row in sheet.iter_rows(values_only=True)
            for value in row
            if isinstance(value, str)
        ]
    book = xlrd.open_workbook(str(path))
    return [
        (sheet.name, str(sheet.cell_value(r, c)))
        for sheet in book.sheets()
        for r in range(sheet.nrows)
        for c in range(sheet.ncols)
        if isinstance(sheet.cell_value(r, c), str)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("patterns", nargs="+", help="подстроки без учёта регистра")
    args = parser.parse_args()
    patterns = [re.compile(re.escape(p), re.IGNORECASE) for p in args.patterns]
    files = sorted(
        p
        for p in STREETS.rglob("*")
        if p.suffix.lower() in {".xls", ".xlsx"} and "PaxHeader" not in p.parts
    )
    for path in files:
        try:
            cells = _cells(path)
        except Exception as error:  # noqa: BLE001 - битые и защищённые книги пропускаем с причиной
            print(f"! {path.relative_to(STREETS)}: {error}")
            continue
        for sheet, text in cells:
            for pattern in patterns:
                if pattern.search(text):
                    street = path.relative_to(STREETS).parts[0]
                    section = path.relative_to(STREETS).parts[1]
                    print(f"{pattern.pattern!s:20} | {street} | {section} | {path.name} | {sheet} | {text.strip()[:90]}")


if __name__ == "__main__":
    main()
