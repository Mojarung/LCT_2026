"""Count how much of a converted REGION's inline SAT reaches ezdxf meshes.

This is a diagnostic only: a nonempty mesh is not proof of a complete contour.
No CAD geometry or SAT records are written to the report.
"""

# ruff: noqa: INP001, T201 - standalone research diagnostic prints aggregate counts

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import ezdxf
from ezdxf.acis import api
from ezdxf.entities import Region


def survey(path: Path) -> dict[str, object]:
    doc = ezdxf.readfile(path)
    outcome: Counter[str] = Counter()
    curve_records: Counter[str] = Counter()
    nonstraight_regions = 0
    for region in doc.entitydb.values():
        if not isinstance(region, Region):
            continue
        region_curves = Counter(
            fields[0]
            for line in region.sat
            if (fields := line.split()) and fields[0].endswith("-curve")
        )
        curve_records.update(region_curves)
        nonstraight_regions += any(kind != "straight-curve" for kind in region_curves)
        if not region.sat and not region.sab:
            outcome["no_payload"] += 1
            continue
        try:
            bodies = api.load_dxf(region)
            meshes = [mesh for body in bodies for mesh in api.mesh_from_body(body)]
        except (ValueError, TypeError, RuntimeError, api.AcisException):
            outcome["parse_error"] += 1
            continue
        if not bodies:
            outcome["no_body"] += 1
        elif not meshes or not any(mesh.vertices and mesh.faces for mesh in meshes):
            outcome["empty_mesh"] += 1
        else:
            outcome["nonempty_mesh"] += 1
    return {
        "converted_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "region_count": sum(outcome.values()),
        "outcomes": dict(sorted(outcome.items())),
        "curve_record_counts": dict(sorted(curve_records.items())),
        "regions_with_nonstraight_curves": nonstraight_regions,
        "scope": (
            "ezdxf acis.api mesh_from_body only returns flat polygonal faces; "
            "nonempty mesh does not certify full curves, holes, or exact footprint."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("converted", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = survey(args.converted)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
