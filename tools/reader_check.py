"""Проверка чтения на всех улицах каталога: собрать комплект, прочитать, записать учёт.

Для каждой улицы: склейка комплекта так же, как в сервисе (пути файлов в архиве, ссылки без
файла у заказчика - названный пробел), чтение ридером и учёт: посещения по типам, исход
каждого посещения, пробелы геометрии по причинам, неразрешённые внешние ссылки, знаки по
блокам. Итог - out/reader-check/<улица>.json и сводная таблица в консоли.

    uv run python tools/reader_check.py                      все улицы каталога
    uv run python tools/reader_check.py --only 6 --only 18   выбранные
    uv run python tools/reader_check.py --catalog dataset/streets_oda --workers 2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from green.application.semantic_names import base_name, local_name  # noqa: E402
from green.infrastructure.cad.documents import DocumentCache  # noqa: E402
from green.infrastructure.cad.merge import EzdxfDrawingMerger  # noqa: E402
from green.infrastructure.cad.reader import EzdxfSceneReader  # noqa: E402
from green.infrastructure.streets import JsonStreetCatalog  # noqa: E402

OUT = ROOT / "out" / "reader-check"


class _Tally(logging.Handler):
    """Сообщения ezdxf (например, объекты OBJECTS, пропущенные при внедрении ссылки) - числом
    по видам, а не тысячами строк в консоли."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.kinds: Counter[str] = Counter()

    def emit(self, record: logging.LogRecord) -> None:
        text = record.getMessage()
        self.kinds[re.sub(r"\(#[0-9A-Fa-f]+\)", "", text)[:120]] += 1


def _symbol_detail(scene) -> dict:  # noqa: ANN001 - Scene
    """По базовому имени знака: число, слои, число штрихов и примеры точек."""
    detail: dict[str, dict] = {}
    for symbol in scene.symbols:
        entry = detail.setdefault(
            base_name(symbol.block),
            {"count": 0, "layers": Counter(), "strokes": Counter(), "examples": []},
        )
        entry["count"] += 1
        entry["layers"][symbol.layer] += 1
        entry["strokes"][symbol.strokes] += 1
        if len(entry["examples"]) < 3:  # noqa: PLR2004
            entry["examples"].append(
                {"block": symbol.block, "layer": symbol.layer,
                 "x": round(symbol.x, 2), "y": round(symbol.y, 2)}
            )
    return {
        name: {"count": e["count"], "layers": dict(e["layers"].most_common(8)),
               "strokes": {str(k): v for k, v in e["strokes"].most_common(5)},
               "examples": e["examples"]}
        for name, e in sorted(detail.items(), key=lambda kv: -kv[1]["count"])
    }


def _draw_symbols(doc, scene, slug: str) -> int:  # noqa: ANN001 - Drawing, Scene
    """Рисунок определения блока для каждого базового имени знака улицы: сырьё переписи.

    Документ уже загружен ридером (DocumentCache), второй раз сотни мегабайт не читаются.
    Картинка: out/reader-check/symbols/<базовое имя>__<улица>.png.
    """
    import matplotlib as mpl

    mpl.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    out = OUT / "symbols"
    out.mkdir(parents=True, exist_ok=True)
    config = Configuration(
        color_policy=ColorPolicy.BLACK, background_policy=BackgroundPolicy.WHITE
    )
    first: dict[str, str] = {}
    for symbol in scene.symbols:
        first.setdefault(base_name(symbol.block), symbol.block)
    drawn = 0
    for base, name in first.items():
        block = doc.blocks.get(name)
        if block is None:
            continue
        figure = plt.figure(figsize=(1.6, 1.6), dpi=100)
        axes = figure.add_axes((0, 0, 1, 1))
        try:
            backend = MatplotlibBackend(axes, adjust_figure=False)
            Frontend(RenderContext(doc), backend, config=config).draw_entities(block)
            backend.finalize()  # пределы осей по рисунку знака
            axes.set_aspect("equal", "datalim")
            axes.margins(0.08)
            axes.axis("off")
            safe = re.sub(r'[\\/:*?"<>|\s]+', "_", base)
            figure.savefig(out / f"{safe}__{slug}.png", facecolor="white")
            drawn += 1
        except Exception:  # noqa: BLE001, S112 - знак без рисунка не ломает проверку
            continue
        finally:
            plt.close(figure)
    return drawn


def _kit_key(paths: list[Path], names: tuple[str, ...], absent: tuple) -> str:
    digest = hashlib.sha256()
    for path in paths:
        stat = path.stat()
        digest.update(f"{path.name}|{stat.st_size}|{stat.st_mtime_ns}".encode())
    digest.update(json.dumps([names, absent], ensure_ascii=False).encode())
    return digest.hexdigest()[:16]


