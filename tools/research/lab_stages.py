"""Экспериментальные этапы пайплайна для стенда (прототипы: победители переезжают в src).

Каждый этап - функция (lab, plan) -> plan, как этапы базового пайплайна в pipeline_lab.
Нормы проверяются тем же ConstraintIndex и теми же правилами, что в сервисе: этап может
поставить посадку только туда, куда её поставил бы сервис.
"""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, Any

import numpy as np
import shapely

from green.application.assortment.context import site_context
from green.application.assortment.scoring import percent, score_species
from green.application.constraints import ConstraintIndex
from green.application.params import active_distance_rules
from green.application.placement import (
    _SPACING_TOLERANCE,
    MODE_LAWN,
    _Candidate,
    _Grid,
    _Selector,
    curb_lines,
)
from green.application.shrub_rows import Blockers as _Blockers
from green.application.shrub_rows import _hedge_species, _plant, _runs
from green.application.shrub_rows import ranked_species as _ranked
from green.application.surfaces import Material
from green.domain.norms import PlantingType
from green.domain.planting import SHRUB_FORMS, AssortmentInfo, Placement, Reason, Verdict

if TYPE_CHECKING:
    from pipeline_lab import Lab

    from green.domain.planting import Plan

ALLEY_LABEL = "аллея вдоль борта"
CURB_HEDGE_LABEL = "живая изгородь вдоль борта"
UNDER_LABEL = "кустарник под кроной дерева"


def named(fn: Any, name: str) -> Any:
    fn.__name__ = name
    return fn


def renumber(plan: Plan) -> Plan:
    return replace(
        plan, placements=tuple(replace(p, number=i) for i, p in enumerate(plan.placements, 1))
    )


def _accepted(params: Any) -> set[Verdict]:
    ok = {Verdict.ALLOWED}
    if params.allow_needs_approval:
        ok.add(Verdict.NEEDS_APPROVAL)
    return ok


# --- Больше деревьев: добор зоны мелкой сеткой -------------------------------------------


def gap_fill(lab: Lab, plan: Plan | None, *, step_m: float = 1.0, order: str = "scan") -> Plan:
    """После аллеи и сетки газона - добор мест, которые крупная сетка 6 м пропустила.

    Кандидаты - центры ячеек грунта с шагом step_m; каждый проверяется всеми нормами дерева и
    принимается, если до всех уже поставленных деревьев не меньше шага посадки. Порядок обхода:
    scan - построчно (плотная упаковка), slack - сначала места с большим запасом до сетей.
    """
    assert plan is not None
    params, surface = lab.params, lab.surface
    if surface is None:
        return plan
    rules = active_distance_rules(lab.rulebook, params, lab.species.name_lat, None, frozenset())
    index = ConstraintIndex(lab.features, rules, require_utility_data=params.require_utility_data)
    index.surface = surface
    stride = max(1, round(step_m / surface.cell))
    soil = surface.grid[::stride, ::stride] == Material.SOIL
    rows, cols = np.nonzero(soil)
    xy = np.column_stack(
        [
            surface.origin[0] + (cols * stride + 0.5) * surface.cell,
            surface.origin[1] + (rows * stride + 0.5) * surface.cell,
        ]
    )
    points = shapely.points(xy)
    keep = np.flatnonzero(index.plantable(points))
    if not len(keep):
        return plan
    xy, points = xy[keep], points[keep]
    batch = index.evaluate(points)
    order_ids = np.arange(len(xy))
    if order == "slack":
        slack = np.where(np.isfinite(batch.slack()), batch.slack(), 9.0)
        order_ids = np.argsort(-np.minimum(slack, 2.0), kind="stable")
    selector = _Selector(species=lab.species, params=params)
    gap = params.spacing_m * _SPACING_TOLERANCE
    planted = _Grid(gap)
    for p in plan.placements:
        if p.planting_type is PlantingType.TREE:
            planted.add(p.x, p.y)
    added: list[Placement] = []
    ranks = [(Verdict.ALLOWED, False), (Verdict.ALLOWED, True)]
    if params.allow_needs_approval:
        ranks += [(Verdict.NEEDS_APPROVAL, False), (Verdict.NEEDS_APPROVAL, True)]
    for verdict, barrier in ranks:
        for row in order_ids.tolist():
            if batch.verdict(row) is not verdict or batch.needs_barrier(row) is not barrier:
                continue
            x, y = float(xy[row, 0]), float(xy[row, 1])
            if planted.near(x, y):
                continue
            planted.add(x, y)
            candidate = _Candidate(3_000_000 + row, MODE_LAWN, x, y)
            added.append(selector._placement(candidate, batch, row))  # noqa: SLF001
    lab.notes.append(f"gap_fill({order}, {step_m} м): +{len(added)} деревьев")
    stats = dict(plan.stats)
    stats["gap_fill_added"] = len(added)
    return renumber(replace(plan, placements=(*plan.placements, *added), stats=stats))


