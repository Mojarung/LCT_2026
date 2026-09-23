"""Local visual review of synthetic benchmark output; requires Pillow, not CAD uploads."""
# ruff: noqa: INP001, T201 - standalone artifact script

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1] / "out/placement-benchmark"


def main() -> None:
    image = Image.new("RGB", (1500, 1040), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.text((25, 20), "Complete layouts: baseline vs portfolio", fill="#153d2e", font_size=30)
    draw.text(
        (25, 60),
        "Green circles: tree symbols (10-year crowns); orange: shrubs; blue: water pipe.",
        fill="#444444",
        font_size=18,
    )
    colors = {"lawn": "#edf7ed", "road": "#dedee2", "sidewalk": "#f0e9dc", "building": "#b4b4ba"}
    for row, (case, angle) in enumerate((("strip-0.37", 0.37), ("courtyard-0.83", 0.83))):
        for col, solver in enumerate(("greedy", "portfolio")):
            directory = ROOT / case / solver
            plan = json.loads((directory / "plan.json").read_text())
            basemap = json.loads((directory / "basemap.geojson").read_text())
            quality = json.loads((directory / "quality.json").read_text())
            ox, oy = 45 + col * 750, 160 + row * 440

            def point(
                x: float, y: float, ox: float = ox, oy: float = oy, angle: float = angle
            ) -> tuple[float, float]:
                dx, dy = x - 100_000, y - 200_000
                return (
                    ox + 6.5 * (dx * math.cos(angle) + dy * math.sin(angle)),
                    oy + 6.5 * (50 + dx * math.sin(angle) - dy * math.cos(angle)),
                )

            draw.text((ox, oy - 52), f"{case} / {solver}", fill="#153d2e", font_size=21)
            draw.text(
                (ox, oy - 26),
                f"Quality: {quality['index']:.3f} | plants: {len(plan['placements'])}",
                fill="#444444",
                font_size=18,
            )
            for feature in basemap["features"]:
                kind, geom = feature["properties"]["class"], feature["geometry"]
                if geom["type"] == "Polygon":
                    pts = [point(*xy[:2]) for xy in geom["coordinates"][0]]
                    if kind in colors:
                        draw.polygon(pts, fill=colors[kind])
                    else:
                        draw.line(pts, fill="#888888", width=1)
                elif geom["type"] == "LineString":
                    draw.line(
                        [point(*xy[:2]) for xy in geom["coordinates"]],
                        fill="#3983b8" if kind.startswith("utility") else "#555555",
                        width=2,
                    )
            for p in plan["placements"]:
                x, y = point(p["x"], p["y"])
                radius = p["species"]["crown_diameter_m"] * 3.25
                tree = p["planting_type"] == "tree"
                draw.ellipse(
                    (x - radius, y - radius, x + radius, y + radius),
                    outline="#267b4a" if tree else "#b97b31",
                    width=2 if tree else 1,
                )
                draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill="#174d2e" if tree else "#b97b31")
    target = ROOT / "comparison.png"
    image.save(target)
    print(target)


if __name__ == "__main__":
    main()
