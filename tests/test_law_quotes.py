"""Цитаты из docs/requirements/quotes.yaml дословно есть в текстах актов заказчика.

Акты в git не идут. Папка с HTML-файлами задаётся переменной GREEN_LAWS_DIR, без неё проверка
по текстам пропускается. Сам файл цитат и ссылки на него из документа требований проверяются
всегда.
"""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "research" / "check_law_quotes.py"
REQUIREMENTS = ROOT / "docs" / "requirements" / "planting-requirements.md"
LAWS_DIR = os.environ.get("GREEN_LAWS_DIR", "")
QUOTE_ID = re.compile(
    r"(?<![A-Za-z0-9-])(?:SP42|SP82|SP59|PP743|PP515|PP369|MGSN|GOST|ZAKON18|PPRF160)-[A-Za-z0-9][A-Za-z0-9.\-]*"
)


def _tool():  # noqa: ANN202 - модуль инструмента грузится по пути
    spec = importlib.util.spec_from_file_location("check_law_quotes", TOOL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quotes_file_is_well_formed() -> None:
    tool = _tool()
    quotes = tool.load_quotes()
    ids = [q["id"] for q in quotes]
    assert len(ids) == len(set(ids))
    for quote in quotes:
        assert quote["law"] == "external" or quote["law"] in tool.LAW_FILES, quote["id"]
        assert quote["clause"], quote["id"]
        assert len(quote["quote"]) >= 10, quote["id"]
        if quote["law"] == "external":
            assert quote["url"].startswith("https://"), quote["id"]


def test_requirements_cite_only_known_quotes() -> None:
    """Каждый идентификатор цитаты в документе требований есть в quotes.yaml."""
    known = {q["id"] for q in _tool().load_quotes()}
    text = REQUIREMENTS.read_text(encoding="utf-8")
    cited = {match.rstrip(".-") for match in QUOTE_ID.findall(text)}
    assert cited, "в документе требований нет ссылок на цитаты"
    assert cited <= known, sorted(cited - known)


@pytest.mark.skipif(not LAWS_DIR, reason="GREEN_LAWS_DIR не задан: актов заказчика нет")
def test_every_quote_is_found_verbatim_in_the_law_text() -> None:
    results = _tool().check(Path(LAWS_DIR))
    bad = [item for item in results if item[1] in {"fail", "no_file"}]
    assert not bad, bad
