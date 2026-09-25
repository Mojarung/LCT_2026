"""Перепись неразрешённых классов улицы: что именно остановит строгий прогон и где оно лежит.

Группы классификатора (слой, блок, геометрия, класс, основание) с классом unknown или
utility.unknown: число объектов, длина и площадь, охват, сколько лежит у границы работ.
Для осмотра без повторного чтения чертежа - образцы геометрии группы и окружение первых
образцов (объекты других классов и подписи) в отдельный файл.

Вызывается из `tools/reader_check.py`; отдельно - `render` рисует образцы из файла.
"""
# ruff: noqa: INP001 - инструмент разведки

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import shapely

from green.application.classification import classification_report
from green.application.params import PlanParams
from green.application.quality.site import site_of
from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from green.application.classification import LayerMap
    from green.domain.objects import Feature, Scene

UNRESOLVED = frozenset({ObjectClass.UNKNOWN, ObjectClass.UTILITY_UNKNOWN})
# Основания вывода по словам и осторожной замены (задача 14): их группы идут в отчёт отдельно,
# замены - и в образцы для картинок: это самое рискованное решение классификатора.
INFERRED = ("inferred_", "symbol_inferred:")
ASSUMED = ("assumed_", "symbol_assumed:")
TOP = 80
# Дальше наибольшего нормативного отступа объект на посадку внутри границы работ не влияет.
NEAR_WORK_M = 10.0
SAMPLES = 300
CONTEXT_M = 25.0
CONTEXT_CAP = 4000


def semantics(classified: Scene, layer_map: LayerMap, dump: Path | None = None) -> dict:
    """Итог классификации улицы; с dump - образцы неразрешённых групп в JSONL."""
    report = classification_report(classified, layer_map, PlanParams())
    members: dict[tuple, list[Feature]] = defaultdict(list)
    guessed: dict[tuple[str, str, str], int] = defaultdict(int)
    for feature in classified.features:
        method = feature.classification.method if feature.classification else "unmatched"
        if method.startswith(INFERRED + ASSUMED):
            guessed[(feature.layer, feature.object_class.value, method)] += 1
        if feature.object_class in UNRESOLVED or method.startswith(ASSUMED):
            evidence = feature.classification
            members[
                (
                    feature.layer,
                    feature.block,
                    feature.geometry.geom_type,
                    feature.object_class.value,
                    evidence.method if evidence else "unmatched",
                )
            ].append(feature)
    work = site_of(classified.features).boundary
    near = work.buffer(NEAR_WORK_M) if work is not None and not work.is_empty else None
    groups = []
    for key, items in sorted(members.items(), key=lambda kv: -len(kv[1])):
        geometries = shapely.GeometryCollection([f.geometry for f in items])
        x0, y0, x1, y1 = geometries.bounds
        groups.append(
            {
                "layer": key[0],
                "block": key[1],
                "geometry": key[2],
                "class": key[3],
                "why": key[4],
                "count": len(items),
                "length_m": round(float(sum(f.geometry.length for f in items)), 1),
                "area_m2": round(float(sum(f.geometry.area for f in items)), 1),
                "bbox": [round(v, 1) for v in (x0, y0, x1, y1)],
                "near_work": None
                if near is None
                else int(sum(near.intersects(f.geometry) for f in items)),
                "examples": [str(f.ref) for f in items[:5]],
            }
        )
    if dump is not None:
        _dump(classified, members, dump)
    return {
        "ready": report.ready,
        "features": report.features,
        "unresolved": report.unresolved_features,
        "work_boundary": near is not None,
        "classes": _class_counts(classified),
        "groups": [g for g in groups if g["class"] in {c.value for c in UNRESOLVED}],
        "assumed": [g for g in groups if g["why"].startswith(ASSUMED)][:TOP],
        "inferred": [
            {"layer": layer, "class": kind, "why": method, "count": count}
            for (layer, kind, method), count in sorted(guessed.items(), key=lambda kv: -kv[1])
            if method.startswith(INFERRED)
        ][:TOP],
    }


def _class_counts(scene: Scene) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for feature in scene.features:
        counts[feature.object_class.value] += 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def _dump(scene: Scene, members: dict[tuple, list[Feature]], path: Path) -> None:
    """Образцы групп и окружение первых образцов: картинка без повторного чтения чертежа."""
    tree = shapely.STRtree([f.geometry for f in scene.features])
    labels = scene.labels
    label_points = shapely.points([(label.x, label.y) for label in labels]) if labels else None
    label_tree = shapely.STRtree(label_points) if label_points is not None else None
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        for key, items in sorted(members.items(), key=lambda kv: -len(kv[1])):
            focus = shapely.union_all([f.geometry for f in items[:3]]).envelope.buffer(CONTEXT_M)
            around = [
                scene.features[i]
                for i in tree.query(focus, predicate="intersects")[:CONTEXT_CAP]
                if scene.features[i].object_class not in UNRESOLVED
            ]
            texts = (
                [labels[i] for i in label_tree.query(focus, predicate="intersects")[:400]]
                if label_tree is not None
                else []
            )
            row = {
                "key": list(key),
                "count": len(items),
                "focus": focus.bounds,
                "samples": [
                    shapely.to_wkt(f.geometry, rounding_precision=2) for f in items[:SAMPLES]
                ],
                "context": [
                    [f.object_class.value, shapely.to_wkt(f.geometry, rounding_precision=2)]
                    for f in around
                ],
                "labels": [[t.x, t.y, t.text[:30]] for t in texts],
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")


def render(dump: Path, out_dir: Path, limit: int = 40) -> None:
    """Картинки групп из файла образцов: окружение серым, группа красным, подписи."""
    import matplotlib as mpl  # noqa: PLC0415 - нужен только здесь

    mpl.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415

    out_dir.mkdir(parents=True, exist_ok=True)
    for index, line in enumerate(dump.read_text(encoding="utf-8").splitlines()[:limit]):
        row = json.loads(line)
        x0, y0, x1, y1 = row["focus"]
        fig, ax = plt.subplots(figsize=(9, 9), dpi=100)
        for _kind, wkt in row["context"]:
            _draw(ax, shapely.from_wkt(wkt), color="0.75", width=0.5)
        for wkt in row["samples"]:
            _draw(ax, shapely.from_wkt(wkt), color="red", width=1.0)
        for x, y, text in row["labels"]:
            ax.text(x, y, text, fontsize=6, color="0.3")
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        ax.set_aspect("equal")
        layer, block, geometry, _kind, why = row["key"]
        ax.set_title(f"{layer[-60:]} | {block} | {geometry} | {why} | {row['count']}", fontsize=8)
        fig.tight_layout()
        fig.savefig(out_dir / f"{index:02d}.png")
        plt.close(fig)


def _draw(ax, geometry, *, color: str, width: float) -> None:  # noqa: ANN001 - оси matplotlib
    for part in shapely.get_parts(geometry):
        if part.geom_type == "Point":
            ax.plot(part.x, part.y, marker=".", color=color, markersize=3)
        elif part.geom_type == "Polygon":
            ax.plot(*part.exterior.xy, color=color, linewidth=width)
        elif hasattr(part, "xy"):
            ax.plot(*part.xy, color=color, linewidth=width)
        else:
            for sub in shapely.get_parts(part):
                _draw(ax, sub, color=color, width=width)


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "render":  # noqa: PLR2004
        raise SystemExit("uv run python tools/semantic_census.py render ДАМП.jsonl ПАПКА")
    render(Path(sys.argv[2]), Path(sys.argv[3]))
