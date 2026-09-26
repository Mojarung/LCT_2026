"""Газоны плана: травянистое покрытие на грунте, который посадки оставили свободным.

П. 3 ТЗ требует рекомендовать не только деревья и кустарники, но и травянистые покрытия. Газон
плана - грунт карты покрытий (`SurfaceMap.soil_area`) в границе работ без посадочных мест
деревьев и кустарников итогового плана и без существующих массивов. Где газон по чертежу уже
есть (контур слоя газона, знак газона, подпись «ГАЗОН»), участок сохраняемый или
восстанавливаемый, на остальном грунте - устраиваемый. Цветник по чертежу газоном не
становится. Каждый участок объясняется только правилами `lawn_rules` свода норм: для вида
газона без своего правила участки не выделяются.

Грунт, выведенный по близости подписи (совмещённый режим карты покрытий), есть только в растре:
газоном он не становится, пока контур не замкнут, и предупреждение называет его площадь.
Сохраняется газон или восстанавливается после посадки, сервис не различает: объём работ на
участке определяет проектировщик.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
import shapely
from shapely import STRtree
from shapely.geometry import Point

from green.application.approximation import inner_area, reserved_buffer
from green.application.constraints import work_boundary
from green.application.surfaces import Material, label_material
from green.domain.norms import LawnKind, PlantingType
from green.domain.objects import ObjectClass
from green.domain.planting import Lawn

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from shapely.geometry.base import BaseGeometry

    from green.application.params import PlanParams
    from green.application.surfaces import SurfaceMap
    from green.domain.norms import RuleBook
    from green.domain.objects import Feature, TextLabel
    from green.domain.planting import Placement, Plan

LAWN_PREFIX = "L"
# Все предупреждения этапа начинаются так: правка плана пересчитывает газоны, и предупреждения
# прошлого расчёта снимаются по этому началу, а не копятся.
WARNING_PREFIX = "Газоны: "
_AREA_TYPES = frozenset({"Polygon", "MultiPolygon"})
_LINE_TYPES = frozenset({"LineString", "LinearRing"})
_LAWN_WORD = "ГАЗОН"
_FLOWERBED_WORD = "ЦВЕТНИК"
_MARKER = "SYMBOL_MARKER"
# Посадочное место касается участка по границе разности; касание ищется с запасом округления.
_TOUCH_M = 0.01
_ORDER = {LawnKind.KEPT: 0, LawnKind.NEW: 1}
_KIND_NOTES = {
    LawnKind.KEPT: "газон по чертежу (контур слоя газона, знак или подпись «ГАЗОН»)",
    LawnKind.NEW: "грунт без газона и цветника по чертежу",
}
_KIND_NAMES = {LawnKind.KEPT: "сохраняемого газона", LawnKind.NEW: "устраиваемого газона"}


def plan_lawns(  # noqa: PLR0913 - этап читает план, подоснову, карту покрытий, нормы и профиль
    plan: Plan,
    *,
    features: Sequence[Feature],
    labels: Sequence[TextLabel],
    surface: SurfaceMap | None,
    rulebook: RuleBook,
    params: PlanParams,
) -> Plan:
    """Газоны итогового плана. Выключено параметром lawns - газонов нет, предупреждений тоже."""
    warnings = tuple(w for w in plan.warnings if not w.startswith(WARNING_PREFIX))
    plan = replace(plan, lawns=(), warnings=warnings)
    if not params.lawns:
        return plan
    soil = surface.soil_area if surface is not None else None
    if surface is None or soil is None or soil.is_empty:
        return _warn(plan, ["не выделены, в карте покрытий нет грунта замкнутых контуров."])
    boundary = work_boundary(features)
    if boundary is None and params.require_work_boundary:
        return _warn(plan, ["не выделены, в чертеже нет границы работ."])
    if boundary is not None:
        soil = soil.intersection(boundary)
    if surface.woodland_area is not None:
        soil = soil.difference(surface.woodland_area)
    pits, is_tree = _pits(plan.placements, params)
    free = soil.difference(shapely.union_all(pits)) if len(pits) else soil
    drawn, flowerbeds = _drawn(features, labels, soil)
    areas = {
        LawnKind.KEPT: free.intersection(drawn),
        LawnKind.NEW: free.difference(shapely.union_all([drawn, flowerbeds])),
    }

    notes: list[str] = []
    chosen: list[tuple[LawnKind, BaseGeometry, tuple[str, ...]]] = []
    small: list[float] = []
    for kind, area in areas.items():
        polygons = _polygons(area)
        big = [p for p in polygons if p.area >= params.lawn_min_area_m2]
        small.extend(p.area for p in polygons if p.area < params.lawn_min_area_m2)
        rule_ids = _rule_ids(rulebook, kind, params)
        if big and not rule_ids:
            total = _m2(sum(p.area for p in big))
            notes.append(
                f"в своде норм нет правила {_KIND_NAMES[kind]}, {total} м² газоном не выделены."
            )
            continue
        chosen.extend((kind, polygon, rule_ids) for polygon in big)
    chosen.sort(key=lambda item: (_ORDER[item[0]], -item[1].area, item[1].bounds))

    touched = _touching_pits(np.array([g for _, g, _ in chosen], dtype=object), pits, is_tree)
    lawns = tuple(
        Lawn(
            lawn_id=f"{LAWN_PREFIX}{number:05d}",
            number=number,
            kind=kind,
            geometry=geometry,
            rule_ids=rule_ids,
            notes=_notes(kind, touched[number - 1], params),
        )
        for number, (kind, geometry, rule_ids) in enumerate(chosen, 1)
    )
    if surface.fallback_soil_m2:
        notes.append(
            f"{_m2(surface.fallback_soil_m2)} м² грунта по близости подписи в газон не вошли, "
            "нужен замкнутый контур грунта."
        )
    if not flowerbeds.is_empty:
        notes.append(
            f"цветники по чертежу, {_m2(flowerbeds.area)} м², сохраняются и в газон не входят."
        )
    stats = {
        **plan.stats,
        "lawn_small_parts": len(small),
        "lawn_small_m2": round(sum(small), 1),
    }
    return _warn(replace(plan, lawns=lawns, stats=stats), notes)


def _warn(plan: Plan, notes: Sequence[str]) -> Plan:
    return replace(plan, warnings=(*plan.warnings, *(WARNING_PREFIX + note for note in notes)))


def _rule_ids(rulebook: RuleBook, kind: LawnKind, params: PlanParams) -> tuple[str, ...]:
    """Основания вида газона: сначала своё правило, потом общие. Нет своего - пусто."""
    rules = [r for r in rulebook.lawn_rules_for(kind) if r.rule_id not in params.disabled_rules]
    if not any(r.kind is kind for r in rules):
        return ()
    return tuple(r.rule_id for r in sorted(rules, key=lambda r: r.kind is None))


def _pits(
    placements: Sequence[Placement], params: PlanParams
) -> tuple[NDArray[np.object_], NDArray[np.bool_]]:
    """Посадочные места плана кругами с запасом наружу: газон не заходит в яму даже хордой."""
    is_tree = np.array([p.planting_type is PlantingType.TREE for p in placements], dtype=bool)
    pits = np.array(
        [
            reserved_buffer(
                Point(p.x, p.y),
                params.planting_radius_m if tree else params.shrub_planting_radius_m,
            )
            for p, tree in zip(placements, is_tree, strict=True)
        ],
        dtype=object,
    )
    return pits, is_tree


def _drawn(
    features: Sequence[Feature], labels: Sequence[TextLabel], soil: BaseGeometry
) -> tuple[BaseGeometry, BaseGeometry]:
    """Газон и цветники по чертежу внутри грунта.

    Контур слоя газона - газон. Грань грунта со знаком газона или подписью «ГАЗОН» - газон, с
    подписью «ЦВЕТНИК» и без признака газона - цветник, и цветник газоном не бывает, даже внутри
    контура слоя газона.
    """
    contours = [
        inner_area(f)
        for f in features
        if f.object_class is ObjectClass.LAWN and f.geometry.geom_type in _AREA_TYPES
    ]
    lawn_marks = [
        f.geometry
        for f in features
        if f.object_class is ObjectClass.LAWN and f.source_entity_type == _MARKER
    ]
    flower_marks = []
    for label in labels:
        word = _material_word(label)
        if word == _LAWN_WORD:
            lawn_marks.append(Point(label.x, label.y))
        elif word == _FLOWERBED_WORD:
            flower_marks.append(Point(label.x, label.y))
    faces = _faces(features, soil)
    lawn_faces = _marked(faces, lawn_marks)
    flowerbeds = shapely.union_all(faces[_marked(faces, flower_marks) & ~lawn_faces])
    drawn = shapely.union_all([*contours, *faces[lawn_faces]]).difference(flowerbeds)
    return drawn, flowerbeds


def _faces(features: Sequence[Feature], soil: BaseGeometry) -> NDArray[np.object_]:
    """Грани грунта: грунт, разрезанный линиями смены покрытия, которые лежат внутри него.

    В карте покрытий соседние грани грунта срастаются в одну область, а подпись или знак
    материала относятся к своей грани: цветник за садовым бортом не забирает соседний газон.
    """
    polygons = np.array(_polygons(soil), dtype=object)
    lines = np.array(
        [
            part
            for f in features
            if f.object_class.is_surface_barrier and f.object_class is not ObjectClass.WORK_BOUNDARY
            for part in shapely.get_parts(
                f.geometry.boundary if f.geometry.geom_type in _AREA_TYPES else f.geometry
            )
            if part.geom_type in _LINE_TYPES
        ],
        dtype=object,
    )
    if not len(polygons) or not len(lines):
        return polygons
    inside = STRtree(lines).query(soil, predicate="intersects")
    if not len(inside):
        return polygons
    # Граница грунта входит в сеть линий, поэтому каждая грань целиком внутри грунта или вне его.
    noded = shapely.union_all([soil.boundary, *lines[inside]])
    faces = shapely.get_parts(shapely.polygonize(shapely.get_parts(noded)))
    return faces[shapely.within(shapely.point_on_surface(faces), soil)]


def _material_word(label: TextLabel) -> str | None:
    """Газон или цветник в подписи. Роль подписи из профиля решает раньше текста."""
    if label.surface_role not in {"auto", "soil"}:
        return None
    if label.surface_role == "auto" and label_material(label.text) is not Material.SOIL:
        return None
    text = label.text.upper()
    if _LAWN_WORD in text:
        return _LAWN_WORD
    if _FLOWERBED_WORD in text:
        return _FLOWERBED_WORD
    return None


def _marked(parts: NDArray[np.object_], marks: Sequence[BaseGeometry]) -> NDArray[np.bool_]:
    hit = np.zeros(len(parts), dtype=bool)
    if len(parts) and marks:
        pairs = STRtree(parts).query(np.array(marks, dtype=object), predicate="within")
        hit[pairs[1]] = True
    return hit


def _touching_pits(
    lawns: NDArray[np.object_], pits: NDArray[np.object_], is_tree: NDArray[np.bool_]
) -> NDArray[np.int64]:
    """Сколько посадочных мест деревьев и кустарников вырезано из каждого участка."""
    counts = np.zeros((len(lawns), 2), dtype=np.int64)
    if not len(lawns) or not len(pits):
        return counts
    pairs = STRtree(lawns).query(pits, predicate="dwithin", distance=_TOUCH_M)
    np.add.at(counts, (pairs[1], np.where(is_tree[pairs[0]], 0, 1)), 1)
    return counts


def _notes(kind: LawnKind, touched: NDArray[np.int64], params: PlanParams) -> tuple[str, ...]:
    trees, shrubs = int(touched[0]), int(touched[1])
    pits = []
    if trees:
        pits.append(f"деревьев {trees} (круг радиусом {_metres(params.planting_radius_m)} м)")
    if shrubs:
        pits.append(
            f"кустарников {shrubs} (круг радиусом {_metres(params.shrub_planting_radius_m)} м)"
        )
    if not pits:
        return (_KIND_NOTES[kind],)
    return (_KIND_NOTES[kind], "без посадочных мест: " + ", ".join(pits))


def _polygons(geometry: BaseGeometry | None) -> list[BaseGeometry]:
    """Полигоны из результата наложения: линии и точки касания газоном не бывают."""
    if geometry is None or geometry.is_empty:
        return []
    result: list[BaseGeometry] = []
    for part in shapely.get_parts(geometry):
        if part.geom_type == "Polygon" and not part.is_empty:
            result.append(part)
        elif part.geom_type in {"MultiPolygon", "GeometryCollection"}:
            result.extend(_polygons(part))
    return result


def _m2(value: float) -> str:
    return f"{value:,.1f}".replace(",", " ").replace(".", ",")


def _metres(value: float) -> str:
    return f"{value:g}".replace(".", ",")


__all__ = ["LAWN_PREFIX", "WARNING_PREFIX", "plan_lawns"]
