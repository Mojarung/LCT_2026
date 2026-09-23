"""Count material-label exclusions locally; no source geometry or accuracy claims."""
# ruff: noqa: INP001, T201 - standalone research driver

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from green.application.classification import classify_scene
from green.application.surfaces import PAVED_LABELS, SOIL_LABELS
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    layers = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()
    rows = []
    for arg in sys.argv[1:]:
        scene, _ = classify_scene(EzdxfSceneReader().read(Path(arg)), layers)
        material = [
            label
            for label in scene.labels
            if label.text.strip().upper().rstrip(".") in PAVED_LABELS | SOIL_LABELS
        ]
        excluded = [label for label in material if label.surface_role == "ignore"]
        row = {
            "name": scene.source_name,
            "source_sha256": scene.source_sha256,
            "labels": len(scene.labels),
            "material_words": len(material),
            "retained_material_words": len(material) - len(excluded),
            "excluded_material_words": len(excluded),
            "exclusions_by_layer": dict(Counter(label.layer for label in excluded)),
            "exclusions_by_reason": dict(
                Counter(
                    label.surface_evidence.method for label in excluded if label.surface_evidence
                )
            ),
        }
        rows.append(row)
        print(row, flush=True)
    (ROOT / "docs/research/verified-pipeline/label_context_survey.json").write_text(
        json.dumps(
            {
                "scope": "Material word coverage under automatic annotation/work-context "
                "assumptions, not expert-labelled semantic accuracy or a planting certificate.",
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
