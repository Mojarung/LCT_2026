"""Картинка: зоны допустимости и посадки green рядом с деревьями проектировщика.

Вход: папка прогона (plan.json, zones.geojson), provenance.pkl из нормоконтроля эталона
(деревья проектировщика и сети), окно в метрах. Выход: PNG всего участка и окна.
"""

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from shapely import from_wkb
from shapely.geometry import shape

run_dir, prov_path, out_dir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
window = float(sys.argv[4]) if len(sys.argv) > 4 else 60.0
out_dir.mkdir(parents=True, exist_ok=True)

plan = json.loads((run_dir / "plan.json").read_text("utf-8"))
zones = json.loads((run_dir / "zones.geojson").read_text("utf-8"))
prov = pickle.load(prov_path.open("rb"))

ours = np.array([(p["x"], p["y"]) for p in plan["placements"]]) if plan["placements"] else np.zeros((0, 2))
rejects = np.array([(r["x"], r["y"]) for r in plan["rejections"]]) if plan["rejections"] else np.zeros((0, 2))
designer = np.array([(t["x"], t["y"]) for t in prov["trees"] if t["r"] >= 1.0])
COL = {"Кабель электрический": "#d62728", "Водопровод": "#1f77b4", "Канализация самотёчная": "#8c564b",
       "Газопровод": "#d4a000", "Теплосеть": "#ff7f0e", "Кабель связи": "#9467bd", "Бортовой камень": "#444444",
       "Здания": "#000000"}


def draw(ax, bounds):
    minx, miny, maxx, maxy = bounds
    for feature in zones["features"]:
        geom = shape(feature["geometry"])
        color = "#2ca02c" if feature["properties"]["verdict"] == "allowed" else "#ff7f0e"
        for poly in getattr(geom, "geoms", [geom]):
            if not poly.intersects_bbox(bounds) if hasattr(poly, "intersects_bbox") else True:
                pass
            xs, ys = poly.exterior.xy
            ax.fill(xs, ys, color=color, alpha=0.25, lw=0)
    for rec in prov["recs"]:
        color = COL.get(rec["cls"])
        if color is None:
            continue
        geom = from_wkb(rec["wkb"])
        bx = geom.bounds
        if bx[2] < minx or bx[0] > maxx or bx[3] < miny or bx[1] > maxy:
            continue
        x, y = geom.xy
        ax.plot(x, y, color=color, lw=0.6, alpha=0.8)
    if len(rejects):
        ax.plot(rejects[:, 0], rejects[:, 1], "x", color="#bbbbbb", ms=3, mew=0.6, label="отказы green")
    if len(designer):
        ax.plot(designer[:, 0], designer[:, 1], "o", mfc="none", mec="#1f77b4", ms=7, mew=1.2, label="деревья проектировщика")
    if len(ours):
        ax.plot(ours[:, 0], ours[:, 1], "o", color="#2ca02c", ms=4, label="посадки green")
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_aspect("equal")


pts = np.vstack([p for p in (ours, designer) if len(p)])
minx, miny = pts.min(axis=0) - 20
maxx, maxy = pts.max(axis=0) + 20
fig, ax = plt.subplots(figsize=(28, 12))
draw(ax, (minx, miny, maxx, maxy))
ax.legend(loc="upper right")
ax.set_title(f"Берзарина: посадок green {len(ours)}, отказов {len(rejects)}, деревьев проектировщика {len(designer)}")
fig.savefig(out_dir / "overview.png", dpi=80, bbox_inches="tight")
plt.close(fig)

# окно там, где больше всего наших посадок
if len(ours):
    hist, xe, ye = np.histogram2d(ours[:, 0], ours[:, 1], bins=[int((maxx - minx) / window) + 1, int((maxy - miny) / window) + 1])
    i, j = np.unravel_index(hist.argmax(), hist.shape)
    cx, cy = (xe[i] + xe[i + 1]) / 2, (ye[j] + ye[j + 1]) / 2
    fig, ax = plt.subplots(figsize=(14, 14))
    draw(ax, (cx - window, cy - window, cx + window, cy + window))
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)
    ax.set_title(f"Окно {2 * window:.0f} м вокруг ({cx:.0f}, {cy:.0f})")
    fig.savefig(out_dir / "window.png", dpi=90, bbox_inches="tight")
    print("window center", round(cx, 1), round(cy, 1))
print("saved", out_dir)
