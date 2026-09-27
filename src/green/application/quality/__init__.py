"""Индекс качества плана: насколько план хорош, а не только допустим.

Устройство v3 (docs/plans/2026-09-26-index-v3-design.md, заметка 29):

- проверка перед оценкой: план с нарушением норм не оценивается, а чинится (заказчик назвал
  нарушение отступов причиной возврата номер один); без границы работ нет участка, и индекс
  не выставляется - слагаемые при этом всё равно считаются и показываются;
- индекс - взвешенная сумма слагаемых от 0 до 1 минус штраф за брошенные места; слагаемое,
  которое на участке не определено, выпадает, его вес делится между остальными;
- монотонность: посадка, прошедшая нормы, индекс не снижает - слагаемые меряются к целям
  участка (МГСН 1.02-02, табл. В.1, вместимость мест, прошедших нормы), а не средним по плану;
- ценность посадки - насколько упадёт индекс без неё, с разбивкой по слагаемым и
  человеческой причиной из уже посчитанного.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from green.application.params import DEFAULT_QUALITY_WEIGHTS
from green.application.quality.site import Site, site_of
from green.application.quality.terms import (
    Layout,
    TermResult,
    canopy,
    category,
    density,
    diversity,
    dust,
    fit,
    lost_places,
    margin,
    obligation,
    rows,
    season,
    targets_of,
    tiers,
    tightest,
)
from green.application.zones import CAPACITY_STAT, SITE_CAPACITY_STAT
from green.domain.planting import Verdict
from green.domain.quality import PlanQuality, PlantingValue, QualityTerm

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from green.application.params import PlanParams
    from green.domain.planting import Placement, Plan

# Заголовок и основание каждого слагаемого. Основание идёт в отчёт дословно: то, что не из
# акта, так и названо - параметром проекта.
TERMS: dict[str, tuple[str, str]] = {
    "density": (
        "Плотность",
        (
            "МГСН 1.02-02, прил. В, табл. В.1: 150 деревьев и 600 кустарников на 1 км улицы; "
            "деревьев - не больше вместимости мест, прошедших нормы (сноска: «при условии "
            "допустимости насаждений»)"
        ),
    ),
    "fit": (
        "Пригодность вида месту",
        (
            "оценка подбора по семи факторам с той же поправкой за условие посадки и слабый "
            "аллерген, что в подборе; заказчик: пригодность к условиям места первой строкой"
        ),
    ),
    "diversity": (
        "Разнообразие",
        (
            "заказчик: биоразнообразие; цель - 5 видов деревьев и 5 видов кустарников (медиана "
            "принятых проектов, заметка 34), вид засчитан полностью с 10% цели"
        ),
    ),
    "rows": (
        "Ряды: один вид и ровный шаг",
        "743-ПП, табл. 3.6.2: однорядная посадка деревьев 5-6 м, кустарников 0,3-1 м",
    ),
    "tiers": (
        "Ярусность",
        "МГСН 1.02-02, п. 4.2.9.2: под кронами ряды кустарника; заказчик: многоярусность",
    ),
    "category": (
        "Категория насаждений",
        "МГСН 1.02-02, прил. В, табл. В.6; вид, о котором таблица молчит, - половина балла",
    ),
    "canopy": (
        "Тень: площадь взрослых крон",
        (
            "заказчик: тень; цель - 75% крон целевого числа деревьев с кроной 8,5 м (медиана "
            "каталога; Kenney, van Wassenaer, Satel 2011)"
        ),
    ),
    "dust": (
        "Пылезащита: борта под кронами",
        "заказчик: пылезащита; газоустойчивость вида из каталога, цель - параметр проекта",
    ),
    "margin": (
        "Запас до норм",
        "СП 317.1325800.2017, п. 5.3.5.3: сети на плане 1:500 - до 0,5 м от натуры",
    ),
    "season": (
        "Сезонность",
        "декоративность по месяцам из каталога; в актах требования нет",
    ),
}

# Штраф вычитается из индекса: это не качество, которого бывает больше, а цена плана. Условие
# посадки и слабый аллерген штрафом не считаются: они снижают пригодность посадки так же, как
# в подборе, и посадка с ними всё равно добавляет, а не отнимает.
PENALTIES: dict[str, tuple[float, str]] = {
    "lost": (0.05, "места, допустимые по нормам, но оставшиеся без посадки"),
}
_EPS = 1e-12
# Вклад меньше половины сотой промилле индекса - ноль: такая посадка не сильна и не слаба.
WEAK_PERMILLE = 0.005
# Слабое место на карте - посадка, которая тянет индекс вниз больше чем на десятую долю
# средней доли одной посадки (индекс / число посадок). На плане из полутора тысяч посадок
# куст вида чуть ниже среднего по категории даёт -0,03 ‰: это не повод его двигать, и тысяча
# треугольников на карте прятала бы настоящие слабые места - дерево впритык к кабелю.
WEAK_SHARE = 0.1
_TOP_REASONS = 3


def assess(plan: Plan, site: Site, params: PlanParams) -> Plan:
    """План с индексом качества и ценностью каждой посадки."""
    quality = evaluate(plan, site, params)
    stats = dict(plan.stats)
    stats.pop("quality_index", None)
    if quality.index is not None:
        stats["quality_index"] = round(quality.index, 4)
    return replace(plan, quality=quality, stats=stats)


def evaluate(plan: Plan, site: Site, params: PlanParams, *, values: bool = True) -> PlanQuality:
    """Индекс плана; values=False - только индекс и слагаемые, без ценности каждой посадки
    (сдвиг слабых мест сравнивает сотни пробных планов, ему нужен только индекс)."""
    layout = Layout.of(plan.placements)
    targets = targets_of(site, params, capacity_of(plan))
    results: dict[str, TermResult] = {
        "density": density(layout, site, targets),
        "fit": fit(layout, params, targets),
        "diversity": diversity(layout, params, targets),
        "rows": rows(layout, params, targets, exact=values),
        "tiers": tiers(layout, site, targets),
        "category": category(layout, params, targets),
        "canopy": canopy(layout, site, params, targets, exact=values),
        "dust": dust(layout, site, params),
        "margin": margin(layout, params, targets),
        "season": season(layout),
    }
    weights = {**DEFAULT_QUALITY_WEIGHTS, **params.quality_weights}
    defined = [k for k, r in results.items() if r.score is not None and weights.get(k, 0) > 0]
    total = sum(weights[k] for k in defined)
    share = {k: weights[k] / total for k in defined} if total else {}
    raw = sum(share[k] * (results[k].score or 0.0) for k in defined)

    penalties, penalty_deltas, penalty_flags = _penalties(plan, layout)
    penalty = sum(penalties.values())
    gate = _gate(plan, site)
    index = None if gate else min(1.0, max(0.0, raw - penalty))

    terms = tuple(
        QualityTerm(
            key=key,
            title=TERMS[key][0],
            weight=round(share.get(key, 0.0), 4),
            score=None if result.score is None else round(result.score, 4),
            basis=TERMS[key][1],
            note=result.note,
            measure=result.measure,
        )
        for key, result in results.items()
    )
    worth = (
        _values(
            plan,
            results,
            share,
            penalty_deltas,
            penalty_flags,
            unclipped=raw - penalty,
            threshold=weak_threshold(index, len(plan.placements)),
        )
        if index is not None and values
        else {}
    )
    summary = _summary(index, gate, terms, penalties, worth)
    return PlanQuality(
        index=None if index is None else round(index, 6),
        gate=gate,
        terms=terms,
        penalty=round(penalty, 4),
        penalties={k: round(v, 4) for k, v in penalties.items()},
        summary=summary,
        values=worth,
    )


def weak_threshold(index: float | None, count: int) -> float:
    """Вклад, ниже которого посадка - слабое место: большее из WEAK_PERMILLE и доли WEAK_SHARE."""
    floor = WEAK_PERMILLE / 1000
    if not count or index is None:
        return floor
    return max(floor, WEAK_SHARE * index / count)


def capacity_of(plan: Plan) -> float | None:
    """Вместимость участка в деревьях: общая по вариантам портфеля, иначе своя у плана.

    Размещение считает, сколько деревьев встаёт с шагом 5 м на все проверенные места
    (stats["capacity_trees"]); портфель ставит всем вариантам наибольшую из них
    (stats["site_capacity_trees"]), чтобы цель плотности была общей для сравнения.
    """
    value = plan.stats.get(SITE_CAPACITY_STAT, plan.stats.get(CAPACITY_STAT))
    return float(value) if value is not None else None


def _gate(plan: Plan, site: Site) -> str:
    # Нарушение - только жёсткая норма. Посадка «на согласование» не выполняет мягкую норму:
    # это условие, а не нарушение, и оно уходит в запас до норм нулём.
    violating = sum(1 for p in plan.placements if p.verdict is Verdict.FORBIDDEN)
    if violating:
        return (
            f"Посадок с нарушением норм: {violating}. План не оценивается, пока нарушения не "
            "исправлены: заказчик называет их первой причиной возврата проектов."
        )
    if site.boundary is None:
        return (
            "Граница работ в чертеже не найдена: участок не определён, поэтому индекс не "
            "выставляется. Слагаемые ниже посчитаны по всему чертежу."
        )
    return ""


def _penalties(
    plan: Plan, layout: Layout
) -> tuple[dict[str, float], NDArray[np.float64], list[list[str]]]:
    """Штраф за брошенные места и что каждая посадка в нём меняет (P - P без посадки).

    Отметки посадки (условие, аллерген, ближе нормы на согласовании) идут в «слабее всего» её
    объяснения: индекс их уже учёл в пригодности и запасе.
    """
    n = layout.size
    lost = lost_places(plan.rejections)
    penalties: dict[str, float] = {}
    deltas = np.zeros(n)
    lost_weight = PENALTIES["lost"][0]
    penalties["lost"] = lost_weight * lost / (n + lost) if n + lost else 0.0
    if n and lost:
        deltas += penalties["lost"] - lost_weight * lost / (n - 1 + lost)
    return penalties, deltas, [_marks(p) for p in plan.placements]


def _marks(placement: Placement) -> list[str]:
    marks = obligation(placement)
    tight = tightest(placement)
    if tight is not None and tight[0] < 0:
        marks.append(f"ближе нормы, на согласовании: {tight[1]}")
    return marks


def _values(  # noqa: PLR0913 - term and penalty decomposition of the counterfactual
    plan: Plan,
    results: dict[str, TermResult],
    share: dict[str, float],
    penalty_deltas: NDArray[np.float64],
    penalty_flags: list[list[str]],
    *,
    unclipped: float,
    threshold: float,
) -> dict[str, PlantingValue]:
    n = len(plan.placements)
    if not n:
        return {}
    # A disappearing term loses its weight; the remaining terms are normalised
    # exactly as in evaluate(). No N full geometric evaluations are necessary.
    remaining = {}
    for key, weight in share.items():
        undefined = results[key].undefined_without
        remaining[key] = (
            np.where(undefined, 0.0, weight) if undefined is not None else np.full(n, weight)
        )
    totals = sum(remaining.values(), np.zeros(n))
    by_term = {}
    for key, weights in remaining.items():
        after_weight = np.divide(weights, totals, out=np.zeros(n), where=totals > 0)
        score = results[key].score or 0.0
        by_term[key] = share[key] * score - after_weight * (score - results[key].deltas)
    raw_delta = sum(by_term.values(), np.zeros(n)) - penalty_deltas
    delta = np.clip(unclipped, 0.0, 1.0) - np.clip(unclipped - raw_delta, 0.0, 1.0)
    # Keep the decomposition additive when either index reaches its 0..1 bound.
    by_term["index_bounds"] = delta - raw_delta
    ranks = np.argsort(np.argsort(delta, kind="stable"), kind="stable")
    values: dict[str, PlantingValue] = {}
    for i, placement in enumerate(plan.placements):
        parts = {key: float(contribution[i]) for key, contribution in by_term.items()}
        if penalty_deltas[i]:
            parts["penalties"] = -float(penalty_deltas[i])
        reasons, weak = _reasons(i, parts, results, penalty_flags[i])
        values[placement.placement_id] = PlantingValue(
            placement_id=placement.placement_id,
            delta=round(float(delta[i]), 6),
            by_term={key: round(value, 6) for key, value in parts.items() if abs(value) > _EPS},
            reasons=reasons,
            weak=weak,
            percentile=round(float(ranks[i]) / max(n - 1, 1), 4),
            flagged=bool(delta[i] <= -threshold),
        )
    return values


def _reasons(
    i: int, parts: dict[str, float], results: dict[str, TermResult], flags: list[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Чем посадка ценна и что в ней слабо: слагаемые с наибольшим вкладом в обе стороны."""
    positive = sorted(
        (key for key, value in parts.items() if value > _EPS and key in results),
        key=lambda key: -parts[key],
    )
    negative = sorted(
        (key for key, value in parts.items() if value < -_EPS and key in results),
        key=lambda key: parts[key],
    )
    reasons = [results[key].details[i] for key in positive if results[key].details[i]]
    weak = [results[key].details[i] for key in negative if results[key].details[i]]
    return tuple(reasons[:_TOP_REASONS]), (*weak[:2], *flags)


