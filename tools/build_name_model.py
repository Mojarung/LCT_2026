"""Обучающие имена для третьей ступени классификации (application/name_model.py).

Берёт classification.json прогонов улиц пилота: имена слоёв и блоков, класс которых решило
правило имени (name_rule) - то есть проверенный классификатор config/layer_map.yaml, а не
догадка. Одинаковое имя с разными классами отбрасывается. Пишет config/name_model.json и
печатает проверку «без одной улицы»: модель, обученная на остальных улицах, угадывает классы
имён отложенной (доля верных среди предложенных и доля предложенных).

    uv run python tools/build_name_model.py <каталог runs> [<каталог runs> ...]
"""
# ruff: noqa: INP001, T201 - инструмент сборки данных

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from green.application.name_model import NEVER, NameModel, name_key  # noqa: E402
from green.domain.objects import ObjectClass  # noqa: E402


def collect(dirs: list[Path]) -> dict[str, dict[str, str]]:
    """Улица (sha исходника) -> имя -> класс."""
    streets: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    for root in dirs:
        for path in root.glob("*/output/classification.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            for group in data["groups"]:
                if group["evidence"]["method"] != "name_rule":
                    continue
                if ObjectClass(group["object_class"]) in NEVER:
                    continue
                key = name_key(group["layer"], group["block"])
                streets[data["source_sha256"]][key][group["object_class"]] += group["features"]
    return {
        street: {name: classes.most_common(1)[0][0] for name, classes in names.items() if len(classes) == 1}
        for street, names in streets.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, default=ROOT / "config" / "name_model.json")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute]
    streets = collect(args.runs)
    merged: dict[str, set[str]] = defaultdict(set)
    for names in streets.values():
        for name, cls in names.items():
            merged[name].add(cls)
    names = sorted(n for n, c in merged.items() if len(c) == 1)
    print(f"улиц {len(streets)}, имён {len(names)} (спорных отброшено {len(merged) - len(names)})")
    proposed = correct = total = 0
    for held in streets:
        train = sorted(
            {(n, c) for street, items in streets.items() if street != held for n, c in items.items()}
        )
        model = NameModel(tuple(n for n, _ in train), tuple(ObjectClass(c) for _, c in train))
        known = {n for n, _ in train}
        for name, cls in streets[held].items():
            if name in known:
                continue  # то же имя на другой улице - это уже правило, а не модель
            total += 1
            guess = model.guess(name, None)
            if guess is None:
                continue
            proposed += 1
            correct += guess.object_class.value == cls
    print(
        f"без одной улицы: новых имён {total}, предложено {proposed} "
        f"({proposed / max(total, 1):.0%}), верно {correct} ({correct / max(proposed, 1):.0%})"
    )
    payload = {
        "version": 1,
        "source": "classification.json прогонов улиц пилота, основание name_rule",
        "evaluation": {"new_names": total, "proposed": proposed, "correct": correct},
        "names": names,
        "classes": [next(iter(merged[n])) for n in names],
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
