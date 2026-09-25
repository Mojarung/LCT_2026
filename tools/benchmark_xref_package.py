"""Audit geometry import of an explicitly supplied DWG/DXF package.

The first drawing is the base. This diagnostic does not claim semantic or planting accuracy.
"""

# ruff: noqa: INP001, T201 - local customer-CAD diagnostic

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import time
from collections import Counter
from pathlib import Path

from green.application.errors import ConversionError, InputError
from green.application.input_quality import require_complete_geometry
from green.application.use_case import to_dxf
from green.infrastructure.cad.merge import EzdxfDrawingMerger
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.convert.hybrid import HybridDwgConverter
from green.infrastructure.convert.libredwg import LibreDwgConverter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("extras", type=Path, nargs="+")
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources = (args.source, *args.extras)
    result = {"source_sha256": [hashlib.sha256(path.read_bytes()).hexdigest() for path in sources]}
    started = time.perf_counter()
    try:
        converters = (
            HybridDwgConverter(bridge_binary=str(args.bridge.resolve())),
            LibreDwgConverter(),
        )
        converted = []
        converters_used = []
        for source in sources:
            path, converter = to_dxf(converters, source, args.work_dir)
            converted.append(path)
            converters_used.append(converter)
        result["converters"] = converters_used
        merged = EzdxfDrawingMerger().merge(
            converted,
            args.work_dir / "merged.dxf",
            source_names=tuple(str(source) for source in sources),
        )
        result["references"] = (
            dict(Counter(binding.action for binding in merged.assembly.references))
            if merged.assembly is not None
            else None
        )
        scene = EzdxfSceneReader().read(merged.path)
        result["features"] = len(scene.features)
        result["labels"] = len(scene.labels)
        result["bounded_uncertainty"] = scene.read_diagnostics.bounded_uncertainty_by_type
        result["unresolved_xrefs"] = len(scene.read_diagnostics.unresolved_xrefs)
        gaps_by_type: Counter[str] = Counter()
        for gap in scene.read_diagnostics.geometry_gaps:
            gaps_by_type[gap.entity_type] += gap.count
        result["geometry_gaps"] = dict(gaps_by_type)
        try:
            require_complete_geometry(scene)
        except InputError as error:
            result["complete"] = False
            result["barrier"] = str(error).split(":", 1)[0]
        else:
            result["complete"] = True
    except (ConversionError, InputError, OSError, ValueError) as error:
        result["complete"] = False
        result["error"] = str(error)[:400]
    result["seconds"] = round(time.perf_counter() - started, 3)
    result["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(result)


if __name__ == "__main__":
    main()
