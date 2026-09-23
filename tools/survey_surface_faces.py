"""Local topology coverage only; no CAD coordinates or certified planting claims."""
# ruff: noqa: INP001, T201 - research probe of intermediate evidence

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from green.application.classification import classification_report, classify_scene
from green.application.input_quality import require_complete_geometry
from green.application.params import PlanParams
from green.application.surfaces import Material, _closed_materials, _seeds, _uncertainty_area
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs/research/verified-pipeline/surface_face_survey.json",
    )
    args = parser.parse_args()
    rows = []
    layers = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()
    for arg in args.inputs:
        begin = time.perf_counter()
        scene = EzdxfSceneReader().read(Path(arg))
        require_complete_geometry(scene)
        scene, _ = classify_scene(scene, layers, PlanParams())
        semantics = classification_report(scene, layers, PlanParams())
        xy, kinds = _seeds(scene.features, scene.labels)
        keep = (kinds == Material.SOIL) | (kinds == Material.PAVED)
        xy, kinds = xy[keep], kinds[keep]
        uncertain = _uncertainty_area(scene.features)
        faces = _closed_materials(scene.features, xy, kinds, uncertain)
        row = {
            "name": scene.source_name,
            "sha256": scene.source_sha256,
            "semantic_unresolved_features": semantics.unresolved_features,
            "material_labels": len(xy),
            "closed_faces": faces.count,
            "conflicting_faces": faces.conflicts,
            "unassigned_labels": faces.unassigned_labels,
            "open_edges": faces.open_edges,
            "unsupported_boundary_faces": faces.unsupported_boundaries,
            "inferred_soil_m2": faces.soil.area,
            "inferred_paved_m2": faces.paved.area,
            "unresolved_face_m2": faces.unresolved.area,
            "seconds": round(time.perf_counter() - begin, 4),
        }
        rows.append(row)
        print(row, flush=True)
    payload = {
        "scope": (
            "Local topology coverage under current automatic name/text assumptions. "
            "Unresolved semantics remain unresolved: this is not a planting certificate "
            "or measurement of material recognition accuracy."
        ),
        "rows": rows,
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
