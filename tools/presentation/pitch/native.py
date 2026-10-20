# ruff: noqa: INP001, SLF001, PLR0913, E501, ISC004, PLR2004 - модуль колоды рядом с assemble.py; текст
# слайдов длинными строками, файл больше 800 строк из-за него же; у python-pptx нет API для фона,
# скругления картинок, прозрачности заливки и полей номера слайда.
"""Свободные слайды презентации нативными объектами PowerPoint: текст, фигуры, таблицы, графики.

Порядок - по рекомендуемой структуре шаблона ЛЦТ 2026: 01 описание, 02 маркетинг, 03 бизнес,
04 техника, 05 уникальность, 06 развитие. Картинками идут только снимки сервиса; их обрезка
задана свойствами кадра PowerPoint, и её можно поменять в самом PowerPoint.

Числа: facts.json и приложение B документации (прогон 20 улиц пилота), правила, акты и виды -
заново из config/, нормоконтроль Берзарина - docs/notes/24-audit.md, ответы заказчика -
docs/notes/15-organizers-qa.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from lxml import etree
from PIL import Image
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls, qn
from pptx.util import Inches, Pt

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pptx.chart.chart import Chart
    from pptx.presentation import Presentation as Deck
    from pptx.shapes.autoshape import Shape
    from pptx.slide import Slide

ROOT = Path(__file__).resolve().parents[3]
PITCH = ROOT / "out" / "presentation" / "pitch"
SHOTS = PITCH / "shots"
BG = PITCH / "bg"
ASSETS = PITCH / "assets"
GENERATED = ROOT / "docs" / "documentation" / "generated"

# палитра шаблона ЛЦТ 2026 (слайд «Оформление»)
PINK = "FF0053"
ROSE = "FC3777"
BLUSH = "FFD6E4"
LAV = "8A83D1"
PLUM = "520978"
NIGHT = "310F53"
INK = "1C1D22"
BODY = "3C3548"
MUTE = "5E5670"
WHITE = "FFFFFF"
MIST = "E6DDF0"  # мелкий текст на фиолетовом фоне

X_BOLD = "Montserrat ExtraBold"
SEMI = "Montserrat SemiBold"
MEDIUM = "Montserrat Medium"
SANS = "Montserrat"
MONO = "Consolas"

LEFT = 0.67  # поле слайда, дюймы: 96 px сетки 1920
RIGHT = 12.67
WIDTH = RIGHT - LEFT

SECTIONS = (
    "Подробное описание решения",
    "Маркетинговая часть решения",
    "Бизнесовая составляющая решения",
    "Техническая проработка решения",
    "Уникальность решения",
    "Планы по развитию решения",
)


# --------------------------------------------------------------------------- данные


def facts() -> dict[str, str]:
    """facts.json прогонов пилота; число правил, актов и видов - заново из config/.

    Свод норм меняется чаще, чем пересобирается документация: слайд не должен отставать
    от config/rules.yaml.
    """
    found = json.loads((GENERATED / "facts.json").read_text(encoding="utf-8"))
    return {**found, **config_counts()}


def config_counts() -> dict[str, str]:
    """Правила, акты и виды по config/ - так же, как их считает tools/docs/annexes.py."""
    # пакет проекта нужен только здесь
    from green.domain.norms import CitationStatus  # noqa: PLC0415
    from green.infrastructure.config.repositories import (  # noqa: PLC0415
        YamlRuleBookSource,
        YamlSpeciesCatalog,
    )

    config = ROOT / "config"
    book = YamlRuleBookSource(config / "acts.yaml", config / "rules.yaml").load()
    rules = book.all_rules
    species = YamlSpeciesCatalog(config / "species.yaml").all()
    symbols = (config / "symbols.yaml").read_text(encoding="utf-8")
    by_text = sum(
        1
        for r in rules
        if r.citation.act_id != "PROJECT" and r.citation.status is CitationStatus.VERIFIED
    )
    return {
        "rules_total": str(len(rules)),
        "rules_distance": str(len(book.distance_rules)),
        "rules_by_text": str(by_text),
        "acts": str(sum(1 for act_id in book.acts if act_id != "PROJECT")),
        "species": str(len(species)),
        "symbols": str(len(yaml.safe_load(symbols)["symbols"])),
    }


def table_rows(markdown: str) -> list[list[str]]:
    """Строки markdown-таблицы без шапки и разделителя."""
    rows = [
        [c.strip() for c in line.strip().strip("|").split("|")]
        for line in markdown.splitlines()
        if line.strip().startswith("|")
    ]
    return [r for r in rows[2:] if r]


def num(value: str) -> float:
    return float(value.replace("\xa0", "").replace(" ", "").replace(",", "."))


SHORT_NAMES = {
    "Олимпийская деревня": "Олимпийская деревня",
    "Песчаный переулок": "Песчаный пер.",
    "3-я Парковая улица": "3-я Парковая",
    "Харьковская улица": "Харьковская",
    "улица Багрицкого": "Багрицкого",
    "Камчатская улица": "Камчатская",
    "Улица Нижние Поля": "Нижние Поля",
    "Лодочная улица": "Лодочная",
    "Измайловская площадь": "Измайловская пл.",
    "Старый Гай ул.": "Старый Гай",
    "Фрунзенская набережная": "Фрунзенская наб.",
    "Наташинский пр-д": "Наташинский пр-д",
    "Харьковский проезд": "Харьковский пр-д",
    "Куликовская улица": "Куликовская",
    "Академика Понтрягина ул.": "Ак. Понтрягина",
    "улица Берзарина": "Берзарина",
    "Малая Грузинская ул.": "Малая Грузинская",
    "Кустанайская улица": "Кустанайская",
    "2-я Прядильная ул.": "2-я Прядильная",
    "Улица Сергея Макеева": "Сергея Макеева",
}


def street_minutes(f: dict[str, str]) -> list[tuple[str, float]]:
    """Минуты прогона по улицам: таблица техники из facts.json (приложение B)."""
    return [(SHORT_NAMES[r[0]], num(r[1])) for r in table_rows(f["streets_tech_table"])]


def street_curbs() -> list[tuple[str, float, float]]:
    """Борта под зеленью, % было и стало: первая таблица приложения B."""
    text = (GENERATED / "B-streets.md").read_text(encoding="utf-8")
    first = text.split("| № | Улица |", 1)[1].split("\n\n", 1)[0]
    out = []
    for r in table_rows("| № | Улица |" + first):
        before, after = (num(v) for v in r[5].split("→"))
        out.append((SHORT_NAMES[r[1]], before, after))
    return out


# нормоконтроль принятого плана улицы Берзарина (docs/notes/24-audit.md): 785 нарушений
AUDIT = (
    ("силовой кабель", 159),
    ("бортовой камень", 104),
    ("опора освещения", 77),
    ("теплосеть", 74),
    ("водопровод", 71),
    ("кабель связи", 62),
    ("стена здания", 59),
    ("граница покрытия", 49),
    ("прочие нормы", 130),
)
AUDIT_BAD, AUDIT_ALL = 391, 554
# тесты на 20.10.2026: uv run pytest --cov (2 619 прошли, 4 пропущены без локальных данных),
# npx vitest run --coverage в frontend/; покрытие - строки
TESTS_BACKEND, TESTS_FRONTEND = "2 623", "1 083"
COVER_BACKEND, COVER_FRONTEND = "95%", "96%"


def grouped(value: int) -> str:
    """Число с неразрывным пробелом между тысячами: 1 998."""
    return f"{value:,}".replace(",", " ")


def im_counts() -> tuple[str, str]:
    """Строки классификаторов Москвы для ИМ и коды с классом сервиса: config/im_classifier.yaml."""
    import yaml  # noqa: PLC0415 - нужен только здесь

    raw = (ROOT / "config" / "im_classifier.yaml").read_text(encoding="utf-8")
    # строки таблиц - по записям файла: один код в классификаторе повторяется, словарь его схлопнет
    rows = sum(1 for line in raw.splitlines() if line.startswith("  '"))
    codes = yaml.safe_load(raw).get("codes") or {}
    return grouped(rows), grouped(len(codes))


IM_ROWS, IM_CODES = im_counts()


# --------------------------------------------------------------------------- примитивы


@dataclass(frozen=True)
class Style:
    font: str = MEDIUM
    size: float = 13
    color: str = BODY
    bold: bool = False


type Chunk = tuple[str, Style]
type Para = Sequence[Chunk]


def rgb(value: str) -> RGBColor:
    return RGBColor.from_string(value)


def style_run(run: object, st: Style) -> None:
    run.font.name = st.font
    run.font.size = Pt(st.size)
    run.font.bold = st.bold
    run.font.color.rgb = rgb(st.color)
    rpr = run._r.get_or_add_rPr()
    rpr.set("lang", "ru-RU")
    for tag in ("a:latin", "a:ea", "a:cs"):
        el = rpr.find(qn(tag))
        if el is None:
            el = etree.SubElement(rpr, qn(tag))
        el.set("typeface", st.font)


def fill_frame(
    tf: object,
    paras: Sequence[Para],
    *,
    line: float = 1.15,
    after: float = 0,
    align: PP_ALIGN = PP_ALIGN.LEFT,
    anchor: MSO_ANCHOR = MSO_ANCHOR.TOP,
    bullet: str | None = None,
) -> None:
    tf.word_wrap = True
    tf.auto_size = None
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = line
        p.space_after = Pt(after)
        if bullet:
            ppr = p._p.get_or_add_pPr()
            ppr.set("marL", str(Inches(0.22)))
            ppr.set("indent", str(-Inches(0.22)))
            clr = etree.SubElement(ppr, qn("a:buClr"))
            etree.SubElement(clr, qn("a:srgbClr"), val=bullet)
            etree.SubElement(ppr, qn("a:buFont"), typeface="Arial")
            etree.SubElement(ppr, qn("a:buChar"), char="•")
        for chunk, st in para:
            if chunk == "\n":
                p.add_line_break()
                continue
            r = p.add_run()
            r.text = chunk
            style_run(r, st)


def text(
    slide: Slide,
    box: tuple[float, float, float, float],
    paras: Sequence[Para],
    **flow: object,
) -> Shape:
    x, y, w, h = box
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    fill_frame(shape.text_frame, paras, **flow)
    return shape


def para(value: str, st: Style) -> Para:
    return [(value, st)]


def alpha(shape: Shape, fill_pct: int | None = None, line_pct: int | None = None) -> None:
    """Прозрачность заливки и обводки в процентах непрозрачности."""
    sppr = shape._element.spPr
    if fill_pct is not None:
        clr = sppr.find(qn("a:solidFill")).find(qn("a:srgbClr"))
        etree.SubElement(clr, qn("a:alpha"), val=str(fill_pct * 1000))
    if line_pct is not None:
        clr = sppr.find(qn("a:ln")).find(qn("a:solidFill")).find(qn("a:srgbClr"))
        etree.SubElement(clr, qn("a:alpha"), val=str(line_pct * 1000))


def rect(
    slide: Slide,
    box: tuple[float, float, float, float],
    fill: str | None,
    *,
    line: tuple[str, float] | None = None,
    radius: float | None = None,
    shape: MSO_SHAPE = MSO_SHAPE.RECTANGLE,
) -> Shape:
    """Прямоугольник; radius - скругление в дюймах."""
    x, y, w, h = box
    kind = MSO_SHAPE.ROUNDED_RECTANGLE if radius else shape
    s = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    s.shadow.inherit = False
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.rgb = rgb(fill)
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = rgb(line[0])
        s.line.width = Pt(line[1])
    if radius:
        s.adjustments[0] = min(0.5, radius / min(w, h))
    return s


def circle_number(slide: Slide, x: float, y: float, d: float, label: str, *, size: float) -> None:
    c = rect(slide, (x, y, d, d), PINK, shape=MSO_SHAPE.OVAL)
    fill_frame(
        c.text_frame,
        [para(label, Style(X_BOLD, size, WHITE))],
        align=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE,
    )


def arrow(slide: Slide, start: tuple[float, float], end: tuple[float, float], color: str) -> None:
    line = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT, Inches(start[0]), Inches(start[1]), Inches(end[0]), Inches(end[1])
    )
    line.line.color.rgb = rgb(color)
    line.line.width = Pt(2.5)
    ln = line.line._get_or_add_ln()
    etree.SubElement(ln, qn("a:tailEnd"), type="triangle", w="med", len="med")


# --------------------------------------------------------------------------- картинки


def asset(name: str) -> Path:
    """Снимок сервиса в JPEG целиком: обрезка - свойствами кадра, файл меньше PNG вчетверо."""
    ASSETS.mkdir(parents=True, exist_ok=True)
    src = SHOTS / name
    out = ASSETS / f"{src.stem}.jpg"
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        Image.open(src).convert("RGB").save(out, "JPEG", quality=86, optimize=True)
    return out


@dataclass(frozen=True)
class Crop:
    """Кадр как object-fit: cover с object-position и увеличением scale вокруг origin."""

    pos: tuple[float, float] = (0.5, 0.5)
    scale: float = 1.0
    origin: tuple[float, float] = (0.5, 0.5)


# снимки 3D-вида и фото ИИ (shots.mjs): кадр как есть
SCENE_CROP = Crop(scale=1.12)  # без шапки сайта и кнопки «Панели»
# фото ИИ: JPEG после апскейла до 4K или PNG без апскейлера - что скачал shots.mjs
PHOTO = next((n for n in ("photo-ai.jpg", "photo-ai.png") if (SHOTS / n).exists()), "photo-ai.jpg")
PHOTO_CROP = Crop()
REVIEW_CROP = Crop((0.5, 0.0))  # страница по центру окна, поля по краям срезаны
WORK_CROP = Crop((0.5, 0.5))


def picture(
    slide: Slide,
    name: str,
    box: tuple[float, float, float, float],
    crop: Crop = Crop(),  # noqa: B008 - неизменяемый dataclass
    *,
    dark: bool = False,
    radius: float = 0.125,
    shadow: bool = True,
    border: str | None = None,
) -> None:
    path = asset(name)
    x, y, w, h = box
    iw, ih = Image.open(path).size
    frame = w / h
    if iw / ih > frame:
        vw, vh = ih * frame, ih
        left, top = (iw - vw) * crop.pos[0], 0.0
    else:
        vw, vh = iw, iw / frame
        left, top = 0.0, (ih - vh) * crop.pos[1]
    s = crop.scale
    x0 = left + crop.origin[0] * (1 - 1 / s) * vw
    y0 = top + crop.origin[1] * (1 - 1 / s) * vh
    pic = slide.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w), Inches(h))
    pic.crop_left = x0 / iw
    pic.crop_right = 1 - (x0 + vw / s) / iw
    pic.crop_top = y0 / ih
    pic.crop_bottom = 1 - (y0 + vh / s) / ih
    sppr = pic._element.spPr
    geom = sppr.find(qn("a:prstGeom"))
    geom.set("prst", "roundRect")
    av = geom.find(qn("a:avLst"))
    if av is None:
        av = etree.SubElement(geom, qn("a:avLst"))
    etree.SubElement(av, qn("a:gd"), name="adj", fmla=f"val {round(radius / min(w, h) * 100000)}")
    if border:
        pic.line.color.rgb = rgb(border)
        pic.line.width = Pt(2.25)
    if shadow:
        sppr.append(
            parse_xml(
                f'<a:effectLst {nsdecls("a")}><a:outerShdw blurRad="330000" dist="120000" '
                f'dir="5400000" algn="t" rotWithShape="0"><a:srgbClr val="{"000000" if dark else NIGHT}">'
                f'<a:alpha val="{40000 if dark else 26000}"/></a:srgbClr></a:outerShdw></a:effectLst>'
            )
        )


def tag(slide: Slide, x: float, y: float, label: str) -> None:
    """Подпись поверх снимка: тёмная плашка с белым текстом."""
    w = 0.35 + len(label) * 0.088
    t = rect(slide, (x, y, w, 0.3), INK, radius=0.15)
    alpha(t, 82)
    fill_frame(
        t.text_frame,
        [para(label, Style(SEMI, 10, WHITE))],
        align=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    t.text_frame.word_wrap = False


# --------------------------------------------------------------------------- каркас слайда


def set_background(slide: Slide, image: Path) -> None:
    """Фон слайда картинкой шаблона: не выделяется и не сдвигается при правке."""
    _, rid = slide.part.get_or_add_image_part(str(image))
    bg = parse_xml(
        f"<p:bg {nsdecls('p', 'a', 'r')}><p:bgPr>"
        f'<a:blipFill dpi="0" rotWithShape="1"><a:blip r:embed="{rid}"/><a:srcRect/>'
        "<a:stretch><a:fillRect/></a:stretch></a:blipFill><a:effectLst/></p:bgPr></p:bg>"
    )
    slide._element.cSld.insert(0, bg)


def slide_number(slide: Slide, *, dark: bool) -> None:
    shape = slide.shapes.add_textbox(Inches(12.3), Inches(7.0), Inches(0.5), Inches(0.28))
    tf = shape.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.RIGHT
    fld = etree.SubElement(
        p._p, qn("a:fld"), id="{B6F15528-21DE-4FAA-801E-634DDDAF4B2B}", type="slidenum"
    )
    rpr = etree.SubElement(fld, qn("a:rPr"), lang="ru-RU", sz="1000", b="1")
    fill = etree.SubElement(rpr, qn("a:solidFill"))
    etree.SubElement(fill, qn("a:srgbClr"), val=WHITE if dark else PLUM)
    etree.SubElement(rpr, qn("a:latin"), typeface=SEMI)
    etree.SubElement(fld, qn("a:t")).text = "#"


def new_slide(prs: Deck, section: int, heading: str, *, bg: str = "light") -> Slide:
    """Слайд раздела section (1-6): фон шаблона, метка раздела, заголовок, номер."""
    layout = next(lay for lay in prs.slide_layouts if lay.name == "Пустой")
    slide = prs.slides.add_slide(layout)
    set_background(slide, BG / f"{bg}.png")
    dark = bg != "light"
    label = f"{section:02d}   {SECTIONS[section - 1].upper()}"
    chip = rect(slide, (LEFT, 0.42, 0.45 + len(label) * 0.098, 0.36), PINK, radius=0.18)
    fill_frame(
        chip.text_frame,
        [para(label, Style(SEMI, 10.5, WHITE))],
        align=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    chip.text_frame.word_wrap = False
    text(
        slide,
        (LEFT, 0.98, WIDTH, 1.0),
        [para(heading, Style(X_BOLD, 30, WHITE if dark else NIGHT))],
        line=1.0,
    )
    slide_number(slide, dark=dark)
    return slide


def notes(slide: Slide, say: str) -> None:
    slide.notes_slide.notes_text_frame.text = say


def foot(slide: Slide, value: str, *, dark: bool, y: float = 6.55, w: float = WIDTH) -> None:
    text(slide, (LEFT, y, w, 0.6), [para(value, Style(MEDIUM, 12, MIST if dark else BODY))])


# --------------------------------------------------------------------------- графики


def style_chart(chart: Chart, *, dark: bool, size: float = 11) -> None:
    chart.font.name = MEDIUM
    chart.font.size = Pt(size)
    chart.font.color.rgb = rgb(MIST if dark else BODY)
    chart.has_title = False


def paint(series: object, color: str) -> None:
    series.format.fill.solid()
    series.format.fill.fore_color.rgb = rgb(color)
    series.format.line.fill.background()


def hbar_chart(
    slide: Slide,
    box: tuple[float, float, float, float],
    categories: Sequence[str],
    series: Sequence[tuple[str, Sequence[float], str]],
    *,
    dark: bool = False,
    number_format: str = "0",
    size: float = 11,
    legend: bool = True,
) -> Chart:
    data = CategoryChartData(number_format=number_format)
    data.categories = list(categories)
    for name, values, _ in series:
        data.add_series(name, list(values))
    x, y, w, h = box
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.BAR_CLUSTERED, Inches(x), Inches(y), Inches(w), Inches(h), data
    ).chart
    style_chart(chart, dark=dark, size=size)
    plot = chart.plots[0]
    plot.gap_width = 40
    plot.overlap = 0
    plot.vary_by_categories = False
    plot.has_data_labels = True
    labels = plot.data_labels
    labels.number_format = number_format
    labels.number_format_is_linked = False
    labels.position = XL_LABEL_POSITION.OUTSIDE_END
    labels.font.size = Pt(size)
    labels.font.bold = True
    labels.font.color.rgb = rgb(WHITE if dark else NIGHT)
    for (_, _, color), s in zip(series, plot.series, strict=True):
        paint(s, color)
    cat = chart.category_axis
    cat.reverse_order = True
    cat.has_major_gridlines = False
    cat.format.line.fill.background()
    cat.tick_labels.font.size = Pt(size)
    cat.tick_labels.font.color.rgb = rgb(MIST if dark else BODY)
    val = chart.value_axis
    val.visible = False
    val.has_major_gridlines = False
    val.minimum_scale = 0
    chart.has_legend = len(series) > 1 and legend
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.TOP
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(size)
        chart.legend.font.color.rgb = rgb(WHITE if dark else BODY)
    return chart


# --------------------------------------------------------------------------- 01 описание


def s_problem(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 1, "Под газоном идут кабели и трубы")
    picture(s, "utilities.png", (LEFT, 2.1, 6.95, 4.45), Crop((0.5, 0.5), 1.35, (0.5, 0.45)))
    x, w = 8.0, 4.67
    text(
        s,
        (x, 2.1, w, 2.0),
        [
            para(
                "Дерево нельзя посадить ближе 2 м к силовому кабелю, 1,5 м к газопроводу, "
                "5 м к стене дома (СП 42.13330.2016, табл. 9.1).",
                Style(SEMI, 15, INK),
            )
        ],
        line=1.2,
    )
    text(
        s,
        (x, 3.55, w, 1.1),
        [
            para(
                "Проектировщик сверяет каждое место с сетями на чертеже вручную. Заказчик "
                "назвал разбор сетей самым трудоёмким этапом проекта.",
                Style(MEDIUM, 12.5, BODY),
            )
        ],
        line=1.25,
    )
    for i, (value, label) in enumerate(
        (("14 316", "мест-кандидатов вдоль бортов Кустанайской"), ("1 639", "проходят все нормы"))
    ):
        y = 4.85 + i * 0.85
        text(s, (x, y, 2.0, 0.6), [para(value, Style(X_BOLD, 26, PINK))])
        text(s, (x + 2.05, y + 0.1, w - 2.05, 0.6), [para(label, Style(MEDIUM, 12, BODY))])
    text(
        s,
        (LEFT, 6.7, 6.95, 0.3),
        [para("Подземные сети Кустанайской улицы, слои плана скрыты", Style(MEDIUM, 10, MUTE))],
    )
    notes(
        s,
        "Задача: посадить деревья и кусты по нормам отступов от сетей, зданий и бортов. "
        f"На Кустанайской (прогон 20.10.2026) из 14 316 мест вдоль бортов нормы проходят 1 639. "
        f"Всего в своде {f['rules_distance']} норм расстояний.",
    )


def s_solution(prs: Deck, f: dict[str, str]) -> None:  # noqa: ARG001 - общая подпись слайдов
    s = new_slide(prs, 1, "Чертёж на входе, план и объяснения на выходе", bg="dark")
    w, h, gap = 3.5, 2.7, 0.75
    frames = (
        (
            "flow-before.png",
            Crop((0.3, 0.5), 2.0, (0.25, 0.3)),
            "DXF улицы",
            "подоснова Мосгеотреста и сети; по желанию слои ГИС, кадастр, перечётная ведомость",
        ),
        (
            "flow-after.png",
            Crop((0.3, 0.5), 2.0, (0.25, 0.3)),
            "План посадок",
            "слои GREEN_*: деревья, кусты, газоны, цветники, отказы, зоны допустимости",
        ),
        (
            "explain-card.png",
            Crop((0.5, 0.0)),
            "Объяснение каждой посадки",
            "замер, норма и акт",
        ),
    )
    for i, (name, crop, head, sub) in enumerate(frames):
        x = LEFT + i * (w + gap)
        picture(s, name, (x, 2.1, w, h), crop, dark=True)
        text(
            s,
            (x, 2.1 + h + 0.2, w, 1.1),
            [para(head, Style(SEMI, 15, WHITE)), para(sub, Style(MEDIUM, 11.5, MIST))],
            line=1.2,
            after=3,
        )
        if i < len(frames) - 1:
            arrow(s, (x + w + 0.15, 2.1 + h / 2), (x + w + gap - 0.15, 2.1 + h / 2), ROSE)
    foot(s, "У каждой посадки в DXF есть атрибуты вида и нормы.", dark=True)
    notes(
        s, "Вход - DXF улицы, выход - тот же DXF со слоями GREEN_* и объяснения по каждой посадке."
    )


def s_steps(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 1, "Семь шагов до решения")
    steps = (
        (
            "Точный парсинг",
            "Учёт 100% примитивов чертежа и сквозная сверка геометрии с исходным DXF.",
        ),
        (
            "Семантика слоёв",
            f"Распознавание сетей, бортов, застройки и {f['symbols']} типов условных знаков "
            "геоподосновы.",
        ),
        (
            "Анализ покрытий",
            "Выделение газонов, тротуаров, проездов и зон с открытым грунтом под посадки.",
        ),
        (
            "Сценарии посадки",
            "Аллея вдоль бортов, куртины на газонах, живые изгороди, цветники.",
        ),
        (
            "Подбор пород (MILP)",
            f"Подбор из {f['species']} видов с учётом инсоляции, габаритов и городских квот.",
        ),
        (
            "Аудит и валидация",
            f"Финальная проверка готового плана по {f['rules_total']} правилам: "
            f"{f['violations']} нарушений на выходе.",
        ),
        (
            "Экспорт и отчётность",
            "Слои GREEN_*, ведомость, таблицы CSV, записка DOCX и протокол со ссылками на акты.",
        ),
    )
    gap = 0.16
    w = (WIDTH - gap * 6) / 7
    for i, (head, sub) in enumerate(steps):
        x = LEFT + i * (w + gap)
        circle_number(s, x, 2.3, 0.56, str(i + 1), size=16)
        if i < len(steps) - 1:
            dash = s.shapes.add_connector(
                MSO_CONNECTOR.STRAIGHT,
                Inches(x + 0.66),
                Inches(2.58),
                Inches(x + w + gap - 0.1),
                Inches(2.58),
            )
            dash.line.color.rgb = rgb(BLUSH)
            dash.line.width = Pt(2)
        text(s, (x, 3.1, w, 0.75), [para(head, Style(X_BOLD, 13.5, NIGHT))], line=1.05)
        text(s, (x, 3.9, w, 2.2), [para(sub, Style(MEDIUM, 11.5, BODY))], line=1.25)
    card = rect(s, (LEFT, 5.75, WIDTH, 0.95), WHITE, line=(BLUSH, 1.25), radius=0.16)
    card.text_frame.margin_left = card.text_frame.margin_right = Inches(0.3)
    fill_frame(
        card.text_frame,
        [
            [
                ("Математическая оптимизация вместо машинного обучения. ", Style(SEMI, 12, PINK)),
                (
                    "В принятом плане Берзарина нормы отступов нарушены в 391 посадке из 554: "
                    "обучать нейросеть на таких данных нельзя. Солвер MILP (HiGHS) строго "
                    "соблюдает нормативные пороги, каждое дерево проверяемо. Локальная языковая "
                    "модель только подсказывает класс незнакомого слоя.",
                    Style(MEDIUM, 12, BODY),
                ),
            ]
        ],
        anchor=MSO_ANCHOR.MIDDLE,
        line=1.2,
    )
    card.text_frame.margin_left = card.text_frame.margin_right = Inches(0.3)
    notes(
        s, "Семь шагов конвейера. Ключевое: генерация и проверка разделены, проверка независимая."
    )


def s_explain(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 1, "Проверка норм для каждого растения")
    picture(s, "explain-map.png", (LEFT, 1.95, 4.85, 4.7), Crop((0.3, 0.5), 1.3, (0.5, 0.5)))
    picture(s, "explain-card.png", (5.75, 1.95, 3.25, 4.7), Crop((0.5, 0.0)))
    x, w = 9.35, 3.32
    text(
        s,
        (x, 1.95, w, 4.8),
        [
            [
                ("Наглядные замеры на плане и в карточке. ", Style(SEMI, 13, INK)),
                (
                    "Сервис рассчитывает расстояние до сетей (теплосеть: факт 3,47 м ≥ норма "
                    "2,50 м) и прикрепляет пункт документа с дословной цитатой.",
                    Style(MEDIUM, 11.5, BODY),
                ),
            ],
            [
                ("Аргументированное выявление нарушений. ", Style(SEMI, 13, INK)),
                (
                    "Отказ со ссылкой на регламент: «до силового кабеля 0,51 м при норме "
                    "2,00 м» (R-POWER-TREE-001, СП 42.13330.2016, п. 9.6, табл. 9.1).",
                    Style(MEDIUM, 11.5, BODY),
                ),
            ],
            [
                ("Без «галлюцинаций». ", Style(SEMI, 13, INK)),
                (
                    f"В базе {f['rules_total']} правил из {f['acts']} нормативных актов. "
                    "Формулировки собирает строгий алгоритм, а не нейросеть: результат "
                    "детерминирован и проверяем.",
                    Style(MEDIUM, 11.5, BODY),
                ),
            ],
        ],
        line=1.2,
        after=12,
    )
    notes(s, "Интерпретируемость: у каждой посадки и отказа замер, правило, акт, пункт, цитата.")


# --------------------------------------------------------------------------- 02 маркетинг


def s_users(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 2, "Кому нужен сервис")
    roles = (
        (
            "Проектировщик благоустройства",
            "Загружает чертёж, автоматически получает схему посадок, вносит правки "
            "в веб-интерфейсе и возвращает результат в привычный CAD.",
            f"Скорость: {f['minutes_median']} мин на улицу",
        ),
        (
            "Специалист ДПиООС",
            "Автоматически проверяет отступы от сетей и нормативную базу. За минуты "
            "проверяет готовые чертежи подрядчиков перед согласованием.",
            "Контроль: аудит каждой посадки",
        ),
        (
            "Согласующие ведомства",
            "Оценивают баланс и объёмы озеленения, ведомость, записку DOCX и будущий облик "
            "улицы в интерактивном 3D-виде.",
            "Наглядность: ведомость и 3D",
        ),
    )
    gap = 0.3
    w = (WIDTH - 2 * gap) / 3
    for i, (head, body, metric) in enumerate(roles):
        x = LEFT + i * (w + gap)
        rect(s, (x, 1.95, w, 2.85), WHITE, line=(BLUSH, 1.25), radius=0.18)
        circle_number(s, x + 0.3, 2.22, 0.5, str(i + 1), size=14)
        text(
            s,
            (x + 0.95, 2.22, w - 1.2, 0.55),
            [para(head, Style(X_BOLD, 14, NIGHT))],
            anchor=MSO_ANCHOR.MIDDLE,
            line=1.0,
        )
        text(s, (x + 0.3, 2.95, w - 0.6, 1.3), [para(body, Style(MEDIUM, 11.5, BODY))], line=1.25)
        text(s, (x + 0.3, 4.33, w - 0.6, 0.35), [para(metric, Style(SEMI, 12, PINK))])
    text(
        s,
        (LEFT, 5.05, WIDTH, 0.35),
        [para("Валидация болей заказчика", Style(SEMI, 13, PLUM))],
    )
    quotes = (
        (
            "Топ-1 и Топ-2",
            "главные причины возврата проектов: нарушение отступов от сетей и ошибки "
            "в объёмах посадок",
        ),
        (
            "0",
            "свободная ниша: у заказчика не было попыток автоматизировать проектирование "
            "озеленения",
        ),
        (
            "DXF",
            "работа в стандартном AutoCAD без плагинов: результат - в обычных слоях чертежа",
        ),
        (
            "до 60 мин",
            "ориентир на генерацию плана улицы, до 30 мин на подбор мест; сервис - "
            f"{f['minutes_median']} мин",
        ),
    )
    qw = (WIDTH - 3 * 0.25) / 4
    for i, (big, label) in enumerate(quotes):
        x = LEFT + i * (qw + 0.25)
        text(s, (x, 5.45, qw, 0.45), [para(big, Style(X_BOLD, 20, PINK))])
        text(s, (x, 5.95, qw, 0.9), [para(label, Style(MEDIUM, 10.5, BODY))], line=1.2)
    notes(
        s,
        "Три пользователя из ТЗ, у каждого свой вход. Ниже - ответы заказчика (docs/notes/15): "
        "главная боль - отступы, автоматизации не было, нужен обычный DXF.",
    )


def s_audit(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 2, "Распределение 785 нарушений по типам объектов")
    data = CategoryChartData(number_format="0")
    data.categories = ["с нарушениями", "без нарушений"]
    data.add_series("посадки", [AUDIT_BAD, AUDIT_ALL - AUDIT_BAD])
    chart = s.shapes.add_chart(
        XL_CHART_TYPE.DOUGHNUT, Inches(LEFT), Inches(1.95), Inches(3.3), Inches(3.3), data
    ).chart
    style_chart(chart, dark=False)
    chart.has_legend = False
    plot = chart.plots[0]
    plot.vary_by_categories = True
    for point, color in zip(plot.series[0].points, (PINK, BLUSH), strict=True):
        point.format.fill.solid()
        point.format.fill.fore_color.rgb = rgb(color)
        point.format.line.fill.background()
    hole = plot._element.find(qn("c:holeSize"))
    if hole is None:
        hole = etree.SubElement(plot._element, qn("c:holeSize"))
    hole.set("val", "68")
    share = round(AUDIT_BAD / AUDIT_ALL * 100)
    text(
        s,
        (LEFT, 2.98, 3.3, 1.2),
        [
            para(f"{share}%", Style(X_BOLD, 34, PINK)),
            para("посадок", Style(SEMI, 10, BODY)),
            para("с нарушениями", Style(SEMI, 10, BODY)),
        ],
        align=PP_ALIGN.CENTER,
        line=1.0,
    )
    text(
        s,
        (LEFT, 5.45, 4.2, 1.4),
        [
            para(
                f"В принятом плане улицы Берзарина {AUDIT_BAD} из {AUDIT_ALL} посадок нарушают "
                "отступы; нормоконтроль занял 162 с.",
                Style(MEDIUM, 12, BODY),
            ),
            para(
                f"В плане сервиса для той же улицы нарушений {f['violations']}.",
                Style(SEMI, 12, NIGHT),
            ),
        ],
        line=1.2,
        after=6,
    )
    x = 5.35
    text(
        s,
        (x, 1.95, RIGHT - x, 0.4),
        [
            para(
                "На одну посадку может приходиться несколько нарушений",
                Style(SEMI, 13, NIGHT),
            )
        ],
    )
    chart = hbar_chart(
        s,
        (x, 2.35, RIGHT - x, 4.4),
        [a for a, _ in AUDIT],
        [("нарушения", [v for _, v in AUDIT], PINK)],
    )
    last = chart.plots[0].series[0].points[len(AUDIT) - 1]
    last.format.fill.solid()
    last.format.fill.fore_color.rgb = rgb(LAV)
    notes(
        s,
        "Второй продукт - нормоконтроль: green audit проверяет план проектировщика теми же "
        "правилами и пишет, сколько метров не хватает.",
    )


def s_visual(prs: Deck, f: dict[str, str]) -> None:  # noqa: ARG001 - общая подпись слайдов
    s = new_slide(prs, 2, "3D-визуализация и фотореализм", bg="dark")
    # 3D-вид в ТЗ не просили, фото ИИ - бонус ТЗ: жюри видит это до того, как читает слайд.
    # Плашка - на уровне заголовка у правого края: верхнюю полосу занимают логотипы шаблона.
    extra = "СВЕРХ ТЗ: 3D-ВИД  ·  БОНУС ТЗ: ФОТО ИИ"
    w = 0.45 + len(extra) * 0.098
    chip = rect(s, (RIGHT - w, 1.2, w, 0.4), LAV, radius=0.2)
    fill_frame(
        chip.text_frame,
        [para(extra, Style(SEMI, 10.5, WHITE))],
        align=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    chip.text_frame.word_wrap = False
    # верхний ряд: фото ИИ, город вокруг, пульт сцены
    y, h, gap = 1.95, 2.1, 0.15
    wide = 4.5
    narrow = (WIDTH - wide - 2 * gap) / 2
    picture(s, PHOTO, (LEFT, y, wide, h), PHOTO_CROP, dark=True)
    tag(s, LEFT + 0.15, y + h - 0.45, "фото ИИ по кадру 3D-вида")
    x = LEFT + wide + gap
    picture(
        s, "extra/scene-city.png", (x, y, narrow, h), Crop(scale=1.3, origin=(0.5, 0.2)), dark=True
    )
    tag(s, x + 0.15, y + h - 0.45, "город вокруг: OpenStreetMap")
    x += narrow + gap
    # пульт справа: время и сезон, слои плана, камера, окружение
    picture(
        s,
        "extra/scene-panel.png",
        (x, y, narrow, h),
        Crop(scale=1.7, origin=(1.0, 0.75)),
        dark=True,
    )
    tag(s, x + 0.15, y + h - 0.45, "пульт сцены")
    # нижний ряд: сезоны, ночь и возраст посадок одним ракурсом
    y2, h2, gap2 = y + h + gap, 1.3, 0.12
    tiles = (
        ("extra/season-spring.png", "весна"),
        ("extra/season-summer.png", "лето"),
        ("extra/season-autumn.png", "осень"),
        ("extra/season-winter.png", "зима"),
        ("scene-night.png", "ночь"),
        ("extra/age-0.png", "посадка"),
        ("extra/age-60.png", "взрослые"),
    )
    tw = (WIDTH - (len(tiles) - 1) * gap2) / len(tiles)
    for i, (name, label) in enumerate(tiles):
        tx = LEFT + i * (tw + gap2)
        crop = Crop(scale=2.0, origin=(0.6, 0.6))
        if name == "scene-night.png":
            crop = Crop((0.5, 0.85), 1.6, (0.6, 0.85))
        elif "age-" in name:  # саженцы и взрослые деревья в середине бульвара
            crop = Crop(scale=3.0, origin=(0.61, 0.8))
        picture(s, name, (tx, y2, tw, h2), crop, dark=True, radius=0.1)
        tag(s, tx + 0.1, y2 + h2 - 0.38, label)
    text(
        s,
        (LEFT, y2 + h2 + 0.2, WIDTH - 0.6, 1.0),
        [
            [
                ("На пульте: ", Style(SEMI, 11, WHITE)),
                (
                    "сезон, час и поворот солнца, возраст посадок; ветер, дождь, снег, листопад; "
                    "люди, машины, оборудование площадок; город вокруг из OpenStreetMap; слои "
                    "сетей и граница работ; облёт, полёт и пешеход; перелёт по схеме плана; "
                    "красные отметки деревьев, стоящих ближе нормы к зданию.",
                    Style(MEDIUM, 11, MIST),
                ),
            ],
            para(
                "Покрытия, борта и ограды - по линиям чертежа, этажность - по подписям. Фото по "
                "кадру рисует Qwen-Image-2.1-Turbo на своей видеокарте, без внешних сервисов.",
                Style(MEDIUM, 11, MIST),
            ),
        ],
        line=1.15,
        after=4,
    )
    notes(
        s,
        "3D-вид сделан сверх ТЗ, фото ИИ - бонус ТЗ; оба из того же плана. Посадки стоят там же, "
        "где в DXF; по тротуарам ходят люди, на площадках дети. Сцена настраивается целиком: сезон "
        "и зима без листвы, время суток и поворот солнца, возраст посадок от года посадки до "
        "взрослых, погода (ветер, дождь, снег, листопад), люди, машины и оборудование, город "
        "вокруг из OpenStreetMap, слои сетей и граница работ, облёт, полёт и пешеход, схема "
        "плана для перелёта в точку. Существующие деревья ближе нормы к зданию отмечены красным. "
        "Фото по кадру: режим «по плану» не дорисовывает деревья, которых нет в плане. Время: на "
        "RTX 5070 кадр 1536 x 864 - 85 с, через API с апскейлом до 4K - 94 с (docs/notes/40).",
    )


# --------------------------------------------------------------------------- 03 бизнес


def s_city(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 3, "Эффект внедрения для города")
    share = round(AUDIT_BAD / AUDIT_ALL * 100)
    cards = (
        ("570 улиц", "в плане благоустройства Москвы на 2026 год [1]"),
        ("12\u00a0000", "крупномерных деревьев высажено в Москве за 2025 год [2]"),
        (
            f"{share}%",
            f"посадок проектировщика на Берзарина ближе нормы: {AUDIT_BAD} из {AUDIT_ALL} [3]",
        ),
        (
            f"{f['minutes_median']} мин",
            f"на план улицы, медиана по {f['streets_done']} улицам пилота; вручную - рабочий день*",
        ),
    )
    gap = 0.25
    w = (WIDTH - 3 * gap) / 4
    y, h = 1.95, 1.55
    for i, (big, sub) in enumerate(cards):
        x = LEFT + i * (w + gap)
        rect(s, (x, y, w, h), WHITE, line=(BLUSH, 1.25), radius=0.16)
        text(s, (x + 0.25, y + 0.18, w - 0.5, 0.55), [para(big, Style(X_BOLD, 26, PINK))])
        text(
            s,
            (x + 0.25, y + 0.78, w - 0.5, 0.7),
            [para(sub, Style(MEDIUM, 10.5, BODY))],
            line=1.15,
        )
    py, ph = 3.7, 2.45
    rect(s, (LEFT, py, WIDTH, ph), NIGHT, radius=0.18)
    text(
        s,
        (LEFT + 0.35, py + 0.18, 8.0, 0.35),
        [para("Экономия в рублях - оценка с допущениями*", Style(SEMI, 13, ROSE))],
    )
    cols = (
        (
            "На работника",
            (
                (
                    "≈ 7\u00a0800 ₽",
                    "на улицу: 7,85 ч проектировщика по ≈ 1\u00a0000 ₽/ч [5]",
                ),
                ("≈ 2 млн ₽ в год", "на ставку, освобождённую от ручного подбора"),
            ),
        ),
        (
            "На улицу",
            (
                ("≈ 0,3 млн ₽", "типичная улица: 148 деревьев, медиана принятых проектов"),
                ("5% переделок", "посадок ближе нормы, крупномер 55\u00a0000 ₽ [4]"),
            ),
        ),
        (
            "По Москве",
            (
                ("от 24 млн ₽ в год", "по 12\u00a0000 деревьев в год и 570 улицам"),
                ("≈ 4,5 млн ₽ в год", "≈ 4\u00a0500 ч проектировщиков, ≈ 2,3 ставки"),
            ),
        ),
    )
    cgap = 0.35
    cw = (WIDTH - 0.7 - 2 * cgap) / 3
    for i, (head, rows) in enumerate(cols):
        x = LEFT + 0.35 + i * (cw + cgap)
        text(s, (x, py + 0.62, cw, 0.3), [para(head, Style(SEMI, 12, WHITE))])
        for j, (big, sub) in enumerate(rows):
            ry = py + 0.95 + j * 0.72
            text(s, (x, ry, cw, 0.4), [para(big, Style(X_BOLD, 18, WHITE))])
            text(s, (x, ry + 0.37, cw, 0.35), [para(sub, Style(MEDIUM, 9.5, MIST))], line=1.1)
    text(
        s,
        (LEFT, 6.25, WIDTH - 0.6, 0.75),
        [
            para(
                "* Допущения: ручной план улицы - рабочий день, экономия 7,85 ч; из посадок ближе "
                "нормы переделывают 5%; ставка ≈ 1\u00a0000 ₽/ч - 126\u00a0123 ₽/мес [5] и ≈ 30% "
                "взносов на ≈ 165 ч/мес; по медиане hh.ru 97\u00a0975 ₽/мес [6] - ≈ 770 ₽/ч и "
                "≈ 6\u00a0000 ₽ на улицу. Справочно: одна липа на Тверской стоила 191\u00a0171 ₽ [7].",
                Style(MEDIUM, 8.5, MUTE),
            ),
            para(
                "[1] Москвич Mag, 28.11.2025  [2] sobyanin.ru, 13.08.2026  [3] нормоконтроль "
                "green audit  [4] Русский парк, прайс 2026  [5] ГородРабота, 2025  "
                "[6] career.hh.ru  [7] Meduza, 2017, госзакупки",
                Style(MEDIUM, 8.5, MUTE),
            ),
        ],
        line=1.1,
        after=2,
    )
    notes(
        s,
        "Масштаб: 570 улиц в плане благоустройства Москвы на 2026 год, 12 000 крупномерных "
        f"деревьев за 2025 год. На Берзарина {AUDIT_BAD} из {AUDIT_ALL} посадок проектировщика "
        "ближе нормы (green audit). План улицы - "
        f"{f['minutes_median']} мин (медиана по {f['streets_done']} улицам пилота) против рабочего "
        "дня вручную. Всё в рублях - оценка с допущениями. На работника: 7,85 ч на улицу "
        "≈ 7 800 ₽ при ≈ 1 000 ₽/ч (126 123 ₽/мес + ≈ 30% взносов, ≈ 165 ч/мес); по медиане "
        "hh.ru ≈ 770 ₽/ч и ≈ 6 000 ₽. По Москве ≈ 4 500 ч в год ≈ 2,3 ставки ≈ 4,5 млн ₽, то есть "
        "≈ 2 млн ₽ в год на одну ставку. Переделки: на типичной улице 148 деревьев (медиана "
        "принятых проектов), 5% посадок с нарушением переделывают, крупномер 55 000 ₽: ≈ 0,3 млн ₽ "
        "на улицу, по Москве от 24 млн ₽ в год.\n"
        "Источники:\n"
        "[1] Москвич Mag, 28.11.2025 - https://moskvichmag.ru/?p=466614\n"
        "[2] sobyanin.ru, 13.08.2026 - https://www.sobyanin.ru/ozelenenie-moskvy-itogi-proshlogo-goda\n"
        "[3] нормоконтроль green audit, docs/notes/24-audit.md\n"
        "[4] Русский парк, прайс 2026 - https://russian-park.ru/posadochnij-material/derevya-"
        "krupnomery/listvennye/lipa/krupnomer-lipa-5-metrov/\n"
        "[5] ГородРабота, 2025: зарплата проектировщика 126 123 ₽/мес\n"
        "[6] hh.ru, медиана 97 975 ₽/мес - https://career.hh.ru/profession/230\n"
        "[7] Meduza, 2017, по данным госзакупок: липа на Тверской - 191 171 ₽",
    )


def s_effect(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 3, "Экологический эффект: тень и защита от пыли", bg="dark")
    top = sorted(street_curbs(), key=lambda r: r[2] - r[1], reverse=True)[:7]
    text(
        s,
        (LEFT, 1.9, 7.0, 0.6),
        [
            [
                ("Борта под кронами и кустарником, %: ", Style(SEMI, 13, WHITE)),
                ("было", Style(SEMI, 13, LAV)),
                (" и ", Style(SEMI, 13, WHITE)),
                ("с планом сервиса", Style(SEMI, 13, ROSE)),
            ],
            para("7 улиц с наибольшим приростом", Style(MEDIUM, 11, MIST)),
        ],
    )
    hbar_chart(
        s,
        (LEFT, 2.55, 7.0, 4.25),
        [r[0] for r in top],
        [("было", [r[1] for r in top], LAV), ("с планом сервиса", [r[2] for r in top], PINK)],
        dark=True,
        number_format="0.0",
        size=10.5,
        legend=False,
    )
    stats = effect_stats(f)
    x, w = 8.2, RIGHT - 8.2
    for i, (big, label) in enumerate(stats):
        y = 1.95 + i * 1.18
        text(s, (x, y, w, 0.5), [para(big, Style(X_BOLD, 22, ROSE))])
        text(s, (x, y + 0.48, w, 0.6), [para(label, Style(MEDIUM, 11, MIST))], line=1.15)
    notes(
        s,
        "Эффект для города: тень, пылезащита, ярусность - то, что заказчик назвал признаками хорошего плана.",
    )


def effect_stats(f: dict[str, str]) -> tuple[tuple[str, str], ...]:
    """Четыре числа эффекта по facts.json с подписями-пояснениями."""

    def whole(value: str) -> int:
        return int("".join(ch for ch in value if ch.isdigit()))

    before, after = (part.strip() for part in f["effect_tiers"].split("→"))
    times = round(whole(after) / whole(before))
    km = round(whole(f["effect_curb_m"]) / 1000)
    curb = f["effect_curb"].replace(" длины бортов", "")
    canopy = f["effect_canopy"].replace(" площади участков", "").replace(" → ", "% до ")
    return (
        (
            f"{f['trees']} и {f['shrubs']}",
            f"деревьев и кустов подобрано с соблюдением норм на {f['streets_done']} улицах "
            f"Москвы, нарушений {f['violations']}",
        ),
        (
            f"{curb} (+{km} км)",
            "прирост длины бортов под кронами и кустарником: меньше шума, пыли и выхлопа "
            "на тротуарах",
        ),
        (
            f["effect_canopy_m2"],
            f"площадь затенения от взрослых крон: доля участков под кронами с {canopy}",
        ),
        (
            f"{f['effect_tiers']} (в {times} раз)",
            "деревьев с кустарником под кроной: устойчивые двухъярусные посадки",
        ),
    )


# --------------------------------------------------------------------------- 04 техника


def node(
    slide: Slide, box: tuple[float, float, float, float], head: str, sub: str, *, core: bool = False
) -> None:
    n = rect(slide, box, PINK if core else WHITE, line=None if core else (WHITE, 1.0), radius=0.14)
    if not core:
        alpha(n, 10, 30)
    tf = n.text_frame
    fill_frame(
        tf,
        [
            para(head, Style(SEMI, 14, WHITE)),
            para(sub, Style(MEDIUM, 10.5, WHITE if core else MIST)),
        ],
        anchor=MSO_ANCHOR.MIDDLE,
        line=1.15,
        after=2,
    )
    tf.margin_left = tf.margin_right = Inches(0.2)


def s_deploy(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 4, "Архитектура: единое ядро и гибкие интерфейсы", bg="dark")
    y0, h, gap = 1.95, 0.8, 0.2
    for i, (head, sub) in enumerate(
        (
            ("CLI", "пакетная обработка улиц, аудит чужих чертежей"),
            ("REST API", "OpenAPI 3.1, Swagger для интеграции с ГИС"),
            ("Веб-интерфейс", "React: просмотр и правка плана, 3D и фото"),
        )
    ):
        node(s, (LEFT, y0 + i * (h + gap), 2.8, h), head, sub)
    mid = y0 + (3 * h + 2 * gap) / 2
    arrow(s, (LEFT + 2.95, mid), (LEFT + 3.55, mid), ROSE)
    node(
        s,
        (LEFT + 3.7, mid - 0.55, 2.95, 1.1),
        "Единое ядро",
        "общие правила и алгоритмы для всех интерфейсов",
        core=True,
    )
    code = rect(s, (LEFT, 4.95, 6.65, 0.85), "000000", radius=0.12)
    alpha(code, 35)
    fill_frame(
        code.text_frame,
        [
            para("docker compose up --build", Style(MONO, 12, WHITE, bold=True)),
            para(
                "green run улица.dxf --profile barriers --set spacing_m=6",
                Style(MONO, 12, WHITE, bold=True),
            ),
        ],
        anchor=MSO_ANCHOR.MIDDLE,
        line=1.3,
    )
    code.text_frame.margin_left = Inches(0.25)
    text(
        s,
        (LEFT, 5.95, 6.65, 0.9),
        [
            para(
                "Образ на Ubuntu 26.04: по ТЗ МосТех.ОС близка к Ubuntu; ODA File Converter - "
                f"аргументом сборки. {f['params']} параметров, 5 профилей. Тесты: {TESTS_BACKEND} "
                f"бэкенда, покрытие строк {COVER_BACKEND}; {TESTS_FRONTEND} фронтенда, "
                f"{COVER_FRONTEND}. Ollama для подсказок - профиль llm в "
                "compose. Манифесты Kubernetes проверены kubeconform.",
                Style(MEDIUM, 11.5, MIST),
            )
        ],
        line=1.2,
    )
    picture(s, "swagger.png", (7.85, 1.95, RIGHT - 7.85, 4.85), Crop((0.0, 0.0)), dark=True)
    notes(s, "Архитектура: гексагональное ядро, три тонкие обёртки. Swagger без интернета.")


def s_speed(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 4, "Результаты пилота на реальных данных")
    rows = sorted(street_minutes(f), key=lambda r: r[1])
    text(
        s,
        (LEFT, 1.9, 8.7, 0.6),
        [
            para(
                f"Минуты прогона по улицам, медиана {f['minutes_median']}", Style(SEMI, 13, NIGHT)
            ),
            para(
                "Пунктир - ориентиры заказчика: 30 мин на подбор мест, 60 мин на генерацию",
                Style(MEDIUM, 11, BODY),
            ),
        ],
    )
    data = CategoryChartData(number_format="0.0")
    data.categories = [r[0] for r in rows]
    data.add_series("минуты", [r[1] for r in rows])
    chart = s.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(LEFT), Inches(2.5), Inches(8.7), Inches(4.4), data
    ).chart
    style_chart(chart, dark=False, size=9)
    chart.has_legend = False
    plot = chart.plots[0]
    plot.gap_width = 45
    plot.has_data_labels = True
    labels = plot.data_labels
    labels.number_format = "0.0"
    labels.number_format_is_linked = False
    labels.position = XL_LABEL_POSITION.OUTSIDE_END
    labels.font.size = Pt(9)
    labels.font.bold = True
    labels.font.color.rgb = rgb(NIGHT)
    paint(plot.series[0], PINK)
    val = chart.value_axis
    val.minimum_scale = 0
    val.maximum_scale = 60
    val.major_unit = 30
    val.has_major_gridlines = True
    grid = val.major_gridlines.format.line
    grid.color.rgb = rgb(PLUM)
    grid.width = Pt(1.25)
    grid.dash_style = MSO_LINE_DASH_STYLE.DASH
    val.format.line.fill.background()
    val.tick_labels.font.size = Pt(9)
    val.tick_labels.number_format = "0"
    val.tick_labels.number_format_is_linked = False
    cat = chart.category_axis
    cat.format.line.color.rgb = rgb(BLUSH)
    cat.tick_labels.font.size = Pt(9)
    body_pr = cat._element.find(qn("c:txPr")).find(qn("a:bodyPr"))
    body_pr.set("rot", "-2700000")
    body_pr.set("vert", "horz")
    x, w = 9.75, RIGHT - 9.75
    stats = (
        (
            f"{f['streets_done']} из {len(rows)}",
            "улиц каталога с планом; Фрунзенская собрана из PDF-генплана, DWG у неё нет",
        ),
        (f["violations"], "нарушений норм в выданных планах по независимой проверке"),
        (
            f"{f['entities_changed']} из {f['entities']}",
            "исходных объектов изменено при записи",
        ),
    )
    for i, (big, label) in enumerate(stats):
        y = 2.0 + i * 1.6
        text(s, (x, y, w, 0.55), [para(big, Style(X_BOLD, 24 if len(big) < 10 else 17, PINK))])
        text(s, (x, y + 0.6, w, 0.9), [para(label, Style(MEDIUM, 11, BODY))], line=1.2)
    notes(
        s,
        "Время по всем улицам пилота, строгий профиль. Каждая улица - один прогон без ручных "
        "правок. Фрунзенская набережная в материалах пилота есть только листами PDF: "
        "tools/pdf_to_dxf.py собрал из пяти листов чертёж в метрах.",
    )


def s_inputs(prs: Deck, f: dict[str, str]) -> None:  # noqa: ARG001 - общая подпись слайдов
    s = new_slide(prs, 4, "Чужой чертёж и данные города")
    picture(s, "review.png", (LEFT, 1.95, 6.3, 4.85), REVIEW_CROP)
    text(
        s,
        (LEFT, 6.88, 6.3, 0.3),
        [
            para(
                "Уточнение объектов чертежа: класс каждого слоя и основание",
                Style(MEDIUM, 10, MUTE),
            )
        ],
    )
    x, w = 7.35, RIGHT - 7.35
    items = (
        (
            "Чертёж жюри",
            "236287.dxf проходит без ручных правок: слова слоёв паспорта ОГХ, единицы без "
            "заголовка, пунктир MicroStation собирается в линии.",
        ),
        (
            "Классификаторы Москвы для ИМ, 2024",
            f"{IM_ROWS} строк, у {IM_CODES} кодов есть класс сервиса: слой с кодом "
            "«ТС 22 00 01» в имени читается как деревья.",
        ),
        (
            "Незнакомый слой",
            "Класс - по словам имени и по геометрии. Локальная gemma4 в Ollama подсказывает "
            "в таблице уточнения, решает человек.",
        ),
        (
            "Слои ГИС и кадастр",
            "GeoJSON и SHP: тип территории по 369-ПП, охранные зоны газа и ЛЭП. Яма на чужом "
            "участке - на согласование с правообладателем.",
        ),
        (
            "Деревья у стен",
            "Существующее дерево ближе нормы к зданию отмечено красным на плане и в 3D. "
            "Это повод проверить его, а не назначение к вырубке.",
        ),
    )
    paras: list[Para] = []
    for head, body in items:
        paras += [para(head, Style(X_BOLD, 12.5, NIGHT)), para(body, Style(MEDIUM, 11, BODY))]
    box = text(s, (x, 1.95, w, 4.9), paras, line=1.15, after=1)
    for i, p in enumerate(box.text_frame.paragraphs):
        if i and i % 2 == 0:  # отбивка перед заголовком пункта
            p.space_before = Pt(10)
    notes(
        s,
        "Устойчивость к входу: чертёж жюри 236287 считается без JSON-переопределений; "
        "Фрунзенская собрана из PDF. Подсказки LLM - совет в таблице уточнения, класс и план они "
        "не меняют. Кадастр: ГрК РФ ст. 1 п. 12, ЖК РФ ст. 44 - правила R-PARCEL-* и R-MKD-*; "
        "на участке дома посадка - через собрание собственников. Классификаторы для "
        "информационного моделирования (Москва, 2024), части ТС и ПО ЗУ - config/im_classifier.yaml: "
        f"{IM_ROWS} строк, {IM_CODES} кодов с классом; код в имени слоя решает раньше слов.",
    )


def s_workspace(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 4, "Рабочее место в браузере")
    # снимки 3200 x 1800: верхние ~100 px - шапка сайта, её срезает увеличение от нижнего края
    no_head = Crop(scale=1.06, origin=(0.5, 1.0))
    tiles = (
        ("extra/ws-home.png", no_head, "главная: улица пилота или свой DXF"),
        ("workspace.png", WORK_CROP, "клик по кроне: замеры и пункт нормы"),
        (
            "extra/ws-effect.png",
            Crop(scale=1.6, origin=(1.0, 0.3)),
            "«Эффект»: было - стало, индекс",
        ),
        ("extra/ws-reports.png", Crop(scale=1.7, origin=(0.5, 0.34)), "отчёты, CSV, DOCX и JSON"),
        ("extra/ws-journal.png", Crop(scale=1.3), "как собран план"),
        (
            "extra/ws-models.png",
            Crop(scale=1.15, origin=(0.0, 0.45)),
            f"модели {f['species']} видов",
        ),
    )
    gap_x, gap_y = 0.2, 0.2
    w = (WIDTH - 2 * gap_x) / 3
    h = w * 9 / 16
    for i, (name, crop, label) in enumerate(tiles):
        x = LEFT + (i % 3) * (w + gap_x)
        y = 1.95 + (i // 3) * (h + gap_y)
        picture(s, name, (x, y, w, h), crop, border=BLUSH)
        tag(s, x + 0.12, y + h - 0.42, label)
    foot(
        s,
        "«Править»: перенос проверяется нормами на лету, пересборка переписывает DXF. "
        "Веб, CLI и API работают через одно ядро.",
        dark=False,
        y=1.95 + 2 * h + gap_y + 0.12,
        w=WIDTH - 0.6,
    )
    notes(
        s,
        "Интерфейс второстепенен по ТЗ, но правка желательна. Главная: улица пилота или свой "
        "DXF/DWG и реестр прогонов. План: клик по кроне - замеры до сетей и пункт нормы. Вкладка "
        "«Эффект» - баланс было - стало и индекс качества. Окно «Отчёты и файлы прогона»: нормы "
        "CSV, отчёт по посадкам, записка DOCX, распознавание объектов JSON. «Как собран план» - "
        "какие варианты отброшены и почему. Каталог моделей растений - отдельная страница.",
    )


# --------------------------------------------------------------------------- 05 уникальность


def s_unique(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 5, "Чем green отличается", bg="dark")
    cards = (
        (
            f"{f['rules_total']} правил · {f['acts']} актов",
            "Прозрачное объяснение",
            "Каждая посадка и каждый отказ - с замером, кодом проверки и цитатой из акта. "
            "Текст собирает детерминированный алгоритм, без LLM.",
        ),
        (
            "Нормы в YAML",
            "Обновление норм без релиза",
            "Правила, коэффициенты и профили (включая прикорневые барьеры по СП 42) вынесены "
            "в YAML. Новая редакция норм действует без пересборки Docker-образа.",
        ),
        (
            f"{f['violations']} нарушений",
            "Двухконтурный аудит",
            "Готовый план повторно проверяется всеми правилами. Тот же нормоконтроль нашёл "
            f"в принятом плане Берзарина {AUDIT_BAD} из {AUDIT_ALL} посадок с нарушениями.",
        ),
        (
            f"{f['entities_changed']} из {f['entities']}",
            "Гарантия неизменности CAD",
            "Новое пишется только в слои GREEN_*. Каждый примитив исходной подосновы "
            "сверяется по хэшу blake2b до и после записи.",
        ),
        (
            f"{f['species']} видов",
            "Вид под место",
            "Задача MILP подбирает породу по условиям места: соль у проезда, свет, сети "
            "рядом, квоты на разнообразие пород.",
        ),
        (
            "Один план",
            "DXF, 3D, фото и отчёты",
            "Проектировщик получает CAD-слои, согласующий - отчёт HTML и Markdown с нормами, "
            "жители - 3D-сцену. Всё строится из одного проверенного плана.",
        ),
    )
    gap_x, gap_y = 0.28, 0.24
    w = (WIDTH - 2 * gap_x) / 3
    h = 2.25
    for i, (metric, head, body) in enumerate(cards):
        x = LEFT + (i % 3) * (w + gap_x)
        y = 1.95 + (i // 3) * (h + gap_y)
        c = rect(s, (x, y, w, h), WHITE, line=(WHITE, 1.0), radius=0.16)
        alpha(c, 9, 26)
        text(s, (x + 0.28, y + 0.22, w - 0.56, 0.5), [para(metric, Style(X_BOLD, 19, ROSE))])
        text(s, (x + 0.28, y + 0.7, w - 0.56, 0.3), [para(head, Style(SEMI, 13, WHITE))], line=1.0)
        text(
            s,
            (x + 0.28, y + 1.1, w - 0.56, 1.05),
            [para(body, Style(MEDIUM, 10.5, MIST))],
            line=1.2,
        )
    notes(
        s,
        "Уникальность: объяснимость без LLM, нормы как данные, независимая проверка и "
        "нормоконтроль чужих планов, неприкосновенность исходника, вид под место, единый план "
        "для DXF, 3D и фото.",
    )


# --------------------------------------------------------------------------- 06 развитие


def s_roadmap(prs: Deck, f: dict[str, str]) -> None:  # noqa: ARG001 - общая подпись слайдов
    s = new_slide(prs, 6, "Как сервис будет расти")
    stages = (
        (
            "Пилот в ДПиООС",
            (
                "образ Docker на МосТех.ОС, работает без интернета",
                "проектировщики получают черновик улицы с объяснениями",
                "нормоконтроль проектов подрядчиков по запуску команды green audit",
            ),
        ),
        (
            "Шире нормы и данные",
            (
                "водоохранные зоны и объекты наследия: нужен сверенный пункт о посадке",
                "охранные зоны по линиям сетей чертежа",
                "почвы и корнеобитаемый объём по данным изысканий",
            ),
        ),
        (
            "Масштаб",
            (
                "площадки, дорожки и малые формы скверов",
                "интеграция с системами департамента по OpenAPI",
                "сервер департамента на Kubernetes",
                "другие регионы: свой свод норм без правки кода",
            ),
        ),
    )
    gap = 0.4
    w = (WIDTH - 2 * gap) / 3
    for i, (head, items) in enumerate(stages):
        x = LEFT + i * (w + gap)
        circle_number(s, x, 2.0, 0.6, str(i + 1), size=17)
        text(
            s,
            (x + 0.8, 2.0, w - 0.8, 0.6),
            [para(f"Этап {i + 1}", Style(SEMI, 11, PINK)), para(head, Style(X_BOLD, 15, NIGHT))],
            anchor=MSO_ANCHOR.MIDDLE,
            line=1.05,
        )
        card = rect(s, (x, 2.9, w, 3.2), WHITE, line=(BLUSH, 1.25), radius=0.16)
        del card
        text(
            s,
            (x + 0.28, 3.15, w - 0.56, 2.8),
            [para(item, Style(MEDIUM, 12, BODY)) for item in items],
            line=1.2,
            after=9,
            bullet=PINK,
        )
    text(
        s,
        (LEFT, 6.4, WIDTH, 0.4),
        [
            [
                ("green", Style(X_BOLD, 16, PLUM)),
                ("   команда MISIS MOJARUNG · github.com/Mojarung/LCT_2026", Style(SEMI, 12, BODY)),
            ]
        ],
        anchor=MSO_ANCHOR.MIDDLE,
    )
    notes(
        s,
        "Путь внедрения по ТЗ: пилот на ресурсах ДПиООС, затем данные ГИС и изысканий, затем масштаб.",
    )


OUR_SLIDES: tuple[Callable[[Deck, dict[str, str]], None], ...] = (
    s_problem,
    s_solution,
    s_steps,
    s_explain,
    s_users,
    s_audit,
    s_visual,
    s_city,
    s_effect,
    s_deploy,
    s_speed,
    s_inputs,
    s_workspace,
    s_unique,
    s_roadmap,
)


def add_slides(prs: Deck) -> None:
    f = facts()
    for build in OUR_SLIDES:
        build(prs, f)
