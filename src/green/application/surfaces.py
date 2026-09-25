"""Покрытия из площадей или замкнутых контуров с непротиворечивыми подписями.

Граница работ не заменяет границы материала. Дерево не доказывает наличие грунта.
Политика distance сохранена для явно запрошенного исследовательского эскиза.
Это интерпретация чертежа, а не обследование физического грунта.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import IntEnum
from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy import sparse
from scipy.ndimage import distance_transform_edt
from scipy.sparse.csgraph import dijkstra

from green.application.approximation import error_bound, inner_area, outer_area, reserved_buffer
from green.application.surface_faces import FaceMaterials, closed_face_materials
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
    closed_faces_mode: bool = True
    closed_faces: int = 0
    conflicting_faces: int = 0
    unassigned_labels: int = 0
    open_edges: int = 0
    unsupported_boundary_faces: int = 0
    # Display raster and exact polygon evidence are kept separate: painting a
    # polygon into a cell must not expand it or erase a sub-cell hole.
    inferred_grid: NDArray[np.int8] | None = field(default=None, repr=False)
    soil_area: BaseGeometry | None = None
    paved_area: BaseGeometry | None = None
    uncertainty_area: BaseGeometry | None = None
    _soil_distances: NDArray[np.float64] | None = field(default=None, init=False, repr=False)

    def material(self, points: NDArray[np.object_]) -> NDArray[np.int8]:
        """Материал под каждой точкой; вне растра UNKNOWN."""
        if not len(points):
            return np.zeros(0, dtype=np.int8)
        rows, cols = self._cells(shapely.get_coordinates(points))
        inside = (
            (rows >= 0) & (rows < self.grid.shape[0]) & (cols >= 0) & (cols < self.grid.shape[1])
        )
        result = np.full(len(points), int(Material.UNKNOWN), dtype=np.int8)
        grid = self.grid if self.inferred_grid is None else self.inferred_grid
        result[inside] = grid[rows[inside], cols[inside]]
        if self.soil_area is not None:
            result[shapely.contains(self.soil_area, points)] = int(Material.SOIL)
        if self.paved_area is not None:
            result[shapely.intersects(self.paved_area, points)] = int(Material.PAVED)
        if self.uncertainty_area is not None:
            result[shapely.intersects(self.uncertainty_area, points)] = int(Material.UNKNOWN)
        return result

    def fits_soil(self, points: NDArray[np.object_], radius_m: float) -> NDArray[np.bool_]:
        """A disk fits exact lawn geometry or a conservative union of inferred cells.

        EDT measures centre-to-centre distance. Subtract the half-diagonal of
        the nearest non-soil cell and the query's offset from its own centre.
        The triangle inequality gives a lower bound on continuous clearance.
        This is deliberately conservative at raster edges; it is not a claim
        that the material inferred from labels is physically correct.
        """
        on_soil = self.material(points) == Material.SOIL
        if radius_m <= 0 or not len(points):
            return on_soil
        fits = np.zeros(len(points), dtype=bool)
        if self.soil_area is not None:
            fits |= shapely.contains(self.soil_area, points) & (
                shapely.distance(points, self.soil_area.boundary) >= radius_m
            )
        grid = self.grid if self.inferred_grid is None else self.inferred_grid
        distances = self._soil_distances
        if distances is None:
            # Outside the finite raster is unknown, even if every cell is soil.
            distances = distance_transform_edt(
                np.pad(grid == Material.SOIL, 1), sampling=self.cell
            )[1:-1, 1:-1]
            object.__setattr__(self, "_soil_distances", distances)
        xy = shapely.get_coordinates(points)
        rows, cols = self._cells(xy)
        inside = (rows >= 0) & (rows < grid.shape[0]) & (cols >= 0) & (cols < grid.shape[1])
        rr, cc = rows[inside], cols[inside]
        centers = np.column_stack((cc + 0.5, rr + 0.5)) * self.cell + self.origin
        offset = np.linalg.norm(xy[inside] - centers, axis=1)
        lower = distances[rr, cc] - self.cell / np.sqrt(2) - offset
        fits[inside] |= (grid[rr, cc] == Material.SOIL) & (lower >= radius_m)
        if self.paved_area is not None:
            fits &= shapely.distance(points, self.paved_area) >= radius_m
        if self.uncertainty_area is not None:
            fits &= shapely.distance(points, self.uncertainty_area) >= radius_m
        return fits & on_soil

    def summary(self) -> dict[str, int | float]:
        counted = {m: int((self.grid == m).sum()) for m in Material}
        return {
            "cell_m": self.cell,
            "seeds_paved": self.seeds_paved,
            "seeds_soil": self.seeds_soil,
            "max_distance_m": self.max_distance_m,
            "ambiguity_m": self.ambiguity_m,
            "tree_distance_m": self.tree_distance_m,
            "closed_faces_mode": int(self.closed_faces_mode),
            "closed_faces": self.closed_faces,
            "conflicting_faces": self.conflicting_faces,
            "unassigned_labels": self.unassigned_labels,
            "open_edges": self.open_edges,
            "unsupported_boundary_faces": self.unsupported_boundary_faces,
            **{f"cells_{m.name.lower()}": counted[m] for m in Material},
        }

    def review_notes(self) -> tuple[str, ...]:
        if not self.closed_faces_mode:
            return ()
        notes = []
        if self.soil_area is None or self.soil_area.is_empty:
            notes.append(
                "Грунт не определён: нужны площади озеленения или замкнутые границы "
                "покрытий с непротиворечивыми подписями."
            )
        if self.conflicting_faces:
            notes.append(
                f"Контуров с противоречивыми подписями покрытий: {self.conflicting_faces}; "
                "грунт в них требует уточнения."
            )
        if self.unassigned_labels:
            notes.append(
                f"Подписей без определённого замкнутого контура: {self.unassigned_labels}; "
                "они не разрешают посадку в соседнем пространстве."
            )
        if self.unsupported_boundary_faces:
            notes.append(
                f"Контуров, замкнутых без подтверждённых границ покрытия: "
                f"{self.unsupported_boundary_faces}; забор, ось дороги или рельсы "
                "не определяют грунт внутри. Уточните роль линий по исходнику."
            )
        return tuple(notes)

    def _cells(self, xy: NDArray[np.float64]) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
        cols = np.floor((xy[:, 0] - self.origin[0]) / self.cell).astype(np.int64)
        rows = np.floor((xy[:, 1] - self.origin[1]) / self.cell).astype(np.int64)
        return rows, cols


def build_surface_map(  # noqa: C901, PLR0913 - explicit evidence stages and named metric limits
    features: Sequence[Feature],
    labels: Sequence[TextLabel],
    extent: BaseGeometry | None,
    cell_m: float,
    *,
    max_distance_m: float = 30.0,
    ambiguity_m: float = 1.0,
    tree_distance_m: float = 2.0,
    inference_mode: str = "closed_faces",
) -> SurfaceMap | None:
    """Use explicit polygons or bounded, competing material evidence; preserve unknowns."""
    if not np.isfinite([cell_m, max_distance_m, ambiguity_m, tree_distance_m]).all():
        raise ValueError("Surface distances must be finite")
    if cell_m <= 0 or max_distance_m <= 0 or ambiguity_m < 0 or tree_distance_m < 0:
        raise ValueError("Invalid surface distance or resolution")
    if inference_mode not in {"closed_faces", "distance"}:
        raise ValueError("Unknown surface inference mode")
    seed_xy, seed_kind = _seeds(features, labels)
    if inference_mode == "closed_faces":
        keep = seed_kind != _TREE_SEED
        seed_xy, seed_kind = seed_xy[keep], seed_kind[keep]
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
    uncertain = _uncertainty_area(features)
    barrier = _rasterize(barriers, origin, cell, shape, uncertain=uncertain)
    free = ~barrier
    if extent is not None:
        free &= _inside(extent, origin, cell, shape)
    soil_area, paved_area = _exact_areas(polygons, extent)
    faces = None
    if inference_mode == "closed_faces":
        faces = _closed_materials(features, seed_xy, seed_kind, uncertain)
        if soil_area is not None:
            # A declared material polygon is independent of label propagation:
            # unfinished separators cannot erase its positive area evidence.
            # A paved label is a real contradiction, including in an unfinished
            # face where it cannot itself establish a known paved area.
            soil_area = soil_area.difference(faces.paved_evidence)
        soil_area = _merge_material_area(soil_area, faces.soil, extent)
        paved_area = _merge_material_area(paved_area, faces.paved, extent)
        grid = np.full(shape, int(Material.UNKNOWN), dtype=np.int8)
    else:
        cols = np.floor((seed_xy[:, 0] - origin[0]) / cell).astype(np.int64)
        rows = np.floor((seed_xy[:, 1] - origin[1]) / cell).astype(np.int64)
        grid = _assign(
            free,
            _Seeds(rows, cols, seed_kind),
            limit=max_distance_m / cell,
            ambiguity=ambiguity_m / cell,
            tree_limit=tree_distance_m / cell,
        )
    soil_area = _soil_polygons(soil_area)
    grid[barrier] = int(Material.BARRIER)
    inferred_grid = grid.copy()
    _paint_materials(grid, (soil_area, paved_area, uncertain), origin, cell)
    return SurfaceMap(
        grid=grid,
        origin=origin,
        cell=cell,
        seeds_paved=paved,
        seeds_soil=soil,
        max_distance_m=max_distance_m,
        ambiguity_m=ambiguity_m,
        tree_distance_m=tree_distance_m,
        inferred_grid=inferred_grid,
        soil_area=soil_area,
        paved_area=paved_area,
        uncertainty_area=uncertain,
        closed_faces_mode=inference_mode == "closed_faces",
        closed_faces=faces.count if faces else 0,
        conflicting_faces=faces.conflicts if faces else 0,
        unassigned_labels=faces.unassigned_labels if faces else 0,
        open_edges=faces.open_edges if faces else 0,
        unsupported_boundary_faces=faces.unsupported_boundaries if faces else 0,
    )


def _soil_polygons(area: BaseGeometry | None) -> BaseGeometry | None:
    # Overlay against touching areas/extent may leave isolated lines or points.
    # They are not positive soil evidence. GeometryCollection.boundary is None,
    # so retaining them would also invalidate clearance inside real polygons.
    if area is None or area.is_empty:
        return None
    if area.geom_type in _AREA_TYPES:
        return area
    pending = [area]
    polygons = []
    while pending:
        part = pending.pop()
        if part.geom_type in _AREA_TYPES:
            polygons.append(part)
        elif part.geom_type == "GeometryCollection":
            pending.extend(shapely.get_parts(part))
    result = shapely.union_all(polygons)
    return None if result.is_empty else result


def _paint_materials(
    grid: NDArray[np.int8],
    areas: tuple[BaseGeometry | None, BaseGeometry | None, BaseGeometry | None],
    origin: tuple[float, float],
    cell: float,
) -> None:
    # Areas have already been clipped to the work extent. Exact query geometry
    # stays separate from this display raster, including sub-cell holes.
    for material, area in zip(
        (Material.SOIL, Material.PAVED, Material.UNKNOWN), areas, strict=True
    ):
        if area is not None:
            grid[_inside(area, origin, cell, grid.shape)] = int(material)


def _closed_materials(
    features: Sequence[Feature],
    seed_xy: NDArray[np.float64],
    seed_kind: NDArray[np.int8],
    uncertain: BaseGeometry | None,
) -> FaceMaterials:
    certain = (
        ~shapely.intersects(uncertain, shapely.points(seed_xy))
        if uncertain is not None
        else np.ones(len(seed_xy), dtype=bool)
    )
    separating_lines = _barrier_lines(
        [f for f in features if f.object_class is not ObjectClass.WORK_BOUNDARY]
    )
    material_lines = _barrier_lines(
        [
            f
            for f in features
            if f.object_class in {ObjectClass.CURB, ObjectClass.PAVEMENT_EDGE, ObjectClass.LAWN}
            or (f.object_class.is_hard_surface and f.geometry.geom_type in _AREA_TYPES)
        ]
    )
    faces = closed_face_materials(
        separating_lines,
        seed_xy[certain & (seed_kind == Material.SOIL)],
        seed_xy[certain & (seed_kind == Material.PAVED)],
        material_lines=material_lines,
    )
    return replace(faces, unassigned_labels=faces.unassigned_labels + int((~certain).sum()))


def _merge_material_area(
    explicit: BaseGeometry | None, inferred: BaseGeometry, extent: BaseGeometry | None
) -> BaseGeometry | None:
    area = shapely.union_all([explicit, inferred])
    if extent is not None:
        area = area.intersection(extent)
    return None if area.is_empty else area


def _exact_areas(
    polygons: Sequence[Feature], extent: BaseGeometry | None
) -> tuple[BaseGeometry | None, BaseGeometry | None]:
    soil = shapely.union_all(
        [inner_area(f) for f in polygons if f.object_class is ObjectClass.LAWN]
    )
    paved = shapely.union_all([outer_area(f) for f in polygons if f.object_class.is_hard_surface])
    if extent is not None:
        soil, paved = soil.intersection(extent), paved.intersection(extent)
    soil = soil.difference(paved)
    return (None if soil.is_empty else soil, None if paved.is_empty else paved)


def _uncertainty_area(features: Sequence[Feature]) -> BaseGeometry | None:
    bands = []
    for feature in features:
        if feature.source_entity_type == "IMAGE" and feature.object_class is not ObjectClass.IGNORE:
            bands.append(feature.geometry)
            continue
        if feature.object_class in {ObjectClass.DRAWING_MASK, ObjectClass.UNCERTAIN_AREA}:
            bands.append(feature.geometry)
            continue
        error = error_bound(feature)
        if not error or not feature.object_class.is_surface_barrier:
            continue
        shape = feature.geometry
        border = shape.boundary if shape.geom_type in _AREA_TYPES else shape
        bands.append(reserved_buffer(border, error))
    return shapely.union_all(bands) if bands else None


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
        if label.surface_role == "ignore":
            continue
        text = label.text.strip().upper().rstrip(".")
        if label.surface_role == "paved" or (label.surface_role == "auto" and text in PAVED_LABELS):
            xy.append((label.x, label.y))
            kind.append(int(Material.PAVED))
        elif label.surface_role == "soil" or (label.surface_role == "auto" and text in SOIL_LABELS):
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
    *,
    uncertain: BaseGeometry | None = None,
) -> NDArray[np.bool_]:
    """Отмечает ячейки под линиями; шаг выборки меньше половины ячейки даёт 8-связную цепочку."""
    barrier = np.zeros(shape, dtype=bool)
    if uncertain is not None:
        # The entire cell must avoid the possible position of a curved border.
        barrier |= _inside(reserved_buffer(uncertain, cell / np.sqrt(2)), origin, cell, shape)
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
