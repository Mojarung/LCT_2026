"""Векторный PDF чертежа -> DXF по слоям (задача 18 плана финала: Фрунзенская набережная).

У Фрунзенской набережной в материалах пилота нет ни DWG, ни DXF: только PDF-экспорты листов
из AutoCAD (генплан, дендроплан, ПОР). Экспорт сохранил слои чертежа как группы
необязательного содержимого (OCG) - 839 слоёв у генплана, с именами подосновы Мосгеотреста и
внешних ссылок. Инструмент читает поток содержимого страницы сам (линии, кривые, заливки,
невидимый текст SHX с ToUnicode) и пишет DXF: слой сущности - имя OCG без префикса внешней
ссылки, координаты - метры при масштабе листа (по умолчанию 1:500).

На листе, кроме плана, штамп, таблицы и условные обозначения: они лежат вне видового экрана.
Сохраняется только содержимое под отсечением видового экрана плана - самого большого
прямоугольника отсечения листа (--all - весь лист).

    uv run python tools/pdf_to_dxf.py 06_ГенПлан.pdf --page 1 --out frunzenskaya-1.dxf
    uv run python tools/pdf_to_dxf.py 06_ГенПлан.pdf --out-dir dataset/frunzenskaya  все листы

Без PyMuPDF (AGPL): поток разбирается своим токенизатором, pypdf только распаковывает потоки
и словари.
"""
# ruff: noqa: INP001, T201, PLR2004, C901 - инструмент конвертации, коды и счётчики формата PDF

from __future__ import annotations

import argparse
import itertools
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import ezdxf
import numpy as np
import shapely
from pypdf import PdfReader
from pypdf.generic import IndirectObject
from scipy.spatial import cKDTree

if TYPE_CHECKING:
    from collections.abc import Iterator

POINT_M = 0.0254 / 72  # пункт PDF на бумаге, м
BEZIER_STEPS = 8
# Вершины соседних листов совпали, если ближе 5 см; совмещение - от 90 % совпавших.
MATCH_M = 0.05
STITCH_SHARE = 0.9
# Приближение по подписям: две подписи «Лист N» или не меньше трёх совпавших редких подписей.
SEED_SAMPLE = 20_000
MIN_TEXT = 3
MAX_PAIRS = 6
MIN_HITS = 3
MIN_SPAN_M = 5.0
SPAN_TOL_M = 0.3
HIT_M = 0.5
MIN_ICP = 10
PAIR_POINTS = 2
# Символы, недопустимые в имени слоя DXF.
_BAD_LAYER = re.compile(r'[<>/\\":;?*|=`]')
_TOKEN = re.compile(
    rb"""
    (?P<ws>[\s]+)
  | (?P<comment>%[^\r\n]*)
  | (?P<name>/[^\s/\[\]<>(){}%]*)
  | (?P<number>[-+]?(?:\d+\.?\d*|\.\d+))
  | (?P<hex><[0-9A-Fa-f\s]*>)
  | (?P<dict><<|>>)
  | (?P<array>[\[\]])
  | (?P<string>\()
  | (?P<op>[A-Za-z'"*]+[0-9]?)
  | (?P<other>.)
    """,
    re.VERBOSE | re.DOTALL,
)

type Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def multiply(a: Matrix, b: Matrix) -> Matrix:
    """a, затем b (как в PDF: cm умножает слева текущую матрицу)."""
    return (
        a[0] * b[0] + a[1] * b[2],
        a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2],
        a[2] * b[1] + a[3] * b[3],
        a[4] * b[0] + a[5] * b[2] + b[4],
        a[4] * b[1] + a[5] * b[3] + b[5],
    )


def apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def _literal(data: bytes, start: int) -> tuple[bytes, int]:
    """Строка в скобках с вложенными скобками и экранированием; start - после «(»."""
    depth, i, out = 1, start, bytearray()
    escapes = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
    while i < len(data):
        c = data[i]
        if c == 0x5C:  # обратная косая
            i += 1
            n = data[i]
            if n in escapes:
                out.append(escapes[n])
            elif 0x30 <= n <= 0x37:
                digits = data[i : i + 3]
                k = 0
                while k < len(digits) and 0x30 <= digits[k] <= 0x37:
                    k += 1
                out.append(int(digits[:k], 8) & 0xFF)
                i += k - 1
            elif n in (10, 13):
                pass
            else:
                out.append(n)
        elif c == 0x28:
            depth += 1
            out.append(c)
        elif c == 0x29:
            depth -= 1
            if depth == 0:
                return bytes(out), i + 1
            out.append(c)
        else:
            out.append(c)
        i += 1
    return bytes(out), i


def tokens(data: bytes) -> Iterator[tuple[str, Any]]:
    """Токены потока содержимого: (вид, значение); inline-картинки пропускаются."""
    pos = 0
    size = len(data)
    while pos < size:
        match = _TOKEN.match(data, pos)
        if match is None:
            pos += 1
            continue
        kind = match.lastgroup
        pos = match.end()
        if kind in {"ws", "comment", "other"}:
            continue
        text = match.group()
        if kind == "string":
            value, pos = _literal(data, pos)
            yield "string", value
        elif kind == "hex":
            digits = re.sub(rb"\s", b"", text[1:-1])
            if len(digits) % 2:
                digits += b"0"
            yield "string", bytes.fromhex(digits.decode())
        elif kind == "number":
            yield "number", float(text)
        elif kind == "name":
            yield "name", text[1:].decode("latin-1")
        elif kind == "op" and text == b"ID":
            end = data.find(b"EI", pos)
            pos = size if end < 0 else end + 2
        else:
            yield kind or "", text.decode("latin-1")


def _to_unicode(font: Any) -> tuple[dict[int, str], int]:  # noqa: ANN401 - словарь pypdf
    """Карта кодов шрифта в текст по ToUnicode и ширина кода в байтах."""
    width = 2 if font.get("/Subtype") == "/Type0" else 1
    mapping: dict[int, str] = {}
    stream = font.get("/ToUnicode")
    if stream is None:
        return mapping, width
    text = stream.get_object().get_data().decode("latin-1")

    def utf16(hexa: str) -> str:
        return bytes.fromhex(hexa).decode("utf-16-be", errors="replace")

    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.DOTALL):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
            mapping[int(src, 16)] = utf16(dst)
    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.DOTALL):
        for lo, hi, rest in re.findall(
            r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]*>|\[[^\]]*\])", block
        ):
            first, last = int(lo, 16), int(hi, 16)
            if rest.startswith("["):
                for k, dst in enumerate(re.findall(r"<([0-9A-Fa-f]*)>", rest)):
                    mapping[first + k] = utf16(dst)
            else:
                base = int(rest[1:-1], 16)
                digits = len(rest) - 2
                for code in range(first, last + 1):
                    mapping[code] = utf16(f"{base + code - first:0{digits}x}")
    return mapping, width


@dataclass
class _State:
    ctm: Matrix = IDENTITY
    clip: tuple[float, float, float, float] | None = None
    font: tuple[dict[int, str], int] | None = None
    size: float = 1.0
    scale: float = 1.0  # Tz / 100
    leading: float = 0.0


@dataclass
class Sheet:
    """Разобранная страница: полилинии и подписи в пунктах листа."""

    lines: list[tuple[str, list[tuple[float, float]], bool, bool, int]] = field(
        default_factory=list
    )  # слой, точки, замкнута, залита, номер отсечения
    texts: list[tuple[str, str, float, float, float, float, int]] = field(
        default_factory=list
    )  # слой, текст, x, y, высота, угол, номер отсечения
    clips: list[tuple[float, float, float, float]] = field(default_factory=list)