def check(job: tuple[str, str]) -> dict:
    catalog_dir, slug = job
    tally = _Tally()
    ezdxf_log = logging.getLogger("ezdxf")
    ezdxf_log.addHandler(tally)
    ezdxf_log.propagate = False
    street = JsonStreetCatalog(Path(catalog_dir)).get(slug)
    if street is None:
        return {"slug": slug, "error": "нет в каталоге"}
    paths = [street.main, *street.extra]
    started = time.perf_counter()
    notes: list[str] = []
    source = street.main
    if street.extra:
        key = _kit_key(paths, street.sources, street.absent_references)
        cached = OUT / "cache" / f"{slug}-{key}.dxf"
        if not cached.exists():
            cached.parent.mkdir(parents=True, exist_ok=True)
            try:
                result = EzdxfDrawingMerger().merge(
                    paths,
                    cached,
                    source_names=street.sources,
                    absent_references=street.absent_references,
                )
            except Exception as error:  # noqa: BLE001 - причина уходит в отчёт, улицы не падают
                return {"slug": slug, "number": street.number, "error": f"склейка: {error}",
                        "traceback": traceback.format_exc(limit=12)}
            notes = list(result.notes)
            (cached.with_suffix(".notes.json")).write_text(
                json.dumps(notes, ensure_ascii=False), encoding="utf-8"
            )
        else:
            notes = json.loads(cached.with_suffix(".notes.json").read_text(encoding="utf-8"))
        source = cached
    merged_s = time.perf_counter() - started
    documents = DocumentCache(capacity=1)
    try:
        scene = EzdxfSceneReader(documents=documents).read(source)
    except Exception as error:  # noqa: BLE001
        return {"slug": slug, "number": street.number, "error": f"чтение: {error}",
                "traceback": traceback.format_exc(limit=12)}
    read_s = time.perf_counter() - started
    drawn = _draw_symbols(documents.load(source)[0], scene, slug)
    diagnostics = scene.read_diagnostics
    symbols = Counter(local_name(symbol.block) for symbol in scene.symbols)
    return {
        "slug": slug,
        "number": street.number,
        "title": street.title,
        "files": len(paths),
        "absent_references": [list(pair) for pair in street.absent_references],
        "merge_notes": notes,
        "seconds": {
            "merge": round(merged_s, 1),
            "read": round(read_s - merged_s, 1),
            "total": round(time.perf_counter() - started, 1),
        },
        "symbol_drawings": drawn,
        "unit_m": scene.unit_m,
        "visited": dict(diagnostics.visited_by_type),
        "outcomes": dict(diagnostics.outcomes),
        "gaps": [
            {"type": g.entity_type, "layer": g.layer, "block": g.block, "reason": g.reason,
             "count": g.count, "examples": list(g.source_refs)}
            for g in diagnostics.geometry_gaps
        ],
        "unresolved_xrefs": list(diagnostics.unresolved_xrefs),
        "features": len(scene.features),
        "labels": len(scene.labels),
        "symbols": len(scene.symbols),
        "symbol_blocks": dict(symbols.most_common()),
        "symbol_detail": _symbol_detail(scene),
        "source": str(source),
        "ezdxf_messages": dict(tally.kinds.most_common()),
        "warnings": list(scene.warnings),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "dataset" / "streets_oda")
    parser.add_argument("--only", action="append", type=int, help="номера улиц")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    catalog_dir = args.catalog if args.catalog.is_absolute() else ROOT / args.catalog
    streets = [
        street
        for street in JsonStreetCatalog(catalog_dir).all()
        if not args.only or street.number in args.only
    ]
    # Тяжёлые комплекты первыми, чтобы пул не ждал в конце одну большую улицу.
    streets.sort(key=lambda street: -street.size_mb)
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(str(catalog_dir), street.slug) for street in streets]
    with ProcessPoolExecutor(args.workers) as pool:
        for row in pool.map(check, jobs):
            (OUT / f"{row['slug']}.json").write_text(
                json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            if "error" in row:
                print(f"{row.get('number', '?'):>2} {row['slug']}: ОШИБКА {row['error'][:300]}")
                continue
            gaps = sum(g["count"] for g in row["gaps"])
            visited = sum(row["visited"].values())
            accounted = sum(row["outcomes"].values())
            print(
                f"{row['number']:>2} {row['slug'][:28]:<28} файлов {row['files']:>3}  "
                f"посещено {visited:>8}  исходов {accounted:>8}  пробелов {gaps:>6}  "
                f"знаков {row['symbols']:>6}  ссылок без файла {len(row['absent_references'])}  "
                f"неразрешённых {len(row['unresolved_xrefs'])}  {row['seconds']['total']} с",
                flush=True,
            )


if __name__ == "__main__":
    main()
