"""Абляция итога: сколько индекса теряет план без каждого рычага (docs/notes/30).

    uv run python tools/research/lab_ablation.py E50,E46 E51 E52 E53 E54 E55 E56 E57 E58 E59
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lab_experiments  # noqa: E402, F401 - регистрирует эксперименты
from lab_report import TITLES  # noqa: E402
from pipeline_lab import ALL_STREETS, EXPERIMENTS, latest, load_results  # noqa: E402


def main(full: str, *drops: str) -> None:
    rows = latest(load_results())
    keys = full.split(",")
    streets = [s for s in ALL_STREETS if any((k, s) in rows for k in keys)]
    streets = [s for s in streets if all((d, s) in rows for d in drops)]
    print("| Без чего | " + " | ".join(TITLES.get(s, s) for s in streets) + " | среднее |")
    print("|---|" + "---|" * (len(streets) + 1))
    base = {s: next(rows[k, s]["index"] for k in keys if (k, s) in rows) for s in streets}
    for drop in drops:
        loss = [rows[drop, s]["index"] - base[s] for s in streets]
        title = EXPERIMENTS[drop].title.replace("E50 ", "")
        cells = " | ".join(f"{v:+.3f}".replace(".", ",") for v in loss)
        mean = f"{sum(loss) / len(loss):+.3f}".replace(".", ",")
        print(f"| {drop}: {title} | {cells} | **{mean}** |")


if __name__ == "__main__":
    main(*sys.argv[1:])
