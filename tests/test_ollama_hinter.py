"""Ответ LLM приводится к классам сервиса кодом: формат и словарь - не обещание промпта.

Сетевой вызов подменяется: проверяется разбор ответа, партии и отказ на сбое. Качество
подсказок модели здесь не проверяется: живой прогон - tools/research/ml/llm_hints_smoke.py.
"""

from __future__ import annotations

import json
import socket
import threading
import time

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

    def fake(_self: OllamaNameHinter, batch: list[str], _timeout: float) -> str:
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
    def broken(_self: OllamaNameHinter, _batch: list[str], _timeout: float) -> str:
        message = "connection refused"
        raise OSError(message)

    monkeypatch.setattr(OllamaNameHinter, "_ask", broken)
    with pytest.raises(OSError, match="refused"):
        OllamaNameHinter("http://ollama", "qwen3:8b").suggest(["a"])


def _serve_once(reply: bytes) -> str:
    """Настоящий сокет: один ответ как есть (мок транспорта ошибок HTTP не воспроизводит)."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)

    def answer() -> None:
        connection, _ = server.accept()
        with connection:
            # Запрос дочитывается целиком: закрытие с недочитанным телом даёт сброс соединения.
            data = b""
            while b"\r\n\r\n" not in data:
                data += connection.recv(65536)
            head, _, body = data.partition(b"\r\n\r\n")
            length = next(
                int(line.split(b":")[1])
                for line in head.split(b"\r\n")
                if line.lower().startswith(b"content-length")
            )
            while len(body) < length:
                body += connection.recv(65536)
            connection.sendall(reply)
        server.close()

    threading.Thread(target=answer, daemon=True).start()
    return f"http://127.0.0.1:{server.getsockname()[1]}"


def test_broken_http_reply_is_an_os_error_the_run_can_log() -> None:
    """Ревью 18.10.2026: BadStatusLine (не-HTTP сервис или прокси на адресе модели) уходил мимо
    перехвата прогона и ронял всю улицу."""
    url = _serve_once(b"HTTP/1.1 abc\r\n\r\n")
    with pytest.raises(OSError, match="BadStatusLine"):
        OllamaNameHinter(url, "m", timeout_s=5).suggest(["a"])


def test_reply_without_a_message_is_an_os_error() -> None:
    body = b'{"message": null}'
    url = _serve_once(
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(body)).encode()
        + b"\r\nConnection: close\r\n\r\n"
        + body
    )
    with pytest.raises(OSError, match="TypeError"):
        OllamaNameHinter(url, "m", timeout_s=5).suggest(["a"])


def test_time_budget_covers_all_batches_not_each(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ревью 18.10.2026: предел был на каждую партию по 25 имён, и три партии на процессоре
    держали прогон втрое дольше обещанного. Предел - на все подсказки прогона: что не успели
    спросить, остаётся без подсказки."""
    calls: list[float] = []

    def slow(_self: OllamaNameHinter, batch: list[str], timeout: float) -> str:
        calls.append(timeout)
        time.sleep(0.2)
        rows = [{"id": i, "cls": "pole", "confidence": 0.7} for i in range(len(batch))]
        return json.dumps({"rows": rows})

    monkeypatch.setattr(OllamaNameHinter, "_ask", slow)
    out = OllamaNameHinter("http://ollama", "m", timeout_s=0.3, batch=1).suggest(["a", "b", "c"])
    assert out == [("pole", 0.7), ("pole", 0.7), (None, 0.0)]
    assert calls[0] == pytest.approx(0.3, abs=0.05)
    assert calls[1] < 0.15
