"""Готовит демонстрационный фрагмент настоящей улицы из большого чертежа.

Зачем. Генплан улицы Берзарина весит 95 МБ, считается больше двух минут и в git не
кладётся. Для кнопки «показать сразу» нужен настоящий кусок городской подосновы: подлинные
слои Мосгеотреста, настоящие сети с подписанными диаметрами, борт, газоны и здания.

Почему нельзя просто вырезать сущности. В модельном пространстве генплана 95 объектов -
всё остальное лежит внутри блоков и внешних ссылок. Поэтому фрагмент собирается из уже
развёрнутой сцены: загрузчик сервиса раскрывает блоки и чинит строки, после чего геометрия
переносится в новый чертёж с исходными именами слоёв. Это перенос, а не перерисовка:
координаты и слои те же, теряется только блочная структура, которая сервису не нужна.

    uv run python tools/make_demo_fragment.py исходный.dxf out.dxf --size 420 --auto
    uv run python tools/make_demo_fragment.py исходный.dxf out.dxf --x0 ... --y0 ... --x1 ... --y1 ...
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import ezdxf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from green.bootstrap.container import build_container  # noqa: E402
from green.bootstrap.settings import Settings  # noqa: E402

Window = tuple[float, float, float, float]


def feature_bbox(geometry: object) -> Window | None:
    try:
        bounds = geometry.bounds  # type: ignore[attr-defined]
    except AttributeError, ValueError:
        return None
    if not bounds or bounds[0] != bounds[0]:  # NaN
        return None
    return (bounds[0], bounds[1], bounds[2], bounds[3])


def overlaps(box: Window, window: Window) -> bool:
    return not (
        box[2] < window[0] or box[0] > window[2] or box[3] < window[1] or box[1] > window[3]
    )


def pick_window(boxes: list[Window], size: float, cell: float) -> Window:
    """Самая плотная клетка сетки, расширенная до нужного окна.

    Плотность считается по числу объектов: там, где их больше всего, гарантированно есть
    и сети, и борт, и застройка - то есть то, ради чего демонстрация и показывается.
    """
    grid: Counter[tuple[int, int]] = Counter()
    for box in boxes:
        cx = (box[0] + box[2]) / 2
        cy = (box[1] + box[3]) / 2
        grid[(int(cx // cell), int(cy // cell))] += 1
    (gx, gy), count = grid.most_common(1)[0]
    print(f"самая плотная клетка {cell:.0f} м: {count} объектов")
    cx = (gx + 0.5) * cell
    cy = (gy + 0.5) * cell
    half = size / 2
    return (cx - half, cy - half * 0.45, cx + half, cy + half * 0.45)


def write_fragment(
    features: list, labels: list, window: Window, target: Path, unit_m: float
) -> None:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6  # метры: сцена уже пересчитана в метры
    msp = doc.modelspace()
    layers = {f.layer for f in features} | {label.layer for label in labels}
    for name in sorted(layers):
        if name and name not in doc.layers:
            doc.layers.add(name)

    written = Counter()
    for feature in features:
        geometry = feature.geometry
        attribs = {"layer": feature.layer or "0"}
        for part in _parts(geometry):
            kind = part.geom_type
            if kind == "Point":
                msp.add_circle((part.x, part.y), 0.25, dxfattribs=attribs)
            elif kind == "LineString":
                coords = [(x, y) for x, y, *_ in part.coords]
                if len(coords) >= 2:
                    msp.add_lwpolyline(coords, dxfattribs=attribs)
            elif kind == "Polygon":
                ring = [(x, y) for x, y, *_ in part.exterior.coords]
                if len(ring) >= 3:
                    msp.add_lwpolyline(ring, close=True, dxfattribs=attribs)
            else:
                continue
            written[kind] += 1

    for label in labels:
        msp.add_text(
            label.text[:240],
            height=1.2,
            dxfattribs={"layer": label.layer or "0"},
        ).set_placement((label.x, label.y))

    doc.saveas(target)
    print(f"перенесено: {dict(written)}, подписей {len(labels)}, единица {unit_m} м")


def _parts(geometry: object) -> list:
    kind = getattr(geometry, "geom_type", "")
    if kind.startswith("Multi") or kind == "GeometryCollection":
        return list(geometry.geoms)  # type: ignore[attr-defined]
    return [geometry]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source")
    ap.add_argument("target")
    ap.add_argument("--size", type=float, default=420.0, help="ширина окна, м")
    ap.add_argument("--cell", type=float, default=300.0)
    ap.add_argument("--auto", action="store_true", help="выбрать самое плотное место")
    ap.add_argument("--x0", type=float)
    ap.add_argument("--y0", type=float)
    ap.add_argument("--x1", type=float)
    ap.add_argument("--y1", type=float)
    args = ap.parse_args()

    container = build_container(Settings(config_dir=ROOT / "config"))
    print(f"читаем {args.source} загрузчиком сервиса ...", flush=True)
    scene = container.reader.read(Path(args.source))
    print(f"объектов в сцене: {len(scene.features)}, подписей: {len(scene.labels)}")

    boxes = [(f, feature_bbox(f.geometry)) for f in scene.features]
    known = [(f, b) for f, b in boxes if b]
    if not known:
        print("не удалось взять габариты")
        return

    if args.x0 is not None:
        window = (args.x0, args.y0, args.x1, args.y1)
    elif args.auto:
        window = pick_window([b for _, b in known], args.size, args.cell)
    else:
        xs = [b[0] for _, b in known]
        ys = [b[1] for _, b in known]
        print(
            f"границы: x {min(xs):.0f}..{max(b[2] for _, b in known):.0f}, "
            f"y {min(ys):.0f}..{max(b[3] for _, b in known):.0f}"
        )
        return

    print(f"окно: x {window[0]:.0f}..{window[2]:.0f}, y {window[1]:.0f}..{window[3]:.0f}")
    features = [f for f, b in known if overlaps(b, window)]
    labels = [
        label
        for label in scene.labels
        if window[0] <= label.x <= window[2] and window[1] <= label.y <= window[3]
    ]
    print(f"в окне: {len(features)} объектов, {len(labels)} подписей")
    if not features:
        print("окно пустое")
        return

    target = Path(args.target)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_fragment(features, labels, window, target, scene.unit_m)
    print(f"записано {target} ({target.stat().st_size / 1048576:.2f} МБ)")
    top = Counter(f.layer for f in features).most_common(10)
    print(f"слои: {len(set(f.layer for f in features))}; частые: {top}")


if __name__ == "__main__":
    main()
