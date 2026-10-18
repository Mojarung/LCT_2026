"""Дрейф сквозного прогона улиц против эталона (задача 19 плана финала: воспроизводимость).

Прогон 19 улиц пилота - инструмент, а не pytest: каталога улиц в git нет. Эталон -
docs/data/street-golden.json: что прогон обязан повторить. Числа посадок, отказов, газона
сверяются с допуском 5 % (не меньше 5 штук или м²), признаки целостности и проверки плана -
точно.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import street_runs as sr  # noqa: E402

GOLDEN = {
    "6-kamchatskaya": {
        "state": "succeeded",
        "placements": 1000,
        "rejections": 300,
        "lawn_m2": 20.0,
        "integrity_ok": True,
        "plan_valid": True,
    }
}


def _row(**summary: object) -> dict:
    values = {
        "placements": 1000,
        "rejections": 300,
        "lawn_m2": 20.0,
        "integrity_ok": True,
        "plan_valid": True,
        **summary,
    }
    return {"slug": "6-kamchatskaya", "state": "succeeded", "summary": values}


def test_same_numbers_are_no_drift() -> None:
    assert sr.drift([_row()], GOLDEN) == []


def test_small_change_is_within_tolerance() -> None:
    assert sr.drift([_row(placements=1040, lawn_m2=24.0)], GOLDEN) == []


def test_large_change_is_named_with_street_and_key() -> None:
    issues = sr.drift([_row(placements=1100)], GOLDEN)

    assert len(issues) == 1
    assert issues[0].startswith("6-kamchatskaya: placements 1000 -> 1100")


def test_broken_integrity_is_drift_even_without_numbers_moving() -> None:
    issues = sr.drift([_row(integrity_ok=False)], GOLDEN)

    assert issues == ["6-kamchatskaya: integrity_ok True -> False"]


def test_failed_or_missing_street_is_drift() -> None:
    crashed = {"slug": "6-kamchatskaya", "state": "crashed", "summary": {}}

    assert sr.drift([crashed], GOLDEN) == ["6-kamchatskaya: state succeeded -> crashed"]
    assert sr.drift([], GOLDEN) == ["6-kamchatskaya: нет в прогоне"]


def test_golden_written_from_rows_round_trips() -> None:
    golden = sr.golden_of([_row()])

    assert golden == GOLDEN
    assert sr.drift([_row()], golden) == []