class _Reader:
    def __init__(self, layer_names: dict[int, str]) -> None:
        self.sheet = Sheet()
        self._layer_names = layer_names
        self._fonts: dict[int, tuple[dict[int, str], int]] = {}

    def run(self, data: bytes, resources: Any, ctm: Matrix) -> None:  # noqa: ANN401, PLR0912, PLR0915 - автомат потока
        state = _State(ctm=ctm)
        stack: list[_State] = []
        layers: list[str | None] = []
        operands: list[Any] = []
        path: list[list[tuple[float, float]]] = []
        closed: list[bool] = []
        pending_clip = False
        text_m: Matrix = IDENTITY
        line_m: Matrix = IDENTITY
        array: list[Any] | None = None
        props = _dict(resources, "/Properties")
        fonts = _dict(resources, "/Font")
        xobjects = _dict(resources, "/XObject")
        depth = 0
        for kind, value in tokens(data):
            if kind == "array":
                if value == "[":
                    array = []
                else:
                    operands.append(array or [])
                    array = None
                continue
            if kind == "dict":
                depth += 1 if value == "<<" else -1
                continue
            if depth:
                continue
            if kind != "op":
                (array if array is not None else operands).append(value)
                continue
            op = value
            if op == "q":
                stack.append(_State(state.ctm, state.clip, state.font, state.size, state.scale))
            elif op == "Q":
                if stack:
                    restored = stack.pop()
                    state.ctm, state.clip = restored.ctm, restored.clip
            elif op == "cm" and len(operands) >= 6:
                state.ctm = multiply(tuple(operands[-6:]), state.ctm)  # type: ignore[arg-type]
            elif op == "m" and len(operands) >= 2:
                path.append([apply(state.ctm, operands[-2], operands[-1])])
                closed.append(False)
            elif op == "l" and len(operands) >= 2 and path:
                path[-1].append(apply(state.ctm, operands[-2], operands[-1]))
            elif op in {"c", "v", "y"} and path:
                _curve(path[-1], op, operands, state.ctm)
            elif op == "re" and len(operands) >= 4:
                x, y, w, h = operands[-4:]
                corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
                path.append([apply(state.ctm, px, py) for px, py in corners])
                closed.append(True)
            elif op == "h" and closed:
                closed[-1] = True
            elif op in {"W", "W*"}:
                pending_clip = True
            elif op in {"S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n"}:
                if pending_clip and path:
                    state.clip = _intersect(state.clip, _bbox(path))
                    self.sheet.clips.append(state.clip)
                pending_clip = False
                if op != "n":
                    layer = next((name for name in reversed(layers) if name), "0")
                    filled = op not in {"S", "s"}
                    clip = self._clip_index(state.clip)
                    for points, shut in zip(path, closed, strict=True):
                        if len(points) >= 2:
                            self.sheet.lines.append(
                                (layer, points, shut or op in {"s", "b", "b*"}, filled, clip)
                            )
                path, closed = [], []
            elif op == "BDC" and len(operands) >= 2:
                tag, prop = operands[-2], operands[-1]
                name = None
                if tag == "OC" and isinstance(prop, str):
                    ref = props.get("/" + prop)
                    if isinstance(ref, IndirectObject):
                        name = self._layer_names.get(ref.idnum)
                layers.append(name)
            elif op == "BMC":
                layers.append(None)
            elif op == "EMC":
                if layers:
                    layers.pop()
            elif op == "Do" and operands:
                self._form(xobjects.get("/" + operands[-1]), state.ctm)
            elif op == "BT":
                text_m = line_m = IDENTITY
            elif op == "Tf" and len(operands) >= 2:
                font = fonts.get("/" + operands[-2])
                state.font = self._font(font) if font is not None else None
                state.size = operands[-1]
            elif op == "Tz" and operands:
                state.scale = operands[-1] / 100
            elif op == "TL" and operands:
                state.leading = operands[-1]
            elif op == "Tm" and len(operands) >= 6:
                text_m = line_m = tuple(operands[-6:])  # type: ignore[assignment]
            elif op in {"Td", "TD"} and len(operands) >= 2:
                if op == "TD":
                    state.leading = -operands[-1]
                line_m = multiply((1, 0, 0, 1, operands[-2], operands[-1]), line_m)
                text_m = line_m
            elif op == "T*":
                line_m = multiply((1, 0, 0, 1, 0, -state.leading), line_m)
                text_m = line_m
            elif op in {"Tj", "'", '"', "TJ"} and operands:
                raw = operands[-1]
                if isinstance(raw, list):
                    raw = b"".join(part for part in raw if isinstance(part, bytes))
                if isinstance(raw, bytes):
                    layer = next((name for name in reversed(layers) if name), "0")
                    self._text(layer, raw, state, multiply(text_m, state.ctm))
            operands = []

    def _clip_index(self, clip: tuple[float, float, float, float] | None) -> int:
        if clip is None:
            return -1
        try:
            return self.sheet.clips.index(clip)
        except ValueError:
            self.sheet.clips.append(clip)
            return len(self.sheet.clips) - 1

    def _font(self, font: Any) -> tuple[dict[int, str], int]:  # noqa: ANN401 - словарь pypdf
        key = font.idnum if isinstance(font, IndirectObject) else id(font)
        if key not in self._fonts:
            self._fonts[key] = _to_unicode(font.get_object())
        return self._fonts[key]

    def _text(self, layer: str, raw: bytes, state: _State, matrix: Matrix) -> None:
        if state.font is None:
            return
        mapping, width = state.font
        codes = [int.from_bytes(raw[i : i + width], "big") for i in range(0, len(raw), width)]
        text = "".join(mapping.get(code, "") for code in codes).strip()
        if not text:
            return
        x, y = matrix[4], matrix[5]
        height = state.size * math.hypot(matrix[2], matrix[3])
        angle = math.degrees(math.atan2(matrix[1], matrix[0]))
        clip = self._clip_index(None)
        self.sheet.texts.append((layer, text, x, y, height, angle, clip))

    def _form(self, ref: Any, ctm: Matrix) -> None:  # noqa: ANN401 - словарь pypdf
        if ref is None:
            return
        form = ref.get_object()
        if form.get("/Subtype") != "/Form":
            return
        matrix = tuple(float(v) for v in form.get("/Matrix", IDENTITY))
        resources = form.get("/Resources")
        self.run(form.get_data(), resources, multiply(matrix, ctm))  # type: ignore[arg-type]


