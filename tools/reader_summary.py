"""Сводка проверки чтения по улицам: одна таблица из out/reader-check/<улица>.json.

По каждой улице: посещено и исходов (учёт полон, если числа равны), пробелы, сверка чернил
(доля непокрытых линий и худшее окно 100 x 100 м против порога 0,5%), знаки двумя счётами,
деревья исходника и сцены, время. Ниже - пробелы по причинам по всем улицам и пропущенные
чернила по слоям. Итог печатается в Markdown и пишется в out/reader-check/summary.md.

    uv run python tools/reader_summary.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "out" / "reader-check"
WINDOW_LIMIT = 0.005


def _row(d: dict) -> str:
    if "error" in d:
        return f"| {d.get('number', '?')} | {d['slug']} | ОШИБКА: {d['error'][:120]} |" + " |" * 7
    visited = sum(d["visited"].values())
    outcomes = sum(d["outcomes"].values())
    gaps = sum(g["count"] for g in d["gaps"])
    ink = d.get("fidelity") or {}
    ink_text = f"{ink['missed_m']:.1f} м ({ink['missed_share']:.3%})" if ink else "не считалась"
    worst = f"{ink['worst_window_share']:.2%}" if ink else ""
    veg = d.get("vegetation") or {}
    trees = next((c for c in veg.get("classes", []) if c["class"] == "existing_tree"), None)
    trees_text = f"{trees['source']}/{trees['scene']}" if trees else "-"
    census = veg.get("census_inserts")
    symbols = f"{census}/{d['symbols']}" if census is not None else str(d["symbols"])
    match = "да" if veg.get("matches") else ("НЕТ" if veg else "")
    ledger = "полон" if visited == outcomes else f"{outcomes}/{visited}"
    return (
        f"| {d['number']} | {d['title'][:28]} | {visited} | {ledger} | {gaps} | {ink_text} "
        f"| {worst} | {symbols} | {trees_text} | {match} | {d['seconds']['total']:.0f} |"
    )


def main() -> None:
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CHECK.glob("*.json"))]
    rows = [r for r in rows if "slug" in r]
    rows.sort(key=lambda r: r.get("number", 99))
    lines = [
        "| N | Улица | посещено | учёт | пробелов | чернил пропущено | худшее окно "
        "| знаков (перепись/ридер) | деревьев (исходник/сцена) | растительность | с |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
        *(_row(r) for r in rows),
    ]
    reasons: Counter[str] = Counter()
    layers: Counter[str] = Counter()
    over: list[str] = []
    for r in rows:
        for g in r.get("gaps", []):
            reasons[f"{g['type']}: {g['reason']}"] += g["count"]
        ink = r.get("fidelity") or {}
        for key, value in ink.get("missed_by_layer", {}).items():
            layers[f"{r['number']} {key}"] += value
        if ink and ink["worst_window_share"] > WINDOW_LIMIT:
            over.append(f"{r['number']} {r['title']}: {len(ink['windows_over_limit'])} окон")
    lines += ["", "Пробелы по причинам (все улицы):", ""]
    lines += [f"- {n} {reason}" for reason, n in reasons.most_common()]
    lines += ["", "Пропущенные чернила по улице, типу и слою (метры):", ""]
    lines += [f"- {v:.1f} {k}" for k, v in layers.most_common(40)]
    lines += ["", "Окна выше порога 0,5%:", ""]
    lines += [f"- {text}" for text in over] or ["- нет"]
    text = "\n".join(lines) + "\n"
    (CHECK / "summary.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
