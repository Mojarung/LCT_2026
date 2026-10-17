"""Скоркарта «похоже на практику проектировщиков»: application/likeness.py, config/likeness.json."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Polygon

from green.application.likeness import LikenessModel, likeness_model
from green.domain.objects import Feature, ObjectClass, SourceRef

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = likeness_model(json.loads((ROOT / "config" / "likeness.json").read_text("utf-8")))


def _feature(cls: ObjectClass, geometry: object) -> Feature:
    return Feature(SourceRef("f", "x", str(id(geometry))), cls.value, geometry, object_class=cls)  # type: ignore[arg-type]


def _street() -> list[Feature]:
    """Борт по y=0, газон 0..12 м, дом с y=20."""
    return [
        _feature(ObjectClass.CURB, LineString([(-50, 0), (50, 0)])),
        _feature(ObjectClass.LAWN, Polygon([(-50, 0), (50, 0), (50, 12), (-50, 12)])),
        _feature(ObjectClass.BUILDING, Polygon([(-50, 20), (50, 20), (50, 40), (-50, 40)])),
    ]


def test_a_tree_on_the_lawn_beats_one_at_the_kerb_and_one_off_the_lawn() -> None:
    xy = np.array([[0.0, 6.0], [0.0, 0.5], [0.0, 16.0]])
    on_lawn, at_kerb, off_lawn = SHIPPED.probability(xy, _street()).tolist()
    assert on_lawn > at_kerb
    assert on_lawn > off_lawn
    assert all(0.0 < p < 1.0 for p in (on_lawn, at_kerb, off_lawn))


def test_terms_are_summed_as_printed() -> None:
    model = LikenessModel(
        classes=("curb",),
        edges=(0.0, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0),
        terms={"curb 2-3 м": 1.0, "на газоне": 0.5, "глубина в газоне 2-4 м": 0.25},
        intercept=-1.0,
    )
    p = model.probability(np.array([[0.0, 2.5]]), _street())[0]
    logit = -1.0 + 1.0 + 0.5 + 0.25
    assert p == np.float64(1 / (1 + np.exp(-logit)))
