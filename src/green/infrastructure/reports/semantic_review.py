"""Lossless imported geometry for semantic review; never a planting certificate."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import asdict
from typing import TYPE_CHECKING

import orjson
from shapely.geometry import mapping

from green.domain.objects import ClassificationEvidence

if TYPE_CHECKING:
    from pathlib import Path

    from green.application.classification import ClassificationReport
    from green.domain.objects import Scene


def save_review_geometry(
    directory: Path, report: ClassificationReport, scene: Scene, source: Path | None
) -> dict[str, Path]:
    groups = {
        (g.layer, g.block, g.geometry, g.object_class, g.evidence): i
        for i, g in enumerate(report.groups)
    }
    payload = {
        "type": "FeatureCollection",
        "source_sha256": scene.source_sha256,
        "units": "metres",
        "scope": "Imported computational XY geometry, local CAD coordinates, not WGS84. "
        "No simplification or feature sampling. Assignments are input interpretation, "
        "not measured accuracy, complete survey or planting approval.",
        "features": [
            {
                "type": "Feature",
                "id": str(f.ref),
                "geometry": mapping(f.geometry),
                "properties": {
                    "group": groups[
                        (
                            f.layer,
                            f.block,
                            f.geometry.geom_type,
                            f.object_class,
                            f.classification or ClassificationEvidence("unmatched"),
                        )
                    ],
                    "class": f.object_class.value,
                    "error_m": f.geometry_error_m,
                    "source_entity_type": f.source_entity_type,
                    "uncertain_footprint": f.uncertain_footprint,
                    "read_only": f.uncertain_footprint or f.source_entity_type == "WIPEOUT",
                    "symbol_parts": [str(ref) for ref in f.symbol_parts],
                    "symbol_layers": list(f.symbol_layers),
                    "bounds": f.geometry.bounds,
                },
            }
            for f in scene.features
        ],
        "labels": [
            {
                "id": str(label.ref),
                "layer": label.layer,
                "block": label.block,
                "block_chain": label.block_chain,
                "x": label.x,
                "y": label.y,
                "text": label.text,
                "surface_role": label.surface_role,
                "evidence": asdict(label.surface_evidence) if label.surface_evidence else None,
            }
            for label in scene.labels
        ],
    }
    geometry = directory / "semantic-review.geojson"
    geometry.write_bytes(orjson.dumps(payload))
    saved = {geometry.name: geometry}
    if source is not None:
        # Re-uploading this exact computational DXF also works after DWG
        # conversion or XREF assembly. Refuse to publish a stale/different copy.
        temporary = directory / ".review-input.dxf.tmp"
        try:
            shutil.copyfile(source, temporary)
            with temporary.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest == scene.source_sha256:
                drawing = directory / "review-input.dxf"
                temporary.replace(drawing)
                saved[drawing.name] = drawing
        finally:
            temporary.unlink(missing_ok=True)
    return saved
