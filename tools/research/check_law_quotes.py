"""Проверить, что каждая цитата из docs/requirements/quotes.yaml дословно есть в тексте акта.

Акты лежат HTML-файлами в папке заказчика (в git не идут). Скрипт снимает теги, схлопывает
пробелы и ищет цитату подстрокой. Строки таблиц ищутся так же: ячейки после снятия тегов идут
через пробел («Наружная стена здания и сооружения 5,0 1,5»). Цитата, которой в тексте нет,
печатается как FAIL, и скрипт завершается с кодом 1.

    uv run python tools/research/check_law_quotes.py "C:/Users/Kirill/Desktop/Docs as HTML"
    GREEN_LAWS_DIR="..." uv run pytest tests/test_law_quotes.py
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
QUOTES = ROOT / "docs" / "requirements" / "quotes.yaml"
# Ключ акта -> шаблон имени файла в папке с актами.
LAW_FILES = {
    "sp42": "СП 42*.html",
    "pp743": "*743-ПП*.html",
    "mgsn": "ТСН 30-307*.html",
    "sp82": "СП 82*.html",
    "sp59": "СП 59*.html",
    "pp515": "*515-ПП*.html",
    "pp369": "*369-ПП*.html",
    "gost21508": "ГОСТ 21.508*.html",
    "zakon18": "Закон*18*.html",
}
_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_SPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _SPACE.sub(" ", text.replace("\xa0", " ")).strip()


def law_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return normalize(html.unescape(_TAG.sub(" ", _SCRIPT.sub(" ", raw))))


def load_quotes(path: Path = QUOTES) -> list[dict[str, str]]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["quotes"]


def check(laws_dir: Path) -> list[tuple[str, str, str]]:
    """(id, статус, пояснение) по каждой цитате: ok, fail, no_file или external."""
    texts: dict[str, str | None] = {}
    results = []
    for item in load_quotes():
        law = item["law"]
        if law == "external":
            results.append((item["id"], "external", item.get("url", "")))
            continue
        if law not in texts:
            found = sorted(laws_dir.glob(LAW_FILES[law]))
            texts[law] = law_text(found[0]) if found else None
        text = texts[law]
        if text is None:
            results.append((item["id"], "no_file", LAW_FILES[law]))
        elif normalize(item["quote"]) in text:
            results.append((item["id"], "ok", item["clause"]))
        else:
            results.append((item["id"], "fail", item["quote"][:80]))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("laws_dir", type=Path, help="папка с HTML-файлами актов")
    args = parser.parse_args()
    results = check(args.laws_dir)
    for quote_id, status, detail in results:
        print(f"{status.upper():8} {quote_id:28} {detail}")
    counts = {
        s: sum(1 for _, status, _ in results if status == s)
        for s in ("ok", "fail", "no_file", "external")
    }
    print(counts)
    sys.exit(1 if counts["fail"] or counts["no_file"] else 0)


if __name__ == "__main__":
    main()
