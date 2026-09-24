"""Survey real tree-symbol INSERT structure without storing customer geometry in Git."""

# ruff: noqa: INP001, T201 - standalone research CLI prints a JSON result

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import ezdxf

from green.application.classification import classify_scene
from green.application.errors import InputError
from green.domain.objects import ObjectClass
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource
from green.infrastructure.convert.libredwg import LibreDwgConverter

ROOT = Path(__file__).resolve().parents[1]

if TYPE_CHECKING:
    from ezdxf.document import Drawing


class _DiagnosticDocuments:
    """Read-only survey of a rejected DXF; never used to certify or export a plan."""

    def load(self, path: Path) -> tuple[Drawing, list[str]]:
        return ezdxf.readfile(path), ["Diagnostic preview: strict DXF audit was bypassed"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--diagnostic-preview", action="store_true")
    args = parser.parse_args()
    source: Path = args.source
    work_dir: Path = args.work_dir
    work_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    dxf = (
        LibreDwgConverter().to_dxf(source, work_dir)
        if source.suffix.lower() == ".dwg"
        else source
    )
    converted_s = time.perf_counter() - started
    load_error = None
    try:
        scene = EzdxfSceneReader().read(dxf)
    except InputError as error:
        if not args.diagnostic_preview:
            raise
        load_error = str(error)
        scene = EzdxfSceneReader(
            documents=_DiagnosticDocuments()  # ty: ignore[invalid-argument-type]
        ).read(dxf)
    read_s = time.perf_counter() - started - converted_s
    layer_map = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()
    classified, _ = classify_scene(scene, layer_map)
    raw_tree_parts = 0
    raw_groups: dict[tuple[str, str], int] = defaultdict(int)
    for feature in scene.features:
        if layer_map.classify(feature) is not ObjectClass.EXISTING_TREE:
            continue
        raw_tree_parts += 1
        if feature.insert_chain:
            instance = feature.insert_chain[-1]
            raw_groups[(instance.block, str(instance.ref))] += 1
    groups: dict[tuple[str, str], int] = defaultdict(int)
    for feature in classified.features:
        if feature.object_class is ObjectClass.EXISTING_TREE and feature.insert_chain:
            instance = feature.insert_chain[-1]
            groups[(instance.block, str(instance.ref))] += 1
    blocks: dict[str, list[int]] = defaultdict(list)
    for (name, _), count in raw_groups.items():
        blocks[name].append(count)
    report = {
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "conversion_s": round(converted_s, 3),
        "read_s": round(read_s, 3),
        "strict_input_complete": (
            load_error is None
            and not scene.read_diagnostics.block_failures
            and not scene.read_diagnostics.geometry_gaps
            and not scene.read_diagnostics.unresolved_xrefs
        ),
        "strict_load_error": load_error,
        "features": len(scene.features),
        "raw_tree_parts": raw_tree_parts,
        "raw_tree_parts_in_inserts": sum(raw_groups.values()),
        "existing_tree_features": sum(
            feature.object_class is ObjectClass.EXISTING_TREE for feature in classified.features
        ),
        "tree_insert_instances": len(groups),
        "tree_features_in_inserts": sum(groups.values()),
        "block_summary": [
            {"block": name, "instances": len(counts), "parts_per_instance": dict(Counter(counts))}
            for name, counts in sorted(blocks.items(), key=lambda item: -len(item[1]))[:20]
        ],
        "geometry_gaps": dict(
            Counter(gap.entity_type for gap in scene.read_diagnostics.geometry_gaps)
        ),
        "block_failures": scene.read_diagnostics.block_failures[:10],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
