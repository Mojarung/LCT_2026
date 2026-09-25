"""Full XY footprint of an external raster reference, regardless of clipping."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ezdxf.math import Vec3
from shapely.geometry import Polygon

if TYPE_CHECKING:
    from ezdxf.entities.image import Image


def image_footprint(image: Image) -> Polygon | None:
    """The whole image frame encloses every visible clipped pixel."""
    try:
        width, height = image.dxf.image_size.x, image.dxf.image_size.y
        if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
            return None
        origin = Vec3(image.dxf.insert)
        horizontal = Vec3(image.dxf.u_pixel) * width
        vertical = Vec3(image.dxf.v_pixel) * height
        corners = (origin, origin + horizontal, origin + horizontal + vertical, origin + vertical)
        if not all(
            math.isfinite(value) for point in corners for value in (point.x, point.y, point.z)
        ):
            return None
        footprint = Polygon((point.x, point.y) for point in corners)
    except ArithmeticError, AttributeError, TypeError, ValueError:
        return None
    return footprint if footprint.is_valid and footprint.area > 0 else None
