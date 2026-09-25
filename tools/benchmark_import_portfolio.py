"""Repeat the fixed E14 CAD import sample with the current converter and reader.

Only aggregate counts and source hashes are saved; converted drawings stay under out/.
"""

# ruff: noqa: INP001, T201 - standalone local diagnostic for customer CAD

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path, PurePosixPath

from green.application.errors import ConversionError, InputError
from green.application.input_quality import require_complete_geometry
from green.application.use_case import to_dxf
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.convert.hybrid import HybridDwgConverter
from green.infrastructure.convert.libredwg import LibreDwgConverter


def _source(row: dict, catalog: list[dict], root: Path) -> Path:
    for candidate in catalog:
        relative = candidate.get("file")
        if not isinstance(relative, str) or PurePosixPath(relative).name != row["name"]:
            continue
        if candidate.get("size") != row["bytes"] or "/PaxHeader/" in f"/{relative}/":
            continue
        path = root / relative
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest == row["source_sha256"]:
            return path
    raise FileNotFoundError(f"Source SHA-256 not found: {row['source_sha256']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sample = json.loads(args.sample.read_text())
    catalog = [json.loads(line) for line in args.catalog.read_text().splitlines()]
    converters = (
        HybridDwgConverter(bridge_binary=str(args.bridge.resolve())),
        LibreDwgConverter(),
    )
    rows = []
    for original in sample["rows"]:
        started = time.perf_counter()
        row = {
            "street": original["street"],
            "source_sha256": original["source_sha256"],
            "baseline_complete": original.get("block_check") == "passed",
        }
        try:
            source = _source(original, catalog, args.dataset_root)
            converted, converter = to_dxf(converters, source, args.work_dir)
            row["converter"] = converter
            scene = EzdxfSceneReader().read(converted)
            row["features"] = len(scene.features)
            row["unresolved_xrefs"] = len(scene.read_diagnostics.unresolved_xrefs)
            row["gap_count"] = sum(gap.count for gap in scene.read_diagnostics.geometry_gaps)
            gaps_by_type: Counter[str] = Counter()
            for gap in scene.read_diagnostics.geometry_gaps:
                gaps_by_type[gap.entity_type] += gap.count
            row["gaps_by_type"] = dict(gaps_by_type)
            row["bounded_hatches"] = scene.read_diagnostics.bounded_uncertainty_by_type.get(
                "HATCH", 0
            )
            row["images"] = scene.read_diagnostics.visited_by_type.get("IMAGE", 0)
            try:
                require_complete_geometry(scene)
            except InputError as error:
                row["complete"] = False
                row["barrier"] = str(error).split(":", 1)[0]
            else:
                row["complete"] = True
        except (ConversionError, InputError, OSError, ValueError) as error:
            row["complete"] = False
            row["error"] = str(error)[:300]
        row["seconds"] = round(time.perf_counter() - started, 3)
        rows.append(row)
        args.output.write_text(
            json.dumps(
                {
                    "scope": (
                        "Fixed E14 files; geometry import only, no semantic or planting "
                        "accuracy claim"
                    ),
                    "baseline_complete": sum(1 for item in rows if item["baseline_complete"]),
                    "current_complete": sum(1 for item in rows if item["complete"]),
                    "rows": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        print(
            {
                "street": row["street"],
                "baseline_complete": row["baseline_complete"],
                "complete": row["complete"],
                "gaps_by_type": row.get("gaps_by_type"),
                "error": row.get("error"),
                "seconds": row["seconds"],
            },
            flush=True,
        )


if __name__ == "__main__":
    main()