# --- Изгородь вдоль всех бортов -------------------------------------------------------------


def _shrub_index(lab: Lab, shrub_params: Any) -> ConstraintIndex:
    index = ConstraintIndex(
        lab.features,
        active_distance_rules(lab.rulebook, shrub_params),
        require_utility_data=shrub_params.require_utility_data,
    )
    index.surface = lab.surface
    return index


def _rename(placements: list[Placement], prefix: str, label: str) -> list[Placement]:
    out = []
    for p in placements:
        info = p.assortment
        if info is not None:
            info = replace(info, structure_id=f"{prefix}-{info.structure_id}")
        out.append(
            replace(
                p,
                placement_id=f"{prefix}{p.placement_id}",
                assortment=info,
                notes=(label, *p.notes[1:]),
            )
        )
    return out


class _NearShrubs:
    """Дополнительная проверка: не ближе gap к уже посаженным в этом этапе кустам."""

    def __init__(self, base: _Blockers, extra: list[tuple[float, float]], gap: float) -> None:
        self._base = base
        self._tree = shapely.STRtree(shapely.points(extra)) if extra else None
        self._gap = gap

    def clear(self, points: Any) -> Any:
        ok = self._base.clear(points)
        if self._tree is not None and len(points):
            hits = self._tree.query(points, predicate="dwithin", distance=self._gap)
            ok[np.unique(hits[0])] = False
        return ok


def curb_hedges(
    lab: Lab,
    plan: Plan | None,
    *,
    offsets: tuple[float, ...] = (1.3, 1.0),
    spacing_m: float | None = None,
    max_share: float | None = None,
) -> Plan:
    """Живая изгородь вдоль всех бортов, где у борта грунт: не только под кронами аллеи.

    Ось - линия на заданном отступе от ближайшего борта (граница буфера всех бортов): так
    пунктирный борт из сотен кусков даёт сплошную ось, и точка оси не ближе отступа ни к
    одному борту. Дальше всё как у ряда под аллеей: грунт, нормы кустарника, стволы и люки,
    отступ 5 м от разрыва газона, куски короче 3 м не сажаются, вид - солестойкий.
    max_share - доля бортов, которую разрешено закрыть (None - без ограничения).
    """
    assert plan is not None
    params = lab.params
    shrub_params = replace(
        params,
        planting_type=PlantingType.SHRUB,
        shrub_row_spacing_m=spacing_m or params.shrub_row_spacing_m,
    )
    species = _hedge_species(lab.catalog)
    lines = curb_lines(lab.features)
    if not lines or not species:
        return plan
    curbs = shapely.union_all(lines)
    index = _shrub_index(lab, shrub_params)
    base = _Blockers(plan, lab.features, shrub_params)
    planted_xy: list[tuple[float, float]] = []
    segments = []
    for offset in offsets:
        ring = shapely.boundary(shapely.buffer(curbs, offset, quad_segs=4))
        blockers = _NearShrubs(base, planted_xy, max(0.8, shrub_params.shrub_row_spacing_m))
        found = []
        for part in shapely.get_parts(ring):
            if part.length < params.shrub_row_min_length_m:
                continue
            axis = shapely.LineString(shapely.get_coordinates(part))
            found += _runs(axis, offset, index=index, blockers=blockers, params=shrub_params)
        for segment in found:
            planted_xy += [tuple(xy) for xy in segment.points.tolist()]
        segments += found
    if max_share is not None and lab.site.curb_points is not None:
        budget = max_share * len(lab.site.curb_points)
        segments.sort(key=lambda s: -s.length_m)
        kept, total = [], 0.0
        for s in segments:
            if total + s.length_m > budget:
                continue
            kept.append(s)
            total += s.length_m
        segments = kept
    if not segments:
        return plan
    planted, skipped = _plant(segments, species, plan, lab.rulebook, shrub_params)
    planted = _rename(planted, "C", CURB_HEDGE_LABEL)
    length = sum(s.length_m for s in segments)
    lab.notes.append(
        f"curb_hedges: {len(segments)} участков, {length:.0f} м, {len(planted)} кустов, "
        f"без вида {skipped}"
    )
    return renumber(replace(plan, placements=(*plan.placements, *planted)))


