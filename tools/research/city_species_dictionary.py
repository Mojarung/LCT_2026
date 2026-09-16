"""Сверка config/species.yaml со «Справочником пород» из шаблона перечётной ведомости ДПиООС.

Справочник лежит листом в перечётных ведомостях пилота (например, Грузинская М. ул,
«Проектное решение/дендроплан/Перечетная ведомость зеленых насаждений.xlsx»): порода,
жизненная форма (дерево или кустарник), код ценности и компенсационная стоимость. Код
ценности 1 - хвойные, 2 - ценные лиственные, 3 - плодовые и мелкие, 4 - малоценные
(в примечании справочника: «учитывается при расчете итогов по малоценным породам»), пусто -
инвазивные по 369-ПП и служебные строки.

Скрипт печатает для каждого вида каталога найденную строку справочника и расхождения:
жизненная форма каталога против справочника, вид без строки в справочнике.

    uv run python tools/research/city_species_dictionary.py
    uv run python tools/research/city_species_dictionary.py --dump dictionary.csv
"""

from __future__ import annotations

import argparse
import csv
import warnings
from pathlib import Path

import openpyxl

from green.domain.planting import TREE_FORMS
from green.infrastructure.config.repositories import YamlSpeciesCatalog

ROOT = Path(__file__).resolve().parents[2]
WORKBOOK = (
    ROOT
    / "dataset/Датасет/Пилотный проект 20 улиц/17. Грузинская М ул/Проектное решение"
    / "дендроплан/Перечетная ведомость зеленых насаждений.xlsx"
)
SHEET = "Справочник пород"
HEADER_ROWS = 3


def _norm(name: str) -> str:
    return " ".join(name.replace("ё", "е").replace("Ё", "Е").casefold().split())


def _variants(name: str) -> list[str]:
    """«Клен приречный (гиннала)» -> клен приречный (гиннала), клен приречный, клен гиннала.

    В справочнике синонимы видового эпитета стоят в скобках через запятую; род - первое слово.
    """
    variants = [_norm(name)]
    if "(" not in name:
        return variants
    head, _, rest = name.partition("(")
    genus = head.split()[0] if head.split() else ""
    variants.append(_norm(head))
    for synonym in rest.rstrip(") ").split(","):
        if synonym.strip():
            variants.append(_norm(f"{genus} {synonym}"))
    return variants


def load_dictionary(path: Path = WORKBOOK) -> dict[str, tuple[str, str, int | None]]:
    """Вариант названия (нормализованный) -> (строка справочника, жизненная форма, код ценности).

    Точное название строки важнее синонима: синоним не перезаписывает уже найденное.
    """
    warnings.filterwarnings("ignore", module="openpyxl")
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = [r for r in list(book[SHEET].iter_rows(values_only=True))[HEADER_ROWS:] if r[2]]
    found: dict[str, tuple[str, str, int | None]] = {}
    for exact_first in (True, False):
        for r in rows:
            names = _variants(str(r[2]))
            for variant in names[:1] if exact_first else names[1:]:
                found.setdefault(variant, (str(r[2]), str(r[1]), r[3]))
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dump", type=Path, help="выгрузить справочник в CSV")
    args = parser.parse_args()
    dictionary = load_dictionary()
    if args.dump:
        with args.dump.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream, delimiter=";")
            writer.writerow(["порода", "жизненная форма", "код ценности"])
            rows = sorted({row for row in dictionary.values()})
            writer.writerows(rows)
    catalog = YamlSpeciesCatalog(ROOT / "config" / "species.yaml")
    rows = len({row[0] for row in dictionary.values()})
    print(f"справочник: {rows} пород, файл {WORKBOOK.relative_to(ROOT)}")
    for species in catalog.all():
        row = dictionary.get(_norm(species.name_ru))
        expected = "дерево" if species.life_form in TREE_FORMS else "кустарник"
        if row is None:
            print(f"нет в справочнике | {species.code} | {species.name_ru}")
            continue
        title, form, code = row
        mark = "ок" if form == expected else "РАСХОЖДЕНИЕ"
        print(
            f"{mark} | {species.code} | {species.name_ru} | каталог: {expected} | "
            f"справочник: «{title}», {form}, код {code}"
        )


if __name__ == "__main__":
    main()
