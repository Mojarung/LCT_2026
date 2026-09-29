"""Знаки видов из «Шаблонов значков» заказчика -> данные карты веб-интерфейса.

Шаблон `dataset/Датасет/Шаблоны значков.dwg` - чертёж с таблицей «Ведомость элементов
озеленения» (ACAD_TABLE в пространстве модели): «Поз. / Условное обозначение /
Наименование породы или вид насаждения». В ячейке «Условное обозначение» у каждой строки
лежит вставка блока - знак вида: хвойные, лиственные деревья, кустарники, лианы и четыре знака
существующих насаждений. Инструмент берёт знак каждой строки и пишет его геометрию в
`frontend/src/map/templateSigns.json`; карта инженерного стиля и легенда рисуют по нему знак
вида (frontend/src/map/templateSigns.ts, соответствие видам каталога - там же).

    uv run python tools/extract_template_signs.py                  DWG из датасета через ODA
    uv run python tools/extract_template_signs.py --dxf шаблон.dxf готовый DXF (без ODA)
    uv run python tools/extract_template_signs.py --check          сверить с файлом в репозитории

Как читается знак:
- строка таблицы - по линиям сетки из блока самой таблицы, текст ячеек - из её содержимого;
  знак - то, что лежит в ячейке «Условное обозначение» по габариту отрисовки: точка вставки у
  части блоков заказчика вынесена далеко за знак, поэтому по ней строку не найти;
- геометрия - движком отрисовки ezdxf (тот же, что у сверки чернил сервиса): цвет ПоБлоку и
  ПоСлою, прозрачность, вес линий, образцы штриховки уже разрешены. Выключенные, замороженные
  и непечатаемые слои не попадают, как на печатном листе;
- координаты нормированы: центр - середина габарита знака, радиус 1 - половина большей
  стороны габарита; ось y направлена вниз, как на холсте;
- цвет ACI 7 записан как «ink»: на светлом листе он чёрный, в тёмной теме карты - светлый,
  как в модели CAD. Остальные цвета - как в чертеже, с прозрачностью.

Воспроизводимость: образцы штриховки ezdxf сдвигает на случайную долю шага, поэтому генератор
случайных чисел заводится одним и тем же зерном перед каждым знаком. Дата в шапке меняется,
только когда меняются сами знаки; `--check` сравнивает с файлом побайтно.
"""

# Скрипт командной строки: print - его вывод; tools/ - папка скриптов, а не пакет.
# ruff: noqa: T201, INP001

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any

import ezdxf
from ezdxf import bbox
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.config import Configuration
from ezdxf.addons.drawing.recorder import (
    FilledPathsRecord,
    PathRecord,
    PointsRecord,
    Recorder,
    SolidLinesRecord,
)
from ezdxf.entities.acad_table import read_acad_table_content
from ezdxf.tools.text import plain_mtext

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ezdxf.addons.drawing.properties import BackendProperties
    from ezdxf.addons.drawing.recorder import DataRecord
    from ezdxf.document import Drawing
    from ezdxf.entities import DXFGraphic
    from ezdxf.entities.acad_table import AcadTable
    from ezdxf.math import BoundingBox
    from ezdxf.npshapes import NumpyPath2d

Point = tuple[float, float]
Records = list[tuple["DataRecord", "BackendProperties"]]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from green.infrastructure.convert.oda import OdaFileConverter  # noqa: E402

DATASET = ROOT / "dataset" / "Датасет"
OUT = ROOT / "frontend" / "src" / "map" / "templateSigns.json"
SOURCE = "dataset/Датасет/Шаблоны значков.dwg"
COMMAND = "uv run python tools/extract_template_signs.py"

#: Заголовки разделов таблицы -> раздел знака.
SECTIONS = {
    "Хвойные деревья и кустарники": "conifer",
    "Лиственные деревья": "tree",
    "Лиственные кустарники": "shrub",
    "Лианы": "liana",
    "Существующие зеленые насаждения": "existing",
}
#: Колонки таблицы по заголовку.
SIGN_COLUMN = "Условное обозначение"
NAME_COLUMN = "Наименование породы"

