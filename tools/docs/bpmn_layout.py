"""Раскладка BPMN 2.0 (BPMNDiagram DI) по сетке: ряды слева направо, ветки под шлюзом.

bpmn-auto-layout ставит процесс в один столбец - для листа A4 он не годится. Здесь положение
каждого узла задано явно (ряд, столбец, ветка), рёбра прокладываются ортогонально:
по ряду - напрямую, в ветку - вниз, на следующий ряд - через промежуток между рядами,
возврат цикла - под рядом. Семантика процесса (узлы и переходы) берётся из файла как есть.

    uv run python tools/docs/bpmn_layout.py docs/documentation/diagrams/process.bpmn process
"""
# ruff: noqa: INP001, T201, S101, S314, C901, PLR0911, PLR0912, PLR0915 - сборка документации, свой BPMN

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
DI = "http://www.omg.org/spec/BPMN/20100524/DI"
DC = "http://www.omg.org/spec/DD/20100524/DC"
DDI = "http://www.omg.org/spec/DD/20100524/DI"
for prefix, uri in (("", BPMN), ("bpmndi", DI), ("dc", DC), ("di", DDI)):
    ET.register_namespace(prefix, uri)

# Крупные узлы и шрифт 17 px: схема ужимается до ширины листа A4, текст в печати - около 6,5 пт.
COL_W, ROW_H, X0, Y0 = 214, 310, 200, 100
SIZE = {
    "task": (180, 104),
    "exclusiveGateway": (50, 50),
    "startEvent": (36, 36),
    "endEvent": (36, 36),
}
BRANCH_DY = 125  # ветка (тупиковое событие) под узлом
LOOP_DY = 100  # возврат цикла под рядом
WRAP_DY = 225  # переход на следующий ряд - ниже подписей тупиковых событий


@dataclass(frozen=True)
class Slot:
    row: int
    col: int
    branch: bool = False  # под узлом того же столбца


# Положения узлов для каждой схемы: (ряд, столбец, ветка).
LAYOUTS: dict[str, dict[str, Slot]] = {
    "process": {
        "start": Slot(0, 0),
        "g_dwg": Slot(0, 1),
        "t_convert": Slot(0, 2),
        "g_dwg_join": Slot(0, 3),
        "t_assemble": Slot(0, 4),
        "t_read": Slot(0, 5),
        "g_read": Slot(1, 0),
        "e_read": Slot(1, 0, branch=True),
        "t_classify": Slot(1, 1),
        "g_classify": Slot(1, 2),
        "e_classify": Slot(1, 2, branch=True),
        "t_gis": Slot(1, 3),
        "t_surface": Slot(1, 4),
        "t_index": Slot(1, 5),
        "t_candidates": Slot(2, 0),
        "t_select": Slot(2, 1),
        "t_species": Slot(2, 2),
        "t_shrubs": Slot(2, 3),
        "t_validate": Slot(2, 4),
        "g_portfolio": Slot(2, 5),
        "t_choose": Slot(3, 0),
        "t_refine": Slot(3, 1),
        "t_lawns": Slot(3, 2),
        "t_explain": Slot(3, 3),
        "t_write": Slot(3, 4),
        "t_verify": Slot(3, 5),
        "g_verify": Slot(4, 0),
        "e_verify": Slot(4, 0, branch=True),
        "t_artifacts": Slot(4, 1),
        "e_done": Slot(4, 2),
    },
    "editing": {
        "start": Slot(0, 0),
        "g_after": Slot(0, 1),
        "t_edit": Slot(0, 2),
        "t_recheck": Slot(0, 3),
        "t_rewrite": Slot(0, 4),
        "g_ok": Slot(0, 5),
        "e_saved": Slot(0, 6),
        "e_kept": Slot(0, 5, branch=True),
        "t_scene": Slot(1, 2),
        "t_shots": Slot(1, 3),
        "e_scene": Slot(1, 4),
    },
}
# Переходы, которые ведутся через явные точки, а не по общему правилу.
LOOPS = {("g_portfolio", "t_candidates")}
BYPASS_BELOW = {("g_dwg", "g_dwg_join")}


LABEL_W = 170


def text_height(text: str, width: float = LABEL_W) -> float:
    """Высота внешней подписи: 16 px Arial, около 9,4 px на знак кириллицы."""
    per_line = int(width / 9.4)
    words, lines, line = text.split(), 1, 0
    for word in words:
        if line and line + 1 + len(word) > per_line:
            lines, line = lines + 1, len(word)
        else:
            line += len(word) + (1 if line else 0)
    return lines * 19 + 4


def centre(slot: Slot) -> tuple[float, float]:
    x = X0 + slot.col * COL_W
    y = Y0 + slot.row * ROW_H + (BRANCH_DY if slot.branch else 0)
    return x, y


