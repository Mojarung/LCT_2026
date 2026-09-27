"""Отрисовать окно большого DXF со всеми исходными слоями и посадками GREEN_* в PNG.

Чертёж читается потоком (iterdxf): в память попадает только окно, поэтому годится и для
комплекта в сотни мегабайт. Подписи и зоны сервиса (GREEN_LABELS, GREEN_ZONE_*) скрыты,
чтобы было видно, куда встали посадки относительно исходного чертежа.

    uv run --with matplotlib --with pillow python tools/research/render_window.py \
        result.dxf out.png x0 y0 x1 y1
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import ezdxf
import matplotlib.pyplot as plt
from ezdxf.addons import iterdxf
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

src, out = Path(sys.argv[1]), Path(sys.argv[2])
x0, y0, x1, y1 = map(float, sys.argv[3:7])
pad = 5.0


def points(e):
    t = e.dxftype()
    d = e.dxf
    try:
        if t == "LINE":
            return [d.start, d.end]
        if t == "LWPOLYLINE":
            return [(p[0], p[1]) for p in e.get_points()]
        if t == "POLYLINE":
            return [v.dxf.location for v in e.vertices]
        if t in {"CIRCLE", "ARC", "ELLIPSE"}:
            return [d.center]
        if t == "HATCH":
            pts = []
            for path in e.paths:
                if hasattr(path, "vertices"):
                    pts += [(v[0], v[1]) for v in path.vertices]
                else:
                    for edge in path.edges:
                        for name in ("start", "end", "center"):
                            if hasattr(edge, name):
                                pts.append(getattr(edge, name))
            return pts
        if t == "SPLINE":
            return list(e.control_points) or list(e.fit_points)
        if d.hasattr("insert"):
            return [d.insert]
    except Exception:  # noqa: BLE001 - кривую сущность просто пропускаем
        return []
    return []


def inside(pts):
    if not pts:
        return False
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (
        min(xs) <= x1 + pad and max(xs) >= x0 - pad and min(ys) <= y1 + pad and max(ys) >= y0 - pad
    )


window = out.with_suffix(".dxf")
doc = iterdxf.opendxf(str(src))
exporter = doc.export(str(window))
kept = 0
try:
    for entity in doc.modelspace():
        if inside(points(entity)):
            # Словари расширений и реакторы ссылаются на объекты, которых в окне нет.
            entity.extension_dict = None
            entity.reactors = None
            try:
                exporter.write(entity)
            except Exception:  # noqa: BLE001
                continue
            kept += 1
finally:
    exporter.close()
    doc.close()
print("сущностей в окне:", kept)

small = ezdxf.readfile(window)
# Наши подписи и зоны прячем: смотрим, куда встали посадки относительно исходного чертежа.
for layer in small.layers:
    if layer.dxf.name.startswith(("GREEN_LABELS", "GREEN_ZONE")):
        layer.off()
fig = plt.figure(figsize=(14, 14 * (y1 - y0) / (x1 - x0)))
ax = fig.add_axes((0, 0, 1, 1))
ax.set_aspect("equal", adjustable="box")
config = Configuration(
    background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR_NEGATIVE
)
Frontend(RenderContext(small), MatplotlibBackend(ax), config=config).draw_layout(small.modelspace())
ax.set_xlim(x0, x1)
ax.set_ylim(y0, y1)
fig.savefig(out, dpi=110)
print("готово:", out)