def _dict(resources: Any, key: str) -> dict[str, Any]:  # noqa: ANN401 - словарь pypdf
    if resources is None:
        return {}
    value = resources.get_object().get(key)
    if value is None:
        return {}
    return {str(k): v for k, v in value.get_object().items()}


def _curve(points: list[tuple[float, float]], op: str, operands: list[Any], ctm: Matrix) -> None:
    x0, y0 = points[-1]
    if op == "c" and len(operands) >= 6:
        x1, y1, x2, y2, x3, y3 = operands[-6:]
        p1, p2 = apply(ctm, x1, y1), apply(ctm, x2, y2)
    elif op == "v" and len(operands) >= 4:
        x2, y2, x3, y3 = operands[-4:]
        p1, p2 = (x0, y0), apply(ctm, x2, y2)
    elif op == "y" and len(operands) >= 4:
        x1, y1, x3, y3 = operands[-4:]
        p1 = apply(ctm, x1, y1)
        p2 = apply(ctm, x3, y3)
    else:
        return
    p3 = apply(ctm, x3, y3)
    for k in range(1, BEZIER_STEPS + 1):
        t = k / BEZIER_STEPS
        u = 1 - t
        points.append(
            (
                u**3 * x0 + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                u**3 * y0 + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
            )
        )


