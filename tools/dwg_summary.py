"""Сводка по results.jsonl: конверсия, версии, слои через классификатор проекта, эталоны."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from green.application.classification import MatchTarget
from green.infrastructure.config.repositories import YamlLayerMapSource

results = Path(sys.argv[1])
layer_map = YamlLayerMapSource(Path("config/layer_map.yaml")).load()
rows = [
    json.loads(line) for line in results.read_text(encoding="utf-8").splitlines() if line.strip()
]


def classify(layer: str, block: str | None = None) -> str:
    for rule in layer_map.rules:
        value = block if rule.target is MatchTarget.BLOCK else layer
        if value is not None and rule.pattern.search(value):
            return rule.object_class.value
    return "unknown"


ok = [r for r in rows if not r.get("error")]
bad = [r for r in rows if r.get("error")]
print(f"files {len(rows)}, converted {len(ok)}, failed {len(bad)}")
for r in bad[:30]:
    print(
        "  FAIL",
        r["error"],
        r.get("returncode"),
        r["file"][-90:],
        (r.get("stderr_tail") or "")[-120:].replace("\n", " "),
    )
print("versions", Counter(r["header"].get("$ACADVER") for r in ok).most_common())
print("insunits", Counter(r["header"].get("$INSUNITS") for r in ok).most_common())
print("codepage", Counter(r["header"].get("$DWGCODEPAGE") for r in ok).most_common(6))
sizes = sorted((r["size"] for r in ok), reverse=True)
print(
    "dwg size top",
    [round(s / 1e6, 1) for s in sizes[:5]],
    "MB; total entities",
    sum(r["entities"] for r in ok),
)
print("convert_s top", sorted((r["convert_s"], r["file"][-60:]) for r in ok)[-5:])
print("empty (0 entities)", sum(1 for r in ok if r["entities"] == 0))
print("with xrefs", sum(1 for r in ok if r["xrefs"]))


def street(path: str) -> str:
    m = re.search(r"20 улиц[\\/]([^\\/]+)", path)
    return m.group(1) if m else path.split("\\")[0]


def is_reference(path: str) -> bool:
    return "Проектное решение" in path or "Проектные решения" in path


# Слои по всем файлам: суммарные сущности, число файлов, улицы, класс.
layer_total: Counter[str] = Counter()
layer_files: Counter[str] = Counter()
layer_streets: defaultdict[str, set] = defaultdict(set)
layer_kinds: defaultdict[str, Counter] = defaultdict(Counter)
for r in ok:
    src = "ref" if is_reference(r["file"]) else "in"
    for layer, n in r["layers"].items():
        key = (src, layer)
        layer_total[key] += n
        layer_files[key] += 1
        layer_streets[key].add(street(r["file"]))
    for layer, kind, n in r["layer_kinds"]:
        layer_kinds[(src, layer)][kind] += n

for src, title in (("in", "ИСХОДНЫЕ ДАННЫЕ"), ("ref", "ПРОЕКТНЫЕ РЕШЕНИЯ")):
    keys = [k for k in layer_total if k[0] == src]
    by_class: Counter[str] = Counter()
    unknown = []
    for key in keys:
        cls = classify(key[1])
        by_class[cls] += layer_total[key]
        if cls == "unknown":
            unknown.append(key)
    print(f"\n=== {title}: слоёв {len(keys)}, сущностей по классам:")
    for cls, n in by_class.most_common():
        print(f"  {n:>9} {cls}")
    unknown.sort(key=lambda k: -layer_total[k])
    print(
        f"--- нераспознанные слои ({len(unknown)}), топ 80 по сущностям: сущности | файлов | улиц | типы | слой"
    )
    for key in unknown[:80]:
        kinds = ", ".join(f"{k}:{n}" for k, n in layer_kinds[key].most_common(3))
        print(
            f"  {layer_total[key]:>8} | {layer_files[key]:>3} | {len(layer_streets[key]):>2} | {kinds:<40} | {key[1]}"
        )

# Блоки INSERT по всем исходным данным.
blocks: Counter[str] = Counter()
block_files: Counter[str] = Counter()
for r in ok:
    if is_reference(r["file"]):
        continue
    for name, n in r["inserts"].items():
        blocks[name] += n
        block_files[name] += 1
print("\n=== Блоки INSERT в исходных данных, топ 60 (без правила по блоку):")
for name, n in blocks.most_common(200):
    if classify("__", name) == "unknown":
        print(f"  {n:>7} | {block_files[name]:>3} | {name}")

# Эталонные решения: слои, похожие на посадки.
print("\n=== Слои посадок в проектных решениях (по ключевым словам):")
kw = re.compile(
    r"дерев|куст|озелен|посад|газон|цветн|растен|дендро|насажд|tree|plant|green", re.IGNORECASE
)
for key in sorted(
    (k for k in layer_total if k[0] == "ref" and kw.search(k[1])), key=lambda k: -layer_total[k]
)[:60]:
    kinds = ", ".join(f"{k}:{n}" for k, n in layer_kinds[key].most_common(3))
    print(
        f"  {layer_total[key]:>7} | {layer_files[key]:>3} | {len(layer_streets[key]):>2} | {kinds:<40} | {key[1]}"
    )