def _num(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _summary(
    index: float | None,
    gate: str,
    terms: tuple[QualityTerm, ...],
    penalties: dict[str, float],
    values: dict[str, PlantingValue],
) -> tuple[str, ...]:
    """Сводка плана словами: оценка, что поднимет индекс сильнее всего, штрафы, слабые места.

    Сильные и слабые слагаемые не пересказываются: каждое стоит рядом со своей оценкой.
    """
    lines = [gate] if gate else [f"Индекс качества плана {_num(index or 0.0)} из 1."]
    scored = [t for t in terms if t.score is not None and t.weight > 0]
    if scored:
        gains = sorted(scored, key=lambda t: -t.weight * (1 - (t.score or 0.0)))[:2]
        lines.append(
            "Резерв при максимальной оценке отдельного показателя: "
            + "; ".join(
                f"{t.title.lower()} - до +{_num(t.weight * (1 - (t.score or 0.0)))}" for t in gains
            )
            + ". Совместная достижимость этих прибавок не проверена."
        )
    missing = [t for t in terms if t.score is None]
    if missing:
        lines.append(
            "Не определено: " + "; ".join(f"{t.title.lower()} ({t.note})" for t in missing) + "."
        )
    penalty = sum(penalties.values())
    if penalty > _EPS:
        shares = _thousandths(penalties, penalty)
        named = [
            f"{PENALTIES[key][1]} -{_num(share / 1000, 3)}"
            for key, share in shares.items()
            if share > 0  # «-0,000» ничего не говорит
        ]
        lines.append(f"Штрафы -{_num(penalty, 3)}: " + "; ".join(named) + ".")
    harmful = sum(1 for v in values.values() if v.delta < -_EPS)
    if harmful:
        lines.append(
            f"Посадок с отрицательным вкладом: {harmful}. Удаление каждой по отдельности "
            "повышает расчётный индекс; это не разрешение на удаление. Нужно заново "
            "проверить квоты и остальные ограничения. Эффекты удалений не складываются."
        )
    weak = sum(1 for v in values.values() if v.flagged)
    if weak:
        lines.append(f"Слабых мест: {weak}, на карте - треугольник.")
    return tuple(lines)


def _thousandths(parts: dict[str, float], total: float) -> dict[str, int]:
    """Части в тысячных, которые складываются в округлённый итог (метод наибольших остатков).

    Каждая часть, округлённая сама по себе, в сумме расходится с итогом: -0,006 при видимых
    -0,002, -0,002 и -0,001 читается как ошибка счёта.
    """
    scaled = {key: value * 1000 for key, value in parts.items()}
    shares = {key: int(value) for key, value in scaled.items()}
    missing = round(total * 1000) - sum(shares.values())
    for key in sorted(scaled, key=lambda k: shares[k] - scaled[k])[: max(missing, 0)]:
        shares[key] += 1
    return shares


__all__ = [
    "PENALTIES",
    "TERMS",
    "WEAK_PERMILLE",
    "WEAK_SHARE",
    "Site",
    "assess",
    "capacity_of",
    "evaluate",
    "site_of",
    "weak_threshold",
]
