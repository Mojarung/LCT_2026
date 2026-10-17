"""Ответ LLM приводится к классам сервиса кодом: формат и словарь - не обещание промпта.

Сетевой вызов подменяется: проверяется разбор ответа, партии и отказ на сбое. Качество
подсказок модели здесь не проверяется: живой прогон - tools/research/ml/llm_hints_smoke.py.
"""

from __future__ import annotations

import json

import pytest

from green.infrastructure.llm.ollama import OllamaNameHinter, parse_rows


def test_rows_from_fenced_json_and_numbered_ids() -> None:
    text = (
        '```json\n{"rows": [{"id": "0. Наружное освещение", "cls": "pole", '
        '"confidence": 0.8}]}\n```'
    )
    assert parse_rows(text) == {0: ("pole", 0.8)}


def test_garbage_reply_gives_no_rows() -> None:
    assert parse_rows("не знаю") == {}


def test_unknown_class_and_bad_confidence_are_normalised() -> None:
    text = json.dumps(
        {"rows": [{"id": 0, "cls": "streetlight", "confidence": 3}, {"id": 1, "cls": "unknown"}]}
    )
    assert parse_rows(text) == {0: ("streetlight", 1.0), 1: (None, 0.0)}


def test_names_go_in_batches_and_answers_come_back_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake(_self: OllamaNameHinter, batch: list[str]) -> str:
        calls.append(batch)
        rows = [{"id": i, "cls": "pole", "confidence": 0.7} for i in range(len(batch))]
        return json.dumps({"rows": rows})

    monkeypatch.setattr(OllamaNameHinter, "_ask", fake)
    hinter = OllamaNameHinter("http://ollama", "qwen3:8b", batch=2)
    out = hinter.suggest(["a", "b", "c"])
    assert calls == [["a", "b"], ["c"]]
    assert out == [("pole", 0.7)] * 3
    assert hinter.model == "qwen3:8b"


def test_failed_batch_is_an_error_not_a_silent_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_self: OllamaNameHinter, _batch: list[str]) -> str:
        message = "connection refused"
        raise OSError(message)

    monkeypatch.setattr(OllamaNameHinter, "_ask", broken)
    with pytest.raises(OSError, match="refused"):
        OllamaNameHinter("http://ollama", "qwen3:8b").suggest(["a"])
