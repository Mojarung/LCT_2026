"""Independent dense evaluation and refusal cases for experimental exact spline bounds."""
# ruff: noqa: INP001, T201, S101 -- standalone reproducible experiment

from __future__ import annotations

import argparse
import json
import math
import time
from itertools import pairwise
from pathlib import Path

import numpy as np
import shapely
from experimental_spline import flatten_spline
from scipy.interpolate import BSpline


def cases() -> list[tuple[str, np.ndarray, list[float], int, list[float]]]:
    rng = np.random.default_rng(739)
    return [
        ("cubic_s", np.array([(0, 0), (20, 180), (80, -180), (100, 0)]), [0] * 4 + [1] * 4, 3, []),
        (
            "collinear_backtrack",
            np.array([(0, 0), (100, 0), (-100, 0), (0, 0)]),
            [0] * 4 + [1] * 4,
            3,
            [],
        ),
        ("coincident", np.array([(12, 13)] * 4), [0] * 4 + [1] * 4, 3, []),
        (
            "quarter_circle",
            np.array([(100, 0), (100, 100), (0, 100)]),
            [0] * 3 + [1] * 3,
            2,
            [1, math.sqrt(0.5), 1],
        ),
        (
            "rational_cubic",
            np.array([(0, 0), (20, 180), (80, -180), (100, 0)]),
            [0] * 4 + [1] * 4,
            3,
            [1, 0.0001, 7, 1],
        ),
        (
            "multispan",
            rng.uniform(-100, 100, (8, 2)),
            [0] * 4 + [0.2, 0.4, 0.6, 0.8] + [1] * 4,
            3,
            [],
        ),
        (
            "close_knots",
            rng.uniform(-100, 100, (8, 2)),
            [0] * 4 + [0.2, 0.2 + 1e-12, 0.6, 0.8] + [1] * 4,
            3,
            [1, 0.1, 1, 3, 1, 0.4, 7, 1],
        ),
        ("degree_eight", rng.uniform(-100, 100, (9, 2)), [0] * 9 + [1] * 9, 8, []),
        (
            "linear_multispan",
            np.array([(0, 0), (100, 0), (100, 20), (200, 20)]),
            [0, 0, 0.3, 0.7, 1, 1],
            1,
            [],
        ),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for name, xy, knots, degree, weights in cases():
        for pose, scale, angle, shift in (
            ("base", 1, 0, 0),
            ("posed", 1, 113, 1e6),
            ("mm", 1000, -37, 1e8),
        ):
            c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            control = xy @ np.array([[c, s], [-s, c]]) * scale + [shift, -shift]
            begin = time.perf_counter()
            points = flatten_spline(control.tolist(), knots, degree, weights, distance=0.1 * scale)
            seconds = time.perf_counter() - begin
            w = np.array(weights or [1] * len(control))
            # This evaluator does not use the experimental insertion/subdivision code.
            basis = BSpline(knots, np.column_stack((control * w[:, None], w)), degree)
            values = np.unique(knots)
            parameters = np.unique(
                np.concatenate(
                    [
                        np.linspace(0, 1, 10001),
                        *[np.linspace(a, b, 129) for a, b in pairwise(values)],
                    ]
                )
            )
            homogeneous = basis(parameters)
            truth = homogeneous[:, :2] / homogeneous[:, 2, None]
            distances = shapely.distance(shapely.points(truth), shapely.LineString(points)) / scale
            maximum = float(distances.max())
            assert maximum <= 0.1 + 1e-7, (name, pose, maximum)
            row = {
                "case": name,
                "pose": pose,
                "vertices": len(points),
                "max_sample_error_m": maximum,
                "bound_m": 0.1,
                "seconds": round(seconds, 6),
            }
            rows.append(row)
            print(row, flush=True)
    invalid = [
        ("negative_weight", [(0, 0), (1, 1), (2, 0)], [0, 0, 0, 1, 1, 1], 2, [1, -1, 1], 0.1, 4096),
        ("zero_weight", [(0, 0), (1, 1), (2, 0)], [0, 0, 0, 1, 1, 1], 2, [1, 0, 1], 0.1, 4096),
        ("periodic", [(0, 0), (1, 1), (2, 0)], [0, 1, 2, 3, 4, 5], 2, [], 0.1, 4096),
        ("discontinuous", [(0, 0)] * 6, [0, 0, 0, 0.5, 0.5, 0.5, 1, 1, 1], 2, [], 0.1, 4096),
        ("unordered", [(0, 0), (1, 1), (2, 0)], [0, 0, 0, 1, -1, 1], 2, [], 0.1, 4096),
        ("budget", [(0, 0), (1, 100), (2, 0)], [0, 0, 0, 1, 1, 1], 2, [], 0.0001, 2),
        ("nonfinite", [(0, 0), (1, math.nan), (2, 0)], [0, 0, 0, 1, 1, 1], 2, [], 0.1, 4096),
        ("zero_tolerance", [(0, 0), (1, 1), (2, 0)], [0, 0, 0, 1, 1, 1], 2, [], 0, 4096),
    ]
    rejected = []
    for name, control, knots, degree, weights, distance, budget in invalid:
        try:
            flatten_spline(control, knots, degree, weights, distance=distance, max_vertices=budget)
        except ValueError as error:
            rejected.append({"case": name, "reason": str(error)})
        else:
            raise AssertionError(f"Unsafe or unsupported input accepted: {name}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "scope": (
                    "Experimental clamped positive-weight NURBS only; not connected to the reader. "
                    "Dense independent samples test implementation, not a substitute for "
                    "the exact convex-hull bound. No source CAD or survey-accuracy claim."
                ),
                "rows": rows,
                "rejected": rejected,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print({"passed": len(rows), "rejected_as_expected": len(rejected)})


if __name__ == "__main__":
    main()
