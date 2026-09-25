"""Проверка устойчивости индекса качества к весам: Монте-Карло по методичке OECD/JRC.

OECD/JRC, Handbook on Constructing Composite Indicators (2008), шаг 7, с. 117-121: все
спорные решения разыгрываются одновременно, результат - насколько сдвигаются места
участников. Разыгрываются:

- X1 схема весов: нынешние (DEFAULT_QUALITY_WEIGHTS) / равные / ROC по порядку заказчика
  (QA:39: функции и надёжность важнее объёма);
- X2 возмущение весов групп: каждая группа x U(0,5; 1,5), затем нормировка;
- X3 исключение слагаемого: ни одного или одно из десяти, веса остальных нормируются.

Оценки слагаемых берутся из quality.json прогонов: пересчитывать планы не нужно.

    uv run python tools/research/quality_robustness.py --api http://127.0.0.1:8000
    uv run python tools/research/quality_robustness.py out/*/quality.json --draws 5000
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

import numpy as np

from green.application.params import DEFAULT_QUALITY_WEIGHTS
from green.application.quality.weights import GROUPS

KEYS = [key for keys in GROUPS.values() for key in keys]


def _scheme_equal() -> dict[str, float]:
    return dict.fromkeys(KEYS, 1 / len(KEYS))


def _scheme_roc() -> dict[str, float]:
    """ROC-веса по порядку A = B = C > D (QA:39), внутри группы поровну."""
    groups = {"reliability": 0.3125, "functions": 0.3125, "composition": 0.3125, "volume": 0.0625}
    return {k: groups[g] / len(keys) for g, keys in GROUPS.items() for k in keys}


SCHEMES = {
    "нынешние": dict(DEFAULT_QUALITY_WEIGHTS),
    "равные": _scheme_equal(),
    "ROC": _scheme_roc(),
}


def _load(args: argparse.Namespace) -> dict[str, dict]:
    reports: dict[str, dict] = {}
    for path in args.paths:
        reports[path.parent.parent.name] = json.loads(path.read_text(encoding="utf-8"))
    if args.api:
        with urllib.request.urlopen(f"{args.api}/api/v1/runs?limit=200", timeout=60) as r:
            runs = json.load(r)["items"]
        latest: dict[str, dict] = {}
        for run in runs:  # новые первыми: оставляем последний удачный прогон каждого чертежа
            if run["state"] == "succeeded" and run["source_name"] not in latest:
                latest[run["source_name"]] = run
        for name, run in latest.items():
            url = f"{args.api}/api/v1/runs/{run['id']}/artifacts/quality.json"
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    reports[name] = json.load(r)
            except OSError:
                continue  # прогон до появления индекса
    return {n: q for n, q in reports.items() if q.get("index") is not None}


def _index(scores: dict[str, float | None], penalty: float, weights: dict[str, float]) -> float:
    defined = {k: w for k, w in weights.items() if w > 0 and scores.get(k) is not None}
    total = sum(defined.values())
    raw = sum(w * (scores[k] or 0.0) for k, w in defined.items()) / total if total else 0.0
    return min(1.0, max(0.0, raw - penalty))


def _ranks(values: list[float]) -> np.ndarray:
    order = np.argsort(-np.array(values), kind="stable")
    ranks = np.empty(len(values), dtype=int)
    ranks[order] = np.arange(1, len(values) + 1)
    return ranks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path, help="quality.json прогонов")
    parser.add_argument("--api", help="адрес сервиса: взять последний прогон каждой улицы")
    parser.add_argument("--draws", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    reports = _load(args)
    if len(reports) < 2:  # noqa: PLR2004 - места сравниваются хотя бы у двух планов
        raise SystemExit("нужно хотя бы два прогона с индексом")
    names = sorted(reports)
    scores = [{t["key"]: t["score"] for t in reports[n]["terms"]} for n in names]
    penalties = [float(reports[n].get("penalty", 0.0)) for n in names]
    base = _ranks([_index(s, p, SCHEMES["нынешние"]) for s, p in zip(scores, penalties)])

    rng = np.random.default_rng(args.seed)
    ranks = np.empty((args.draws, len(names)), dtype=int)
    scheme_names = list(SCHEMES)
    for d in range(args.draws):
        weights = dict(SCHEMES[scheme_names[rng.integers(len(scheme_names))]])
        for keys in GROUPS.values():
            factor = rng.uniform(0.5, 1.5)
            for key in keys:
                weights[key] *= factor
        dropped = rng.integers(len(KEYS) + 1)  # len(KEYS) - ничего не выкидываем
        if dropped < len(KEYS):
            weights[KEYS[dropped]] = 0.0
        ranks[d] = _ranks([_index(s, p, weights) for s, p in zip(scores, penalties)])

    shift = np.abs(ranks - base).mean(axis=1)
    print(f"Планов: {len(names)}, розыгрышей: {args.draws}, зерно {args.seed}.")
    print(
        f"Средний сдвиг места R_S (OECD, ур. 38): медиана {np.median(shift):.2f}, "
        f"95-й процентиль {np.percentile(shift, 95):.2f}.\n"
    )
    print("| План | Индекс | Место | Медиана места | 5-95% мест |")
    print("|---|---|---|---|---|")
    for j in np.argsort(base):
        low, mid, high = np.percentile(ranks[:, j], [5, 50, 95])
        print(
            f"| {names[j]} | {reports[names[j]]['index']:.3f} | {base[j]} | {mid:.0f} | "
            f"{low:.0f}-{high:.0f} |"
        )


if __name__ == "__main__":
    main()