def _bbox(path: list[list[tuple[float, float]]]) -> tuple[float, float, float, float]:
    xs = [x for points in path for x, _ in points]
    ys = [y for points in path for _, y in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _intersect(
    a: tuple[float, float, float, float] | None, b: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    if a is None:
        return b
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def layer_names(reader: PdfReader) -> dict[int, str]:
    """Номер объекта OCG -> имя слоя DXF: часть после «|» внешней ссылки, без запретных знаков."""
    root = reader.trailer["/Root"]
    oc = root.get("/OCProperties")
    names: dict[int, str] = {}
    if oc is None:
        return names
    for ref in oc.get_object().get("/OCGs", []):
        name = str(ref.get_object().get("/Name", ""))
        layer = _BAD_LAYER.sub("_", name.rsplit("|", maxsplit=1)[-1]).strip() or "0"
        names[ref.idnum] = layer
    return names


def read_page(reader: PdfReader, number: int) -> Sheet:
    page = reader.pages[number]
    worker = _Reader(layer_names(reader))
    worker.run(page.get_contents().get_data(), page.get("/Resources"), IDENTITY)
    return worker.sheet


def main_clip(sheet: Sheet) -> int | None:
    """Видовой экран плана - отсечение, под которым больше всего линий листа.

    Не самое большое: рамка всего листа - тоже отсечение, под ней штамп и таблицы.
    """
    counts = Counter(clip for *_, clip in sheet.lines if clip >= 0)
    return counts.most_common(1)[0][0] if counts else None


# Штриховой тип линии AutoCAD выгружает в PDF отдельными штрихами: граница работ
# Фрунзенской - 1 225 штрихов по 3,2 м с разрывами 1,6 м, и polygonize её не замыкал. Слой,
# где штрихи - большинство, сшивается: конец штриха соединяется с началом следующего, если
# разрыв не больше DASH_GAP_M и штрих продолжает направление (не круче DASH_TURN_DEG).
DASH_GAP_M = 3.0
DASH_TURN_DEG = 30.0
DASH_LONG_M = 12.0  # штрих длиннее - уже линия, а не штрих
DASH_SHARE = 0.6  # доля коротких открытых линий на слое
DASH_PAIRED = 0.7  # доля концов, у которых есть пара ближе DASH_GAP_M


def heal_dashes(
    lines: list[tuple[str, np.ndarray, bool]],
) -> tuple[list[tuple[str, np.ndarray, bool]], dict[str, int]]:
    """Штрихи штриховых слоёв - в непрерывные линии; остальные линии как есть.

    Сначала штрих продолжает штрих по прямой, затем концы получившихся линий сходятся в углах
    (там штрих поворачивает, и прямым продолжением угол не взять). Возвращает линии и число
    штрихов, вошедших в сшитые линии, по слою.
    """
    by_layer: dict[str, list[int]] = {}
    for i, (name, points, shut) in enumerate(lines):
        if not shut and len(points) >= PAIR_POINTS:
            by_layer.setdefault(name, []).append(i)
    replaced: set[int] = set()
    added: list[tuple[str, np.ndarray, bool]] = []
    healed: dict[str, int] = {}
    for name, members in by_layer.items():
        parts = [lines[i][1] for i in members]
        straight = _dash_chains(parts, straight=True)
        if straight is None:
            continue
        joined = _join(parts, straight)
        corners = _dash_chains(joined, straight=False)
        result = _join(joined, corners or [])
        replaced.update(members)
        healed[name] = len(members)
        for points in result:
            closed = len(points) > PAIR_POINTS and bool(
                np.linalg.norm(points[0] - points[-1]) <= DASH_GAP_M
            )
            added.append((name, points, closed))
    out = [line for i, line in enumerate(lines) if i not in replaced]
    return [*out, *added], healed


def _join(parts: list[np.ndarray], chains: list[list[tuple[int, bool]]]) -> list[np.ndarray]:
    """Линии цепочек одной линией каждая, остальные части - как были."""
    used = {k for chain in chains for k, _ in chain}
    joined = [
        np.concatenate([parts[k][::-1] if flip else parts[k] for k, flip in chain])
        for chain in chains
    ]
    return [*joined, *(part for k, part in enumerate(parts) if k not in used)]


def _dash_chains(parts: list[np.ndarray], *, straight: bool) -> list[list[tuple[int, bool]]] | None:
    """Цепочки частей слоя: (номер части, развёрнута ли). None - слой не штриховой.

    straight - штрих продолжает штрих по прямой, и слой сначала проверяется на штриховость;
    иначе концы сходятся в углах в пределах разрыва штриха, ближайшие первыми.
    """
    if len(parts) < PAIR_POINTS:
        return None if straight else []
    ends = np.array([pt for p in parts for pt in (p[0], p[-1])])
    outward = np.array([d for p in parts for d in (_unit(p[0] - p[1]), _unit(p[-1] - p[-2]))])
    tree = cKDTree(ends)
    if straight:
        lengths = np.array([np.linalg.norm(np.diff(p, axis=0), axis=1).sum() for p in parts])
        distance, _ = tree.query(ends, k=2)
        if (lengths <= DASH_LONG_M).mean() < DASH_SHARE or (
            distance[:, 1] <= DASH_GAP_M
        ).mean() < DASH_PAIRED:
            return None
    pairs = sorted(
        (float(np.linalg.norm(ends[a] - ends[b])), a, b)
        for a, b in tree.query_pairs(DASH_GAP_M)
        if a // 2 != b // 2
        and (not straight or _continues(ends[a], outward[a], ends[b], outward[b]))
    )
    partner: dict[int, int] = {}
    for _, a, b in pairs:
        if a not in partner and b not in partner:
            partner[a], partner[b] = b, a
    return _walk(len(parts), partner)


def _walk(count: int, partner: dict[int, int]) -> list[list[tuple[int, bool]]]:
    """Цепочки по парам концов: от головы цепочки до хвоста."""
    seen: set[int] = set()
    chains = []
    for start in range(count):
        if start in seen:
            continue
        # Назад к голове: вход в часть k - её начало (или конец, если она развёрнута).
        k, flip = start, False
        for _ in range(count):
            entry = 2 * k + (1 if flip else 0)
            if entry not in partner:
                break
            other = partner[entry]
            k, flip = other // 2, other % 2 == 0
            if k == start:
                break
        chain = []
        while k not in seen:
            seen.add(k)
            chain.append((k, flip))
            tail = 2 * k + (0 if flip else 1)
            if tail not in partner:
                break
            other = partner[tail]
            k, flip = other // 2, other % 2 == 1
        if len(chain) > 1:
            chains.append(chain)
    return chains


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n else v


def _continues(pa: np.ndarray, da: np.ndarray, pb: np.ndarray, db: np.ndarray) -> bool:
    """Штрих b продолжает штрих a: оба конца смотрят друг на друга почти по одной прямой."""
    gap = pb - pa
    if not np.linalg.norm(gap):
        return True
    limit = math.cos(math.radians(DASH_TURN_DEG))
    toward = _unit(gap)
    return bool(da @ toward >= limit and db @ -toward >= limit and da @ -db >= limit)


@dataclass
class Plate:
    """Лист в метрах: линии и подписи видового экрана плана и его рамка."""

    lines: list[tuple[str, np.ndarray, bool]]
    texts: list[tuple[str, str, float, float, float, float]]
    frame: shapely.Polygon


def plate(sheet: Sheet, *, scale: float, whole: bool = False) -> Plate:
    factor = POINT_M * scale
    keep = None if whole else main_clip(sheet)
    box = sheet.clips[keep] if keep is not None else None
    lines = [
        (name, np.asarray(points, dtype=float) * factor, shut)
        for name, points, shut, _filled, clip in sheet.lines
        if box is None or clip == keep
    ]
    texts = [
        (name, text, x * factor, y * factor, height * factor, angle)
        for name, text, x, y, height, angle, _clip in sheet.texts
        if box is None or (box[0] <= x <= box[2] and box[1] <= y <= box[3])
    ]
    lines, _ = heal_dashes(lines)
    if box is None:
        xy = np.concatenate([pts for _, pts, _ in lines]) if lines else np.zeros((1, 2))
        frame = shapely.box(*xy.min(0), *xy.max(0))
    else:
        frame = shapely.box(*(v * factor for v in box))
    return Plate(lines, texts, frame)


def rigid(angle: float, tx: float, ty: float) -> Matrix:
    c, s = math.cos(angle), math.sin(angle)
    return (c, s, -s, c, tx, ty)


def _fit(p: np.ndarray, q: np.ndarray) -> Matrix:
    """Поворот и сдвиг, переводящие точки p в q (наименьшие квадраты, без масштаба)."""
    pc, qc = p.mean(0), q.mean(0)
    u, _, vt = np.linalg.svd((p - pc).T @ (q - qc))
    r = vt.T @ u.T
    if np.linalg.det(r) < 0:
        vt[1] *= -1
        r = vt.T @ u.T
    t = qc - r @ pc
    return rigid(math.atan2(r[1, 0], r[0, 0]), float(t[0]), float(t[1]))


def move(m: Matrix, xy: np.ndarray) -> np.ndarray:
    return np.column_stack(
        (m[0] * xy[:, 0] + m[2] * xy[:, 1] + m[4], m[1] * xy[:, 0] + m[3] * xy[:, 1] + m[5])
    )


def invert(m: Matrix) -> Matrix:
    angle = math.atan2(m[1], m[0])
    c, s = math.cos(-angle), math.sin(-angle)
    return rigid(-angle, -(c * m[4] - s * m[5]), -(s * m[4] + c * m[5]))


def _vertices(p: Plate, limit: int | None = 150_000) -> np.ndarray:
    """Вершины линий листа; у листа a - выборка (её сверяют), у листа b - все (с ними)."""
    xy = np.concatenate([pts for _, pts, _ in p.lines]) if p.lines else np.zeros((0, 2))
    if limit is not None and len(xy) > limit:
        xy = xy[np.random.default_rng(0).choice(len(xy), limit, replace=False)]
    return xy


def _labels(p: Plate) -> dict[str, list[tuple[float, float, float]]]:
    found: dict[str, list[tuple[float, float, float]]] = {}
    for _, text, x, y, _h, angle in p.texts:
        found.setdefault(text, []).append((x, y, angle))
    return found


def _seed(a: Plate, b: Plate, tree: cKDTree, pa: np.ndarray) -> Matrix | None:
    """Первое приближение по подписям, лучшее по доле вершин листа a у вершин листа b.

    Кандидаты - подписи линии совмещения «Лист N» (поворот листа - разность поворотов
    подписи), затем пары одинаковых редких подписей (отметки, размеры), согласные по
    расстоянию. «Лист 3» встречается на листе дважды, у левой и правой линии совмещения,
    поэтому каждая пара вхождений - отдельный кандидат, а решает совпадение геометрии.
    """
    ia, ib = _labels(a), _labels(b)
    candidates = [
        rigid(
            math.radians(qa - pa_angle),
            *(
                np.array([qx, qy])
                - move(rigid(math.radians(qa - pa_angle), 0, 0), np.array([[px, py]]))[0]
            ),
        )
        for t in set(ia) & set(ib)
        if t.startswith("Лист")
        for px, py, pa_angle in ia[t]
        for qx, qy, qa in ib[t]
    ]
    pairs = [
        (x, y)
        for t in set(ia) & set(ib)
        if len(t) >= MIN_TEXT and len(ia[t]) * len(ib[t]) <= MAX_PAIRS
        for x in ia[t]
        for y in ib[t]
    ]
    if len(pairs) >= MIN_HITS:
        rng = np.random.default_rng(1)
        la = np.array([x[0][:2] for x in pairs])
        lb = np.array([x[1][:2] for x in pairs])
        for _ in range(2000):
            i, j = rng.choice(len(pairs), 2, replace=False)
            span = np.linalg.norm(la[i] - la[j])
            if span < MIN_SPAN_M or abs(span - np.linalg.norm(lb[i] - lb[j])) > SPAN_TOL_M:
                continue
            m = _fit(la[[i, j]], lb[[i, j]])
            if int((np.linalg.norm(move(m, la) - lb, axis=1) < HIT_M).sum()) >= MIN_HITS:
                candidates.append(m)
    best, best_m = 0.0, None
    sample = pa[:: max(1, len(pa) // SEED_SAMPLE)]
    for m in candidates:
        moved = move(m, sample)
        inside = shapely.contains_xy(b.frame, moved[:, 0], moved[:, 1])
        if inside.sum() < MIN_ICP:
            continue
        distance, _ = tree.query(moved[inside])
        score = float((distance < HIT_M).mean())
        if score > best:
            best, best_m = score, m
    return best_m


def register(a: Plate, b: Plate) -> tuple[Matrix, float] | None:
    """Переход из координат листа a в координаты листа b и доля совпавших вершин перекрытия.

    Приближение по подписям уточняется ICP по вершинам линий: порог 2, 0,3 и 0,1 м.
    """
    pa, pb = _vertices(a), _vertices(b, limit=None)
    tree = cKDTree(pb)
    m = _seed(a, b, tree, pa)
    if m is None:
        return None
    share = 0.0
    for limit in (2.0, 2.0, 0.3, 0.3, 0.1, 0.1, 0.1):
        moved = move(m, pa)
        inside = shapely.contains_xy(b.frame, moved[:, 0], moved[:, 1])
        if not inside.any():
            return None
        distance, nearest = tree.query(moved[inside])
        share = float((distance < MATCH_M).mean())
        good = distance < limit
        if good.sum() < MIN_ICP:
            return None
        m = _fit(pa[inside][good], pb[nearest[good]])
    return m, share


def stitch(plates: list[Plate]) -> tuple[list[Matrix], list[float]]:
    """Матрица каждого листа в координаты первого и доля совпадения с предыдущим листом."""
    world = [IDENTITY]
    shares = []
    for a, b in itertools.pairwise(plates):
        found = register(a, b)
        if found is None or found[1] < STITCH_SHARE:
            reason = f"совпало {found[1]:.1%} вершин" if found else "нет общих подписей"
            msg = f"листы не совмещаются: {reason}"
            raise ValueError(msg)
        step, share = found
        shares.append(share)
        # Точка листа b: в лист a обратным переходом, затем в первый лист.
        world.append(multiply(invert(step), world[-1]))
    return world, shares


def write_plates(plates: list[Plate], world: list[Matrix], target: Path) -> dict[str, int]:
    """Один DXF в координатах первого листа. Перекрытие соседних листов не повторяется:
    объект следующего листа, чья середина уже покрыта рамками прежних, не пишется."""
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    counts = {"lines": 0, "texts": 0, "overlap": 0}
    covered = shapely.Polygon()
    for p, m in zip(plates, world, strict=True):
        frame = shapely.Polygon(move(m, np.asarray(p.frame.exterior.coords)))
        shapely.prepare(covered)
        middles = np.array([move(m, pts).mean(0) for _, pts, _ in p.lines])
        seen = (
            shapely.contains_xy(covered, middles[:, 0], middles[:, 1])
            if len(middles) and not covered.is_empty
            else np.zeros(len(p.lines), dtype=bool)
        )
        for (name, points, shut), dup in zip(p.lines, seen, strict=True):
            if dup:
                counts["overlap"] += 1
                continue
            _layer(doc, name)
            msp.add_lwpolyline(move(m, points).tolist(), close=shut, dxfattribs={"layer": name})
            counts["lines"] += 1
        turn = math.degrees(math.atan2(m[1], m[0]))
        for name, text, x, y, height, rotation in p.texts:
            tx, ty = move(m, np.array([[x, y]]))[0]
            if not covered.is_empty and shapely.contains_xy(covered, tx, ty):
                continue
            _layer(doc, name)
            msp.add_text(
                text,
                height=max(height, 0.1),
                rotation=rotation + turn,
                dxfattribs={"layer": name, "insert": (float(tx), float(ty))},
            )
            counts["texts"] += 1
        covered = shapely.union_all([covered, frame])
    doc.saveas(target)
    return counts


def _layer(doc: Any, name: str) -> None:  # noqa: ANN401 - документ ezdxf
    if name not in doc.layers:
        doc.layers.add(name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--page", type=int, action="append", help="номер листа с 1")
    parser.add_argument("--out", type=Path, required=True, help="DXF")
    parser.add_argument("--scale", type=float, default=500.0, help="знаменатель масштаба")
    parser.add_argument("--all", action="store_true", help="весь лист, а не видовой экран")
    args = parser.parse_args()
    reader = PdfReader(args.pdf)
    pages = args.page or list(range(1, len(reader.pages) + 1))
    plates = [plate(read_page(reader, n - 1), scale=args.scale, whole=args.all) for n in pages]
    world, shares = stitch(plates) if len(plates) > 1 else ([IDENTITY], [])
    for n, share in zip(pages[1:], shares, strict=True):
        print(f"лист {n}: совпало {share:.1%} вершин в перекрытии с предыдущим", flush=True)
    counts = write_plates(plates, world, args.out)
    print(f"листов {len(pages)}: {counts} -> {args.out}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
