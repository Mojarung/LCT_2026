"""Inspect unresolved HATCH paths without exporting proprietary CAD coordinates."""

# ruff: noqa: INP001, T201 - local diagnostic of source HATCH topology

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import time
from collections import Counter
from pathlib import Path

import ezdxf
import shapely
from ezdxf import bbox
from ezdxf.entities.boundary_paths import EdgePath, PolylinePath
from ezdxf.entities.polygon import DXFPolygon
from shapely.geometry import Polygon, box

from green.infrastructure.cad.hatch_geometry import HatchGeometryError, _path_polygon


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("--scope", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    review = json.loads(args.review.read_text())
    work_bounds = json.loads(args.scope.read_text())["boundary"]["bounds"] if args.scope else None
    work_bbox = box(*work_bounds) if work_bounds else None
    handles = {
        ref.rsplit(":", 1)[-1].split("~", 1)[0]
        for group in review["geometry_gap_groups"]
        if group["type"] == "HATCH"
        for ref in group["refs"]
    }
    doc = ezdxf.readfile(args.source)
    rows = []
    for handle in sorted(handles):
        entity = doc.entitydb.get(handle)
        if not isinstance(entity, DXFPolygon) or entity.dxftype() != "HATCH":
            rows.append({"handle": handle, "error": "HATCH entity not found"})
            continue
        paths = list(entity.paths.rendering_paths(entity.dxf.hatch_style))
        extent = bbox.extents([entity], fast=True)
        footprint = (
            box(extent.extmin.x, extent.extmin.y, extent.extmax.x, extent.extmax.y)
            if extent.has_data
            else None
        )
        samples = []
        for path in paths:
            entry = {
                "path_type": type(path).__name__,
                "flags": path.path_type_flags,
                "source_boundaries": len(path.source_boundary_objects),
            }
            if isinstance(path, EdgePath):
                entry["edge_types"] = dict(Counter(type(edge).__name__ for edge in path.edges))
            elif isinstance(path, PolylinePath):
                entry["nonzero_bulges"] = sum(bulge != 0 for _, _, bulge in path.vertices)
            try:
                polygon, error, vertices = _path_polygon(entity, path, 0.1, 0.002)
            except HatchGeometryError as failure:
                entry["error"] = str(failure)
            else:
                entry.update(
                    sampled_vertices=vertices,
                    curve_error_m=error,
                    source_area_m2=polygon.area,
                    valid=polygon.is_valid,
                    validity=shapely.is_valid_reason(polygon).split("[")[0],
                )
                if not polygon.is_valid:
                    repaired = shapely.make_valid(polygon)
                    parts = list(shapely.get_parts(repaired))
                    entry["repair_parts"] = [
                        {
                            "type": part.geom_type,
                            "area_m2": part.area if isinstance(part, Polygon) else None,
                            "length_m": part.length,
                        }
                        for part in parts
                    ]
            samples.append(entry)
        rows.append(
            {
                "handle": handle,
                "layer": entity.dxf.layer,
                "hatch_style": entity.dxf.hatch_style,
                "solid_fill": entity.dxf.solid_fill,
                "associative": entity.dxf.associative,
                "rendered_paths": len(paths),
                "path_bbox_area_m2": footprint.area if footprint is not None else None,
                "intersects_work_bbox": footprint.intersects(work_bbox)
                if footprint is not None and work_bbox is not None
                else None,
                "paths": samples,
            }
        )
    result = {
        "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "hatches": rows,
        "seconds": round(time.perf_counter() - started, 3),
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print({"hatches": len(rows), "seconds": result["seconds"], "output": str(args.output)})


if __name__ == "__main__":
    main()