def layout(path: Path, scheme: str) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    for old in root.findall(f"{{{DI}}}BPMNDiagram"):
        root.remove(old)
    process = root.find(f"{{{BPMN}}}process")
    assert process is not None
    slots = LAYOUTS[scheme]
    kinds: dict[str, str] = {}
    for element in process:
        tag = element.tag.split("}")[1]
        if tag in SIZE:
            kinds[element.get("id", "")] = tag
    missing = set(kinds) - set(slots)
    assert not missing, f"нет положения для {missing}"

    diagram = ET.SubElement(root, f"{{{DI}}}BPMNDiagram", id=f"{scheme}_diagram")
    plane = ET.SubElement(
        diagram, f"{{{DI}}}BPMNPlane", id=f"{scheme}_plane", bpmnElement=process.get("id", "")
    )
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for node, kind in kinds.items():
        w, h = SIZE[kind]
        cx, cy = centre(slots[node])
        boxes[node] = (cx - w / 2, cy - h / 2, w, h)
        shape = ET.SubElement(plane, f"{{{DI}}}BPMNShape", id=f"{node}_di", bpmnElement=node)
        if kind == "exclusiveGateway":
            shape.set("isMarkerVisible", "true")
        x, y, bw, bh = boxes[node]
        ET.SubElement(
            shape, f"{{{DC}}}Bounds", x=f"{x:.0f}", y=f"{y:.0f}", width=f"{bw}", height=f"{bh}"
        )
        if kind != "task":
            name = next(e.get("name", "") for e in process if e.get("id") == node)
            label = ET.SubElement(shape, f"{{{DI}}}BPMNLabel")
            if kind == "exclusiveGateway":
                # Вопрос шлюза - над ромбом (вход слева, выходы вправо и вниз); у шлюза в первом
                # столбце вход сверху, поэтому вопрос слева.
                lw, lh = LABEL_W, text_height(name)
                if slots[node].col == 0:
                    lx, ly = x - 10 - lw, cy - lh / 2
                elif node in {source for source, _ in LOOPS}:
                    # Над ним идёт переход ряда, справа - выход: вопрос под входящей линией,
                    # в промежутке до соседней задачи.
                    lw = COL_W - SIZE["task"][0] // 2 - 25 - 16
                    lh = text_height(name, lw)
                    lx, ly = x - 6 - lw, cy + 8
                else:
                    lx, ly = cx - lw / 2, y - 8 - lh
            else:  # событие: подпись под кругом
                lw, lh = LABEL_W, text_height(name)
                lx, ly = cx - lw / 2, y + bh + 4
            ET.SubElement(
                label,
                f"{{{DC}}}Bounds",
                x=f"{lx:.0f}",
                y=f"{ly:.0f}",
                width=f"{lw}",
                height=f"{lh:.0f}",
            )

    for flow in process.findall(f"{{{BPMN}}}sequenceFlow"):
        source, target = flow.get("sourceRef", ""), flow.get("targetRef", "")
        points = route(source, target, slots, boxes)
        edge = ET.SubElement(
            plane, f"{{{DI}}}BPMNEdge", id=f"{flow.get('id')}_di", bpmnElement=flow.get("id", "")
        )
        for px, py in points:
            ET.SubElement(edge, f"{{{DDI}}}waypoint", x=f"{px:.0f}", y=f"{py:.0f}")
        if flow.get("name"):
            (ax, ay), (bx, _) = points[0], points[1]
            lw = 9 * len(flow.get("name", "")) + 10
            if (source, target) in LOOPS:  # возврат цикла: подпись на нижнем участке петли
                lx, ly = points[1][0] - lw - 8, points[1][1] + 4
            elif ax == bx:  # вертикальный выход: подпись справа от линии, у самого шлюза
                lx, ly = ax + 6, ay + 6
            else:  # горизонтальный: над линией, у начала
                lx, ly = ax + 4, ay - 24
            label = ET.SubElement(edge, f"{{{DI}}}BPMNLabel")
            ET.SubElement(
                label, f"{{{DC}}}Bounds", x=f"{lx:.0f}", y=f"{ly:.0f}", width=f"{lw}", height="20"
            )
    ET.indent(tree, space="  ")
    tree.write(path, encoding="UTF-8", xml_declaration=True)


def route(
    source: str,
    target: str,
    slots: dict[str, Slot],
    boxes: dict[str, tuple[float, float, float, float]],
) -> list[tuple[float, float]]:
    s, t = slots[source], slots[target]
    sx, sy, sw, sh = boxes[source]
    tx, ty, tw, th = boxes[target]
    scx, scy = sx + sw / 2, sy + sh / 2
    tcx, tcy = tx + tw / 2, ty + th / 2
    if (source, target) in BYPASS_BELOW:
        low = scy + 60
        return [(scx, sy + sh), (scx, low), (tcx, low), (tcx, ty + th)]
    if (source, target) in LOOPS:
        low = scy + LOOP_DY
        return [(scx, sy + sh), (scx, low), (tcx, low), (tcx, ty + th)]
    if t.branch and t.col == s.col and t.row == s.row:
        return [(scx, sy + sh), (tcx, ty)]
    if t.branch and t.row == s.row:  # ветка под другим столбцом: вниз и вбок
        return [(scx, sy + sh), (scx, tcy), (tx if tcx > scx else tx + tw, tcy)]
    if s.row == t.row and t.col > s.col and not s.branch:
        return [(sx + sw, scy), (tx, tcy)]
    if s.branch and t.row == s.row + 1 and not t.branch:  # из ветки вниз, на следующий ряд
        return [(scx, sy + sh), (scx, tcy - ROW_H / 2 + 20), (tcx, tcy - ROW_H / 2 + 20), (tcx, ty)]
    if t.row == s.row + 1 and t.col > s.col:  # ветвь вниз-вправо: сразу вниз, потом вправо
        return [(scx, sy + sh), (scx, tcy), (tx, tcy)]
    if t.row == s.row + 1:  # на следующий ряд: вправо, вниз в промежуток, влево, вниз
        gap = scy + WRAP_DY
        return [(sx + sw, scy), (sx + sw + 25, scy), (sx + sw + 25, gap), (tcx, gap), (tcx, ty)]
    if t.row > s.row:  # вниз через несколько рядов
        return (
            [(scx, sy + sh), (scx, tcy), (tx, tcy)]
            if tcx > scx
            else [(scx, sy + sh), (scx, ty - 20), (tcx, ty - 20), (tcx, ty)]
        )
    return [(sx + sw, scy), (tx, tcy)]


if __name__ == "__main__":
    layout(Path(sys.argv[1]), sys.argv[2])
    print("laid out", sys.argv[1])