#: Гладкость кривых и допуск упрощения ломаных - в долях радиуса знака. 0,002 радиуса - это
#: 0,2 пикселя у знака радиусом 100 пикселей: крупнее знак на карте не бывает.
FLATTEN = 0.002
SIMPLIFY = 0.0015
DIGITS = 3
#: Штриховка чаще этого (в долях радиуса) - сплошная заливка: линии такого образца не
#: различить ни на одном масштабе карты, а считать их ezdxf может минутами.
MIN_HATCH_GAP = 0.004
SEED = 20260929
#: Вершина дальше этого от центра (в радиусах знака) - запись не из знака.
OUTSIDE = 1.25
#: Яркость, с которой цвет - уже белая маска под знаком, а не его цвет.
WHITE = 0.92
#: Линия сетки таблицы горизонтальна или вертикальна с этой точностью, единиц чертежа.
AXIS_EPS = 1e-6
#: Контур замкнут, если конец совпал с началом с этой точностью (нормированные единицы).
CLOSED_EPS = 1e-9
#: Цвет движка с прозрачностью: #rrggbbaa.
RGBA_LENGTH = 9
#: Перо 7 - ACI 7, цвет «чернил» листа.
ACI_INK = 7
#: Заливке и замкнутому штриху нужно не меньше трёх вершин, отрезку - две.
MIN_RING = 3
SEGMENT = 2


@dataclass(frozen=True)
class Row:
    position: str
    name: str
    section: str
    top: float
    bottom: float


def oda_binary() -> str:
    """ODA File Converter: GREEN_ODA_BINARY, копия в tools/oda, установка Windows, иначе PATH."""
    binary = os.environ.get("GREEN_ODA_BINARY", "")
    if binary:
        return binary
    local = ROOT / "tools" / "oda" / "ODAFileConverter.exe"
    if local.is_file():
        return str(local)
    installed = sorted(Path("C:/Program Files/ODA").glob("ODAFileConverter*/ODAFileConverter.exe"))
    return str(installed[-1]) if installed else "ODAFileConverter"


def template_dwg() -> Path:
    """Шаблон из датасета. Путь с кириллицей берётся перечислением: в argv его портит консоль."""
    found = sorted(path for path in DATASET.glob("*.dwg") if path.stem.startswith("Шаблон"))
    if len(found) != 1:
        message = f"в {DATASET} нет ровно одного DWG «Шаблоны значков»: {found}"
        raise SystemExit(message)
    return found[0]


def convert(dwg: Path, workdir: Path) -> Path:
    converter = OdaFileConverter(binary=oda_binary())
    if not converter.available():
        message = "ODA File Converter не найден: укажите GREEN_ODA_BINARY или готовый DXF (--dxf)"
        raise SystemExit(message)
    return converter.to_dxf(dwg, workdir)


def text(cell: str) -> str:
    return " ".join(plain_mtext(cell).split())


def legend_table(doc: Drawing) -> AcadTable:
    for table in doc.modelspace().query("ACAD_TABLE"):
        rows = read_acad_table_content(table)
        header = [text(cell) for row in rows[:3] for cell in row]
        if SIGN_COLUMN in header:
            return table
    message = f"в шаблоне нет таблицы с колонкой «{SIGN_COLUMN}»"
    raise SystemExit(message)


def grid(doc: Drawing, table: AcadTable) -> tuple[list[float], list[float]]:
    """Линии сетки таблицы в координатах модели: горизонтали сверху вниз, вертикали слева."""
    block = doc.blocks.get(table.dxf.geometry)
    ox, oy = table.dxf.insert.x, table.dxf.insert.y
    horizontal: set[float] = set()
    vertical: set[float] = set()
    for line in block.query("LINE"):
        start, end = line.dxf.start, line.dxf.end
        if abs(start.y - end.y) < AXIS_EPS:
            horizontal.add(round(start.y + oy, 4))
        if abs(start.x - end.x) < AXIS_EPS:
            vertical.add(round(start.x + ox, 4))
    return sorted(horizontal, reverse=True), sorted(vertical)


def table_rows(doc: Drawing, table: AcadTable) -> tuple[list[Row], tuple[float, float]]:
    content = read_acad_table_content(table)
    horizontal, vertical = grid(doc, table)
    if len(horizontal) != len(content) + 1:
        message = f"сетка таблицы не сходится: {len(horizontal)} линий на {len(content)} строк"
        raise SystemExit(message)
    header = next(row for row in content if SIGN_COLUMN in [text(cell) for cell in row])
    names = [text(cell) for cell in header]
    sign_col = names.index(SIGN_COLUMN)
    name_col = next(i for i, name in enumerate(names) if name.startswith(NAME_COLUMN))
    column = (vertical[sign_col], vertical[sign_col + 1])
    rows: list[Row] = []
    section = ""
    for index, cells in enumerate(content):
        first = text(cells[0])
        name = text(cells[name_col])
        if first in SECTIONS and not name:
            section = SECTIONS[first]
            continue
        if not section or not name:
            continue
        rows.append(Row(first, name, section, horizontal[index], horizontal[index + 1]))
    return rows, column


