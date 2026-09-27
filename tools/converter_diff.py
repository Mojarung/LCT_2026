"""Сверка двух независимых читателей DWG: каталог улиц LibreDWG против каталога ODA.

Каждый DWG конвертирован дважды (tools/prepare_streets.py --converter libredwg|oda). Оба
конвертера сохраняют handle объектов DWG, поэтому объект одного DXF находится в другом по
handle и сравнивается по типу, слою и геометрии: координаты, радиусы, вершины, текст,
параметры вставки. Пространство модели и все используемые блоки должны совпасть 1 в 1;
расхождения печатаются с примерами, неиспользуемые блоки - отдельно, для сведения.

    uv run python tools/converter_diff.py                      все улицы, итог в out/converter_diff
    uv run python tools/converter_diff.py --only 6 --only 18   выбранные улицы
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ezdxf  # noqa: E402
from ezdxf import recover  # noqa: E402
from shapely.geometry.base import BaseGeometry  # noqa: E402

from green.infrastructure.cad.hatch_geometry import HatchGeometryError, hatch_geometry  # noqa: E402

LEFT = ROOT / "dataset" / "streets_dxf"
RIGHT = ROOT / "dataset" / "streets_dxf_oda"
OUT = ROOT / "out" / "converter_diff"
TOLERANCE = 1e-3  # единицы чертежа (1 мм при метрах) и градусы для углов
EXAMPLES = 5
HATCH_FLATTEN = 0.01  # единицы чертежа: шаг дуг контура штриховки


def _v(point) -> tuple[float, ...]:
    return tuple(float(c) for c in point)


def _block_name(name: str) -> str:
    """Анонимные блоки (*U123, *D45) конвертеры нумеруют по-своему: сравнивается класс имени,
    а содержимое блока сверяется отдельно, по handle его объектов."""
    return re.sub(r"^(\*[A-Za-z]+)\d+$", r"\1", name or "")


def same(a, b) -> bool:
    """Отпечатки равны: числа - с допуском, области - по Хаусдорфу, остальное - точно."""
    if isinstance(a, BaseGeometry) or isinstance(b, BaseGeometry):
        if not (isinstance(a, BaseGeometry) and isinstance(b, BaseGeometry)):
            return False
        if a.is_empty or b.is_empty:
            return a.is_empty and b.is_empty
        return a.hausdorff_distance(b) <= 2 * HATCH_FLATTEN + TOLERANCE
    if isinstance(a, float) or isinstance(b, float):
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=TOLERANCE)
        except (TypeError, ValueError):
            return False
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def digest(entity) -> tuple:  # noqa: C901, PLR0911 - один разбор на тип
    """Отпечаток объекта: то, что должно совпасть у двух читателей одного DWG."""
    kind = entity.dxftype()
    dxf = entity.dxf
    if kind == "LINE":
        return (_v(dxf.start), _v(dxf.end))
    if kind == "CIRCLE":
        return (_v(dxf.center), float(dxf.radius))
    if kind == "ARC":
        return (_v(dxf.center), float(dxf.radius), float(dxf.start_angle),
                float(dxf.end_angle))
    if kind == "LWPOLYLINE":
        return (entity.closed, tuple(_v(p) for p in entity.get_points("xyb")))
    if kind == "POLYLINE":
        return (entity.is_closed, tuple(_v(v.dxf.location) for v in entity.vertices))
    if kind in ("TEXT", "ATTRIB", "ATTDEF"):
        return (dxf.text, _v(dxf.insert), float(dxf.get("height", 0)))
    if kind == "MTEXT":
        return (entity.plain_text(), _v(dxf.insert))
    if kind == "INSERT":
        return (_block_name(dxf.name), _v(dxf.insert), float(dxf.get("xscale", 1)),
                float(dxf.get("yscale", 1)), float(dxf.get("rotation", 0)),
                len(entity.attribs))
    if kind == "POINT":
        return (_v(dxf.location),)
    if kind == "ELLIPSE":
        return (_v(dxf.center), _v(dxf.major_axis), float(dxf.ratio))
    if kind == "SPLINE":
        return (dxf.degree, tuple(_v(p) for p in entity.control_points),
                tuple(_v(p) for p in entity.fit_points))
    if kind == "HATCH":
        # Сравнивается область, а не запись контура: LibreDWG пишет контур полилинией,
        # ODA - рёбрами, углы дуг нормирует по-своему. Область строит тот же код, что ридер.
        try:
            area, _ = hatch_geometry(entity, HATCH_FLATTEN)
        except HatchGeometryError as error:
            return (dxf.pattern_name, bool(dxf.solid_fill), ("контур не читается", str(error)))
        return (dxf.pattern_name, bool(dxf.solid_fill), area)
    if kind in ("REGION", "3DSOLID", "BODY"):
        return (bool(entity.sat or entity.sab),)
    if kind == "SOLID" or kind == "TRACE" or kind == "3DFACE":
        return tuple(_v(dxf.get(f"vtx{i}", (0, 0, 0))) for i in range(4))
    if kind == "DIMENSION":
        return (_block_name(dxf.get("geometry", "")), _v(dxf.get("defpoint", (0, 0, 0))))
    return ()


def _load(path: Path):
    try:
        return ezdxf.readfile(path), "readfile"
    except (ezdxf.DXFStructureError, UnicodeDecodeError, ValueError):
        doc, auditor = recover.readfile(path)
        return doc, f"recover ({len(auditor.errors)} исправлений)"


def _used_blocks(doc) -> set[str]:
    seen: set[str] = set()
    stack = [e.dxf.name for e in doc.modelspace().query("INSERT")]
    stack += [e.dxf.geometry for e in doc.modelspace().query("DIMENSION") if e.dxf.hasattr("geometry")]
    while stack:
        name = stack.pop()
        if name in seen or name not in doc.blocks:
            continue
        seen.add(name)
        block = doc.blocks[name]
        stack.extend(e.dxf.name for e in block.query("INSERT"))
        stack.extend(e.dxf.geometry for e in block.query("DIMENSION") if e.dxf.hasattr("geometry"))
    return seen


def snapshot(path: Path) -> dict:
    """Отпечатки всех объектов модели и используемых блоков по handle, плюс сводка по файлу."""
    doc, mode = _load(path)
    used = _used_blocks(doc)
    objects: dict[str, tuple] = {}
    where: dict[str, str] = {}
    unused = Counter()
    missing = Counter()
    for layout, name in [(doc.modelspace(), "*Model_Space")] + [
        (b, b.name) for b in doc.blocks if not b.is_any_layout
    ]:
        in_use = name == "*Model_Space" or name in used
        for entity in layout:
            if entity.dxftype() == "INSERT" and entity.dxf.name not in doc.blocks:
                missing[entity.dxf.name or "(пустое имя)"] += 1
            if not in_use:
                unused[entity.dxftype()] += 1
                continue
            handle = entity.dxf.handle
            try:
                print_ = digest(entity)
            except Exception as error:  # noqa: BLE001 - отпечаток не должен ронять сверку
                print_ = ("ошибка отпечатка", type(error).__name__)
            objects[handle] = (entity.dxftype(), entity.dxf.get("layer", "0"), print_)
            where[handle] = name
    return {"mode": mode, "version": doc.dxfversion, "objects": objects, "where": where,
            "unused": unused, "missing": missing}


def _caret_only(a: tuple, b: tuple) -> bool:
    """В DXF литеральный «^» пишется как «^ », LibreDWG пишет его как есть."""
    if a[0] != b[0] or a[1] != b[1] or not a[2] or not b[2]:
        return False
    left, right = a[2][0], b[2][0]
    return (
        isinstance(left, str)
        and isinstance(right, str)
        and left != right
        and left.replace("^ ", "^") == right.replace("^ ", "^")
        and same(a[2][1:], b[2][1:])
    )


def compare(job: tuple[str, str]) -> dict:
    street, name = job
    left, right = snapshot(LEFT / street / name), snapshot(RIGHT / street / name)
    lo, ro = left["objects"], right["objects"]
    only_left = sorted(set(lo) - set(ro))
    only_right = sorted(set(ro) - set(lo))
    kinds = Counter()
    examples: dict[str, list] = {}
    for handle in sorted(set(lo) & set(ro)):
        a, b = lo[handle], ro[handle]
        if same(a, b):
            continue
        if a[0] == "REGION" and a[2] == (False,) and b[2] == (True,):
            kinds["REGION: у LibreDWG нет ACIS"] += 1
            continue
        if _caret_only(a, b):
            kinds[f"{a[0]}: знак ^ (LibreDWG пишет без экранирования)"] += 1
            continue
        field = "тип" if a[0] != b[0] else "слой" if a[1] != b[1] else "геометрия"
        key = f"{a[0]}: {field}"
        kinds[key] += 1
        if len(examples.setdefault(key, [])) < EXAMPLES:
            examples[key].append({"handle": handle, "block": left["where"][handle],
                                  "libredwg": repr(a)[:300], "oda": repr(b)[:300]})
    def by_type(handles, side):
        return dict(Counter(side["objects"][h][0] for h in handles))
    return {
        "street": street, "file": name,
        "libredwg": {"mode": left["mode"], "version": left["version"], "objects": len(lo),
                     "missing_blocks": dict(left["missing"]), "unused": sum(left["unused"].values())},
        "oda": {"mode": right["mode"], "version": right["version"], "objects": len(ro),
                "missing_blocks": dict(right["missing"]), "unused": sum(right["unused"].values())},
        "only_libredwg": by_type(only_left, left), "only_oda": by_type(only_right, right),
        "only_examples": {"libredwg": only_left[:EXAMPLES], "oda": only_right[:EXAMPLES]},
        "mismatch": dict(kinds), "examples": examples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", type=int, help="номера улиц")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--resume", action="store_true", help="пропустить уже сверенные файлы")
    args = parser.parse_args()
    catalog = json.loads((RIGHT / "catalog.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    report = OUT / "report.jsonl"
    done: set[tuple[str, str]] = set()
    if args.resume and report.exists():
        for line in report.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            done.add((row["street"], row["file"]))
    jobs = [
        (street["slug"], name)
        for street in catalog
        if not args.only or street["number"] in args.only
        for name in street["files"]
        if (LEFT / street["slug"] / name).exists() and (street["slug"], name) not in done
    ]
    # Большие файлы первыми: так пул не ждёт в конце один долгий.
    jobs.sort(key=lambda j: -(RIGHT / j[0] / j[1]).stat().st_size)
    print(f"к сверке {len(jobs)} файлов, уже сверено {len(done)}", flush=True)
    mode = "a" if args.resume else "w"
    with report.open(mode, encoding="utf-8") as sink, ProcessPoolExecutor(args.workers) as pool:
        for row in pool.map(compare, jobs):
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            sink.flush()
            same = not row["only_libredwg"] and not row["only_oda"] and not any(
                not k.startswith("REGION") for k in row["mismatch"]
            )
            print(f"{'OK ' if same else 'РАЗН'} {row['street']}/{row['file']}: объектов "
                  f"{row['libredwg']['objects']}/{row['oda']['objects']}, "
                  f"только LibreDWG {row['only_libredwg']}, только ODA {row['only_oda']}, "
                  f"расхождения {row['mismatch']}", flush=True)
    print(f"отчёт: {report}")


if __name__ == "__main__":
    main()
