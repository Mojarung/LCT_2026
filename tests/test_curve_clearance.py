"""A chord must not grant extra clearance which the true circular obstacle lacks."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

import ezdxf
import numpy as np
import pytest
import shapely
from shapely.geometry import Point, box
from test_clearance_oracle import pipe, rule
from test_pipeline_synthetic import ROOT

from green.application.approximation import reserved_buffer
from green.application.classification import classify_scene
from green.application.constraints import ConstraintIndex
from green.application.errors import InputError
from green.application.input_quality import require_complete_geometry
from green.application.surfaces import Material, build_surface_map
from green.application.validation import _Objects
from green.domain.norms import MeasureTo
from green.domain.objects import Feature, ObjectClass, SourceRef, TextLabel
from green.domain.planting import Verdict
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("kind", ["CIRCLE", "ARC"])
@pytest.mark.parametrize("scale", [1, 1000])
def test_clearance_never_exceeds_analytic_circle_distance(
    tmp_path: Path, kind: str, scale: int
) -> None:
    doc = ezdxf.new()
    doc.units = 6 if scale == 1 else 4
    radius = 100.0
    if kind == "CIRCLE":
        doc.modelspace().add_circle((0, 0), radius * scale)
    else:
        doc.modelspace().add_arc((0, 0), radius * scale, 0, 90)
    source = tmp_path / "round.dxf"
    doc.saveas(source)
    raw = EzdxfSceneReader(flatten_distance_m=0.1).read(source).features[0]
    feature = replace(raw, object_class=ObjectClass.UTILITY_WATER)
    boundary = feature.geometry.exterior if kind == "CIRCLE" else feature.geometry
    first, second = list(boundary.coords)[:2]
    angle = (math.atan2(first[1], first[0]) + math.atan2(second[1], second[0])) / 2
    true_clearance = 1.96
    point = (
        (radius + true_clearance) * math.cos(angle),
        (radius + true_clearance) * math.sin(angle),
    )
    points = shapely.points([point])
    batch = ConstraintIndex([feature], [rule(MeasureTo.AXIS)], require_utility_data=True).evaluate(
        points
    )
    assert batch.clearance[0, 0] <= true_clearance + 1e-8
    assert batch.verdict(0) is Verdict.FORBIDDEN
    independent = _Objects([feature]).nearby_clearance(points, 2.0, MeasureTo.AXIS)
    assert independent[0] <= true_clearance + 1e-8


@pytest.mark.parametrize("measure", [MeasureTo.AXIS, MeasureTo.OUTER_WALL])
def test_weighted_nearest_reserves_each_objects_error(measure: MeasureTo) -> None:
    rng = np.random.default_rng(703)
    features = [
        replace(pipe(float(x), float(r), str(i)), geometry_error_m=float(error))
        for i, (x, r, error) in enumerate(
            zip(rng.uniform(-20, 20, 30), rng.uniform(0, 2, 30), rng.uniform(0, 2, 30), strict=True)
        )
    ]
    points = shapely.points(rng.uniform(-30, 30, (400, 2)))
    batch = ConstraintIndex(features, [rule(measure)], require_utility_data=True).evaluate(points)
    oracle = np.maximum(
        0,
        np.min(
            [
                shapely.distance(points, f.geometry)
                - f.geometry_error_m
                - ((f.diameter_m or 0) / 2 if measure is MeasureTo.OUTER_WALL else 0)
                for f in features
            ],
            axis=0,
        ),
    )
    np.testing.assert_allclose(batch.clearance[0], oracle, atol=1e-10)
    independent = _Objects(features).nearby_clearance(points, 2.0, measure)
    assert (independent[oracle < 2.0] < 2.0).all()


def area(kind: ObjectClass, error: float) -> Feature:
    return Feature(
        SourceRef("file0000", "00000000", "1"),
        "geometry",
        box(0, 0, 10, 10),
        object_class=kind,
        geometry_error_m=error,
    )


def test_boundary_error_shrinks_the_permitted_footprint() -> None:
    boundary = area(ObjectClass.WORK_BOUNDARY, 0.2)
    index = ConstraintIndex(
        [boundary],
        [],
        require_utility_data=False,
        require_work_boundary=True,
        planting_radius_m=1.0,
    )
    assert index.plantable(shapely.points([(1.1, 5), (1.3, 5)])).tolist() == [False, True]


def test_hard_surface_error_enlarges_the_exclusion() -> None:
    road = area(ObjectClass.ROAD, 0.2)
    index = ConstraintIndex([road], [], require_utility_data=False, planting_radius_m=1.0)
    assert index.plantable(shapely.points([(-1.1, 5), (-1.3, 5)])).tolist() == [False, True]


def test_soil_label_cannot_erase_the_uncertain_boundary_band() -> None:
    lawn = area(ObjectClass.LAWN, 0.2)
    label = TextLabel(lawn.ref, "0", 1, 5, "ГАЗОН")
    surface = build_surface_map([lawn], [label], box(-5, -5, 15, 15), 0.1)
    assert surface is not None
    assert surface.material(shapely.points([(0.1, 5), (0.3, 5)])).tolist() == [
        Material.UNKNOWN,
        Material.SOIL,
    ]
    assert surface.fits_soil(shapely.points([(1.1, 5), (1.3, 5)]), 1.0).tolist() == [False, True]


def test_buffer_corner_reserve_contains_the_exact_distance_ball() -> None:
    center = Point(1, 2)
    envelope = reserved_buffer(center, 3)
    angles = np.linspace(0, math.tau, 1001)
    points = shapely.points(np.column_stack((1 + 3 * np.cos(angles), 2 + 3 * np.sin(angles))))
    assert shapely.covers(envelope, points).all()


@pytest.mark.parametrize("ratio", [0.001, 0.1, 1.0])
@pytest.mark.parametrize("normal", [(0, 0, 1), (0, 1, 1)])
def test_ellipse_error_encloses_dense_native_samples(
    tmp_path: Path, ratio: float, normal: tuple
) -> None:
    doc = ezdxf.new()
    ellipse = doc.modelspace().add_ellipse(
        (100, 200), (150, 0), ratio, dxfattribs={"extrusion": normal}
    )
    source = tmp_path / "ellipse.dxf"
    doc.saveas(source)
    scene = EzdxfSceneReader().read(source, unit="m")
    require_complete_geometry(scene)
    feature = scene.features[0]
    points = shapely.points([(v.x, v.y) for v in ellipse.vertices(np.linspace(0, math.tau, 5001))])
    assert (
        shapely.distance(points, feature.geometry.boundary).max() <= feature.geometry_error_m + 1e-8
    )
    assert scene.read_diagnostics.approximation_features == 1


@pytest.mark.parametrize("kind", ["LW", "POLY"])
@pytest.mark.parametrize("bulge", [0.41421356237309503, -0.41421356237309503, 1, -1, 2, -2])
@pytest.mark.parametrize("normal", [(0, 0, 1), (0, 0, -1)])
def test_bulge_orientation_and_error(
    tmp_path: Path, kind: str, bulge: float, normal: tuple
) -> None:
    doc = ezdxf.new()
    vertices = [(0, 0, bulge), (10, 0, 0), (20, 0, 0)]
    if kind == "LW":
        entity = doc.modelspace().add_lwpolyline(
            vertices, format="xyb", dxfattribs={"extrusion": normal}
        )
    else:
        entity = doc.modelspace().add_polyline2d(
            vertices, format="xyb", dxfattribs={"extrusion": normal}
        )
    source = tmp_path / "bulge.dxf"
    doc.saveas(source)
    scene = EzdxfSceneReader().read(source, unit="m")
    require_complete_geometry(scene)
    feature = scene.features[0]
    arc = next(entity.virtual_entities())
    truth = shapely.points([(v.x, v.y) for v in arc.flattening(0.00001)])
    assert feature.geometry.geom_type == "LineString"
    assert tuple(feature.geometry.coords[0]) == pytest.approx((0, 0))
    assert tuple(feature.geometry.coords[-1]) == pytest.approx((20 * normal[2], 0))
    assert shapely.distance(truth, feature.geometry).max() <= feature.geometry_error_m + 1e-8


def test_exact_tree_center_has_no_outline_approximation_error(tmp_path: Path) -> None:
    doc = ezdxf.new()
    doc.layers.add("Отдельно стоящее дерево")
    doc.modelspace().add_circle(
        (123, 456), 5, dxfattribs={"layer": "Отдельно стоящее дерево", "extrusion": (0, 0, -1)}
    )
    source = tmp_path / "tree.dxf"
    doc.saveas(source)
    raw = EzdxfSceneReader().read(source, unit="m")
    assert raw.features[0].geometry_error_m > 0
    scene, _ = classify_scene(raw, YamlLayerMapSource(ROOT / "config/layer_map.yaml").load())
    assert scene.features[0].geometry.equals(Point(-123, 456))
    assert scene.features[0].geometry_error_m == 0


def test_unbounded_spline_is_rejected(tmp_path: Path) -> None:
    doc = ezdxf.new()
    doc.modelspace().add_spline([(0, 0), (5, 8), (10, 0)])
    source = tmp_path / "unbounded.dxf"
    doc.saveas(source)
    scene = EzdxfSceneReader().read(source, unit="m")
    assert len(scene.features) == 1
    assert scene.features[0].geometry_error_m is None
    with pytest.raises(InputError, match="approximation-error-not-bounded"):
        require_complete_geometry(scene)


def test_self_crossing_ring_is_filled_even_odd_as_a_hatch(tmp_path: Path) -> None:
    """«Восьмёрка» из замкнутой полилинии - заливка чёт-нечет, как у штриховки (решение
    пользователя 25.09.2026): те же линии контура, погрешность прежняя, исход помечен."""
    doc = ezdxf.new()
    doc.modelspace().add_lwpolyline([(0, 0), (5, 5), (0, 5), (5, 0)], close=True)
    source = tmp_path / "bowtie.dxf"
    doc.saveas(source)
    scene = EzdxfSceneReader().read(source, unit="m")
    require_complete_geometry(scene)
    (feature,) = scene.features
    assert feature.geometry.is_valid
    assert feature.geometry.area == pytest.approx(12.5)
    assert feature.geometry_error_m == 0.0
    assert scene.read_diagnostics.outcomes["feature:even-odd"] == 1


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("zero_line", {"Point"}), ("folded_ring", {"LineString", "MultiLineString"})],
)
def test_exact_repair_of_degenerate_drawing_keeps_its_bound(
    tmp_path: Path, kind: str, expected: set[str]
) -> None:
    """Отрезок нулевой длины - точка, сложенный контур нулевой площади - линия: починка не
    меняет нарисованного, и погрешность остаётся ограниченной (Куликовская: 455 таких
    отрезков останавливали строгий прогон)."""
    doc = ezdxf.new()
    if kind == "zero_line":
        doc.modelspace().add_line((5, 5), (5, 5))
    else:
        doc.modelspace().add_lwpolyline([(0, 0), (10, 0), (5, 0)], close=True)
    source = tmp_path / f"{kind}.dxf"
    doc.saveas(source)

    scene = EzdxfSceneReader().read(source, unit="m")

    assert scene.read_diagnostics.geometry_gaps == ()
    (feature,) = scene.features
    assert feature.geometry.geom_type in expected
    assert feature.geometry_error_m == 0.0