def cell_entities(
    doc: Drawing, table: AcadTable, rows: list[Row], column: tuple[float, float]
) -> dict[Row, list[DXFGraphic]]:
    """Что лежит в ячейке знака каждой строки - по середине габарита отрисовки."""
    cache = bbox.Cache()
    found: dict[Row, list[DXFGraphic]] = {row: [] for row in rows}
    for entity in doc.modelspace():
        if entity is table:
            continue
        extents = bbox.extents([entity], cache=cache)
        if not extents.has_data:
            continue
        center = extents.center
        if not column[0] < center.x < column[1]:
            continue
        for row in rows:
            if row.bottom < center.y < row.top:
                found[row].append(entity)
    return found


def recordings(doc: Drawing, entities: list[DXFGraphic], gap: float) -> Records:
    context = RenderContext(doc, export_mode=True)
    # Лист белый: ACI 7 разрешается в чёрный, и его можно узнать по перу 7.
    context.current_layout_properties.set_colors("#ffffff")
    config = Configuration(min_hatch_line_distance=gap, hatching_timeout=60.0)
    recorder = Recorder()
    random.seed(SEED)
    Frontend(context, recorder, config=config).draw_entities(entities)
    return list(recorder.player().recordings())


def color_of(properties: BackendProperties) -> tuple[str, float]:
    """Цвет записи: ACI 7 на белом листе разрешён в чёрный - это «ink». Белый с пером 7 -
    истинный цвет (true color перекрывает ACI), он остаётся белым в любой теме."""
    raw = properties.color.lower()
    rgb, alpha = raw[:7], (int(raw[7:9], 16) / 255 if len(raw) == RGBA_LENGTH else 1.0)
    if properties.pen == ACI_INK and rgb == "#000000":
        rgb = "ink"
    return rgb, round(alpha, 2)


def luminance(color: str) -> float:
    if color == "ink":
        return 0.0
    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def simplify(points: list[Point], tolerance: float) -> list[Point]:
    """Рамер - Дуглас - Пекер без рекурсии: концы ломаной остаются на месте."""
    if len(points) < MIN_RING:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        (ax, ay), (bx, by) = points[first], points[last]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        worst, at = 0.0, -1
        for i in range(first + 1, last):
            px, py = points[i]
            if length:
                distance = abs(dy * px - dx * py + bx * ay - by * ax) / length
            else:
                distance = math.hypot(px - ax, py - ay)
            if distance > worst:
                worst, at = distance, i
        if worst > tolerance and at > 0:
            keep[at] = True
            stack.extend(((first, at), (at, last)))
    return [point for point, kept in zip(points, keep, strict=True) if kept]


def number(value: float) -> str:
    """Короткая запись числа для пути SVG: 0.25 -> .25, -0.5 -> -.5, 1.000 -> 1."""
    rounded = round(value, DIGITS) + 0.0
    out = f"{rounded:.{DIGITS}f}".rstrip("0").rstrip(".")
    if out in {"", "-0", "-"}:
        return "0"
    if out.startswith("0."):
        return out[1:]
    if out.startswith("-0."):
        return "-" + out[2:]
    return out


