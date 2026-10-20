"""Обрезка выемок покрытия не роняет surface.json на вырожденном кольце чужого чертежа."""

from __future__ import annotations

import shapely
from shapely.geometry import box

from green.infrastructure.reports import artifacts


def test_clip_retries_with_make_valid(monkeypatch) -> None:  # noqa: ANN001 - фикстура pytest
    real = shapely.clip_by_rect
    calls: list[bool] = []

    def flaky(geometry, *bounds):  # noqa: ANN001, ANN002, ANN202 - подмена GEOS
        calls.append(True)
        if len(calls) == 1:
            message = "IllegalArgumentException: Invalid number of points in LinearRing found 3"
            raise shapely.errors.GEOSException(message)
        return real(geometry, *bounds)

    monkeypatch.setattr(artifacts.shapely, "clip_by_rect", flaky)
    clipped = artifacts._clipped(box(0, 0, 10, 10), (0, 0, 5, 5))  # noqa: SLF001

    assert len(calls) == 2
    assert clipped.area == 25
