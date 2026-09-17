"""Перечётная ведомость: что доехало до квот, что отброшено и почему."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from openpyxl import Workbook

from green.application.errors import InputError
from green.infrastructure.config.repositories import YamlSpeciesCatalog
from green.infrastructure.inventory import read_inventory

if TYPE_CHECKING:
    from collections.abc import Sequence

ROOT = Path(__file__).resolve().parents[1]
CATALOG = YamlSpeciesCatalog(ROOT / "config" / "species.yaml").all()
_SURVEY = (
    Path("Пилотный проект 20 улиц")
    / "16. улица Берзарина"
    / "Исходные данные"
    / "Перечетка_улица Берзарина.xls"
)
# Датасет в git не идёт, у участников команды он распакован в разные папки.
_DATASET_ROOTS = (ROOT / "dataset" / "streets", ROOT / "dataset" / "Датасет")
BERZARINA = next(
    (root / _SURVEY for root in _DATASET_ROOTS if (root / _SURVEY).exists()),
    _DATASET_ROOTS[0] / _SURVEY,
)

HEADER = ("№№", "Наименование", "Кол-во в шт.", "Диаметр", "Заключение")
ROWS: Sequence[tuple[object, ...]] = (
    ("Разработка проектно-сметной документации", "", "", "", ""),
    HEADER,
    (1, "Клен ясенелистный", 1, 16, "Сохранить"),
    (2, "Клен ясенелистный", 1, 24, "Сохранить"),
    (3, "Клен ясенелистный", 1, 12, "Вырубить"),
    (4, "Липа мелколистная", 1, 30, "Сохранить"),
    (5, "Липа", 1, 28, "Сохранить"),
    (6, "Самосев до 8 см.", 1, 6, "Сохранить"),
    (7, "Всего деревьев", 6, "", ""),
)


def _book(path: Path, rows: Sequence[tuple[object, ...]] = ROWS) -> Path:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    for row in rows:
        sheet.append(list(row))
    book.save(path)
    return path


def test_survey_counts_species_and_reports_what_it_dropped(tmp_path: Path) -> None:
    counts = read_inventory(_book(tmp_path / "survey.xlsx"), CATALOG)
    assert counts.matched == {"acer_negundo": 2, "tilia_cordata": 2}
    assert counts.rows_read == 6
    assert counts.rows_removed == 1
    assert counts.unmatched == {"Самосев до 8 см.": 1}
    assert counts.total == 4
    assert counts.balanced


def test_single_word_name_is_matched_by_genus_and_marked_approximate(tmp_path: Path) -> None:
    counts = read_inventory(_book(tmp_path / "survey.xlsx"), CATALOG)
    assert counts.approximate == {"Липа": "tilia_cordata"}


def test_missing_count_is_taken_as_one_tree_and_reported(tmp_path: Path) -> None:
    rows = (HEADER, (1, "Липа мелколистная", "", 30, "Сохранить"))
    counts = read_inventory(_book(tmp_path / "survey.xlsx", rows), CATALOG)
    assert counts.matched == {"tilia_cordata": 1}
    assert counts.rows_without_count == 1


def test_a_file_without_a_header_is_rejected(tmp_path: Path) -> None:
    rows = (("что-то", "другое"), (1, 2))
    with pytest.raises(InputError):
        read_inventory(_book(tmp_path / "survey.xlsx", rows), CATALOG)


def test_unsupported_extension_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "survey.csv"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(InputError):
        read_inventory(path, CATALOG)


@pytest.mark.skipif(not BERZARINA.exists(), reason="датасет не распакован")
def test_real_berzarina_survey_is_read() -> None:
    """Реальная ведомость: 855 строк, 718 деревьев, клён ясенелистный преобладает."""
    counts = read_inventory(BERZARINA, CATALOG)
    assert counts.rows_read > 800
    assert counts.total > 700
    assert counts.matched["acer_negundo"] > 300
    assert counts.rows_removed == 17
    # Отброшенное видно: без этого числа разбор неотличим от полного.
    assert counts.rows_unmatched > 0
    assert counts.balanced