class Sign:
    """Знак одной строки: записи движка -> пути в нормированных координатах."""

    def __init__(self, records: Records, extents: BoundingBox) -> None:
        # Габарит знака - тот же, по которому знак найден в ячейке (ezdxf.bbox). Отрисовка
        # движка бывает шире: у «Рябины» два штриха вырожденной геометрии уходят в начало
        # координат. Запись, вершины которой выходят за OUTSIDE радиуса, - не часть знака.
        (x0, y0), (x1, y1) = extents.extmin.vec2, extents.extmax.vec2
        self.cx, self.cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.width, self.height = x1 - x0, y1 - y0
        self.radius = max(self.width, self.height) / 2
        self.records = records
        self.stray = 0
        self.layers: list[list[Any]] = []
        self.fill_area: dict[tuple[str, float], float] = {}
        self.stroke_length: dict[tuple[str, float], float] = {}

    def inside(self, rings: Iterable[list[Point]]) -> bool:
        """Все вершины записи в пределах знака; иначе запись - постороннее и не пишется."""
        for ring in rings:
            if any(abs(x) > OUTSIDE or abs(y) > OUTSIDE for x, y in ring):
                self.stray += 1
                return False
        return True

    def point(self, x: float, y: float) -> Point:
        return ((x - self.cx) / self.radius, -(y - self.cy) / self.radius)

    def rings(self, path: NumpyPath2d) -> list[tuple[list[Point], bool]]:
        """Контуры пути: вершины в нормированных координатах и замкнут ли контур."""
        out = []
        for part in path.to_path().sub_paths():
            points = [self.point(v.x, v.y) for v in part.flattening(FLATTEN * self.radius)]
            if len(points) < SEGMENT:
                continue
            closed = math.dist(points[0], points[-1]) < CLOSED_EPS
            out.append((simplify(points, SIMPLIFY), closed))
        return out

    def fill(self, color: str, alpha: float, rings: list[list[Point]]) -> None:
        data = "".join(
            "M" + " ".join(f"{number(x)} {number(y)}" for x, y in ring) + "Z"
            for ring in rings
            if len(ring) >= MIN_RING
        )
        if not data:
            return
        self.layers.append(["f", color, alpha, 0, data])
        area = sum(abs(shoelace(ring)) for ring in rings[:1])
        self.fill_area[color, alpha] = self.fill_area.get((color, alpha), 0.0) + area * alpha

    def stroke(
        self, color: str, alpha: float, width: float, lines: list[tuple[list[Point], bool]]
    ) -> None:
        parts = []
        for ring, closed in lines:
            points = ring[:-1] if closed and len(ring) > SEGMENT else ring
            head = f"M{number(points[0][0])} {number(points[0][1])}"
            tail = " ".join(f"{number(x)} {number(y)}" for x, y in points[1:])
            parts.append(head + ("L" + tail if tail else "") + ("Z" if closed else ""))
            length = sum(math.dist(a, b) for a, b in pairwise(ring))
            self.stroke_length[color, alpha] = (
                self.stroke_length.get((color, alpha), 0.0) + length * alpha
            )
        data = "".join(parts)
        if not data:
            return
        last = self.layers[-1] if self.layers else None
        # Штрихи подряд одного вида - один путь: так их рисуют одной обводкой.
        if last and last[0] == "s" and last[1:4] == [color, alpha, width]:
            last[4] += data
        else:
            self.layers.append(["s", color, alpha, width, data])

    def record(self, record: DataRecord, properties: BackendProperties) -> None:
        color, alpha = color_of(properties)
        width = round(properties.lineweight, 2)
        if isinstance(record, FilledPathsRecord):
            rings = [ring for path in record.paths for ring, _ in self.rings(path)]
            if self.inside(rings):
                self.fill(color, alpha, rings)
        elif isinstance(record, PathRecord):
            lines = self.rings(record.path)
            if self.inside(ring for ring, _ in lines):
                self.stroke(color, alpha, width, lines)
        elif isinstance(record, SolidLinesRecord):
            vertices = [self.point(v.x, v.y) for v in record.lines.vertices()]
            pairs = [
                ([vertices[i], vertices[i + 1]], False) for i in range(0, len(vertices) - 1, 2)
            ]
            if self.inside([vertices]):
                self.stroke(color, alpha, width, pairs)
        elif isinstance(record, PointsRecord):
            vertices = [self.point(v.x, v.y) for v in record.points.vertices()]
            if self.inside([vertices]):
                self.points(vertices, color, alpha, width)

    def points(self, vertices: list[Point], color: str, alpha: float, width: float) -> None:
        if len(vertices) >= MIN_RING:
            # Залитый многоугольник (SOLID, широкая полилиния): обход против часовой, чтобы
            # соседние заливки одного цвета не вырезали друг друга.
            ring = vertices if shoelace(vertices) >= 0 else vertices[::-1]
            self.fill(color, alpha, [ring])
        elif len(vertices) == SEGMENT:
            self.stroke(color, alpha, width, [(vertices, False)])

    def paths(self) -> tuple[list[list[Any]], list[Any]]:
        for record, properties in self.records:
            self.record(record, properties)
        return self.layers, tone(self.fill_area, self.stroke_length)


def shoelace(ring: list[Point]) -> float:
    return 0.5 * sum(
        ax * by - bx * ay for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1], strict=True)
    )


