"""Survey inline ACIS REGION variants across converted DXF without saving geometry."""

# ruff: noqa: INP001, T201 - standalone research diagnostic

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import ezdxf
from ezdxf.entities import Region

from green.infrastructure.cad.region_geometry import RegionGeometryError, region_polygon


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def survey(root: Path) -> dict:  # noqa: C901 - survey counts every ACIS outcome
    rows = []
    seen: set[str] = set()
    for path in sorted(root.rglob("*.dxf")):
        digest = _sha256(path)
        if digest in seen:
            continue
        seen.add(digest)
        row: dict = {"file": str(path.relative_to(root)), "sha256": digest}
        try:
            doc = ezdxf.readfile(path)
        except (OSError, ezdxf.DXFError) as exc:
            row["load_error"] = type(exc).__name__
            rows.append(row)
            continue
        counts: Counter[str] = Counter()
        curves: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        for entity in doc.entitydb.values():
            if not isinstance(entity, Region):
                continue
            counts["regions"] += 1
            if entity.sat:
                counts["sat"] += 1
                curve_names = {
                    words[0]
                    for line in entity.sat
                    if (words := line.split()) and words[0].endswith("-curve")
                }
                for name in curve_names:
                    curves[name] += 1
            elif entity.sab:
                counts["sab"] += 1
            else:
                counts["missing_payload"] += 1
                continue
            try:
                _, error = region_polygon(entity, flatten=0.1)
            except RegionGeometryError as exc:
                reasons[str(exc)] += 1
            else:
                counts["accepted_curved" if error else "accepted_straight"] += 1
        row.update(
            counts=dict(counts),
            curves=dict(curves),
            rejection_reasons=dict(reasons),
        )
        rows.append(row)
    totals: Counter[str] = Counter()
    for row in rows:
        totals.update(row.get("counts", {}))
    return {
        "scope": (
            "Converted local DXF only; absence of a curve here is not an independent "
            "holdout test."
        ),
        "files": len(rows),
        "totals": dict(totals),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = survey(args.root)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"files": result["files"], "totals": result["totals"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
