"""Local reading/completeness survey of real files. No semantic accuracy claim.

Usage: python tools/survey_cad_inputs.py SOURCE [SOURCE ...]
Raw converted CAD and converter logs remain under ignored out/; only aggregate
counts and source identities are written to the research journal directory.
"""
# ruff: noqa: INP001, T201 - standalone research driver

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from green.application.classification import classify_scene
from green.application.errors import ConversionError, InputError
from green.application.input_quality import require_complete_geometry
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource
from green.infrastructure.convert.libredwg import LibreDwgConverter

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "out/real-input-survey"


def survey(source: Path) -> dict[str, object]:
    begin = time.perf_counter()
    with source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    row: dict[str, object] = {
        "name": source.name,
        "source_sha256": digest,
        "bytes": source.stat().st_size,
    }
    work = OUTPUT / digest[:20]
    try:
        if source.suffix.lower() == ".dwg":
            dxf = LibreDwgConverter().to_dxf(source, work)
            row["conversion_seconds"] = round(time.perf_counter() - begin, 4)
            row["dxf_bytes"] = dxf.stat().st_size
        else:
            dxf = source
        started = time.perf_counter()
        scene = EzdxfSceneReader().read(dxf)
        row["read_seconds"] = round(time.perf_counter() - started, 4)
        row["unit_m_from_header"] = scene.unit_m
        row["read_diagnostics"] = asdict(scene.read_diagnostics)
        row["warnings"] = scene.warnings
        scene, _ = classify_scene(scene, YamlLayerMapSource(ROOT / "config/layer_map.yaml").load())
        row["features"] = len(scene.features)
        row["labels"] = len(scene.labels)
        row["classes"] = dict(Counter(f.object_class.value for f in scene.features))
        row["geometry_types"] = dict(Counter(f.geometry.geom_type for f in scene.features))
        try:
            require_complete_geometry(scene)
        except InputError as error:
            row["block_check"] = str(error)
        else:
            row["block_check"] = "passed"
        row["read_status"] = "completed"
    except (InputError, ConversionError) as error:
        row.update(read_status="rejected", error=str(error))
    row["seconds"] = round(time.perf_counter() - begin, 4)
    return row


def main() -> None:
    if not sys.argv[1:]:
        raise SystemExit(__doc__)
    target = ROOT / "docs/research/verified-pipeline/real_input_survey.json"
    rows = []
    for arg in sys.argv[1:]:
        row = survey(Path(arg))
        rows.append(row)
        target.write_text(
            json.dumps(
                {
                "scope": (
                    "Local read/structural survey, declared units only; no proof of complete "
                    "survey, correct units or semantic recognition."
                ),
                    "rows": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(
            {k: v for k, v in row.items() if k not in {"warnings", "read_diagnostics"}}, flush=True
        )


if __name__ == "__main__":
    main()
