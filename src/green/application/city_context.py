"""Город вокруг съёмки для 3D-вида: дома, деревья и дороги из открытой карты.

Съёмка Мосгеотреста - полоса вдоль улицы, и за её краем в 3D было поле до горизонта. Улица
на фото «до» стоит в квартале: соседние дома, деревья, проезды. Их берём из открытой карты
(источник за портом `CityContextSource`) в кольце вокруг участка и переводим в систему
координат чертежа.

Внутри съёмки решает только чертёж: дом карты, который пересекает дом чертежа, отбрасывается,
как и дерево карты внутри прямоугольника съёмки (там свои существующие насаждения). Окружение -
фон для картинки, в расчёт посадок оно не попадает.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from shapely import Polygon, box
from shapely.strtree import STRtree

from green.application.errors import GreenError, NotFoundError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from green.application.ports import CityContextSource, RunStore

# Кольцо вокруг прямоугольника съёмки, метры: дальше дома тонут в дымке и только едят кадр.
RING_M = 450.0
MAX_BUILDINGS = 4000
MAX_TREES = 8000
MAX_ROADS = 3000
MAX_GREENS = 1500
# Меньше этого дом карты - будка или ошибка оцифровки, в окружении он не нужен, м2.
MIN_BUILDING_M2 = 4.0
_RING_MIN = 3

Extent = tuple[float, float, float, float]
Point = tuple[float, float]


class ContextUnavailableError(GreenError):
    """Открытая карта недоступна: нет сети, сервис не ответил или окружение выключено."""


@dataclass(frozen=True, slots=True)
class ContextBuilding:
    ring: tuple[Point, ...]
    levels: int | None
    kind: str


@dataclass(frozen=True, slots=True)
class ContextRoad:
    line: tuple[Point, ...]
    width_m: float
    kind: str


@dataclass(frozen=True, slots=True)
class ContextArea:
    """Зелёная зона карты: парк, лес, газон, сквер - 3D-вид засаживает её фоновыми деревьями."""

    ring: tuple[Point, ...]
    kind: str


@dataclass(frozen=True, slots=True)
class CityContext:
    """Окружение в метрах чертежа и откуда оно."""

    extent: Extent
    buildings: tuple[ContextBuilding, ...] = ()
    trees: tuple[Point, ...] = ()
    roads: tuple[ContextRoad, ...] = ()
    greens: tuple[ContextArea, ...] = ()
    # Открытые стоянки карты: в 3D - асфальт с рядами машин.
    parkings: tuple[ContextArea, ...] = ()
    source: str = ""
    notes: tuple[str, ...] = field(default=())


def ring_extent(extent: Extent, ring_m: float = RING_M) -> Extent:
    min_x, min_y, max_x, max_y = extent
    return (min_x - ring_m, min_y - ring_m, max_x + ring_m, max_y + ring_m)


def without_survey(
    context: CityContext,
    survey: Extent,
    drawing_buildings: Sequence[Sequence[Point]],
) -> CityContext:
    """Окружение без того, что уже есть в чертеже: дома карты, пересекающие дома съёмки, и
    деревья внутри съёмки уходят; длинные списки обрезаются по пределам."""
    footprints = [Polygon(ring) for ring in drawing_buildings if len(ring) >= _RING_MIN]
    footprints = [p if p.is_valid else p.buffer(0) for p in footprints]
    tree = STRtree(footprints) if footprints else None
    kept: list[ContextBuilding] = []
    for building in context.buildings:
        if len(building.ring) < _RING_MIN:
            continue
        shape = Polygon(building.ring)
        if not shape.is_valid:
            shape = shape.buffer(0)
        if shape.is_empty or shape.area < MIN_BUILDING_M2:
            continue
        if tree is not None and len(tree.query(shape, predicate="intersects")):
            continue
        kept.append(building)
        if len(kept) >= MAX_BUILDINGS:
            break
    inside = box(*survey)
    trees = tuple((x, y) for x, y in context.trees if not inside.covers(box(x, y, x, y)))[
        :MAX_TREES
    ]
    dropped = len(context.buildings) - len(kept)
    notes = (*context.notes, f"домов карты, совпавших с домами чертежа: {dropped}")
    return CityContext(
        extent=context.extent,
        buildings=tuple(kept),
        trees=trees,
        roads=context.roads[:MAX_ROADS],
        greens=context.greens[:MAX_GREENS],
        parkings=context.parkings[:MAX_GREENS],
        source=context.source,
        notes=notes,
    )


def context_json(context: CityContext) -> dict[str, object]:
    """Окружение для 3D-вида: те же метры чертежа, что у scene.json."""
    return {
        "version": 1,
        "source": context.source,
        "extent": list(context.extent),
        "buildings": [
            {
                "ring": [[round(x, 2), round(y, 2)] for x, y in b.ring],
                "levels": b.levels,
                "kind": b.kind,
            }
            for b in context.buildings
        ],
        "trees": [[round(x, 2), round(y, 2)] for x, y in context.trees],
        "roads": [
            {
                "line": [[round(x, 2), round(y, 2)] for x, y in r.line],
                "width_m": r.width_m,
                "kind": r.kind,
            }
            for r in context.roads
        ],
        "greens": [
            {"ring": [[round(x, 2), round(y, 2)] for x, y in g.ring], "kind": g.kind}
            for g in context.greens
        ],
        "parkings": [
            {"ring": [[round(x, 2), round(y, 2)] for x, y in a.ring], "kind": a.kind}
            for a in context.parkings
        ],
        "notes": list(context.notes),
    }


CONTEXT_FILE = "context.json"


class CityContextService:
    """Окружение прогона для 3D-вида: один запрос к карте, дальше - файл в каталоге прогона."""

    def __init__(self, source: CityContextSource | None, store: RunStore) -> None:
        self._source = source
        self._store = store

    def for_run(self, run_id: str) -> bytes:
        cached = self._store.run_dir(run_id) / CONTEXT_FILE
        if cached.is_file():
            return cached.read_bytes()
        if self._source is None:
            msg = "Окружение из OpenStreetMap выключено в настройках (GREEN_OSM_CONTEXT)."
            raise ContextUnavailableError(msg)
        try:
            scene = json.loads(self._store.artifact(run_id, "scene.json").read_bytes())
        except FileNotFoundError as error:
            msg = "У прогона нет scene.json: окружение строится вокруг зданий и посадок сцены."
            raise NotFoundError(msg) from error
        survey: Extent = tuple(scene["extent"])  # type: ignore[assignment]
        rings = [[tuple(p) for p in b["rings"][0]] for b in scene["buildings"] if b["rings"]]
        context = without_survey(self._source.around(ring_extent(survey)), survey, rings)
        content = json.dumps(context_json(context), ensure_ascii=False).encode()
        temporary = cached.with_suffix(".tmp")
        temporary.write_bytes(content)
        temporary.replace(cached)
        return content