# --- Кустарник под кроной ------------------------------------------------------------------


def _under_species(catalog: Any) -> list[Any]:
    """Под кроной: теневыносливый или полутеневой, без колючек, яда и массовых аллергенов."""
    return sorted(
        (
            s
            for s in catalog
            if s.life_form in SHRUB_FORMS
            and s.light in {"shade", "semi"}
            and not s.thorny
            and not s.toxic
            and s.allergen < 2  # noqa: PLR2004
            and s.categories.get("streets") != "minus"
        ),
        key=lambda s: s.code,
    )


def understory(
    lab: Lab,
    plan: Plan | None,
    *,
    size: int = 3,
    radii: tuple[float, ...] = (1.5, 2.0, 2.5),
    which: str = "alley",
) -> Plan:
    """Группа кустарников под кроной дерева, у которого нижнего яруса нет.

    Точки - на кольцах 1,5-2,5 м от ствола (не ближе 1,25 м: ком дерева и траншея), грунт,
    все нормы кустарника, люки, не ближе 0,8 м друг к другу и к другим кустам. Вид - один на
    группу, теневыносливый (под кроной тень).
    """
    assert plan is not None
    params = lab.params
    shrub_params = replace(params, planting_type=PlantingType.SHRUB)
    trees = [
        p
        for p in plan.placements
        if p.planting_type is PlantingType.TREE and (which == "all" or ALLEY_LABEL in p.notes)
    ]
    shrubs = [p for p in plan.placements if p.planting_type is PlantingType.SHRUB]
    species = _under_species(lab.catalog)
    if not trees or not species:
        return plan
    index = _shrub_index(lab, shrub_params)
    base = _Blockers(plan, lab.features, shrub_params)
    shrub_tree = shapely.STRtree(shapely.points([(p.x, p.y) for p in shrubs])) if shrubs else None
    angles = np.linspace(0, 2 * np.pi, 12, endpoint=False)
    accepted = _accepted(params)
    added: list[Placement] = []
    new_xy: list[tuple[float, float]] = []
    number = len(plan.placements)
    for tree in trees:
        crown = max(tree.species.crown_mature_m or tree.species.crown_diameter_m, 0.0) / 2
        if shrub_tree is not None and len(
            shrub_tree.query(shapely.Point(tree.x, tree.y), predicate="dwithin", distance=crown)
        ):
            continue
        ring = [r for r in radii if r < crown]
        if not ring:
            continue
        xy = np.array(
            [(tree.x + r * np.cos(a), tree.y + r * np.sin(a)) for r in ring for a in angles]
        )
        points = shapely.points(xy)
        ok = index.plantable(points) & base.clear(points)
        if not ok.any():
            continue
        batch = index.evaluate(points)
        chosen: list[int] = []
        for k in np.flatnonzero(ok).tolist():
            if batch.verdict(k) not in accepted:
                continue
            x, y = xy[k]
            near = [*new_xy, *((xy[c][0], xy[c][1]) for c in chosen)]
            if any(np.hypot(x - a, y - b) < 0.8 for a, b in near):  # noqa: PLR2004
                continue
            chosen.append(k)
            if len(chosen) == size:
                break
        if not chosen:
            continue
        structure = f"under-{tree.placement_id}"
        drafts = [
            Placement(
                placement_id=f"U{tree.placement_id}-{i}",
                number=0,
                planting_type=PlantingType.SHRUB,
                species=species[0],
                x=float(xy[k][0]),
                y=float(xy[k][1]),
                verdict=batch.verdict(k),
                checks=batch.checks(k),
                notes=(UNDER_LABEL,),
            )
            for i, k in enumerate(chosen)
        ]
        contexts = [site_context(d, structure, "group") for d in drafts]
        ranked = _ranked(species, contexts, lab.rulebook, shrub_params)
        if not ranked:
            continue
        # Соседние деревья - разные виды подлеска: иначе вся улица одного куста.
        pick = ranked[len(added) // max(size, 1) % min(len(ranked), 3)]
        kind, verdicts, _ = pick
        reason = Reason(
            "reference",
            "второй ярус под кроной дерева: МГСН 1.02-02, п. 4.2.9.2",
            source="МГСН 1.02-02, п. 4.2.9.2",
        )
        for draft, verdict, ctx in zip(drafts, verdicts, contexts, strict=True):
            number += 1
            detail = score_species(kind, ctx, shrub_params)
            added.append(
                replace(
                    draft,
                    number=number,
                    species=kind,
                    assortment=AssortmentInfo(
                        status="assigned",
                        percent=percent(detail),
                        factors=detail.factors,
                        structure_id=structure,
                        structure_kind="group",
                        reasons=(*verdict.reasons, reason),
                    ),
                )
            )
            new_xy.append((draft.x, draft.y))
    lab.notes.append(f"understory({which}): +{len(added)} кустов")
    return renumber(replace(plan, placements=(*plan.placements, *added)))


# --- Удаление посадок, которые тянут индекс вниз ---------------------------------------------


def prune(lab: Lab, plan: Plan | None, *, kind: str = "any", rounds: int = 3) -> Plan:
    """Убрать посадки с отрицательным вкладом, пока индекс растёт (для сравнения)."""
    assert plan is not None
    current = lab.assess(plan)
    removed = 0
    for _ in range(rounds):
        quality = current.quality
        if quality is None or quality.index is None:
            break
        bad = [
            p
            for p in current.placements
            if quality.values[p.placement_id].delta < -1e-6
            and (kind == "any" or p.planting_type.value == kind)
        ]
        if not bad:
            break
        drop = {p.placement_id for p in bad}
        trial = lab.assess(
            replace(current, placements=tuple(p for p in current.placements if p.placement_id not in drop))
        )
        if trial.quality is None or trial.quality.index is None:
            break
        if trial.quality.index <= quality.index:
            break
        removed += len(drop)
        current = trial
    lab.notes.append(f"prune({kind}): -{removed}")
    return current


def stage(fn: Any, name: str, **kwargs: Any) -> Any:
    return named(partial(fn, **kwargs), name)


# --- Подвигать посадки, пока растёт индекс (не только слабые) ---------------------------------


def hill_climb(
    lab: Lab,
    plan: Plan | None,
    *,
    kind: str = "tree",
    tries: int = 120,
    steps: tuple[float, ...] = (0.5, 1.0, 1.5),
    directions: int = 8,
) -> Plan:
    """Каждую посадку (самые слабые первыми) пробуем сдвинуть на 0,5-1,5 м по 8 направлениям.

    Точка должна пройти всё то же, что при сдвиге слабых мест (refine._Mover): грунт, нормы с
    вердиктом не хуже, шаг до соседей, вид заново проходит подбор. Из допустимых точек берётся
    та, что даёт самый высокий индекс плана целиком; сдвиг остаётся, если индекс вырос.
    """
    import math  # noqa: PLC0415

    from green.application.constraints import VERDICT_ORDER  # noqa: PLC0415
    from green.application.quality import evaluate  # noqa: PLC0415
    from green.application.refine import _Mover, _rules_of  # noqa: PLC0415

    assert plan is not None
    current = lab.assess(plan)
    quality = current.quality
    if quality is None or quality.index is None:
        return current
    base = ConstraintIndex(lab.features, (), require_utility_data=lab.params.require_utility_data)
    base.surface = lab.surface
    mover = _Mover(current.placements, base, lab.rulebook, lab.params)
    angles = [2 * math.pi * k / directions for k in range(directions)]
    offsets = np.array([(s * math.cos(a), s * math.sin(a)) for s in steps for a in angles])
    order = sorted(
        (
            p
            for p in current.placements
            if (kind == "any" or p.planting_type.value == kind)
            and (p.assortment is None or p.assortment.structure_kind != "row")
        ),
        key=lambda p: quality.values[p.placement_id].delta,
    )
    index = quality.index
    moved = 0
    for placement in order[:tries]:
        rules = _rules_of(placement, lab.rulebook)
        if rules is None:
            continue
        checker = base.with_rules(rules)
        points = shapely.points(np.array([placement.x, placement.y]) + offsets)
        batch = checker.evaluate(points)
        plantable = checker.plantable(points)
        limit = VERDICT_ORDER.index(placement.verdict)
        i = mover._position[placement.placement_id]  # noqa: SLF001
        best: tuple[float, Any] | None = None
        slack = batch.slack()
        for k in range(len(points)):
            verdict = batch.verdict(k)
            if not plantable[k] or verdict in {Verdict.FORBIDDEN, Verdict.UNKNOWN}:
                continue
            if VERDICT_ORDER.index(verdict) > limit:
                continue
            x, y = float(offsets[k][0] + placement.x), float(offsets[k][1] + placement.y)
            if not mover._spaced(i, x, y):  # noqa: SLF001
                continue
            option = mover._rebuilt(  # noqa: SLF001
                mover.placements[i], batch, k, point=(x, y), margins=(0.0, float(slack[k]))
            )
            if option is None:
                continue
            trial = mover.plan_with(current, option)
            score = evaluate(trial, lab.site, lab.ruler).index
            if score is not None and score > index + 1e-9 and (best is None or score > best[0]):
                best = (score, option)
        if best is not None:
            mover.commit(best[1])
            current = mover.plan_with(current, best[1])
            index = best[0]
            moved += 1
    lab.notes.append(f"hill_climb({kind}): сдвинуто {moved} из {min(tries, len(order))}")
    return lab.assess(current)


# --- Кустарник там, где дереву нельзя: группы до нижней границы В.1 ----------------------------


def shrub_fill(
    lab: Lab,
    plan: Plan | None,
    *,
    tree_gap_m: float = 3.0,
    shrub_gap_m: float = 2.0,
    center_step_m: float = 4.0,
    target: str = "low",
) -> Plan:
    """Группы кустарника на грунте, где кустарник допустим, пока кустов меньше 600 на 1 км.

    Кустарнику нормы мягче, чем дереву (до кабеля 0,7 м против 2,0 м, до борта 1,0 против 2,0),
    поэтому у сетей остаётся полоса, где дереву нельзя, а кустарнику можно. МГСН 1.02-02, табл.
    В.1 ждёт на улице 600-720 кустарников на 1 км. Центры групп - ячейки грунта через 1 м, не
    ближе tree_gap_m к стволам и shrub_gap_m к уже посаженным кустам, между центрами не меньше
    center_step_m; группа - тот же квадрат 3 x 3 с шагом 1 м и тот же подбор видов, что у групп
    на пустых местах дерева.
    """
    import math  # noqa: PLC0415

    from green.application.assortment import assign_species  # noqa: PLC0415
    from green.application.quality.site import street_length  # noqa: PLC0415

    assert plan is not None
    params, surface = lab.params, lab.surface
    boundary = lab.site.boundary
    if surface is None or boundary is None:
        return plan
    km = street_length(boundary) / 1000
    shrubs_now = sum(1 for p in plan.placements if p.planting_type is PlantingType.SHRUB)
    low, high = params.density_shrubs_per_km
    goal = (low if target == "low" else high) * km
    budget = goal - shrubs_now
    if budget <= 0:
        lab.notes.append(f"shrub_fill: кустов уже {shrubs_now}, цель {goal:.0f}")
        return plan
    shrubs_catalog = sorted((s for s in lab.catalog if s.life_form in SHRUB_FORMS), key=lambda s: s.code)
    shrub_params = replace(
        params,
        planting_type=PlantingType.SHRUB,
        spacing_m=params.shrub_group_spacing_m,
        structure_patch_size=params.shrub_group_size**2,
        quota_species=params.shrub_quota_species,
        quota_genus=params.shrub_quota_genus,
        quota_family=params.shrub_quota_family,
        conifer_share=params.shrub_conifer_share,
    )
    index = _shrub_index(lab, shrub_params)
    stride = max(1, round(1.0 / surface.cell))
    rows, cols = np.nonzero(surface.grid[::stride, ::stride] == Material.SOIL)
    xy = np.column_stack(
        [
            surface.origin[0] + (cols * stride + 0.5) * surface.cell,
            surface.origin[1] + (rows * stride + 0.5) * surface.cell,
        ]
    )
    points = shapely.points(xy)
    keep = index.plantable(points)
    trees = [(p.x, p.y) for p in plan.placements if p.planting_type is PlantingType.TREE]
    shrubs = [(p.x, p.y) for p in plan.placements if p.planting_type is PlantingType.SHRUB]
    for coords, gap in ((trees, tree_gap_m), (shrubs, shrub_gap_m)):
        if coords and keep.any():
            tree = shapely.STRtree(shapely.points(coords))
            hits = tree.query(points, predicate="dwithin", distance=gap)
            keep[np.unique(hits[0])] = False
    candidates = np.flatnonzero(keep)
    if not len(candidates):
        return plan
    batch = index.evaluate(points[candidates])
    ok = [k for k in range(len(candidates)) if batch.verdict(k) is Verdict.ALLOWED]
    size = params.shrub_group_size**2
    groups_needed = math.ceil(budget / size)
    taken = _Grid(center_step_m)
    centers: list[tuple[float, float]] = []
    for k in ok:
        x, y = float(xy[candidates[k], 0]), float(xy[candidates[k], 1])
        if taken.near(x, y):
            continue
        taken.add(x, y)
        centers.append((x, y))
        if len(centers) >= groups_needed:
            break
    if not centers:
        return plan
    strategy = lab.container.use_case._strategy  # noqa: SLF001
    group_points = strategy.shrub_groups(
        lab.features, lab.labels, lab.rulebook, shrubs_catalog[0], shrub_params, centers=centers
    )
    # Точки группы не должны лезть к стволам ближе 1,25 м и к уже стоящим кустам ближе 0,5 м.
    near_tree = shapely.STRtree(shapely.points(trees)) if trees else None
    near_shrub = shapely.STRtree(shapely.points(shrubs)) if shrubs else None
    clean = []
    for p in group_points:
        pt = shapely.Point(p.x, p.y)
        if near_tree is not None and len(near_tree.query(pt, predicate="dwithin", distance=1.25)):
            continue
        if near_shrub is not None and len(near_shrub.query(pt, predicate="dwithin", distance=0.5)):
            continue
        clean.append(replace(p, placement_id=f"F{p.placement_id}"))
    from green.domain.planting import Plan as PlanType  # noqa: PLC0415

    assigned = assign_species(
        PlanType(placements=tuple(clean), rejections=()), lab.rulebook, lab.catalog, shrub_params, None
    )
    added = list(assigned.placements)
    lab.notes.append(
        f"shrub_fill: +{len(added)} кустов в {len(centers)} группах (было {shrubs_now}, цель {goal:.0f})"
    )
    return renumber(replace(plan, placements=(*plan.placements, *added)))