def tone(
    fill_area: dict[tuple[str, float], float], stroke_length: dict[tuple[str, float], float]
) -> list[Any]:
    """Главный цвет знака и его непрозрачность - им знак рисуется точкой на общем виде:
    заливка, если она занимает заметную часть круга, иначе самые длинные штрихи. Почти белая
    заливка - маска под знаком, а не его цвет: точка ею на белом листе не видна."""
    fills = {key: area for key, area in fill_area.items() if luminance(key[0]) < WHITE}
    strokes = {key: length for key, length in stroke_length.items() if luminance(key[0]) < WHITE}
    for scores, floor in ((fills, 0.3 * math.pi), (strokes, 0.0)):
        if scores and max(scores.values()) > floor:
            color, alpha = max(sorted(scores), key=lambda key: scores[key])
            return [color, alpha]
    return ["ink", 1.0]


def extract(dxf: Path) -> dict[str, Any]:
    doc = ezdxf.readfile(dxf)
    table = legend_table(doc)
    rows, column = table_rows(doc, table)
    cells = cell_entities(doc, table, rows, column)
    signs = []
    missing = []
    for row in rows:
        entities = cells[row]
        if not entities:
            missing.append(row.name)
            continue
        extents = bbox.extents(entities)
        gap = MIN_HATCH_GAP * max(extents.size.x, extents.size.y) / 2
        sign = Sign(recordings(doc, entities, gap), extents)
        layers, main = sign.paths()
        if sign.stray:
            print(f"{row.name}: {sign.stray} записей вне ячейки знака отброшено")
        blocks = sorted({e.dxf.name for e in entities if e.dxftype() == "INSERT"})
        signs.append(
            {
                "name": row.name,
                "section": row.section,
                "position": row.position,
                "blocks": blocks,
                "tone": main,
                "aspect": round(min(sign.width, sign.height) / max(sign.width, sign.height), 3),
                "paths": layers,
            }
        )
        print(f"{row.section:8} {row.position:>3} {row.name:40} {len(layers):4} путей", flush=True)
    if missing:
        print("без знака в ячейке:", ", ".join(missing))
    if not signs:
        message = "в таблице шаблона не найдено ни одного знака"
        raise SystemExit(message)
    return {"signs": signs, "empty_rows": missing}


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.blake2b(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode(), digest_size=16
    ).hexdigest()


def document(payload: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    digest = payload_hash(payload)
    same = previous is not None and previous.get("hash") == digest
    generated = previous["generated"] if same and previous else datetime.now(UTC).date().isoformat()
    return {
        "source": SOURCE
        + ": таблица «Ведомость элементов озеленения», колонка «Условное обозначение»",
        "converter": "ODA File Converter 27.1, DWG -> DXF ACAD2018",
        "command": COMMAND,
        "generated": generated,
        "hash": digest,
        "coordinates": (
            "центр - середина габарита знака, радиус 1 - половина большей стороны, y вниз"
        ),
        "paths": "[f|s, цвет или ink (ACI 7), непрозрачность, вес линии в мм, путь SVG]",
        **payload,
    }


def dump(data: dict[str, Any]) -> str:
    # Знак - одна строка: файл читается глазами и сравнивается построчно.
    head = {key: value for key, value in data.items() if key != "signs"}
    lines = [json.dumps(sign, ensure_ascii=False, separators=(",", ":")) for sign in data["signs"]]
    body = json.dumps(head, ensure_ascii=False, indent=2)[:-2]
    return body + ',\n  "signs": [\n    ' + ",\n    ".join(lines) + "\n  ]\n}\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--dxf", type=Path, help="готовый DXF шаблона вместо DWG из датасета")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--check", action="store_true", help="не писать, а сверить с --out")
    args = parser.parse_args()
    previous = json.loads(args.out.read_text(encoding="utf-8")) if args.out.is_file() else None
    with tempfile.TemporaryDirectory(prefix="template_signs_") as work:
        dxf = args.dxf or convert(template_dwg(), Path(work))
        text_out = dump(document(extract(dxf), previous))
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.is_file() else ""
        if current != text_out:
            print(f"{args.out}: знаки расходятся с шаблоном, перезапустите без --check")
            raise SystemExit(1)
        print(f"{args.out}: совпадает с шаблоном")
        return
    args.out.write_text(text_out, encoding="utf-8", newline="\n")
    print(f"{args.out}: {len(text_out) // 1024} КБ")


if __name__ == "__main__":
    main()
