"""Aggregate proposed/removed surface ambiguity; never certify incomplete files."""
# ruff: noqa: INP001, T201 - standalone research driver

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from green.application.classification import classification_report, classify_scene
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    rules = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()
    rows = []
    for arg in sys.argv[1:]:
        scene, _ = classify_scene(EzdxfSceneReader().read(Path(arg)), rules)
        report = classification_report(scene, rules)
        withheld = Counter(
            f.layer
            for f in scene.features
            if f.classification and f.classification.method == "material_context"
        )
        row = {
            "name": scene.source_name,
            "sha256": scene.source_sha256,
            "features": len(scene.features),
            "unresolved_features": report.unresolved_features,
            "positive_lawn_assignments_withheld": sum(withheld.values()),
            "by_layer": dict(withheld),
            "geometry_gaps": sum(g.count for g in scene.read_diagnostics.geometry_gaps),
            "unresolved_xrefs": len(scene.read_diagnostics.unresolved_xrefs),
        }
        rows.append(row)
        print(row, flush=True)
    (ROOT / "docs/research/verified-pipeline/material_context_survey.json").write_text(
        json.dumps(
            {
                "scope": "Automatic positive assignments withheld because a layer/block describes "
                "a material transition, negation or construction stage. This is not a "
                "semantic-accuracy score. Files retain geometry gaps and missing XREFs.",
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
