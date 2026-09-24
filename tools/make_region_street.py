"""Create a fixed street with equivalent REGION or LWPOLYLINE obstacles."""

# ruff: noqa: INP001, T201 - standalone fixture generator

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import ezdxf
from ezdxf.acis import api
from ezdxf.render import MeshBuilder


def make(path: Path, *, polyline: bool = False, curved: bool = False) -> None:
    doc = ezdxf.new("R2010" if curved else "R2018")
    doc.header["$INSUNITS"] = 6
    for layer in (
        "Граница заказа",
        "Бортовой камень",
        "Граница улицы",
        "Леса и газоны",
        "Водопровод",
        "Здания",
    ):
        doc.layers.add(layer)
    space = doc.modelspace()
    space.add_lwpolyline(
        [(0, 0), (120, 0), (120, 60), (0, 60)],
        close=True,
        dxfattribs={"layer": "Граница заказа"},
    )
    for x in range(120):
        space.add_line((x, 20), (x + 0.7, 20), dxfattribs={"layer": "Бортовой камень"})
    space.add_lwpolyline(
        [(0, 20), (120, 20), (120, 55), (0, 55)],
        close=True,
        dxfattribs={"layer": "Леса и газоны"},
    )
    space.add_text("А", height=2.5, dxfattribs={"layer": "Граница улицы"}).set_placement(
        (60, 10)
    )
    space.add_text("ГАЗОН", height=2.5, dxfattribs={"layer": "Леса и газоны"}).set_placement(
        (60, 30)
    )
    space.add_line((0, 40), (120, 40), dxfattribs={"layer": "Водопровод"})
    space.add_text("d=300ст.", height=2.5, dxfattribs={"layer": "Водопровод"}).set_placement(
        (60, 40.5)
    )
    space.add_lwpolyline(
        [(0, 55), (120, 55), (120, 60), (0, 60)],
        close=True,
        dxfattribs={"layer": "Здания"},
    )
    corners = [(45, 29), (55, 29), (55, 35), (45, 35)]
    if polyline:
        if curved:
            space.add_lwpolyline(
                [(45, 29, 1), (55, 29, 0), (55, 35, 0), (45, 35, 0)],
                format="xyb",
                close=True,
                dxfattribs={"layer": "Здания"},
            )
        else:
            space.add_lwpolyline(corners, close=True, dxfattribs={"layer": "Здания"})
    else:
        mesh = MeshBuilder()
        mesh.add_face([(x, y, 0) for x, y in corners])
        region = space.add_region(dxfattribs={"layer": "Здания"})
        api.export_dxf(region, [api.body_from_mesh(mesh)])
        if curved:
            sat = list(region.sat)
            index = next(index for index, line in enumerate(sat) if "straight-curve" in line)
            sat[index] = "ellipse-curve $-1 -1 $-1 0 -3 0 0 0 1 5 0 0 1 I I #"
            region.sat = sat
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)
    loaded = ezdxf.readfile(path)
    if not polyline:
        regions = loaded.modelspace().query("REGION")
        if len(regions) != 1 or not (regions[0].sat if curved else regions[0].sab):
            raise RuntimeError("The generated REGION lost its ACIS payload")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--polyline", action="store_true")
    parser.add_argument("--curved", action="store_true")
    args = parser.parse_args()
    make(args.path, polyline=args.polyline, curved=args.curved)
    print(hashlib.sha256(args.path.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
