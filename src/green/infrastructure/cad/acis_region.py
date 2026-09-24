"""Область REGION: плоский полигон из данных ACIS (SAT в DXF 2000, SAB в DXF 2013+).

REGION хранит форму не в группах DXF, а в ядре ACIS: грани, петли, рёбра и кривые. В выгрузках
Мосгеотреста так записаны газоны, ограды, лестницы и участки сетей. ezdxf разбирает ACIS, но из
кривых знает только прямую; дуги и окружности (ellipse-curve) разбираются здесь.

Дуга заменяется ломаной, и граница ошибки честная: наибольший прогиб хорды не больше `flatten`.
Кривые других типов (сплайны intcurve) и неплоские области не угадываются - это пробел
с причиной, как у ридера для прочих неподдержанных сущностей.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import shapely
from ezdxf.acis import api as acis
from ezdxf.acis import entities as acis_entities
from ezdxf.acis.const import AcisException
from ezdxf.math import Matrix44, Vec3
from shapely.geometry import Polygon

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ezdxf.entities import Body
    from shapely.geometry.base import BaseGeometry

# Допуск «лежит в одной плоскости с планом»: высоты вершин области различаются не больше.
_FLAT_Z = 1e-6
# С версии SAT 700 у записи третьим полем идёт номер («-1» - без номера).
_SAT_WITH_IDS = 700
_ID_FIELD = 2


class RegionGeometryError(ValueError):
    """Форму области не удалось получить; reason попадает в пробелы чтения."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@acis_entities.register
class EllipseCurve(acis_entities.Curve):
    """ACIS ellipse-curve: P(t) = центр + большая ось cos t + малая ось sin t.

    Малая ось = отношение * (нормаль x большая ось). Окружность - отношение 1.
    """

    type: str = "ellipse-curve"
    center = Vec3()
    normal = Vec3(0, 0, 1)
    major = Vec3(1, 0, 0)
    ratio = 1.0

    def restore_data(self, loader: acis_entities.DataLoader) -> None:
        self.center = Vec3(loader.read_vec3())
        self.normal = Vec3(loader.read_vec3())
        self.major = Vec3(loader.read_vec3())
        self.ratio = loader.read_double()
        super().restore_data(loader)

    @property
    def minor(self) -> Vec3:
        return self.normal.normalize().cross(self.major) * self.ratio

    def evaluate(self, param: float) -> Vec3:
        return self.center + self.major * math.cos(param) + self.minor * math.sin(param)

    def param_of(self, point: Vec3) -> float:
        offset = point - self.center
        major, minor = self.major, self.minor
        return math.atan2(
            offset.dot(minor) / minor.magnitude_square, offset.dot(major) / major.magnitude_square
        )


def region_polygon(
    entity: Body, matrix: Matrix44 | None, flatten: float
) -> tuple[BaseGeometry, float]:
    """Полигон области в координатах чертежа и наибольшая ошибка аппроксимации дуг.

    matrix - преобразование вставки, внутри которой лежит область (None - пространство модели).
    """
    sab, sat = entity.sab, entity.sat
    if not sat and not sab:
        raise RegionGeometryError("missing-acis-data")
    try:
        bodies = acis.load(bytes(sab) if sab else _normalized_sat(sat))
    except (AcisException, ValueError, IndexError, KeyError, TypeError) as error:
        # Разбор ACIS - чужой формат с вариантами версий: ошибка разбора - пробел с
        # причиной, а не падение всего чтения.
        raise RegionGeometryError(f"acis-not-parsed:{type(error).__name__}") from error
    polygons: list[Polygon] = []
    error = 0.0
    for body in bodies:
        transform = _body_matrix(body)
        if matrix is not None:
            transform = transform @ matrix if transform is not None else matrix
        for face in _faces(body):
            rings = []
            for loop in face.loops():
                points, loop_error = _loop_points(loop, flatten)
                error = max(error, loop_error)
                rings.append(_to_plan(points, transform))
            polygons.append(_face_polygon(rings))
    if not polygons:
        raise RegionGeometryError("no-faces")
    area = shapely.union_all(polygons)
    if area.is_empty:
        raise RegionGeometryError("empty-area")
    return area, error


