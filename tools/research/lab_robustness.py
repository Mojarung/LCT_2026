"""Лучше ли новый пайплайн при любых весах индекса: Монте-Карло по OECD/JRC (docs/notes/30).

Главный упрёк к «мы подняли свой индекс» - веса выбрали мы. Проверка: те же розыгрыши, что у
tools/research/quality_robustness.py (схема весов: нынешние / равные / ROC; веса групп
x U(0,5; 1,5); выброс одного слагаемого), но сравнивается не место улицы, а пара планов одной
улицы: доля розыгрышей, в которых вариант B лучше базы A. Оценки слагаемых и штрафы берутся из
итогов стенда (docs/notes/data/pipeline-lab.jsonl), пересчитывать планы не нужно.

    uv run python tools/research/lab_robustness.py E00 E46 --draws 5000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lab_report import TITLES  # noqa: E402
from pipeline_lab import ALL_STREETS, latest, load_results  # noqa: E402
from quality_robustness import GROUPS, KEYS, SCHEMES, _index  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base")
    parser.add_argument("best")
    parser.add_argument("--draws", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--version", choices=("v1", "v2"), default="v1")
    args = parser.parse_args()

    rows = latest(load_results())
    field = "terms" if args.version == "v1" else "terms_v2"
    keys = args.best.split(",")  # E50,E46: E50, где есть, иначе E46 (как в lab_report)
    args.best = keys[0]
    pairs = [
        (slug, rows[args.base, slug], next(rows[k, slug] for k in keys if (k, slug) in rows))
        for slug in ALL_STREETS
        if (args.base, slug) in rows and any((k, slug) in rows for k in keys)
    ]
    rng = np.random.default_rng(args.seed)
    wins = np.zeros(len(pairs))
    gaps = np.zeros((args.draws, len(pairs)))
    scheme_names = list(SCHEMES)
    for d in range(args.draws):
        weights = dict(SCHEMES[scheme_names[rng.integers(len(scheme_names))]])
        for keys in GROUPS.values():
            factor = rng.uniform(0.5, 1.5)
            for key in keys:
                weights[key] *= factor
        dropped = rng.integers(len(KEYS) + 1)
        if dropped < len(KEYS):
            weights[KEYS[dropped]] = 0.0
        for j, (_, a, b) in enumerate(pairs):
            pa = sum(a["penalties"].values())
            pb = sum(b["penalties"].values())
            gap = _index(b[field], pb, weights) - _index(a[field], pa, weights)
            gaps[d, j] = gap
            wins[j] += gap > 0
    print(f"Индекс {args.version}, розыгрышей {args.draws}, зерно {args.seed}.\n")
    print(f"| Улица | {args.best} лучше {args.base}, доля розыгрышей | прирост: 5% / медиана / 95% |")
    print("|---|---|---|")
    for j, (slug, _, _) in enumerate(pairs):
        low, mid, high = np.percentile(gaps[:, j], [5, 50, 95])
        numbers = f"{wins[j] / args.draws:.1%} | {low:+.3f} / {mid:+.3f} / {high:+.3f}"
        print(f"| {TITLES.get(slug, slug)} | {numbers.replace('.', ',')} |")
    everywhere = (gaps > 0).all(axis=1).mean()
    print(f"\nРозыгрышей, где {args.best} лучше на всех {len(pairs)} улицах сразу: {everywhere:.1%}")


if __name__ == "__main__":
    main()
