"""Итоговая таблица стенда: база против выбранного варианта по всем улицам (docs/notes/30).

Кроме индекса (v1 - как в сервисе до экспериментов, v2 - с плотностью и пылезащитой от
вместимости участка) печатает физические замеры, которые не зависят от весов индекса:
деревья, кустарники, площадь взрослых крон, метры бортов под кустарником или кроной.

    uv run python tools/research/lab_report.py E00 E46
    uv run python tools/research/lab_report.py E00 E50,E46   # E50, где есть, иначе E46

Запасной ключ нужен, когда вариант B по построению совпадает с другим на части улиц: этап
групп на газоне (E50) ничего не делает там, где кустарника уже 600 на 1 км, и E50 там = E46.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline_lab import ALL_STREETS, latest, load_results  # noqa: E402

TITLES = {
    "1-olimpiyskaya-derevnya": "Олимпийская деревня",
    "2-peschanyy-pereulok": "Песчаный переулок",
    "3-3-ya-parkovaya": "3-я Парковая",
    "4-harkovskaya-ulitsa": "Харьковская",
    "5-bagritskogo-ulitsa": "Багрицкого",
    "6-kamchatskaya-ulitsa": "Камчатская",
    "8-lodochnaya": "Лодочная",
    "9-izmaylovskaya-ploschad": "Измайловская площадь",
    "10-staryy-gay-ul": "Старый Гай",
    "12-natashinskiy-pr-d-doroga-ot-ul-borisovskie-prudy-do-pr-pr": "Наташинский пр-д",
    "13-harkovskiy-proezd": "Харьковский проезд",
    "14-kulikovskaya-ulitsa": "Куликовская",
    "15-akademika-pontryagina": "Академика Понтрягина",
    "16-ulitsa-berzarina": "Берзарина",
    "17-gruzinskaya-m-ul": "Грузинская М.",
    "18-kustanayskaya-ulitsa": "Кустанайская",
    "19-2-ya-pryadilnaya": "2-я Прядильная",
    "20-makeeva-s-ul": "Макеева",
}


def _num(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}".replace(".", ",")


def main(base: str, best: str) -> None:
    rows = latest(load_results())
    print(
        f"| Улица | {base} v1 | {best} v1 | прирост | {base} v2 | {best} v2 | деревьев | "
        "кустарников | кроны, м² | бортов под ярусом, м |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|")
    totals = {"a": [], "b": [], "a2": [], "b2": []}
    forbidden = 0
    keys = best.split(",")
    best = keys[0]
    for slug in ALL_STREETS:
        a = rows.get((base, slug))
        b = next((rows[k, slug] for k in keys if (k, slug) in rows), None)
        if a is None or b is None:
            continue
        gain = b["index"] - a["index"]
        totals["a"].append(a["index"])
        totals["b"].append(b["index"])
        totals["a2"].append(a["index_v2"])
        totals["b2"].append(b["index_v2"])
        forbidden += b["forbidden"]
        canopy_a = a["measures"]["canopy"].get("m2", 0)
        canopy_b = b["measures"]["canopy"].get("m2", 0)
        dust_a = a["measures"]["dust"].get("covered_m", 0)
        dust_b = b["measures"]["dust"].get("covered_m", 0)
        print(
            f"| {TITLES.get(slug, slug)} | {_num(a['index'])} | {_num(b['index'])} | "
            f"+{_num(gain)} | {_num(a['index_v2'])} | {_num(b['index_v2'])} | "
            f"{a['trees']} -> {b['trees']} | {a['shrubs']} -> {b['shrubs']} | "
            f"{canopy_a:.0f} -> {canopy_b:.0f} | {dust_a} -> {dust_b} |"
        )
    count = len(totals["a"])
    if count:
        mean = {k: sum(v) / count for k, v in totals.items()}
        print(
            f"| **среднее, {count} улиц** | **{_num(mean['a'])}** | **{_num(mean['b'])}** | "
            f"**+{_num(mean['b'] - mean['a'])}** | {_num(mean['a2'])} | {_num(mean['b2'])} | | | | |"
        )
        worse = sum(1 for x, y in zip(totals["a"], totals["b"], strict=True) if y < x)
        print(f"\nулиц, где {best} хуже {base}: {worse}")
        print(f"посадок с нарушением норм в {best}: {forbidden}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