def _normalized_sat(lines: Sequence[str]) -> list[str]:
    """SAT ASM AutoCAD (версии 21200 и новее в DXF 2004-2010) пишет номер записи указателем.

    ezdxf для версий от 700 ждёт третьим полем число («body $-1 -1 ...»), а AutoCAD пишет
    «body $-1 $-1 ...». Смысл поля тот же - «нет номера», меняется только запись.
    """
    header = lines[0].split()
    if not header or not header[0].isdigit() or int(header[0]) < _SAT_WITH_IDS:
        return list(lines)
    fixed = list(lines[:3])
    for line in lines[3:]:
        tokens = line.split(" ")
        if len(tokens) > _ID_FIELD and tokens[_ID_FIELD] == "$-1":
            tokens[_ID_FIELD] = "-1"
        fixed.append(" ".join(tokens))
    return fixed


def _body_matrix(body: acis_entities.Body) -> Matrix44 | None:
    transform = body.transform
    if transform.is_none:
        return None
    return transform.matrix


def _faces(body: acis_entities.Body) -> list[acis_entities.Face]:
    return [face for lump in body.lumps() for shell in lump.shells() for face in shell.faces()]


def _loop_points(loop: acis_entities.Loop, flatten: float) -> tuple[list[Vec3], float]:
    points: list[Vec3] = []
    error = 0.0
    for coedge in loop.coedges():
        edge = coedge.edge
        start = edge.start_vertex.point.location
        end = edge.end_vertex.point.location
        curve = edge.curve
        if isinstance(curve, EllipseCurve):
            segment = _arc(curve, start, end, reversed_edge=edge.sense, flatten=flatten)
            error = max(error, flatten)
        elif isinstance(curve, acis_entities.StraightCurve):
            segment = [start, end]
        else:
            raise RegionGeometryError(f"unsupported-curve:{curve.type}")
        if coedge.sense:  # coedge идёт против ребра
            segment.reverse()
        if points and points[-1].isclose(segment[0], abs_tol=1e-9):
            segment = segment[1:]
        points.extend(segment)
    return points, error


def _arc(
    curve: EllipseCurve, start: Vec3, end: Vec3, *, reversed_edge: bool, flatten: float
) -> list[Vec3]:
    """Точки ребра по кривой от начальной вершины к конечной.

    Ребро «forward» идёт по возрастанию параметра кривой, «reversed» - по убыванию. Совпавшие
    вершины - полный оборот.
    """
    t0, t1 = curve.param_of(start), curve.param_of(end)
    if reversed_edge:
        while t1 >= t0:
            t1 -= math.tau
        if math.isclose(t0 - t1, math.tau) and not start.isclose(end, abs_tol=1e-9):
            t1 += math.tau
    else:
        while t1 <= t0:
            t1 += math.tau
        if math.isclose(t1 - t0, math.tau) and not start.isclose(end, abs_tol=1e-9):
            t1 -= math.tau
    radius = max(curve.major.magnitude, curve.minor.magnitude)
    step = 2 * math.acos(max(-1.0, 1 - flatten / radius)) if radius > flatten else math.pi / 2
    count = max(2, math.ceil(abs(t1 - t0) / step) + 1)
    points = [curve.evaluate(t0 + (t1 - t0) * i / (count - 1)) for i in range(count)]
    points[0], points[-1] = start, end
    return points


def _to_plan(points: list[Vec3], transform: Matrix44 | None) -> list[tuple[float, float]]:
    world = list(transform.transform_vertices(points)) if transform is not None else points
    heights = [p.z for p in world]
    if heights and max(heights) - min(heights) > _FLAT_Z * max(1.0, *map(abs, heights)):
        raise RegionGeometryError("non-planar-to-plan")
    return [(p.x, p.y) for p in world]


def _face_polygon(rings: list[list[tuple[float, float]]]) -> Polygon:
    """Внешняя петля - наибольшая по площади, остальные внутри неё - дырки."""
    closed = [ring for ring in rings if len(ring) >= 3]  # noqa: PLR2004 - треугольник минимум
    if not closed:
        raise RegionGeometryError("degenerate-loop")
    shells = sorted((Polygon(ring) for ring in closed), key=lambda p: -abs(p.area))
    outer = shells[0]
    holes = [p.exterior.coords for p in shells[1:] if outer.contains(p.representative_point())]
    polygon = Polygon(outer.exterior.coords, holes)
    return polygon if polygon.is_valid else shapely.make_valid(polygon)
