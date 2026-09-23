"""Count top-level alignment changes; retain no coordinates or source CAD."""
# ruff: noqa: INP001, T201 - standalone research driver

from __future__ import annotations

import json
import sys
from pathlib import Path

from ezdxf.entities import Text

from green.application.surfaces import PAVED_LABELS, SOIL_LABELS
from green.infrastructure.cad.documents import DocumentCache
from green.infrastructure.cad.reader import EzdxfSceneReader

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    rows = []
    for arg in sys.argv[1:]:
        path = Path(arg)
        cache = DocumentCache()
        scene = EzdxfSceneReader(documents=cache).read(path)
        doc, _ = cache.load(path)
        texts = [e for e in doc.modelspace() if isinstance(e, Text)]
        moved = [e for e in texts if e.get_placement()[1] != e.dxf.insert]
        row = {
            "name": scene.source_name,
            "source_sha256": scene.source_sha256,
            "all_imported_labels": len(scene.labels),
            "top_level_texts": len(texts),
            "top_level_changed_anchors": len(moved),
            "top_level_changed_material_anchors": sum(
                e.dxf.text.strip().upper().rstrip(".") in PAVED_LABELS | SOIL_LABELS
                for e in moved
            ),
            "invalid_label_placements_including_blocks": sum(
                gap.count
                for gap in scene.read_diagnostics.geometry_gaps
                if gap.entity_type in {"TEXT", "MTEXT", "ATTRIB"}
            ),
        }
        rows.append(row)
        print(row, flush=True)
    (ROOT / "docs/research/verified-pipeline/text_placement_survey.json").write_text(
        json.dumps(
            {
                "scope": "Alignment differences cover modelspace TEXT only; label-loss counts "
                "include expanded blocks/attributes. This is not semantic accuracy.",
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
