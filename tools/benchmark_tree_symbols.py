"""Generate and time the same synthetic tree-symbol DXF with two code revisions."""

# ruff: noqa: INP001, T201 - standalone benchmark prints a JSON record

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import platform
import resource
import statistics
import time
from pathlib import Path

import ezdxf

from green.application.classification import classify_scene
from green.domain.objects import ObjectClass
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource


def make_fixture(path: Path, *, instances: int) -> None:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    doc.layers.add("!!!_1. Дендра_сохранить")
    sign = doc.blocks.new("ANONYMOUS_TREE_SYMBOL")
    for radius in (0.25, 0.4, 0.6, 0.75, 0.9, 1.0, 1.1, 1.2):
        sign.add_circle((0, 0), radius)
    for angle in range(4):
        sign.add_line((-0.5 + angle * 0.1, 0), (0.5 + angle * 0.1, 0))
    for index in range(instances):
        doc.modelspace().add_blockref(
            "ANONYMOUS_TREE_SYMBOL",
            ((index % 100) * 5.0, (index // 100) * 5.0),
            dxfattribs={"layer": "!!!_1. Дендра_сохранить"},
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--make-fixture", type=int, default=0)
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    if args.make_fixture:
        make_fixture(args.source, instances=args.make_fixture)
    if args.repeat == 0:
        return
    layer_map = YamlLayerMapSource(args.config).load()
    read_s = []
    classify_s = []
    raw = trees = 0
    for _ in range(args.repeat):
        started = time.perf_counter()
        scene = EzdxfSceneReader().read(args.source)
        read_s.append(time.perf_counter() - started)
        started = time.perf_counter()
        classified, _ = classify_scene(scene, layer_map)
        classify_s.append(time.perf_counter() - started)
        raw = len(scene.features)
        trees = sum(f.object_class is ObjectClass.EXISTING_TREE for f in classified.features)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_rss_mb = peak / (1024 * 1024) if platform.system() == "Darwin" else peak / 1024
    print(
        json.dumps(
            {
                "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
                "config_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
                "reader_module": inspect.getfile(EzdxfSceneReader),
                "repeats": args.repeat,
                "raw_parts": raw,
                "logical_trees": trees,
                "read_median_s": statistics.median(read_s),
                "classify_median_s": statistics.median(classify_s),
                "peak_rss_mb": peak_rss_mb,
                "peak_rss_scope": "whole process; macOS/Linux ru_maxrss units differ",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
