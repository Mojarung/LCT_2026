# ruff: noqa: INP001, SLF001, E501, PLR2004, PLR0913 - модуль колоды рядом с assemble_bento.py; текст
# слайдов длинными строками; у python-pptx нет API для прозрачности и формы картинки.
"""Свободные слайды презентации бенто-сетками: вторая версия рядом с native.py.

Содержание и числа - те же, что в native.py: факты, константы, снимки и примитивы берутся
оттуда импортом. Меняется только раскладка.

Правила сетки:
- 12 колонок, поле 0,5 дюйма, один промежуток GAP между колонками и рядами;
- 6 рядов под заголовком, карточка занимает целое число колонок и рядов;
- один радиус R у карточек и снимков, без теней;
- на слайде одна главная карточка (снимок сервиса или главное число), она крупнее остальных;
- в карточке крупное число и короткая подпись, отступ внутри PAD;
- одна акцентная заливка (PINK или NIGHT) на слайд, остальные карточки нейтральные.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lxml import etree
from native import (
    AUDIT,
    AUDIT_ALL,
    AUDIT_BAD,
    BG,
    BLUSH,
    BODY,
    INK,
    LAV,
    MEDIUM,
    MIST,
    MONO,
    NIGHT,
    PHOTO,
    PHOTO_CROP,
    PINK,
    PLUM,
    ROSE,
    SCENE_CROP,
    SECTIONS,
    SEMI,
    TESTS_BACKEND,
    TESTS_FRONTEND,
    WHITE,
    WORK_CROP,
    X_BOLD,
    Crop,
    Style,
    alpha,
    circle_number,
    facts,
    fill_frame,
    hbar_chart,
    notes,
    para,
    picture,
    rect,
    rgb,
    set_background,
    slide_number,
    street_curbs,
    street_minutes,
    style_chart,
    tag,
    text,
)
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

if TYPE_CHECKING:
    from collections.abc import Callable

    from native import Para
    from pptx.presentation import Presentation as Deck
    from pptx.shapes.autoshape import Shape
    from pptx.slide import Slide

# --------------------------------------------------------------------------- сетка

MARGIN = 0.5  # поле слайда, дюймы
SLIDE_W = 13.333
COLS, ROWS = 12, 6
GAP = 0.18
TOP, BOTTOM = 1.78, 6.9  # область сетки под заголовком; ниже - номер слайда шаблона
COL_W = (SLIDE_W - 2 * MARGIN - (COLS - 1) * GAP) / COLS
ROW_H = (BOTTOM - TOP - (ROWS - 1) * GAP) / ROWS
R = 0.2  # радиус всех карточек и снимков
PAD = 0.24  # отступ текста внутри карточки
FULL = Crop()  # кадр снимка целиком

type Box = tuple[float, float, float, float]


def cell(col: int, cols: int, row: int, rows: int) -> Box:
    """Прямоугольник карточки: колонки col..col+cols-1, ряды row..row+rows-1."""
    x = MARGIN + col * (COL_W + GAP)
    y = TOP + row * (ROW_H + GAP)
    return x, y, cols * COL_W + (cols - 1) * GAP, rows * ROW_H + (rows - 1) * GAP


def inset(box: Box, pad: float = PAD) -> Box:
    x, y, w, h = box
    return x + pad, y + pad, w - 2 * pad, h - 2 * pad


# --------------------------------------------------------------------------- карточки

# вид карточки: заливка, обводка, прозрачность заливки и обводки
LIGHT = "light"  # белая на светлом фоне
SOFT = "soft"  # розоватая на светлом фоне
GLASS = "glass"  # полупрозрачная на тёмном фоне
ACCENT = "accent"  # розовая акцентная
DEEP = "deep"  # тёмно-фиолетовая акцентная


def card(slide: Slide, box: Box, kind: str = LIGHT) -> Shape:
    match kind:
        case "light":
            return rect(slide, box, WHITE, line=(BLUSH, 1.0), radius=R)
        case "soft":
            return rect(slide, box, "FFF0F5", line=(BLUSH, 1.0), radius=R)
        case "glass":
            c = rect(slide, box, WHITE, line=(WHITE, 0.75), radius=R)
            alpha(c, 9, 22)
            return c
        case "accent":
            return rect(slide, box, PINK, radius=R)
        case "deep":
            return rect(slide, box, NIGHT, radius=R)
    msg = f"неизвестный вид карточки: {kind}"
    raise ValueError(msg)


def on_dark(kind: str) -> bool:
    return kind in {GLASS, ACCENT, DEEP}


def palette(kind: str) -> tuple[str, str, str]:
    """Цвета числа, заголовка и текста для вида карточки."""
    match kind:
        case "accent":
            return WHITE, WHITE, WHITE
        case "deep":
            return ROSE, WHITE, MIST
        case "glass":
            return ROSE, WHITE, MIST
    return PINK, NIGHT, BODY


def stat(
    slide: Slide,
    box: Box,
    big: str,
    label: str,
    *,
    kind: str = LIGHT,
    eyebrow: str | None = None,
    size: float = 30,
    label_size: float = 11.5,
    anchor: MSO_ANCHOR = MSO_ANCHOR.BOTTOM,
) -> None:
    """Карточка с крупным числом и подписью; подпись сверху мелкими прописными."""
    card(slide, box, kind)
    num_c, head_c, body_c = palette(kind)
    x, y, w, h = inset(box)
    if eyebrow:
        text(slide, (x, y, w, 0.3), [para(eyebrow.upper(), Style(SEMI, 9.5, head_c))])
    paras: list[Para] = [
        para(big, Style(X_BOLD, size, num_c)),
        para(label, Style(MEDIUM, label_size, body_c)),
    ]
    text(
        slide,
        (x, y + (0.32 if eyebrow else 0), w, h - (0.32 if eyebrow else 0)),
        paras,
        line=1.12,
        after=3,
        anchor=anchor,
    )


def note(
    slide: Slide,
    box: Box,
    head: str,
    body: str | tuple[str, ...],
    *,
    kind: str = LIGHT,
    eyebrow: str | None = None,
    head_size: float = 14,
    body_size: float = 11,
    anchor: MSO_ANCHOR = MSO_ANCHOR.TOP,
) -> None:
    """Карточка с заголовком и коротким текстом."""
    card(slide, box, kind)
    num_c, head_c, body_c = palette(kind)
    paras: list[Para] = []
    if eyebrow:
        paras.append(para(eyebrow.upper(), Style(SEMI, 9.5, num_c if kind != ACCENT else WHITE)))
    paras.append(para(head, Style(X_BOLD, head_size, head_c)))
    lines = (body,) if isinstance(body, str) else body
    paras.extend(para(line, Style(MEDIUM, body_size, body_c)) for line in lines)
    text(slide, inset(box), paras, line=1.18, after=5, anchor=anchor)


def shot(
    slide: Slide,
    name: str,
    box: Box,
    crop: Crop = FULL,
    label: str | None = None,
    *,
    dark: bool = False,
) -> None:
    """Снимок сервиса во всю карточку; подпись плашкой в левом нижнем углу."""
    picture(slide, name, box, crop, dark=dark, radius=R, shadow=False, border=None)
    if label:
        x, y, _, h = box
        tag(slide, x + 0.16, y + h - 0.46, label)


# --------------------------------------------------------------------------- каркас слайда


def new_slide(prs: Deck, section: int, heading: str, *, bg: str = "light") -> Slide:
    """Слайд раздела: фон шаблона, метка раздела, заголовок, номер - как в native.py, по полю сетки."""
    layout = next(lay for lay in prs.slide_layouts if lay.name == "Пустой")
    slide = prs.slides.add_slide(layout)
    set_background(slide, BG / f"{bg}.png")
    dark = bg != "light"
    label = f"{section:02d}   {SECTIONS[section - 1].upper()}"
    chip = rect(slide, (MARGIN, 0.42, 0.45 + len(label) * 0.098, 0.36), PINK, radius=0.18)
    fill_frame(
        chip.text_frame,
        [para(label, Style(SEMI, 10.5, WHITE))],
        align=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    chip.text_frame.word_wrap = False
    text(
        slide,
        (MARGIN, 0.95, SLIDE_W - 2 * MARGIN, 0.7),
        [para(heading, Style(X_BOLD, 28, WHITE if dark else NIGHT))],
        line=1.0,
    )
    slide_number(slide, dark=dark)
    return slide


# --------------------------------------------------------------------------- 01 описание


def s_problem(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 1, "Под газоном идут кабели и трубы")
    shot(
        s,
        "utilities.png",
        cell(0, 7, 0, 6),
        Crop((0.5, 0.5), 1.35, (0.5, 0.45)),
        "Подземные сети Кустанайской, слои плана скрыты",
        dark=True,
    )
    box = cell(7, 5, 0, 2)
    card(s, box, LIGHT)
    x, y, w, h = inset(box)
    text(s, (x, y, w, 0.3), [para("СП 42.13330.2016, табл. 9.1".upper(), Style(SEMI, 9.5, NIGHT))])
    third = w / 3
    for i, (big, label) in enumerate(
        (("2 м", "до силового кабеля"), ("1,5 м", "до газопровода"), ("5 м", "до стены дома"))
    ):
        text(
            s,
            (x + i * third, y + 0.36, third - 0.08, h - 0.36),
            [para(big, Style(X_BOLD, 26, PINK)), para(label, Style(MEDIUM, 10.5, BODY))],
            line=1.1,
        )
    note(
        s,
        cell(7, 5, 2, 2),
        "Сети сверяют вручную",
        "Проектировщик проверяет каждое место по чертежу сетей. Заказчик назвал разбор сетей самым трудоёмким этапом проекта.",
        body_size=11.5,
    )
    stat(
        s,
        cell(7, 3, 4, 2),
        "14 316",
        "мест-кандидатов вдоль бортов Кустанайской",
        kind=DEEP,
        size=28,
    )
    stat(s, cell(10, 2, 4, 2), "1 639", "проходят все нормы", kind=ACCENT, size=22)
    notes(
        s,
        "Задача: посадить деревья и кусты по нормам отступов от сетей, зданий и бортов. "
        "На Кустанайской (прогон 20.10.2026) из 14 316 мест вдоль бортов нормы проходят 1 639. "
        f"Всего в своде {f['rules_distance']} норм расстояний.",
    )


def s_solution(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 1, "DXF на входе, план и объяснения на выходе", bg="dark")
    zoom = Crop((0.3, 0.5), 2.0, (0.25, 0.3))
    shot(s, "flow-before.png", cell(0, 4, 0, 4), zoom, "1  DXF улицы", dark=True)
    shot(s, "flow-after.png", cell(4, 5, 0, 4), zoom, "2  План посадок", dark=True)
    shot(
        s,
        "explain-card.png",
        cell(9, 3, 0, 6),
        Crop((0.5, 0.0)),
        "3  Объяснение посадки",
        dark=True,
    )
    note(
        s,
        cell(0, 4, 4, 2),
        "Вход",
        "Подоснова Мосгеотреста и сети; по желанию слои ГИС, кадастр, перечётная ведомость.",
        kind=GLASS,
        head_size=13,
    )
    note(
        s,
        cell(4, 3, 4, 2),
        "Выход: слои GREEN_*",
        "Деревья, кусты, газоны, цветники, отказы, зоны допустимости.",
        kind=GLASS,
        head_size=13,
    )
    stat(
        s,
        cell(7, 2, 4, 2),
        f["entities_changed"],
        f"изменено из {f['entities']} объектов исходников",
        kind=ACCENT,
        size=30,
        label_size=10,
    )
    notes(
        s,
        "Вход - DXF улицы, выход - тот же DXF со слоями GREEN_* и объяснения по каждой посадке. "
        f"Исходные слои не меняются: на {f['streets_run']} улицах сверено {f['entities']} объектов, "
        f"изменено {f['entities_changed']}. У каждой посадки в DXF атрибуты вида и нормы.",
    )


def s_steps(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 1, "Семь шагов от DXF до DXF")
    steps = (
        (
            "Чтение без потерь",
            "DXF, DWG через ODA; каждый примитив учтён, пунктир съёмки собран в линии",
        ),
        (
            "Классы слоёв и знаков",
            "сети, борта, здания, деревья; незнакомый слой - по словам имени и геометрии",
        ),
        ("Карта покрытий", "газон, тротуар и проезд: где под ямой грунт, в том числе по подписям"),
        ("Места посадки", "аллея вдоль борта, группы деревьев, ряды кустарника, цветники"),
        (
            "Вид под место",
            f"{f['species']} видов, MILP по условиям места и квотам; светолюбивые - не в тени домов",
        ),
        ("Независимая проверка", f"{f['rules_total']} правил заново по готовому плану"),
        ("Запись и объяснения", "слои GREEN_*, ведомость, отчёт с пунктами актов, записка DOCX"),
    )
    for i, (head, sub) in enumerate(steps):
        box = cell((i % 4) * 3, 3, (i // 4) * 2, 2)
        card(s, box, LIGHT)
        x, y, w, h = inset(box, 0.2)
        circle_number(s, x, y, 0.38, str(i + 1), size=12)
        text(
            s,
            (x + 0.48, y, w - 0.48, 0.38),
            [para(head, Style(X_BOLD, 12.5, NIGHT))],
            anchor=MSO_ANCHOR.MIDDLE,
            line=1.0,
        )
        text(s, (x, y + 0.5, w, h - 0.5), [para(sub, Style(MEDIUM, 10.5, BODY))], line=1.18)
    stat(
        s,
        cell(9, 3, 2, 2),
        f["violations"],
        "нарушений норм в готовых планах по независимой проверке",
        kind=ACCENT,
        size=34,
        label_size=10.5,
    )
    box = cell(0, 12, 4, 2)
    card(s, box, DEEP)
    x, y, w, h = inset(box, 0.3)
    text(
        s,
        (x, y, 3.2, h),
        [
            para("Алгоритм,", Style(X_BOLD, 24, WHITE)),
            para("а не обучение", Style(X_BOLD, 24, ROSE)),
        ],
        line=1.05,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    text(
        s,
        (x + 3.5, y, w - 3.5, h),
        [
            para(
                "Норма - порог расстояния, а принятые планы нарушают её в 391 посадке из 554: учиться на них нельзя. "
                "Места и виды выбирает задача MILP (HiGHS). Локальная языковая модель только подсказывает класс "
                "незнакомого слоя, план она не меняет.",
                Style(MEDIUM, 12.5, MIST),
            )
        ],
        line=1.22,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    notes(
        s, "Семь шагов конвейера. Ключевое: генерация и проверка разделены, проверка независимая."
    )


def s_explain(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 1, "У каждой посадки есть пункт нормы")
    shot(
        s,
        "explain-map.png",
        cell(0, 5, 0, 6),
        Crop((0.3, 0.5), 1.3, (0.5, 0.5)),
        "Выноска: замер до сети",
    )
    shot(s, "explain-card.png", cell(5, 3, 0, 6), Crop((0.5, 0.0)))
    note(
        s,
        cell(8, 4, 0, 2),
        "Посадка",
        "Выноска на карте: «теплосеть 3,47 ≥ 2,50». В карточке - правило, акт, пункт и дословная цитата.",
        eyebrow="замер и норма",
        head_size=13,
        body_size=10.5,
    )
    note(
        s,
        cell(8, 4, 2, 2),
        "Отказ",
        (
            "«До силового кабеля 0,51 м < 2,00 м».",
            "R-POWER-TREE-001, СП 42.13330.2016, п. 9.6, табл. 9.1.",
        ),
        eyebrow="тот же формат",
        head_size=13,
        body_size=10.5,
    )
    stat(
        s,
        cell(8, 4, 4, 2),
        f"{f['rules_total']} правил · {f['acts']} актов",
        f"у {f['rules_by_text']} основание сверено по тексту акта; объяснение собирается из трассы проверок без языковой модели",
        kind=ACCENT,
        size=22,
        label_size=10,
    )
    notes(s, "Интерпретируемость: у каждой посадки и отказа замер, правило, акт, пункт, цитата.")


# --------------------------------------------------------------------------- 02 маркетинг


def s_users(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 2, "Кому нужен сервис")
    box = cell(0, 5, 0, 4)
    card(s, box, DEEP)
    x, y, w, h = inset(box, 0.3)
    text(
        s,
        (x, y, w, h),
        [
            para("1 · ПРОЕКТИРОВЩИК БЛАГОУСТРОЙСТВА", Style(SEMI, 9.5, ROSE)),
            para(f"{f['minutes_median']} мин", Style(X_BOLD, 40, WHITE)),
            para("медиана на улицу", Style(SEMI, 12, ROSE)),
            para(
                "Подаёт DXF подосновы и сетей, получает черновик плана с проверенными отступами, правит его "
                "в браузере и доводит в своём CAD.",
                Style(MEDIUM, 11.5, MIST),
            ),
        ],
        line=1.15,
        after=6,
    )
    roles = (
        (
            cell(5, 4, 0, 4),
            "2 · Специалист ДПиООС",
            "Проверяет отступы и обоснования: у каждой посадки акт, пункт, расстояние и запас. Теми же правилами проверяет план подрядчика.",
            "green audit",
        ),
        (
            cell(9, 3, 0, 4),
            "3 · Участник согласования",
            "Сверяет объёмы озеленения и баланс «было - стало»: ведомость и записка собраны из того же плана, что и DXF.",
            "Excel и DOCX",
        ),
    )
    for b, head, body, metric in roles:
        card(s, b, LIGHT)
        x, y, w, h = inset(b)
        text(
            s,
            (x, y, w, h - 0.55),
            [para(head.upper(), Style(SEMI, 9.5, NIGHT)), para(body, Style(MEDIUM, 12.5, BODY))],
            line=1.2,
            after=8,
        )
        text(
            s,
            (x, y + h - 0.45, w, 0.45),
            [para(metric, Style(X_BOLD, 17, PINK))],
            anchor=MSO_ANCHOR.BOTTOM,
        )
    quotes = (
        ("№ 1", "причина возврата проектов - нарушение отступов, № 2 - неверные объёмы озеленения"),
        ("0", "попыток автоматизировать проектирование озеленения не было"),
        ("DXF", "проектировщики работают в AutoCAD без плагинов: результат - обычные слои"),
        ("до 60 мин", "ориентир на генерацию плана улицы, до 30 мин на подбор мест"),
    )
    for i, (big, label) in enumerate(quotes):
        b = cell(i * 3, 3, 4, 2)
        card(s, b, SOFT)
        x, y, w, h = inset(b, 0.2)
        text(s, (x, y, w, 0.25), [para("ЗАКАЗЧИК", Style(SEMI, 8, PLUM))])
        text(
            s,
            (x, y + 0.26, w, h - 0.26),
            [para(big, Style(X_BOLD, 20, PINK)), para(label, Style(MEDIUM, 10, BODY))],
            line=1.15,
            after=2,
        )
    notes(
        s,
        "Три пользователя из ТЗ, у каждого свой вход. Ниже - ответы заказчика (docs/notes/15): "
        "главная боль - отступы, автоматизации не было, нужен обычный DXF.",
    )


def s_audit(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 2, "Сервис проверяет и чужие планы")
    box = cell(0, 4, 0, 6)
    card(s, box, LIGHT)
    x, y, w, _ = inset(box)
    text(s, (x, y, w, 0.3), [para("ПРИНЯТЫЙ ПЛАН УЛИЦЫ БЕРЗАРИНА", Style(SEMI, 9.5, NIGHT))])
    d = 3.2
    cx = box[0] + (box[2] - d) / 2
    data = CategoryChartData(number_format="0")
    data.categories = ["с нарушениями", "без нарушений"]
    data.add_series("посадки", [AUDIT_BAD, AUDIT_ALL - AUDIT_BAD])
    chart = s.shapes.add_chart(
        XL_CHART_TYPE.DOUGHNUT, Inches(cx), Inches(y + 0.4), Inches(d), Inches(d), data
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
        (cx, y + 0.4 + d / 2 - 0.55, d, 1.1),
        [
            para(f"{share}%", Style(X_BOLD, 32, PINK)),
            para("посадок", Style(SEMI, 10, BODY)),
            para("с нарушениями", Style(SEMI, 10, BODY)),
        ],
        align=PP_ALIGN.CENTER,
        line=1.0,
    )
    text(
        s,
        (x, y + 0.5 + d, w, 1.2),
        [
            para(f"{AUDIT_BAD} из {AUDIT_ALL}", Style(X_BOLD, 22, NIGHT)),
            para("посадок нарушают отступы; нормоконтроль занял 162 с", Style(MEDIUM, 11, BODY)),
        ],
        line=1.12,
        after=2,
    )
    b = cell(4, 8, 0, 4)
    card(s, b, LIGHT)
    x, y, w, h = inset(b)
    text(
        s,
        (x, y, w, 0.3),
        [
            para(
                "785 нарушений по видам объектов: у посадки их бывает несколько",
                Style(SEMI, 12, NIGHT),
            )
        ],
    )
    chart = hbar_chart(
        s,
        (x, y + 0.35, w, h - 0.35),
        [a for a, _ in AUDIT],
        [("нарушения", [v for _, v in AUDIT], PINK)],
        size=10,
    )
    last = chart.plots[0].series[0].points[len(AUDIT) - 1]
    last.format.fill.solid()
    last.format.fill.fore_color.rgb = rgb(LAV)
    stat(
        s,
        cell(4, 4, 4, 2),
        f["violations"],
        "нарушений в плане сервиса для той же улицы",
        kind=ACCENT,
        size=34,
    )
    note(
        s,
        cell(8, 4, 4, 2),
        "green audit",
        "Проверяет план проектировщика теми же правилами и пишет, сколько метров не хватает.",
        kind=SOFT,
        head_size=14,
    )
    notes(
        s,
        "Второй продукт - нормоконтроль: green audit проверяет план проектировщика теми же "
        "правилами и пишет, сколько метров не хватает.",
    )


def s_visual(prs: Deck, f: dict[str, str]) -> None:  # noqa: ARG001 - общая подпись слайдов
    s = new_slide(prs, 2, "Улицу видно до начала работ", bg="dark")
    # 3D-вид в ТЗ не просили, фото ИИ - бонус ТЗ: жюри видит это до того, как читает слайд.
    extra = "СВЕРХ ТЗ: 3D-ВИД  ·  БОНУС ТЗ: ФОТО ИИ"
    w = 0.45 + len(extra) * 0.098
    right = SLIDE_W - MARGIN
    chip = rect(s, (right - w, 1.12, w, 0.4), LAV, radius=0.2)
    fill_frame(
        chip.text_frame,
        [para(extra, Style(SEMI, 10.5, WHITE))],
        align=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    chip.text_frame.word_wrap = False
    shot(s, "scene3d.png", cell(0, 8, 0, 4), SCENE_CROP, "3D-вид по координатам плана", dark=True)
    shot(s, PHOTO, cell(8, 4, 0, 3), PHOTO_CROP, "фото ИИ по этому кадру", dark=True)
    # ночью выразительна нижняя часть кадра: пятна света фонарей у посадок и окна домов
    night = Crop((0.5, 0.85), 1.2, (0.6, 0.85))
    shot(
        s, "scene-night.png", cell(8, 4, 3, 3), night, "та же улица ночью: фонари и окна", dark=True
    )
    note(
        s,
        cell(0, 4, 4, 2),
        "Сцена из чертежа",
        "Покрытия, борта, ограды и площадки - по линиям чертежа, этажность - по подписям, кроны - по виду и возрасту, солнце - по часу над Москвой.",
        kind=GLASS,
        head_size=13,
        body_size=10.5,
    )
    note(
        s,
        cell(4, 4, 4, 2),
        "Фото без внешних сервисов",
        "Фото по кадру рисует Qwen-Image-2.1-Turbo на своей видеокарте.",
        kind=GLASS,
        head_size=13,
        body_size=10.5,
    )
    notes(
        s,
        "3D-вид сделан сверх ТЗ, фото ИИ - бонус ТЗ; оба из того же плана. Посадки стоят там же, где в DXF; по тротуарам "
        "ходят люди, на площадках дети. Время суток и сезон меняются на пульте, ночью горят "
        "фонари. Фото по кадру: режим «по плану» не дорисовывает деревья, которых нет в плане. "
        "Время: на RTX 5070 кадр 1536 x 864 - 85 с, через API с апскейлом до 4K - 94 с "
        "(docs/notes/40); фото на слайде - 1536 x 864 без апскейла.",
    )


# --------------------------------------------------------------------------- 03 бизнес


def s_city(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 3, "Эффект внедрения для города")
    box = cell(0, 6, 0, 3)
    card(s, box, ACCENT)
    x, y, w, h = inset(box, 0.3)
    text(
        s,
        (x, y, w, h),
        [
            para(f"{f['minutes_median']} мин", Style(X_BOLD, 48, WHITE)),
            para("на генерацию плана улицы", Style(SEMI, 14, WHITE)),
            para(
                f"Медиана по {f['streets_done']} улицам пилота, от {f['minutes_min']} до {f['minutes_max']} мин. "
                "Ориентир заказчика - до 60 мин.",
                Style(MEDIUM, 11.5, WHITE),
            ),
        ],
        line=1.1,
        after=5,
        anchor=MSO_ANCHOR.BOTTOM,
    )
    stat(
        s,
        cell(6, 3, 0, 3),
        f["rules_total"],
        f"оцифрованных правил: {f['acts']} актов, в том числе 743-ПП и СП 42.13330; {f['violations']} нарушений в планах {f['streets_done']} улиц",
        size=36,
        label_size=10.5,
    )
    stat(
        s,
        cell(9, 3, 0, 3),
        "2,7 мин",
        "на нормоконтроль плана улицы: пункт акта и недобор в метрах",
        size=32,
        label_size=10.5,
    )
    points = (
        (
            "Гибкость и актуальность",
            "Нормативы вынесены в конфигурацию: смена редакции или региональных правил без переписывания кода. СП00a042.13330 2016 и 2026 уже в своде.",
        ),
        (
            "Данные не уходят (on-premise)",
            "Работа в закрытом контуре заказчика. Расчёту не нужны сеть и GPU, фото и подсказки модели - на своей видеокарте.",
        ),
        (
            "Проверяемость решений",
            "Каждая посадка и каждый отказ со ссылкой на акт, пункт и цитату: согласующий проверяет решение, а не верит ему.",
        ),
    )
    for i, (head, body) in enumerate(points):
        note(
            s,
            cell(i * 4, 4, 3, 3),
            head,
            body,
            kind=SOFT,
            eyebrow="системное преимущество",
            head_size=14,
            body_size=11,
        )
    notes(
        s,
        f"Эффект для города: улица за минуты вместо ручного разбора сетей, {f['rules_total']} "
        "правил вместо ручной сверки, нормоконтроль подрядчика за 2,7 минуты. Внизу - три свойства, "
        "которые важны заказчику: нормы меняются без кода, данные не уходят из контура, "
        "каждое решение проверяемо по пункту акта.",
    )


def s_effect(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 3, f"Тень и защита от пыли на {f['effect_streets']} улицах", bg="dark")
    top = sorted(street_curbs(), key=lambda r: r[2] - r[1], reverse=True)[:7]
    box = cell(0, 7, 0, 6)
    card(s, box, GLASS)
    x, y, w, h = inset(box)
    text(
        s,
        (x, y, w, 0.6),
        [
            [
                ("Борта под кронами и кустарником, %: ", Style(SEMI, 12.5, WHITE)),
                ("было", Style(SEMI, 12.5, LAV)),
                (" и ", Style(SEMI, 12.5, WHITE)),
                ("с планом сервиса", Style(SEMI, 12.5, ROSE)),
            ],
            para("7 улиц с наибольшим приростом", Style(MEDIUM, 10.5, MIST)),
        ],
    )
    hbar_chart(
        s,
        (x, y + 0.65, w, h - 0.65),
        [r[0] for r in top],
        [("было", [r[1] for r in top], LAV), ("с планом сервиса", [r[2] for r in top], PINK)],
        dark=True,
        number_format="0.0",
        size=10,
        legend=False,
    )
    stat(
        s,
        cell(7, 5, 0, 2),
        f["effect_curb"].replace(" длины бортов", ""),
        f"длины бортов под кронами и кустарником, прирост {f['effect_curb_m'].replace(' м', ' м')}",
        kind=ACCENT,
        size=26,
        label_size=10.5,
    )
    stat(
        s,
        cell(7, 5, 2, 2),
        f"{f['trees']} и {f['shrubs']}",
        f"деревьев и кустов в планах {f['streets_done']} улиц пилота",
        kind=GLASS,
        size=24,
        label_size=10.5,
    )
    stat(
        s,
        cell(7, 3, 4, 2),
        f["effect_canopy_m2"],
        f"взрослых крон: {f['effect_canopy']}",
        kind=GLASS,
        size=18,
        label_size=10,
    )
    stat(
        s,
        cell(10, 2, 4, 2),
        f["effect_tiers"],
        "деревьев с кустарником под кроной",
        kind=GLASS,
        size=14,
        label_size=10,
    )
    notes(
        s,
        "Эффект для города: тень, пылезащита, ярусность - то, что заказчик назвал признаками хорошего плана.",
    )


# --------------------------------------------------------------------------- 04 техника


def s_deploy(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 4, "Разворачивается одной командой", bg="dark")
    for i, (head, sub) in enumerate(
        (
            ("CLI", "green run, audit, verify"),
            ("HTTP API", "OpenAPI 3.1, Swagger без сети"),
            ("Веб", "React: план, правка, 3D и фото"),
        )
    ):
        note(
            s,
            cell(i * 2, 2, 0, 2),
            head,
            sub,
            kind=GLASS,
            head_size=14,
            body_size=10,
            anchor=MSO_ANCHOR.TOP,
        )
    b = card(s, cell(0, 6, 2, 1), ACCENT)
    fill_frame(
        b.text_frame,
        [
            [
                ("Одно ядро:  ", Style(X_BOLD, 13, WHITE)),
                ("CLI, API и веб вызывают один сценарий PlanSite", Style(MEDIUM, 11.5, WHITE)),
            ]
        ],
        anchor=MSO_ANCHOR.MIDDLE,
    )
    b.text_frame.margin_left = Inches(PAD)
    code = rect(s, cell(0, 6, 3, 1), "000000", radius=R)
    alpha(code, 35)
    fill_frame(
        code.text_frame,
        [
            para("docker compose up --build", Style(MONO, 11, WHITE, bold=True)),
            para(
                "green run улица.dxf --profile barriers --set spacing_m=6",
                Style(MONO, 11, WHITE, bold=True),
            ),
        ],
        anchor=MSO_ANCHOR.MIDDLE,
        line=1.2,
    )
    code.text_frame.margin_left = Inches(PAD)
    stat(
        s,
        cell(0, 3, 4, 2),
        f"{TESTS_BACKEND} + {TESTS_FRONTEND}",
        "тестов бэкенда и фронтенда",
        kind=GLASS,
        size=20,
        label_size=10.5,
    )
    note(
        s,
        cell(3, 3, 4, 2),
        f"{f['params']} параметров",
        "5 профилей. Образ на Ubuntu 26.04 (МосТех.ОС близка к ней), ODA - аргументом сборки, Kubernetes - kubeconform.",
        kind=GLASS,
        head_size=15,
        body_size=9.5,
    )
    shot(
        s,
        "swagger.png",
        cell(6, 6, 0, 6),
        Crop((0.0, 0.0)),
        "Swagger UI из образа, без интернета",
        dark=True,
    )
    notes(
        s,
        "Архитектура: гексагональное ядро, три тонкие обёртки. Swagger без интернета. "
        "Ollama для подсказок - профиль llm в compose.",
    )


def s_speed(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 4, f"{f['streets_done']} улиц пилота без ручных правок")
    rows = sorted(street_minutes(f), key=lambda r: r[1])
    box = cell(0, 8, 0, 6)
    card(s, box, LIGHT)
    x, y, w, h = inset(box)
    text(
        s,
        (x, y, w, 0.6),
        [
            para(
                f"Минуты прогона по улицам, медиана {f['minutes_median']}", Style(SEMI, 12.5, NIGHT)
            ),
            para(
                "Пунктир - ориентиры заказчика: 30 мин на подбор мест, 60 мин на генерацию",
                Style(MEDIUM, 10.5, BODY),
            ),
        ],
    )
    data = CategoryChartData(number_format="0.0")
    data.categories = [r[0] for r in rows]
    data.add_series("минуты", [r[1] for r in rows])
    chart = s.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(x), Inches(y + 0.6), Inches(w), Inches(h - 0.6), data
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
    labels.font.size = Pt(8.5)
    labels.font.bold = True
    labels.font.color.rgb = rgb(NIGHT)
    plot.series[0].format.fill.solid()
    plot.series[0].format.fill.fore_color.rgb = rgb(PINK)
    plot.series[0].format.line.fill.background()
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
    cat.tick_labels.font.size = Pt(8.5)
    body_pr = cat._element.find(qn("c:txPr")).find(qn("a:bodyPr"))
    body_pr.set("rot", "-2700000")
    body_pr.set("vert", "horz")
    stat(
        s,
        cell(8, 4, 0, 2),
        f"{f['streets_done']} из {len(rows)}",
        "улиц каталога с планом; Фрунзенская собрана из PDF-генплана",
        size=30,
        label_size=10.5,
    )
    stat(
        s,
        cell(8, 4, 2, 2),
        f["violations"],
        "нарушений норм в выданных планах по независимой проверке",
        kind=ACCENT,
        size=34,
        label_size=10.5,
    )
    stat(
        s,
        cell(8, 4, 4, 2),
        f"{f['entities_changed']} из {f['entities']}",
        "объектов исходников изменено после записи",
        kind=DEEP,
        size=20,
        label_size=10.5,
    )
    notes(
        s,
        "Время по всем улицам пилота, строгий профиль. Каждая улица - один прогон без ручных "
        "правок. Фрунзенская набережная в материалах пилота есть только листами PDF: "
        "tools/pdf_to_dxf.py собрал из пяти листов чертёж в метрах.",
    )


def s_inputs(prs: Deck, f: dict[str, str]) -> None:  # noqa: ARG001 - общая подпись слайдов
    s = new_slide(prs, 4, "Чужой чертёж и данные города")
    shot(
        s,
        "review.png",
        cell(0, 6, 0, 6),
        Crop((0.12, 0.0)),
        "Уточнение объектов: класс слоя и основание",
    )
    items = (
        (
            cell(6, 3, 0, 3),
            ACCENT,
            "Чертёж жюри",
            "236287.dxf проходит без ручных правок: слова слоёв паспорта ОГХ, единицы без заголовка, пунктир MicroStation собирается в линии.",
        ),
        (
            cell(9, 3, 0, 3),
            LIGHT,
            "Незнакомый слой",
            "Класс - по словам имени и по геометрии. Локальная модель в Ollama (gemma4) подсказывает в таблице уточнения, решает человек.",
        ),
        (
            cell(6, 3, 3, 3),
            LIGHT,
            "Слои ГИС",
            "GeoJSON и SHP. Охранные и природные территории задают тип территории по 369-ПП, охранные зоны газа и ЛЭП стесняют посадку.",
        ),
        (
            cell(9, 3, 3, 3),
            LIGHT,
            "Кадастр",
            "Участок задаёт назначение места. Яма на частном участке - на согласование с правообладателем, на участке дома - с собранием собственников.",
        ),
    )
    for b, kind, head, body in items:
        note(s, b, head, body, kind=kind, head_size=15, body_size=11.5)
    notes(
        s,
        "Устойчивость к входу: чертёж жюри 236287 считается без JSON-переопределений; "
        "Фрунзенская собрана из PDF. Подсказки LLM - совет в таблице уточнения, класс и план они "
        "не меняют. Кадастр: ГрК РФ ст. 1 п. 12, ЖК РФ ст. 44 - правила R-PARCEL-* и R-MKD-*.",
    )


def s_workspace(prs: Deck, f: dict[str, str]) -> None:  # noqa: ARG001 - общая подпись слайдов
    s = new_slide(prs, 4, "Рабочее место в браузере")
    shot(s, "console.png", cell(0, 7, 0, 4), Crop(), "Главная: улица или свой чертёж")
    shot(s, "workspace.png", cell(7, 5, 0, 4), WORK_CROP, "План и замеры")
    items = (
        "Главная: улица пилота или свой DXF/DWG и реестр прогонов на одном экране.",
        "Клик по кроне - замеры до сетей и пункт нормы. Вкладки «Посадки», «Эффект», «Легенда».",
        "«Править»: перенос проверяется теми же нормами на лету, пересборка переписывает DXF.",
        "Отчёты, ведомость Excel и записка DOCX открываются окном поверх плана.",
    )
    for i, item in enumerate(items):
        b = cell(i * 3, 3, 4, 2)
        card(s, b, ACCENT if i == 2 else LIGHT)
        x, y, w, h = inset(b, 0.2)
        circle_number(s, x, y, 0.36, str(i + 1), size=11)
        if i == 2:
            num = s.shapes[-1]
            num.fill.fore_color.rgb = rgb(NIGHT)
        text(
            s,
            (x, y + 0.46, w, h - 0.46),
            [para(item, Style(MEDIUM, 10.5, WHITE if i == 2 else INK))],
            line=1.18,
        )
    notes(
        s,
        "Интерфейс второстепенен по ТЗ, но правка желательна: перенос, удаление, проверка точки "
        "на лету, пересборка DXF. Каталог моделей растений - отдельная страница.",
    )


# --------------------------------------------------------------------------- 05 уникальность


def s_unique(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 5, "Чем green отличается", bg="dark")
    box = cell(0, 4, 0, 6)
    card(s, box, ACCENT)
    x, y, w, h = inset(box, 0.3)
    text(
        s,
        (x, y, w, h * 0.66),
        [
            para("ПРОЗРАЧНОЕ ОБЪЯСНЕНИЕ", Style(SEMI, 9.5, WHITE)),
            para(f"{f['rules_total']} правил", Style(X_BOLD, 34, WHITE)),
            para(f"{f['acts']} актов", Style(X_BOLD, 22, WHITE)),
            para(
                "У каждой посадки и каждого отказа замер, правило, акт, пункт и дословная цитата. "
                "Текст собирается из трассы проверок, без языковой модели.",
                Style(MEDIUM, 11.5, WHITE),
            ),
        ],
        line=1.12,
        after=6,
    )
    text(
        s,
        (x, y + h * 0.7, w, h * 0.3),
        [
            para(
                "Попыток автоматизации у заказчика не было: green первым ставит посадки по сетям и доказывает каждую норму.",
                Style(SEMI, 11, NIGHT),
            )
        ],
        line=1.18,
        anchor=MSO_ANCHOR.BOTTOM,
    )
    small = (
        (
            cell(4, 4, 0, 2),
            "2 редакции СП 42",
            "Нормы - данные, а не код",
            "Новая редакция акта - правка YAML без программиста. СП 42.13330 2016 и 2026 в своде.",
        ),
        (
            cell(4, 4, 2, 2),
            f"{f['violations']} нарушений",
            "Проверка после генерации",
            "Готовый план заново проверяется всеми правилами; в чужом плане Берзарина - 391 из 554.",
        ),
        (
            cell(4, 4, 4, 2),
            f"{f['species']} видов",
            "Вид под место",
            "MILP подбирает породу: соль у проезда, тень домов, сети, квоты 369-ПП.",
        ),
        (
            cell(8, 4, 0, 3),
            f"{f['entities_changed']} из {f['entities']}",
            "Исходный чертёж не трогаем",
            "План пишется только на слои GREEN_*. После записи каждый объект исходника сверяется по отпечатку blake2b.",
        ),
        (
            cell(8, 4, 3, 3),
            "1 план",
            "DXF, 3D и фото из одного плана",
            "Проектировщик получает чертёж, согласующий - объяснения, жители - вид улицы.",
        ),
    )
    for b, metric, head, body in small:
        card(s, b, GLASS)
        x, y, w, h = inset(b, 0.22)
        text(
            s,
            (x, y, w, h),
            [
                para(metric, Style(X_BOLD, 17, ROSE)),
                para(head, Style(SEMI, 12.5, WHITE)),
                para(body, Style(MEDIUM, 10, MIST)),
            ],
            line=1.12,
            after=3,
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
            cell(0, 5, 0, 5),
            DEEP,
            "Пилот в ДПиООС",
            (
                "образ Docker на МосТех.ОС: расчёт без сети и GPU",
                "проектировщики получают черновик улицы с объяснениями",
                "нормоконтроль проектов подрядчиков: green audit",
            ),
        ),
        (
            cell(5, 4, 0, 5),
            LIGHT,
            "Шире нормы и данные",
            (
                "водоохранные зоны и объекты наследия: нужен сверенный пункт о посадке",
                "охранные зоны по линиям сетей чертежа",
                "почвы и корнеобитаемый объём по данным изысканий",
            ),
        ),
        (
            cell(9, 3, 0, 5),
            LIGHT,
            "Масштаб",
            (
                "площадки, дорожки и малые формы скверов",
                "интеграция с системами департамента по OpenAPI",
                "сервер департамента на Kubernetes",
                "другие регионы: свой свод норм без правки кода",
            ),
        ),
    )
    for i, (b, kind, head, items) in enumerate(stages):
        card(s, b, kind)
        _, head_c, body_c = palette(kind)
        x, y, w, h = inset(b, 0.28)
        circle_number(s, x, y, 0.5, str(i + 1), size=15)
        text(
            s,
            (x + 0.65, y, w - 0.65, 0.5),
            [
                para(f"ЭТАП {i + 1}", Style(SEMI, 9.5, ROSE if kind == DEEP else PINK)),
                para(head, Style(X_BOLD, 15, head_c)),
            ],
            anchor=MSO_ANCHOR.MIDDLE,
            line=1.0,
        )
        text(
            s,
            (x, y + 0.8, w, h - 0.8),
            [para(item, Style(MEDIUM, 13 if kind == DEEP else 11.5, body_c)) for item in items],
            line=1.2,
            after=9,
            bullet=PINK,
        )
    b = card(s, cell(0, 12, 5, 1), SOFT)
    fill_frame(
        b.text_frame,
        [
            [
                ("green", Style(X_BOLD, 16, PLUM)),
                ("   команда MISIS MOJARUNG · github.com/Mojarung/LCT_2026", Style(SEMI, 12, BODY)),
            ]
        ],
        anchor=MSO_ANCHOR.MIDDLE,
    )
    b.text_frame.margin_left = Inches(0.3)
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
