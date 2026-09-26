"""Подбор весов индекса качества по принятым проектам: обратная оптимизация.

Запуск после прогона улиц (tools/street_runs.py пишет out/street-runs):

    uv run python tools/quality_calibration.py --runs out/street-runs \
        --report docs/quality-weights.md --json out/quality-calibration.json

Метод (docs/plans/2026-09-26-index-v3-design.md, раздел «Веса»; docs/quality-weights.md):

- принятый проект - выбор эксперта, наши варианты той же улицы - допустимые альтернативы.
  Веса, при которых выбор эксперта не хуже альтернатив, объясняют этот выбор (обратная
  оптимизация: Ahuja, Orlin 2001; Chan, Lee, Terekhov 2019; порядковая регрессия UTA:
  Jacquet-Lagrèze, Siskos 1982);
- у проекта без координат посадок считаются только слагаемые состава: плотность,
  разнообразие, категория, сезонность и тень (площадь крон по составу с перекрытием крон
  нашего плана той же улицы). Пригодность, запас до сетей, ряды, ярусы и пылезащита требуют
  координат - в сравнении они не участвуют;
- коридор весов - от половины до двойного равного веса: ни один критерий не выпадает и не
  забирает индекс (OECD/JRC 2008, Handbook on Constructing Composite Indicators, с. 31-33);
- два шага: минимум суммарного проигрыша проектов нашим вариантам (линейная задача, HiGHS),
  затем из таких весов - ближайшие к равным по квадрату отклонения (SLSQP);
- устойчивость: бутстреп по улицам и случайные веса Дирихле вокруг найденных (OECD/JRC,
  шаг 7), доля розыгрышей, где наш выбранный план не хуже проекта.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from scipy.optimize import linprog, minimize

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from green.application.params import DEFAULT_QUALITY_WEIGHTS, PlanParams  # noqa: E402
from green.application.quality.terms import _CATEGORY, CATEGORY_SILENT  # noqa: E402

KEYS = tuple(DEFAULT_QUALITY_WEIGHTS)
# Слагаемые, которые у проекта считаются по составу, без координат посадок. Тень проекта
# считается только справкой: сорта проектировщиков часто колоновидные («Crimson Sentry»,
# «Fastigiata»), а каталог даёт им крону исходного вида - оценка площади крон завышена.
COMPOSITION = ("density", "diversity", "category", "season")
LOW, HIGH = 0.5, 2.0  # коридор весов: доля от равного веса
BOOTSTRAP = 400
DIRICHLET = 2000
DIRICHLET_CONCENTRATION = 50.0
SEED = 20260926


@dataclass
class Street:
    slug: str
    title: str
    variants: list[dict[str, float]]
    chosen: dict[str, float]
    measure: dict[str, dict[str, float]]
    designer: dict[str, float] = field(default_factory=dict)
    designer_note: str = ""
    confidence: str = ""


# --- Наши прогоны --------------------------------------------------------------------------


def load_runs(runs: Path) -> dict[str, Street]:
    streets = {}
    for summary in sorted(runs.glob("*.json")):
        data = json.loads(summary.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("state") != "succeeded":
            continue
        output = runs / "runs" / data["run_id"] / "output"
        portfolio = _json(output / "portfolio.json")
        quality = _json(output / "quality.json")
        if not portfolio or not quality:
            continue
        variants = [
            {k: float(v) for k, v in variant.get("terms", {}).items() if v is not None}
            for variant in portfolio.get("variants", [])
            if variant.get("valid") and variant.get("terms")
        ]
        if not variants:
            continue
        terms = quality.get("terms", [])
        streets[data["slug"]] = Street(
            slug=data["slug"],
            title=data.get("title", data["slug"]),
            variants=variants,
            chosen={t["key"]: float(t["score"]) for t in terms if t.get("score") is not None},
            measure={t["key"]: t.get("measure", {}) for t in terms},
        )
    return streets


def _json(path: Path) -> Any:  # noqa: ANN401 - артефакт прогона
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# --- Проект проектировщика: слагаемые состава ------------------------------------------------


class Catalog:
    """Виды каталога по русскому имени: вид (два слова) или род (первое слово)."""

    def __init__(self, path: Path) -> None:
        entries = yaml.safe_load(path.read_text(encoding="utf-8"))["species"]
        self.by_name: dict[str, dict[str, Any]] = {}
        self.by_genus: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            words = _words(entry["name_ru"])
            self.by_name.setdefault(" ".join(words[:2]), entry)
            self.by_genus.setdefault(words[0], []).append(entry)
        trees = [e for e in entries if str(e.get("life_form", "")).startswith("tree")]
        self.median_crown = statistics.median(_crown(e) for e in trees)

    def match(self, name: str) -> list[dict[str, Any]]:
        words = _words(name)
        if not words:
            return []
        exact = self.by_name.get(" ".join(words[:2]))
        return [exact] if exact else self.by_genus.get(words[0], [])


def _words(name: str) -> list[str]:
    return re.sub(r"[«»\"'()/]", " ", name.lower().replace("ё", "е")).split()


def _crown(entry: dict[str, Any]) -> float:
    return float(entry.get("crown_mature_m") or entry.get("crown_diameter_m") or 0.0)


def designer_terms(
    street: Street, plan: dict[str, Any], catalog: Catalog, params: PlanParams
) -> tuple[dict[str, float], str]:
    """Слагаемые состава проекта при тех же целях участка, что у нашего плана."""
    density = street.measure.get("density", {})
    canopy = street.measure.get("canopy", {})
    target_trees = float(density.get("target_trees") or 0)
    target_shrubs = float(density.get("target_shrubs") or 0)
    trees = {k: int(v) for k, v in (plan["trees"].get("by_species") or {}).items()}
    shrubs = {k: int(v) for k, v in (plan["shrubs"].get("by_species") or {}).items()}
    tree_total = float(plan["trees"].get("total") or sum(trees.values()))
    shrub_total = float(plan["shrubs"].get("total") or sum(shrubs.values()))
    if not target_trees or not target_shrubs or not tree_total:
        return {}, "нет целей участка или состава деревьев"
    result = {
        "density": 0.5 * min(1.0, tree_total / target_trees)
        + 0.5 * min(1.0, shrub_total / target_shrubs)
    }
    richness = []
    for counts, goal in ((trees, target_trees), (shrubs, target_shrubs)):
        unit = max(1.0, params.diversity_species_share * goal)
        credit = sum(min(1.0, count / unit) for count in counts.values())
        richness.append(min(1.0, credit / params.diversity_target))
    result["diversity"] = 0.5 * richness[0] + 0.5 * richness[1]
    key = params.planting_category
    sums = []
    months: set[int] = set()
    crown_area = 0.0
    matched = total = 0
    for counts, goal, is_tree in ((trees, target_trees, True), (shrubs, target_shrubs, False)):
        value = 0.0
        for name, count in counts.items():
            entries = catalog.match(name)
            total += count
            if entries:
                matched += count
                marks = [
                    _CATEGORY.get(e.get("categories", {}).get(key, ""), CATEGORY_SILENT)
                    for e in entries
                ]
                value += count * statistics.fmean(marks)
                for entry in entries:
                    months.update(int(m) for m in entry.get("decor_months", []))
            else:
                value += count * CATEGORY_SILENT
            if is_tree:
                crown = (
                    statistics.median(_crown(e) for e in entries)
                    if entries
                    else (catalog.median_crown)
                )
                crown_area += count * math.pi * (crown / 2) ** 2
        sums.append(min(1.0, value / goal))
    result["category"] = 0.5 * sums[0] + 0.5 * sums[1]
    result["season"] = len(months) / 12
    goal_m2 = float(canopy.get("goal_m2") or 0)
    ours_m2, ours_sum = float(canopy.get("m2") or 0), float(canopy.get("sum_m2") or 0)
    if goal_m2 and ours_sum:
        overlap = ours_m2 / ours_sum
        result["canopy"] = min(1.0, overlap * crown_area / goal_m2)
    share = matched / total if total else 0.0
    return result, f"виды каталога у {share:.0%} посадок проекта"


# --- Подбор весов --------------------------------------------------------------------------


def _rows(streets: list[Street]) -> tuple[np.ndarray, list[str]]:
    """Строка на пару «проект - наш вариант»: разница слагаемых состава (проект - вариант)."""
    rows, owners = [], []
    for street in streets:
        for variant in street.variants:
            diff = np.zeros(len(KEYS))
            for k, key in enumerate(KEYS):
                if key in COMPOSITION and key in street.designer and key in variant:
                    diff[k] = street.designer[key] - variant[key]
            rows.append(diff)
            owners.append(street.slug)
    return np.array(rows).reshape(-1, len(KEYS)), owners


def solve(diffs: np.ndarray) -> tuple[np.ndarray, float]:
    """Два шага: минимум суммарного проигрыша, затем ближайшие к равным веса в коридоре."""
    n, m = len(KEYS), len(diffs)
    neutral = np.full(n, 1 / n)
    bounds_w = [(LOW / n, HIGH / n)] * n
    # Шаг 1: переменные [w, xi]; min sum xi; -diff @ w - xi <= 0; sum w = 1.
    c1 = np.r_[np.zeros(n), np.ones(m)]
    a_ub = np.c_[-diffs, -np.eye(m)] if m else None
    b_ub = np.zeros(m) if m else None
    a_eq = np.r_[np.ones(n), np.zeros(m)].reshape(1, -1)
    first = linprog(
        c1,
        A_ub=a_ub,
        b_ub=b_ub,
        A_eq=a_eq,
        b_eq=[1.0],
        bounds=bounds_w + [(0, None)] * m,
        method="highs",
    )
    if not first.success:
        raise RuntimeError(first.message)
    best = float(first.fun)
    # Шаг 2: при тех же проигрышах пар, что дал шаг 1, - веса, ближайшие к равным по квадрату
    # отклонения: вес, который данные не требуют сдвигать, делится поровну (L1 отдавал его
    # любому слагаемому произвольно). Невязки закреплены - в задаче только 10 весов.
    slack = first.x[n:]

    def objective(w: np.ndarray) -> float:
        return float(((w - neutral) ** 2).sum())

    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0, "jac": lambda _: np.ones(n)}]
    if m:
        constraints.append(
            {"type": "ineq", "fun": lambda w: diffs @ w + slack + 1e-9, "jac": lambda _: diffs}
        )
    second = minimize(
        objective,
        first.x[:n],
        jac=lambda w: 2 * (w - neutral),
        bounds=bounds_w,
        constraints=constraints,
        method="SLSQP",
        options={"maxiter": 1000, "ftol": 1e-12},
    )
    weights = second.x if second.success else first.x[:n]
    return weights, best


def total_loss(diffs: np.ndarray, weights: np.ndarray) -> float:
    return float(np.maximum(0.0, -(diffs @ weights)).sum())


# --- Отчёт ---------------------------------------------------------------------------------


def main() -> None:  # noqa: PLR0915 - отчёт идёт одним сценарием
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, default=ROOT / "out" / "street-runs")
    parser.add_argument(
        "--designer", type=Path, default=ROOT / "docs" / "data" / "designer-plans.yaml"
    )
    parser.add_argument("--catalog", type=Path, default=ROOT / "config" / "species.yaml")
    parser.add_argument("--json", type=Path, default=ROOT / "out" / "quality-calibration.json")
    parser.add_argument("--min-confidence", choices=("low", "medium", "high"), default="medium")
    args = parser.parse_args()

    params = PlanParams()
    catalog = Catalog(args.catalog)
    ours = load_runs(args.runs)
    plans = {
        p["slug"]: p for p in yaml.safe_load(args.designer.read_text(encoding="utf-8"))["streets"]
    }
    order = {"low": 0, "medium": 1, "high": 2}
    used: list[Street] = []
    skipped: list[tuple[str, str]] = []
    for slug, street in sorted(ours.items(), key=lambda kv: int(kv[0].split("-")[0])):
        plan = plans.get(slug)
        if plan is None or plan.get("stage") != "project":
            skipped.append((slug, "нет принятого проекта"))
            continue
        confidence = plan["trees"].get("confidence", "low")
        street.confidence = confidence
        if order.get(confidence, 0) < order[args.min_confidence]:
            skipped.append((slug, f"уверенность описи по деревьям: {confidence}"))
            continue
        terms, note = designer_terms(street, plan, catalog, params)
        if not terms:
            skipped.append((slug, note))
            continue
        street.designer, street.designer_note = terms, note
        used.append(street)
    diffs, owners = _rows(used)
    neutral = np.full(len(KEYS), 1 / len(KEYS))
    weights, best = solve(diffs)
    rng = np.random.default_rng(SEED)
    boot = []
    slugs = [s.slug for s in used]
    for _ in range(BOOTSTRAP):
        sample = rng.choice(len(used), size=len(used), replace=True)
        chosen = [used[i] for i in sample]
        sub, _ = _rows(chosen)
        boot.append(solve(sub)[0])
    boot_arr = np.array(boot)
    # Случайные веса вокруг найденных: где наш выбранный план не хуже проекта по составу.
    draws = rng.dirichlet(DIRICHLET_CONCENTRATION * weights, size=DIRICHLET)
    robust = {}
    for street in used:
        diff = np.array(
            [
                street.chosen.get(key, 0.0) - street.designer[key]
                if key in COMPOSITION and key in street.designer
                else 0.0
                for key in KEYS
            ]
        )
        robust[street.slug] = float(((draws @ diff) >= 0).mean())
    result = {
        "streets_used": slugs,
        "streets_skipped": skipped,
        "pairs": len(diffs),
        "weights": dict(zip(KEYS, np.round(weights, 4).tolist(), strict=True)),
        "neutral_loss": total_loss(diffs, neutral),
        "calibrated_loss": best,
        "bootstrap_p05": dict(
            zip(KEYS, np.round(np.percentile(boot_arr, 5, axis=0), 4).tolist(), strict=True)
        ),
        "bootstrap_p95": dict(
            zip(KEYS, np.round(np.percentile(boot_arr, 95, axis=0), 4).tolist(), strict=True)
        ),
        "ours_not_worse_share": robust,
        "designer_terms": {s.slug: s.designer for s in used},
        "ours_chosen": {
            s.slug: {k: s.chosen.get(k) for k in (*COMPOSITION, "canopy")} for s in used
        },
        "designer_notes": {s.slug: s.designer_note for s in used},
        "owners": owners,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        json.dumps(
            {k: result[k] for k in ("weights", "neutral_loss", "calibrated_loss", "pairs")},
            ensure_ascii=False,
            indent=1,
        )
    )
    for slug in slugs:
        street = next(s for s in used if s.slug == slug)
        row = " ".join(
            f"{k}: {street.designer.get(k, float('nan')):.2f}/{street.chosen.get(k, float('nan')):.2f}"
            for k in (*COMPOSITION, "canopy")
        )
        print(f"{slug[:28]:28} проект/наш {row} | не хуже: {robust[slug]:.0%}")
    for slug, why in skipped:
        print(f"пропущена {slug}: {why}")


if __name__ == "__main__":
    main()
