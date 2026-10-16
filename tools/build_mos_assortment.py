"""Официальный ассортимент Москвы (mos.ru) -> config/mos_assortment.yaml.

Источник: «Основной и дополнительный ассортимент деревьев, кустарников и лиан, рекомендуемый для
озеленения различных категорий территорий города Москвы» (PDF, 19 стр.):
https://www.mos.ru/upload/content/files/c6ee55bb75792e008a490f28cfe834fb/Osnovnoiidopolnitelniiassortimentderevevkystarnikovilian.pdf
Документ на этот ассортимент постановщик задачи давал ссылкой на сессии вопросов
(docs/notes/15-organizers-qa.md); им пользуются 4 команды-соперника.

У каждого вида 8 отметок «+» / «-» по категориям территорий (графы 3-10). Строка, где отметок не
ровно 8, не угадывается: marks = null и сырой текст строки (правило полуструктурированного
текста). Вид каталога сервиса (config/species.yaml) сопоставляется по названию: точное
совпадение после нормализации, иначе первые два слова; несопоставленные перечисляются.

    uv run --with pdfplumber python tools/build_mos_assortment.py dataset/assortment/mos-assortment.pdf
"""
# ruff: noqa: INP001, T201 - инструмент сборки данных

from __future__ import annotations

import argparse
import difflib
import hashlib
import re
import sys
from pathlib import Path

import pdfplumber
import yaml

ROOT = Path(__file__).resolve().parents[1]
URL = (
    "https://www.mos.ru/upload/content/files/c6ee55bb75792e008a490f28cfe834fb/"
    "Osnovnoiidopolnitelniiassortimentderevevkystarnikovilian.pdf"
)
# Графы 3-10 документа по порядку.
CATEGORIES = (
    "yards",  # дворовые территории
    "kindergartens",  # дошкольные учреждения
    "schools",  # общеобразовательные и спортивные учреждения
    "healthcare",  # учреждения здравоохранения
    "roads",  # магистрали; *внутриквартальные улицы и проезды местного значения
    "plazas",  # площади, общественно-деловые пространства
    "parks",  # парки; *бульвары, скверы, набережные, сады
    "industrial",  # производственные территории; *охранные и санитарно-защитные зоны
)
GROUPS = (
    "Хвойные деревья",
    "Лиственные деревья",
    "Хвойные кустарники",
    "Лиственные кустарники",
    "Лианы",
)
MARK = re.compile(r"^[+\-–−]$")


# Вид каталога, названный в документе иначе: код -> название строки документа.
ALIASES = {"salix_alba_tristis": "Ива белая"}
# Сходство названий (difflib) для опечаток документа: «Недзведцкого» вместо «Недзвецкого».
FUZZY = 0.92
# Короткие слова, которые не хвост переноса: «формы и сорта».
_SHORT_WORDS = frozenset({"и", "в", "с", "к", "о", "у", "а", "на", "по", "до", "от"})


def _rejoin(text: str) -> str:
    """Слова, разорванные переносом строки в таблице PDF («приречны й», «перисто- ветвистый»)."""
    text = re.sub(r"-\s+", "-", text)
    words: list[str] = []
    for word in text.split():
        if words and len(word) <= 2 and word.isalpha() and word not in _SHORT_WORDS:  # noqa: PLR2004
            words[-1] += word
        else:
            words.append(word)
    return " ".join(words)


def normalize(name: str) -> str:
    text = _rejoin(name.lower().replace("ё", "е").replace("\n", " "))
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(r"[*«»\"']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse(pdf_path: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    listing, group = "main", ""
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            for table in page.extract_tables():
                for row in table:
                    cells = [(c or "").strip() for c in row]
                    text = " ".join(c for c in cells if c)
                    if "Дополнительный ассортимент" in text:
                        listing = "extra"
                    for name in GROUPS:
                        if text.startswith(name):
                            group = name
                    if [c for c in cells if c] == [str(i) for i in range(1, len(CATEGORIES) + 4)]:
                        continue  # строка номеров граф
                    if not cells or not cells[0].isdigit():
                        if entries and text and not any(MARK.match(t) for t in text.split()):
                            if not any(g in text for g in GROUPS) and "ассортимент" not in text:
                                entries[-1]["note"] = f"{entries[-1]['note']} {text}".strip()
                        continue
                    rest = cells[1:]
                    tokens = [t for c in rest for t in c.split()]
                    marks = [t for t in tokens if MARK.match(t)]
                    texts = [c for c in rest if c and not all(MARK.match(t) for t in c.split())]
                    name = _rejoin(texts[0].replace("\n", " ")) if texts else ""
                    note = " ".join(t.replace("\n", " ") for t in texts[1:])
                    entry: dict[str, object] = {
                        "list": listing,
                        "group": group,
                        "row": int(cells[0]),
                        "page": page_number,
                        "name": name,
                        "marks": dict(zip(CATEGORIES, (m == "+" for m in marks), strict=True))
                        if len(marks) == len(CATEGORIES)
                        else None,
                        "note": note,
                    }
                    if entry["marks"] is None:
                        entry["raw"] = " | ".join(cells)
                    entries.append(entry)
    return entries


def match(entries: list[dict[str, object]], species: list[dict[str, object]]) -> dict[str, int]:
    """Код вида каталога -> индекс строки документа."""
    by_full: dict[str, int] = {}
    by_two: dict[str, int] = {}
    for index, entry in enumerate(entries):
        for variant in str(entry["name"]).split("/"):
            key = normalize(variant)
            if not key:
                continue
            by_full.setdefault(key, index)
            by_two.setdefault(" ".join(key.split()[:2]), index)
    found = {}
    for item in species:
        key = normalize(ALIASES.get(str(item["code"]), str(item["name_ru"])))
        index = by_full.get(key, by_two.get(" ".join(key.split()[:2])))
        if index is None:
            close = difflib.get_close_matches(key, list(by_full), n=1, cutoff=FUZZY)
            index = by_full[close[0]] if close else None
        if index is not None:
            found[str(item["code"])] = index
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "config" / "mos_assortment.yaml")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute]
    entries = parse(args.pdf)
    catalog = yaml.safe_load((ROOT / "config" / "species.yaml").read_text(encoding="utf-8"))
    species = catalog["species"]
    matched = match(entries, species)
    for code, index in matched.items():
        entries[index].setdefault("species_codes", []).append(code)  # ty: ignore[call-non-callable]
    digest = hashlib.sha256(args.pdf.read_bytes()).hexdigest()
    payload = {
        "version": 1,
        "source": {
            "title": "Основной и дополнительный ассортимент деревьев, кустарников и лиан, "
            "рекомендуемый для озеленения различных категорий территорий города Москвы",
            "url": URL,
            "sha256": digest,
        },
        "categories": list(CATEGORIES),
        "entries": entries,
    }
    args.out.write_text(
        "# Сгенерировано tools/build_mos_assortment.py из PDF mos.ru, руками не править.\n"
        + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
        newline="\n",
    )
    unparsed = [e for e in entries if e["marks"] is None]
    print(f"строк {len(entries)}, без 8 отметок {len(unparsed)}")
    for e in unparsed:
        print("  нет отметок:", e["page"], e["row"], e["name"], "|", e.get("raw", "")[:80])
    print(f"видов каталога {len(species)}, сопоставлено {len(matched)}")
    for item in species:
        if item["code"] not in matched:
            print("  нет в документе:", item["code"], item["name_ru"])


if __name__ == "__main__":
    main()
