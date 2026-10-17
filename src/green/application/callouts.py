"""Conservative recognition of exploded callouts; never edits source CAD entities."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from itertools import combinations
from typing import TYPE_CHECKING

from shapely import STRtree
from shapely.geometry import Point
from shapely.ops import unary_union

from green.domain.objects import Callout

if TYPE_CHECKING:
    from green.domain.objects import Feature, Scene, TextLabel

# Imported coordinates may differ in the last decimals after a CAD transformation.
_JOIN_M = 0.0001
_MAX_WING_M = 2.0
_MAX_DEGREE = 12
_LINE_VERTICES = 2
_SHAFT_VERTICES = 5
_FORWARD_COS = 0.5
# Выноска без проверки (leader): стержень до 40 м, полка под подписью до 8 м, вдоль чужих
# линий слоя (в 15 см) - не больше пятой части стержня.
_MAX_LEADER_M = 40.0
_MAX_SHELF_M = 8.0
_OVERLAP_M = 0.15
_MAX_OVERLAP = 0.2
# Линия у острия ближе 35° к ходу стержня - продолжение, иначе острие лежит на трассе.
_STRAIGHT_COS = math.cos(math.radians(35))


def _context(item: Feature | TextLabel) -> tuple[str, str, str, str | None]:
    return item.ref.file_sha8, item.ref.xref_hash8, item.layer, item.block


def _unit(vector: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(*vector)
    return vector[0] / length, vector[1] / length


def _dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]


def recognise_callouts(scene: Scene) -> tuple[Callout, ...]:
    """Require a connected shaft, two arrow wings, and a nearby label.

    Automatic exclusion is restricted to an isolated cable-well annotation.
    Other labels, competing text, and network continuations require human review.
    The spatial index bounds each search to local neighbours, not all feature pairs.
    """
    contexts: dict[tuple, list[Feature]] = defaultdict(list)
    for feature in scene.features:
        geom = feature.geometry
        if (
            feature.symbol is None
            and geom.geom_type == "LineString"
            and not geom.is_ring
            and geom.length > 0
        ):
            contexts[_context(feature)].append(feature)
    labels: dict[tuple, list[TextLabel]] = defaultdict(list)
    for label in scene.labels:
        if label.text.strip():
            labels[_context(label)].append(label)
    result = []
    for key, features in contexts.items():
        local_labels = labels.get(key, [])
        if not local_labels:
            continue
        result.extend(_recognise(features, local_labels))
    return tuple(result)


def _recognise(  # noqa: C901 - bounded geometric motif with explicit rejection conditions
    features: list[Feature], labels: list[TextLabel]
) -> list[Callout]:
    endpoints = []
    owners = []
    for index, feature in enumerate(features):
        coords = list(feature.geometry.coords)
        endpoints.extend([Point(coords[0]), Point(coords[-1])])
        owners.extend([index, index])
    tree = STRtree(endpoints)
    line_tree = STRtree([feature.geometry for feature in features])
    text_tree = STRtree([Point(label.x, label.y) for label in labels])
    found: dict[tuple[str, ...], Callout] = {}
    for index, shaft in enumerate(features):
        coords = list(shaft.geometry.coords)
        if not _LINE_VERTICES <= len(coords) <= _SHAFT_VERTICES or shaft.geometry.length < 1:
            continue
        for points in (coords, coords[::-1]):
            tip, following, tail = points[0], points[1], points[-1]
            if math.dist(tip[:2], following[:2]) <= _JOIN_M:
                continue
            near = {
                owners[int(i)]
                for i in tree.query(Point(tip).buffer(_JOIN_M))
                if endpoints[int(i)].distance(Point(tip)) <= _JOIN_M
            } - {index}
            if len(near) > _MAX_DEGREE:
                continue
            wings = [
                i
                for i in sorted(near)
                if len(features[i].geometry.coords) == _LINE_VERTICES
                and _JOIN_M < features[i].geometry.length <= _MAX_WING_M
            ]
            for left, right in combinations(wings, 2):
                motif = _motif(shaft, features[left], features[right], tip, following)
                if motif is None:
                    continue
                text_ids = sorted(int(i) for i in text_tree.query(Point(tail).buffer(4 * motif)))
                text_ids = [
                    i
                    for i in text_ids
                    if Point(labels[i].x, labels[i].y).distance(Point(tail)) <= 4 * motif
                ]
                text_ids.sort(
                    key=lambda i: (
                        Point(labels[i].x, labels[i].y).distance(Point(tail)),
                        str(labels[i].ref),
                    )
                )
                if not text_ids:
                    continue
                label = labels[text_ids[0]]
                is_well = re.sub(r"[^а-яa-z]", "", label.text.casefold()) in {
                    "кабкол",
                    "кабельныйколодец",
                }
                isolated = near == {left, right}
                certain = len(text_ids) == 1 and isolated and is_well
                shelf = _free_tail(features, index, tail, tree, endpoints, owners)
                leader = (
                    not certain
                    and not _continues(features, near - {left, right}, tip, following)
                    and shelf is not None
                    and shaft.geometry.length <= _MAX_LEADER_M
                    and _overlap(shaft, features, {index, left, right, *shelf}, line_tree)
                    <= _MAX_OVERLAP
                )
                members = (index, left, right, *(shelf if leader and shelf else ()))
                refs = tuple(sorted(str(features[i].ref) for i in members))
                reason = (
                    "подпись кабельного колодца, полка и отдельный наконечник"
                    if certain
                    else "выноска: стержень не продолжается за острием, хвост свободен"
                    if leader
                    else "несколько подписей, продолжение линии или неоднозначный текст"
                )
                candidate = Callout(refs, str(label.ref), label.text, certain, reason, leader)
                previous = found.get(refs)
                # Competing interpretations must never promote an uncertain motif.
                if previous is None or not certain:
                    found[refs] = candidate
    return list(found.values())


def _touching(point: tuple, tree: STRtree, endpoints: list[Point], owners: list[int]) -> set[int]:
    probe = Point(point)
    return {
        owners[int(i)]
        for i in tree.query(probe.buffer(_JOIN_M))
        if endpoints[int(i)].distance(probe) <= _JOIN_M
    }


def _continues(features: list[Feature], others: set[int], tip: tuple, following: tuple) -> bool:
    """Линия, отходящая от острия почти прямо по ходу стержня (ближе _STRAIGHT_DEG), -
    продолжение сети через стрелку, а не трасса под выноской."""
    incoming = _unit((tip[0] - following[0], tip[1] - following[1]))
    for other in others:
        coords = list(features[other].geometry.coords)
        if math.dist(coords[0][:2], tip[:2]) > math.dist(coords[-1][:2], tip[:2]):
            coords.reverse()
        step = next((p for p in coords[1:] if math.dist(p[:2], tip[:2]) > _JOIN_M), None)
        if step is None:
            continue
        if _dot(incoming, _unit((step[0] - tip[0], step[1] - tip[1]))) >= _STRAIGHT_COS:
            return True
    return False


def _free_tail(  # noqa: PLR0913, PLR0917 - индексы концов те же, что у _touching
    features: list[Feature],
    shaft: int,
    tail: tuple,
    tree: STRtree,
    endpoints: list[Point],
    owners: list[int],
) -> tuple[int, ...] | None:
    """Хвост стержня свободен или кончается полкой: короткой линией, второй конец которой
    ничего не касается. Вернуть полку (или пустой кортеж); None - хвост продолжает сеть."""
    others = _touching(tail, tree, endpoints, owners) - {shaft}
    shelves = []
    for other in others:
        geometry = features[other].geometry
        if geometry.length > _MAX_SHELF_M:
            return None
        coords = list(geometry.coords)
        far = max((coords[0], coords[-1]), key=lambda p: math.dist(p[:2], tail[:2]))
        if _touching(far, tree, endpoints, owners) - {other}:
            return None
        shelves.append(other)
    return tuple(shelves)


def _overlap(shaft: Feature, features: list[Feature], own: set[int], line_tree: STRtree) -> float:
    """Доля стержня, лежащая вдоль других линий того же слоя (стрелка течения на трубе)."""
    zone = shaft.geometry.buffer(_OVERLAP_M)
    others = [
        features[int(i)].geometry
        for i in line_tree.query(zone)
        if int(i) not in own and features[int(i)].geometry.intersects(zone)
    ]
    if not others:
        return 0.0
    covered = shaft.geometry.intersection(unary_union(others).buffer(_OVERLAP_M))
    return covered.length / shaft.geometry.length


def _motif(
    shaft: Feature,
    left: Feature,
    right: Feature,
    tip: tuple,
    following: tuple,
) -> float | None:
    lengths = [left.geometry.length, right.geometry.length]
    size = max(lengths)
    if min(lengths) < 0.8 * size or shaft.geometry.length < 4 * size:
        return None
    directions = []
    for feature in (left, right):
        coords = list(feature.geometry.coords)
        far = max(coords, key=lambda p: math.dist(p[:2], tip[:2]))
        directions.append(_unit((far[0] - tip[0], far[1] - tip[1])))
    direction = _unit((following[0] - tip[0], following[1] - tip[1]))
    if min(_dot(direction, wing) for wing in directions) < _FORWARD_COS:
        return None
    angle = _dot(*directions)
    # Both wings must sit on opposite sides of the shaft direction.
    sides = [direction[0] * wing[1] - direction[1] * wing[0] for wing in directions]
    if sides[0] * sides[1] >= 0 or not math.cos(math.radians(80)) < angle < math.cos(
        math.radians(15)
    ):
        return None
    return size
