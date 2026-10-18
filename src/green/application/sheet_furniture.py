"""Оформление листа среди объектов без класса: условные обозначения, штамп, текст штрихами.

Листы ИГДИ вставлены в чертёж блоком внешней ссылки, и слой 0 внутри блока наследует слой
вставки («!ВН_ССЫЛ_ИТП», «Вн.ссылка_Первомайская»), которого в словаре слоёв нет. Перепись
19 улиц пилота (17-18.10.2026): на этом слое лежат легенда листа, штампы с рамками и текст,
разобранный на штрихи по 0,1-0,3 м. По одной геометрии они становились «линией без смысла»
и попадали на проверку человеку тысячами.

Решает близость, а не имя: объекты без класса одного контекста (файл, цепочка внешних
ссылок, слой, блок) вместе с подписями этого контекста связываются в группы по расстоянию
до LINK_M. Группа - оформление, если в ней есть подпись-якорь оформления (шапка легенды,
графы штампа) или если она почти целиком из коротких штрихов (разобранный текст). Объекты
с классом по имени слоя, знаку или словам сюда не попадают: правило не меняет решённое.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

if TYPE_CHECKING:
    from collections.abc import Iterable

    from green.domain.objects import Feature, TextLabel

# Строки легенды идут через 3-4 м, графы штампа - через 1-5 м: группа держится шагом строки.
LINK_M = 4.5
# Штрих разобранного текста: отрезок букв короче этого.
STROKE_M = 0.6
STROKE_SHARE = 0.7
STROKE_MIN_COUNT = 20
# Штрихи букв идут во все стороны; поперечные штрихи откоса или лестницы - в одну.
STROKE_ONE_DIRECTION = 0.6
TEXT_STROKES = "text_strokes"

_ANCHOR = re.compile(
    r"условн\w*обознач|^лист(ов)?$|^изм$|^колуч$|^№?док$|^подпись$|^дата$|^разработал$"
    r"|^проверил$|^нконтр|^гип$|полевыеработы|камералработы|^стадия$|^масштаб|^формат"
    r"|^заказчик$|наименованиеобъекта|схемарасположения|^инв№|взаминв|^согласовано$"
    r"|^утверждаю$"
)


def _norm(text: str) -> str:
    return re.sub(r"[^а-яёa-z№]", "", text.casefold())


def is_anchor(text: str) -> bool:
    return bool(_ANCHOR.search(_norm(text)))


def _context(item: Feature | TextLabel) -> tuple[str, str, str, str | None]:
    # Анонимный блок (*U, *X) - кусок одного листа: слова легенды 2-й Прядильной лежат
    # каждое в своём *U. Такие блоки считаются одним контекстом со своим слоем.
    # Хеш цепочки вставок у каждого *U свой, поэтому для них контекст - файл и слой.
    if item.block is not None and item.block.startswith("*"):
        return item.ref.file_sha8, "", item.layer, None
    return item.ref.file_sha8, item.ref.xref_hash8, item.layer, item.block


def sheet_furniture(
    candidates: Iterable[Feature], labels: Iterable[TextLabel], *, strokes: bool
) -> dict[str, str]:
    """ref объекта -> основание: текст подписи-якоря или TEXT_STROKES. strokes=False
    отключает признак штрихов: он чисто геометрический."""
    features: dict[tuple, list[Feature]] = defaultdict(list)
    for feature in candidates:
        features[_context(feature)].append(feature)
    texts: dict[tuple, list[TextLabel]] = defaultdict(list)
    for label in labels:
        if label.text.strip():
            texts[_context(label)].append(label)
    found: dict[str, str] = {}
    for key, members in features.items():
        found.update(_furniture(members, texts.get(key, []), strokes=strokes))
    return found


def _furniture(members: list[Feature], labels: list[TextLabel], *, strokes: bool) -> dict[str, str]:
    geoms = [f.geometry for f in members] + [shapely.Point(t.x, t.y) for t in labels]
    count = len(geoms)
    tree = shapely.STRtree(geoms)
    left, right = tree.query(geoms, predicate="dwithin", distance=LINK_M)
    graph = coo_matrix((np.ones(len(left), dtype=np.int8), (left, right)), shape=(count, count))
    _, component = connected_components(graph, directed=False)
    anchors: dict[int, str] = {}
    for offset, label in enumerate(labels):
        if is_anchor(label.text):
            anchors.setdefault(int(component[len(members) + offset]), label.text.strip())
    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(members)):
        groups[int(component[index])].append(index)
    found: dict[str, str] = {}
    for group, indices in groups.items():
        reason = anchors.get(group)
        if reason is None and strokes and _strokes(members, indices):
            reason = TEXT_STROKES
        if reason is not None:
            found.update((str(members[i].ref), reason) for i in indices)
    return found


def _strokes(members: list[Feature], indices: list[int]) -> bool:
    lines = [
        members[i].geometry
        for i in indices
        if members[i].geometry.geom_type in {"LineString", "MultiLineString"}
    ]
    if len(lines) < STROKE_MIN_COUNT:
        return False

    short = [line for line in lines if line.length < STROKE_M]
    if len(short) < STROKE_SHARE * len(lines):
        return False
    return _one_direction(short) < STROKE_ONE_DIRECTION


def _one_direction(lines: list) -> float:
    """Доля штрихов самого частого направления (по 15°, без учёта знака)."""
    bins: dict[int, int] = defaultdict(int)
    for line in lines:
        coords = list(line.coords) if line.geom_type == "LineString" else list(line.geoms[0].coords)
        (x0, y0), (x1, y1) = coords[0][:2], coords[-1][:2]
        bins[int(math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180 // 15)] += 1
    return max(bins.values()) / len(lines)
