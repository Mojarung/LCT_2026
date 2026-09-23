"""Карта покрытий из топоплана: где грунт, а где асфальт, плитка или проезжая часть.

Топоплан Геотреста не содержит полигонов покрытий: есть линии, по которым покрытие
меняется (борт, граница покрытия, стены, ограды, граница растительности), и подписи
материала внутри участков («А» асфальт, «Ц» цементобетон, «ПЛ» плитка, «ГАЗОН»).
Карта строится на растре: линии становятся барьерами, подписи и условные знаки
деревьев источниками, каждая ячейка получает материал ближайшего источника по пути
в обход барьеров. Разрыв в штриховой линии пропускает только то, что ближе,
поэтому карта устойчива к разрывам на въездах и в местах стыков.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy import sparse
from scipy.sparse.csgraph import dijkstra

from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from shapely.geometry.base import BaseGeometry

    from green.domain.objects import Feature, TextLabel

PAVED_LABELS = frozenset({"А", "Ц", "ПЛ", "БР", "Б", "Щ", "ГР", "АСФ", "ПЛИТКА"})
SOIL_LABELS = frozenset({"ГАЗОН", "ГРУНТ", "ЦВЕТНИК"})
# Подписи-фразы площадок и покрытий: «ДЕТ.ПЛ.», «СПОРТ ПЛ.», «СПЕЦ.ПОКРЫТИЕ», «ПЛИТКА БЕТОННАЯ».
# Короткие обозначения («А», «Б») фразами не ищутся: «ж.б.» у трубы - не бетонное покрытие.
PAVED_PHRASE = re.compile(r"ПОКР|^(ДЕТ|СПОРТ|ХОЗ|ИГР)\W*ПЛ|ПЛОЩАДК|АСФАЛЬТ|БРУСЧ|ПЛИТК|ТЕРРАВЕЙ")
SOIL_PHRASE = re.compile(r"ГАЗОН|ЦВЕТНИК")
# Полигоны, чья середина - известный материал: штриховки газонов, тротуаров, проезжей части.
SOIL_AREAS = frozenset({ObjectClass.LAWN})
PAVED_AREAS = frozenset({ObjectClass.SIDEWALK, ObjectClass.ROAD})
MAX_CELLS = 20_000_000
_LINE_TYPES = frozenset({"LineString", "MultiLineString"})
_AREA_TYPES = frozenset({"Polygon", "MultiPolygon"})


class Material(IntEnum):
    UNKNOWN = 0
    PAVED = 1
    SOIL = 2
    BARRIER = 3


@dataclass(frozen=True, slots=True)
class SurfaceMap:
    """Растр материалов: origin в метрах чертежа, cell в метрах, grid[row, col]."""

    grid: NDArray[np.int8]
    origin: tuple[float, float]
    cell: float
    seeds_paved: int
    seeds_soil: int

    def material(self, points: NDArray[np.object_]) -> NDArray[np.int8]:
        """Материал под каждой точкой; вне растра UNKNOWN."""
        if not len(points):
            return np.zeros(0, dtype=np.int8)
        rows, cols = self._cells(shapely.get_coordinates(points))
        inside = (
            (rows >= 0) & (rows < self.grid.shape[0]) & (cols >= 0) & (cols < self.grid.shape[1])
        )
        result = np.full(len(points), int(Material.UNKNOWN), dtype=np.int8)
        result[inside] = self.grid[rows[inside], cols[inside]]
        return result

    def summary(self) -> dict[str, int | float]:
        counted = {m: int((self.grid == m).sum()) for m in Material}
        return {
            "cell_m": self.cell,
            "seeds_paved": self.seeds_paved,
            "seeds_soil": self.seeds_soil,
            **{f"cells_{m.name.lower()}": counted[m] for m in Material},
        }

    def _cells(self, xy: NDArray[np.float64]) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
        cols = np.floor((xy[:, 0] - self.origin[0]) / self.cell).astype(np.int64)
        rows = np.floor((xy[:, 1] - self.origin[1]) / self.cell).astype(np.int64)
        return rows, cols


def build_surface_map(
    features: Sequence[Feature],
    labels: Sequence[TextLabel],
    extent: BaseGeometry | None,
    cell_m: float,
) -> SurfaceMap | None:
    """Строит карту, если в чертеже есть подписи покрытий и хотя бы один признак грунта."""
    seed_xy, seed_kind = _seeds(features, labels)
    paved, soil = int((seed_kind == Material.PAVED).sum()), int((seed_kind == Material.SOIL).sum())
    if paved == 0 or soil == 0:
        return None
    barriers = _barrier_lines(features)
    bounds = extent.bounds if extent is not None else shapely.total_bounds(barriers)
    cell = _cell_size(bounds, cell_m)
    origin = (float(bounds[0]) - cell, float(bounds[1]) - cell)
    shape = (int((bounds[3] - bounds[1]) / cell) + 3, int((bounds[2] - bounds[0]) / cell) + 3)
    barrier = _rasterize(barriers, origin, cell, shape)
    free = ~barrier
    if extent is not None:
        free &= _inside(extent, origin, cell, shape)
    cols = np.floor((seed_xy[:, 0] - origin[0]) / cell).astype(np.int64)
    rows = np.floor((seed_xy[:, 1] - origin[1]) / cell).astype(np.int64)
    grid = _assign(free, _Seeds(rows, cols, seed_kind))
    grid[barrier] = int(Material.BARRIER)
    return SurfaceMap(grid=grid, origin=origin, cell=cell, seeds_paved=paved, seeds_soil=soil)


@dataclass(frozen=True, slots=True)
class _Seeds:
    rows: NDArray[np.int64]
    cols: NDArray[np.int64]
    kinds: NDArray[np.int8]


def _seeds(
    features: Sequence[Feature], labels: Sequence[TextLabel]
) -> tuple[NDArray[np.float64], NDArray[np.int8]]:
    xy: list[tuple[float, float]] = []
    kind: list[int] = []
    for label in labels:
        material = label_material(label.text)
        if material is not None:
            xy.append((label.x, label.y))
            kind.append(int(material))
    for feature in features:
        area = feature.object_class in SOIL_AREAS or feature.object_class in PAVED_AREAS
        if not area or feature.geometry.geom_type not in _AREA_TYPES:
            continue
        point = feature.geometry.representative_point()
        xy.append((point.x, point.y))
        paved = feature.object_class in PAVED_AREAS
        kind.append(int(Material.PAVED if paved else Material.SOIL))
    trees = [f.geometry for f in features if f.object_class is ObjectClass.EXISTING_TREE]
    if trees:
        centers = shapely.get_coordinates(shapely.centroid(np.array(trees, dtype=object)))
        xy.extend(map(tuple, centers))
        kind.extend([int(Material.SOIL)] * len(centers))
    return np.array(xy, dtype=np.float64).reshape(-1, 2), np.array(kind, dtype=np.int8)


def label_material(text: str) -> Material | None:
    """Материал по подписи: короткое обозначение целиком или фраза площадки и покрытия."""
    normalized = text.strip().upper().rstrip(".")
    if normalized in PAVED_LABELS:
        return Material.PAVED
    if normalized in SOIL_LABELS:
        return Material.SOIL
    paved, soil = bool(PAVED_PHRASE.search(normalized)), bool(SOIL_PHRASE.search(normalized))
    if paved and not soil:
        return Material.PAVED
    if soil and not paved:
        return Material.SOIL
    return None


def _barrier_lines(features: Sequence[Feature]) -> NDArray[np.object_]:
    lines: list[BaseGeometry] = []
    for feature in features:
        if not feature.object_class.is_surface_barrier:
            continue
        geometry = feature.geometry
        if geometry.geom_type in _AREA_TYPES:
            geometry = geometry.boundary
        if geometry.geom_type in _LINE_TYPES:
            lines.extend(shapely.get_parts(geometry))
    return np.array(lines, dtype=object)


def _cell_size(bounds: tuple[float, float, float, float], requested: float) -> float:
    width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    cell = requested
    while (width / cell + 3) * (height / cell + 3) > MAX_CELLS:
        cell *= 2
    return cell


def _rasterize(
    lines: NDArray[np.object_],
    origin: tuple[float, float],
    cell: float,
    shape: tuple[int, int],
) -> NDArray[np.bool_]:
    """Отмечает ячейки под линиями; шаг выборки меньше половины ячейки даёт 8-связную цепочку."""
    barrier = np.zeros(shape, dtype=bool)
    if not len(lines):
        return barrier
    lengths = shapely.length(lines)
    counts = np.maximum(2, (lengths / (cell * 0.45)).astype(np.int64) + 1)
    repeated = np.repeat(lines, counts)
    offsets = np.repeat(np.cumsum(counts) - counts, counts)
    position = np.arange(int(counts.sum())) - offsets
    fraction = position / np.repeat(counts - 1, counts)
    xy = shapely.get_coordinates(
        shapely.line_interpolate_point(repeated, fraction, normalized=True)
    )
    cols = np.floor((xy[:, 0] - origin[0]) / cell).astype(np.int64)
    rows = np.floor((xy[:, 1] - origin[1]) / cell).astype(np.int64)
    keep = (rows >= 0) & (rows < shape[0]) & (cols >= 0) & (cols < shape[1])
    barrier[rows[keep], cols[keep]] = True
    return barrier


def _inside(
    extent: BaseGeometry, origin: tuple[float, float], cell: float, shape: tuple[int, int]
) -> NDArray[np.bool_]:
    rows, cols = np.mgrid[0 : shape[0], 0 : shape[1]]
    xs = origin[0] + (cols.ravel() + 0.5) * cell
    ys = origin[1] + (rows.ravel() + 0.5) * cell
    shapely.prepare(extent)
    return shapely.contains_xy(extent, xs, ys).reshape(shape)


def _assign(free: NDArray[np.bool_], seeds: _Seeds) -> NDArray[np.int8]:
    """Материал ближайшего по пути источника: многоисточниковый Дейкстра по сетке 4-связности."""
    height, width = free.shape
    index = np.full(free.shape, -1, dtype=np.int64)
    count = int(free.sum())
    index[free] = np.arange(count)
    pairs = []
    for dr, dc in ((0, 1), (1, 0)):
        a, b = index[: height - dr, : width - dc], index[dr:, dc:]
        keep = (a >= 0) & (b >= 0)
        pairs.append((a[keep], b[keep]))
    a = np.concatenate([p[0] for p in pairs])
    b = np.concatenate([p[1] for p in pairs])
    graph = sparse.coo_matrix((np.ones(len(a)), (a, b)), shape=(count, count)).tocsr()

    rows, cols = seeds.rows, seeds.cols
    valid = (rows >= 0) & (rows < height) & (cols >= 0) & (cols < width)
    nodes = np.full(len(rows), -1, dtype=np.int64)
    nodes[valid] = index[rows[valid], cols[valid]]
    usable = nodes >= 0
    grid = np.full(free.shape, int(Material.UNKNOWN), dtype=np.int8)
    if not usable.any():
        return grid
    seed_nodes, kinds = nodes[usable], seeds.kinds[usable]
    distances, _, sources = dijkstra(
        graph, directed=False, indices=seed_nodes, min_only=True, return_predecessors=True
    )
    kind_by_node = np.zeros(count, dtype=np.int8)
    kind_by_node[seed_nodes] = kinds
    reached = np.isfinite(distances)
    material = np.zeros(count, dtype=np.int8)
    material[reached] = kind_by_node[sources[reached]]
    grid[free] = material
    return grid
