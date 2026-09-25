"""Summarize unresolved raster extents without exposing source coordinates."""

# ruff: noqa: INP001, T201 - local diagnostic for customer CAD

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import ezdxf
from ezdxf.entities import Insert
from ezdxf.entities.image import Image
from shapely.geometry import Polygon, box


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("scope", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    review = json.loads(args.review.read_text())
    bounds = json.loads(args.scope.read_text())["boundary"]["bounds"]
    work_bbox = box(*bounds)
    doc = ezdxf.readfile(args.source)
    rows = []
    for group in review["geometry_gap_groups"]:
        if group["type"] != "IMAGE":
            continue
        for ref in group["refs"]:
            identity = ref.rsplit(":", 1)[-1]
            handle, separator, position = identity.partition("~")
            entity = doc.entitydb.get(handle)
            if separator and isinstance(entity, Insert):
                children = list(entity.virtual_entities())
                entity = children[int(position)] if int(position) < len(children) else None
            if not isinstance(entity, Image):
                rows.append({"ref": ref, "error": "IMAGE entity not found"})
                continue
            vertices = entity.boundary_path_wcs()
            polygon = Polygon((vertex.x, vertex.y) for vertex in vertices)
            rows.append(
                {
                    "ref": ref,
                    "layer": group["layer"],
                    "area_m2": polygon.area,
                    "valid": polygon.is_valid,
                    "intersects_work_bbox": polygon.intersects(work_bbox),
                    "covers_work_bbox": polygon.covers(work_bbox),
                    "clipping": entity.dxf.get("clipping", 0),
                    "clip_mode": entity.dxf.get("clip_mode", 0),
                    "boundary_vertices": len(entity.boundary_path),
                }
            )
    with args.source.open("rb") as stream:
        source_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    result = {
        "source_sha256": source_sha256,
        "images": rows,
        "seconds": round(time.perf_counter() - started, 3),
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print({"images": len(rows), "seconds": result["seconds"], "output": str(args.output)})


if __name__ == "__main__":
    main()
