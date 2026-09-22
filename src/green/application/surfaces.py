"""Карта покрытий из топоплана: где грунт, а где асфальт, плитка или проезжая часть.

Топоплан Геотреста не содержит полигонов покрытий: есть линии, по которым покрытие
меняется (борт, граница покрытия, стены, ограды, граница растительности), и подписи
материала внутри участков («А» асфальт, «Ц» цементобетон, «ПЛ» плитка, «ГАЗОН»).
Карта строится на растре: линии становятся барьерами, подписи и условные знаки
деревьев источниками. Свидетельство действует на ограниченном расстоянии по пути
в обход барьеров. Конкурирующие метки дают UNKNOWN, явные полигоны задают покрытие
в своих границах. Это интерпретация чертежа, а не обследование физического грунта.
"""

from __future__ import annotations

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
MAX_CELLS = 20_000_000
_LINE_TYPES = frozenset({"LineString", "MultiLineString"})
_AREA_TYPES = frozenset({"Polygon", "MultiPolygon"})
_TREE_SEED = 4


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
    max_distance_m: float = 30.0
    ambiguity_m: float = 1.0
    tree_distance_m: float = 2.0

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
            "max_distance_m": self.max_distance_m,
            "ambiguity_m": self.ambiguity_m,
            "tree_distance_m": self.tree_distance_m,
            **{f"cells_{m.name.lower()}": counted[m] for m in Material},
        }

    def _cells(self, xy: NDArray[np.float64]) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
        cols = np.floor((xy[:, 0] - self.origin[0]) / self.cell).astype(np.int64)
        rows = np.floor((xy[:, 1] - self.origin[1]) / self.cell).astype(np.int64)
        return rows, cols


def build_surface_map(  # noqa: PLR0913 - independent named evidence limits, in metres
    features: Sequence[Feature],
    labels: Sequence[TextLabel],
    extent: BaseGeometry | None,
    cell_m: float,
    *,
    max_distance_m: float = 30.0,
    ambiguity_m: float = 1.0,
    tree_distance_m: float = 2.0,
) -> SurfaceMap | None:
    """Use explicit polygons or bounded, competing material evidence; preserve unknowns."""
    if not np.isfinite([cell_m, max_distance_m, ambiguity_m, tree_distance_m]).all():
        raise ValueError("Surface distances must be finite")
    if cell_m <= 0 or max_distance_m <= 0 or ambiguity_m < 0 or tree_distance_m < 0:
        raise ValueError("Invalid surface distance or resolution")
    seed_xy, seed_kind = _seeds(features, labels)
    paved = int((seed_kind == Material.PAVED).sum())
    soil = int(np.isin(seed_kind, [Material.SOIL, _TREE_SEED]).sum())
    polygons = [
        f
        for f in features
        if f.geometry.geom_type in _AREA_TYPES
        and (f.object_class is ObjectClass.LAWN or f.object_class.is_hard_surface)
    ]
    if not len(seed_xy) and not polygons:
        return None
    barriers = _barrier_lines(features)
    if extent is not None and not extent.is_empty:
        bounds = extent.bounds
    else:
        geometry = [f.geometry for f in features if not f.geometry.is_empty]
        geometry.extend(shapely.points(seed_xy))
        bounds = tuple(shapely.total_bounds(geometry))
    if not np.isfinite(bounds).all():
        return None
    cell = _cell_size(bounds, cell_m)
    origin = (float(bounds[0]) - cell, float(bounds[1]) - cell)
    shape = (int((bounds[3] - bounds[1]) / cell) + 3, int((bounds[2] - bounds[0]) / cell) + 3)
    barrier = _rasterize(barriers, origin, cell, shape)
    free = ~barrier
    if extent is not None:
        free &= _inside(extent, origin, cell, shape)
    cols = np.floor((seed_xy[:, 0] - origin[0]) / cell).astype(np.int64)
    rows = np.floor((seed_xy[:, 1] - origin[1]) / cell).astype(np.int64)
    grid = _assign(
        free,
        _Seeds(rows, cols, seed_kind),
        limit=max_distance_m / cell,
        ambiguity=ambiguity_m / cell,
        tree_limit=tree_distance_m / cell,
    )
    grid[barrier] = int(Material.BARRIER)
    # Explicit polygons keep holes. Hard material wins over competing lawn geometry.
    for material, predicate in (
        (Material.SOIL, lambda f: f.object_class is ObjectClass.LAWN),
        (Material.PAVED, lambda f: f.object_class.is_hard_surface),
    ):
        areas = [f.geometry for f in polygons if predicate(f)]
        if areas:
            mask = _inside(shapely.union_all(areas), origin, cell, shape)
            if extent is not None:
                mask &= _inside(extent, origin, cell, shape)
            grid[mask] = int(material)
    return SurfaceMap(
        grid=grid,
        origin=origin,
        cell=cell,
        seeds_paved=paved,
        seeds_soil=soil,
        max_distance_m=max_distance_m,
        ambiguity_m=ambiguity_m,
        tree_distance_m=tree_distance_m,
    )


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
        text = label.text.strip().upper().rstrip(".")
        if text in PAVED_LABELS:
            xy.append((label.x, label.y))
            kind.append(int(Material.PAVED))
        elif text in SOIL_LABELS:
            xy.append((label.x, label.y))
            kind.append(int(Material.SOIL))
    trees = [f.geometry for f in features if f.object_class is ObjectClass.EXISTING_TREE]
    if trees:
        centers = shapely.get_coordinates(shapely.centroid(np.array(trees, dtype=object)))
        xy.extend(map(tuple, centers))
        kind.extend([_TREE_SEED] * len(centers))
    coordinates = np.array(xy, dtype=np.float64).reshape(-1, 2)
    kinds = np.array(kind, dtype=np.int8)
    finite = np.isfinite(coordinates).all(axis=1)
    return coordinates[finite], kinds[finite]


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


def _assign(
    free: NDArray[np.bool_],
    seeds: _Seeds,
    *,
    limit: float,
    ambiguity: float,
    tree_limit: float,
) -> NDArray[np.int8]:
    """Bounded distance per material; competition is independent of seed ordering."""
    grid = np.full(free.shape, int(Material.UNKNOWN), dtype=np.int8)
    if not free.any() or not len(seeds.rows):
        return grid
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
    if not usable.any():
        return grid
    seed_nodes, kinds = nodes[usable], seeds.kinds[usable]

    def distances(kind: int, reach: float) -> NDArray[np.float64]:
        sources = np.unique(seed_nodes[kinds == kind])
        if not len(sources):
            return np.full(count, np.inf)
        return dijkstra(graph, directed=False, indices=sources, min_only=True, limit=reach)

    paved = distances(Material.PAVED, limit)
    soil = np.minimum(distances(Material.SOIL, limit), distances(_TREE_SEED, tree_limit))
    material = np.zeros(count, dtype=np.int8)
    material[paved + ambiguity < soil] = int(Material.PAVED)
    material[soil + ambiguity < paved] = int(Material.SOIL)
    grid[free] = material
    return grid
