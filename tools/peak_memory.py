"""Команда с замером пиковой памяти всего дерева процессов (сумма рабочих наборов раз в 0,5 с).

    uv run --with psutil python tools/peak_memory.py out/street-runs/mem-15.json -- \
        uv run python tools/street_runs.py --only 15 --profile strict --catalog dataset/streets_oda

Итог - JSON с кодом возврата, пиком в ГБ и временем; его берёт приложение B документации.
"""
# ruff: noqa: INP001, S603 - инструмент замера, команда задаётся явно

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import psutil


def main() -> None:
    out, command = Path(sys.argv[1]), sys.argv[3:]
    started = time.time()
    process = subprocess.Popen(command)
    root = psutil.Process(process.pid)
    peak = 0
    while process.poll() is None:
        try:
            total = root.memory_info().rss + sum(
                child.memory_info().rss for child in root.children(recursive=True)
            )
            peak = max(peak, total)
        except psutil.Error:
            pass
        time.sleep(0.5)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "cmd": command,
                "exit": process.returncode,
                "peak_rss_gb": round(peak / 2**30, 2),
                "seconds": round(time.time() - started),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
