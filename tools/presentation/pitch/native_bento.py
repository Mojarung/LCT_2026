# ruff: noqa: INP001, SLF001, E501, PLR0913 - модуль колоды рядом с assemble_bento.py; текст
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
    CITY_ASSUMPTIONS,
    CITY_ECON,
    CITY_ECON_HEAD,
    CITY_SOURCES,
    COVER_BACKEND,
    COVER_FRONTEND,
    INK,
    INPUT_ITEMS,
    INPUT_NOTES,
    LAV,
    MEDIUM,
    MIST,
    MONO,
    MUTE,
    NIGHT,
    PINK,
    PLUM,
    ROSE,
    SECTIONS,
    SEMI,
    TESTS_BACKEND,
    TESTS_FRONTEND,
    VISUAL_CHIP,
    VISUAL_NOTES,
    VISUAL_PANEL,
    VISUAL_SCENE,
    VISUAL_TILES,
    VISUAL_TOP,
    WHITE,
    WORKSPACE_FOOT,
    X_BOLD,
    Crop,
    Style,
    alpha,
    circle_number,
    city_cards,
    city_notes,
    effect_stats,
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
    text,
    tile_crop,
    workspace_tiles,
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


def caption(slide: Slide, box: Box, label: str) -> None:
    """Подпись снимка плашкой в левом нижнем углу; длинная переносится в узкой карточке."""
    x, y, w, h = box
    room = w - 0.32
    need = 0.3 + len(label) * 0.085
    lines = 1 if need <= room else -(-need // room)
    tw = min(need, room)
    th = 0.3 + (lines - 1) * 0.17
    t = rect(slide, (x + 0.16, y + h - 0.16 - th, tw, th), INK, radius=0.15)
    alpha(t, 82)
    fill_frame(
        t.text_frame,
        [para(label, Style(SEMI, 10, WHITE))],
        align=PP_ALIGN.CENTER if lines == 1 else PP_ALIGN.LEFT,
        anchor=MSO_ANCHOR.MIDDLE,
        line=1.0,
    )
    t.text_frame.word_wrap = lines > 1
    t.text_frame.margin_left = t.text_frame.margin_right = Inches(0.1)


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
        caption(slide, box, label)


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
        "Подземные сети Кустанайской улицы, слои плана скрыты",
        dark=True,
    )
    box = cell(7, 5, 0, 2)
    card(s, box, LIGHT)
    x, y, w, h = inset(box)
    text(
        s,
        (x, y, w, 0.3),
        [
            para(
                "Дерево нельзя посадить ближе · СП 42.13330.2016, табл. 9.1".upper(),
                Style(SEMI, 9, NIGHT),
            )
        ],
    )
    third = w / 3
    for i, (big, label) in enumerate(
        (("2 м", "к силовому кабелю"), ("1,5 м", "к газопроводу"), ("5 м", "к стене дома"))
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
        "Проектировщик сверяет каждое место с сетями на чертеже вручную. Заказчик назвал разбор сетей самым трудоёмким этапом проекта.",
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
    s = new_slide(prs, 1, "Чертёж на входе, план и объяснения на выходе", bg="dark")
    zoom = Crop((0.3, 0.5), 2.0, (0.25, 0.3))
    shot(s, "flow-before.png", cell(0, 4, 0, 4), zoom, "1  DXF улицы", dark=True)
    shot(s, "flow-after.png", cell(4, 5, 0, 4), zoom, "2  План посадок", dark=True)
    shot(
        s,
        "explain-card.png",
        cell(9, 3, 0, 4),
        Crop((0.5, 0.0)),
        "3  Объяснение каждой посадки: замер, норма и акт",
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
        cell(4, 5, 4, 2),
        "Выход: слои GREEN_*",
        "Деревья, кусты, газоны, цветники, отказы, зоны допустимости. У каждой посадки в DXF есть атрибуты вида и нормы.",
        kind=GLASS,
        head_size=13,
    )
    stat(
        s,
        cell(9, 3, 4, 2),
        f["entities_changed"],
        f"изменено из {f['entities']} объектов исходников",
        kind=ACCENT,
        size=26,
        label_size=10,
    )
    notes(
        s,
        "Вход - DXF улицы, выход - тот же DXF со слоями GREEN_* и объяснения по каждой посадке. "
        f"Исходные слои не меняются: на {f['streets_run']} улицах сверено {f['entities']} объектов, "
        f"изменено {f['entities_changed']}. У каждой посадки в DXF атрибуты вида и нормы.",
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
            f"Распознавание сетей, бортов, застройки и {f['symbols']} типов условных знаков геоподосновы.",
        ),
        (
            "Анализ покрытий",
            "Выделение газонов, тротуаров, проездов и зон с открытым грунтом под посадки.",
        ),
        ("Сценарии посадки", "Аллея вдоль бортов, куртины на газонах, живые изгороди, цветники."),
        (
            "Подбор пород (MILP)",
            f"Подбор из {f['species']} видов с учётом инсоляции, габаритов и городских квот.",
        ),
        (
            "Аудит и валидация",
            f"Финальная проверка готового плана по {f['rules_total']} правилам: {f['violations']} нарушений на выходе.",
        ),
        (
            "Экспорт и отчётность",
            "Слои GREEN_*, ведомость, таблицы CSV, записка DOCX и протокол со ссылками на акты.",
        ),
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
        (x, y, 4.3, h),
        [
            para("Математическая оптимизация", Style(X_BOLD, 18, WHITE)),
            para("вместо машинного обучения", Style(X_BOLD, 18, ROSE)),
        ],
        line=1.05,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    text(
        s,
        (x + 4.6, y, w - 4.6, h),
        [
            para(
                "В принятом плане Берзарина нормы отступов нарушены в 391 посадке из 554: обучать "
                "нейросеть на таких данных нельзя. Солвер MILP (HiGHS) строго соблюдает нормативные "
                "пороги, каждое дерево проверяемо. Локальная языковая модель только подсказывает "
                "класс незнакомого слоя.",
                Style(MEDIUM, 12, MIST),
            )
        ],
        line=1.2,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    notes(
        s, "Семь шагов конвейера. Ключевое: генерация и проверка разделены, проверка независимая."
    )


def s_explain(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 1, "Проверка норм для каждого растения")
    shot(
        s,
        "explain-map.png",
        cell(0, 4, 0, 6),
        Crop((0.3, 0.5), 1.3, (0.5, 0.5)),
        "Выноска: замер до сети",
    )
    shot(s, "explain-card.png", cell(4, 3, 0, 6), Crop((0.5, 0.0)))
    note(
        s,
        cell(7, 5, 0, 2),
        "Наглядные замеры на плане и в карточке",
        "Сервис рассчитывает расстояние до сетей (теплосеть: факт 3,47 м ≥ норма 2,50 м) и прикрепляет пункт документа с дословной цитатой.",
        eyebrow="посадка",
        head_size=12.5,
        body_size=10.5,
    )
    note(
        s,
        cell(7, 5, 2, 2),
        "Аргументированное выявление нарушений",
        "Отказ со ссылкой на регламент: «до силового кабеля 0,51 м при норме 2,00 м» (R-POWER-TREE-001, СП 42.13330.2016, п. 9.6, табл. 9.1).",
        eyebrow="отказ",
        head_size=12.5,
        body_size=10.5,
    )
    stat(
        s,
        cell(7, 5, 4, 2),
        f"{f['rules_total']} правил · {f['acts']} актов",
        f"Без «галлюцинаций»: в базе {f['rules_total']} правил из {f['acts']} нормативных актов. Формулировки собирает строгий алгоритм, а не нейросеть: результат детерминирован и проверяем.",
        kind=ACCENT,
        size=22,
        label_size=10,
    )
    notes(s, "Интерпретируемость: у каждой посадки и отказа замер, правило, акт, пункт, цитата.")


# --------------------------------------------------------------------------- 02 маркетинг


def s_users(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 2, "Кому нужен сервис")
    box = cell(0, 5, 0, 3)
    card(s, box, DEEP)
    x, y, w, h = inset(box, 0.28)
    text(
        s,
        (x, y, w, h),
        [
            para("1 · ПРОЕКТИРОВЩИК БЛАГОУСТРОЙСТВА", Style(SEMI, 9.5, ROSE)),
            para(f"{f['minutes_median']} мин", Style(X_BOLD, 36, WHITE)),
            para("Скорость: медиана на улицу", Style(SEMI, 12, ROSE)),
            para(
                "Загружает чертёж, автоматически получает схему посадок, вносит правки в "
                "веб-интерфейсе и возвращает результат в привычный CAD.",
                Style(MEDIUM, 11, MIST),
            ),
        ],
        line=1.12,
        after=4,
    )
    roles = (
        (
            cell(5, 4, 0, 3),
            "2 · Специалист ДПиООС",
            (
                "Автоматически проверяет отступы от сетей и нормативную базу. За минуты "
                "проверяет готовые чертежи подрядчиков перед согласованием."
            ),
            "Контроль: аудит каждой посадки",
        ),
        (
            cell(9, 3, 0, 3),
            "3 · Согласующие ведомства",
            "Оценивают баланс и объёмы озеленения, ведомость, записку DOCX и будущий облик улицы в интерактивном 3D-виде.",
            "Наглядность: ведомость и 3D",
        ),
    )
    for b, head, body, metric in roles:
        card(s, b, LIGHT)
        x, y, w, h = inset(b)
        text(
            s,
            (x, y, w, h - 0.6),
            [para(head.upper(), Style(SEMI, 9.5, NIGHT)), para(body, Style(MEDIUM, 11, BODY))],
            line=1.15,
            after=6,
        )
        text(
            s,
            (x, y + h - 0.5, w, 0.5),
            [para(metric, Style(X_BOLD, 12.5, PINK))],
            anchor=MSO_ANCHOR.BOTTOM,
        )
    quotes = (
        (
            "Топ-1 и Топ-2",
            "главные причины возврата проектов: нарушение отступов от сетей и ошибки в объёмах посадок",
        ),
        (
            "0",
            "свободная ниша: у заказчика не было попыток автоматизировать проектирование озеленения",
        ),
        ("DXF", "работа в стандартном AutoCAD без плагинов: результат - в обычных слоях чертежа"),
        (
            "до 60 мин",
            f"ориентир на генерацию плана улицы, до 30 мин на подбор мест; сервис - {f['minutes_median']} мин",
        ),
    )
    for i, (big, label) in enumerate(quotes):
        b = cell(i * 3, 3, 3, 3)
        card(s, b, SOFT)
        x, y, w, h = inset(b, 0.2)
        text(s, (x, y, w, 0.25), [para("ВАЛИДАЦИЯ БОЛЕЙ ЗАКАЗЧИКА", Style(SEMI, 9, PLUM))])
        text(
            s,
            (x, y + 0.26, w, h - 0.26),
            [para(big, Style(X_BOLD, 22, PINK)), para(label, Style(MEDIUM, 11, BODY))],
            line=1.15,
            after=2,
        )
    notes(
        s,
        "Три пользователя из ТЗ, у каждого свой вход. Ниже - ответы заказчика (docs/notes/15): "
        "главная боль - отступы, автоматизации не было, нужен обычный DXF.",
    )


def s_audit(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 2, "Распределение 785 нарушений по типам объектов")
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
                "На одну посадку может приходиться несколько нарушений",
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
    s = new_slide(prs, 2, "3D-визуализация и фотореализм", bg="dark")
    # 3D-вид в ТЗ не просили, фото ИИ - бонус ТЗ: жюри видит это до того, как читает слайд.
    w = 0.45 + len(VISUAL_CHIP) * 0.098
    chip = rect(s, (SLIDE_W - MARGIN - w, 1.12, w, 0.4), LAV, radius=0.2)
    fill_frame(
        chip.text_frame,
        [para(VISUAL_CHIP, Style(SEMI, 10.5, WHITE))],
        align=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    chip.text_frame.word_wrap = False
    # главная карточка - фото ИИ; рядом город вокруг и пульт, под ними что настраивается
    (photo, photo_crop, photo_label), city, panel = VISUAL_TOP
    shot(s, photo, cell(0, 5, 0, 4), photo_crop, photo_label, dark=True)
    shot(s, city[0], cell(5, 4, 0, 2), city[1], city[2], dark=True)
    shot(s, panel[0], cell(9, 3, 0, 2), panel[1], panel[2], dark=True)
    box = cell(5, 7, 2, 2)
    card(s, box, GLASS)
    text(
        s,
        inset(box, 0.2),
        [
            [(VISUAL_PANEL[0], Style(SEMI, 10, WHITE)), (VISUAL_PANEL[1], Style(MEDIUM, 10, MIST))],
            para(VISUAL_SCENE, Style(MEDIUM, 10, MIST)),
        ],
        line=1.1,
        after=3,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    # нижняя полоса: семь кадров одного ракурса - сезоны, ночь, возраст посадок
    x0, y0, strip_w, strip_h = cell(0, 12, 4, 2)
    tw = (strip_w - (len(VISUAL_TILES) - 1) * GAP) / len(VISUAL_TILES)
    for i, (name, label) in enumerate(VISUAL_TILES):
        shot(s, name, (x0 + i * (tw + GAP), y0, tw, strip_h), tile_crop(name), label, dark=True)
    notes(s, VISUAL_NOTES)


# --------------------------------------------------------------------------- 03 бизнес


def s_city(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 3, "Эффект внедрения для города")
    for i, (big, label) in enumerate(city_cards(f)):
        stat(s, cell(i * 3, 3, 0, 2), big, label, size=26, label_size=10.5)
    # главная карточка - экономия в рублях: три колонки по два числа
    box = cell(0, 12, 2, 3)
    card(s, box, DEEP)
    x, y, w, _ = inset(box, 0.3)
    text(s, (x, y - 0.06, w, 0.32), [para(CITY_ECON_HEAD, Style(SEMI, 13, ROSE))])
    cw = (w - 2 * 0.4) / 3
    for i, (head, rows) in enumerate(CITY_ECON):
        cx = x + i * (cw + 0.4)
        text(s, (cx, y + 0.36, cw, 0.3), [para(head.upper(), Style(SEMI, 10, WHITE))])
        for j, (big, sub) in enumerate(rows):
            ry = y + 0.7 + j * 0.74
            text(s, (cx, ry, cw, 0.38), [para(big, Style(X_BOLD, 18, WHITE))])
            text(s, (cx, ry + 0.36, cw, 0.32), [para(sub, Style(MEDIUM, 10, MIST))], line=1.05)
    text(
        s,
        cell(0, 12, 5, 1),
        [
            para(CITY_ASSUMPTIONS, Style(MEDIUM, 9, MUTE)),
            para(CITY_SOURCES, Style(MEDIUM, 9, MUTE)),
        ],
        line=1.05,
        after=2,
    )
    notes(s, city_notes(f))


def s_effect(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 3, "Экологический эффект: тень и защита от пыли", bg="dark")
    top = sorted(street_curbs(), key=lambda r: r[2] - r[1], reverse=True)[:7]
    box = cell(0, 6, 0, 6)
    card(s, box, GLASS)
    x, y, w, h = inset(box)
    text(
        s,
        (x, y, w, 0.6),
        [
            [
                ("Борта под кронами и кустарником, %: ", Style(SEMI, 11.5, WHITE)),
                ("было", Style(SEMI, 11.5, LAV)),
                (" и ", Style(SEMI, 11.5, WHITE)),
                ("с планом сервиса", Style(SEMI, 11.5, ROSE)),
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
    (trees, trees_l), (curb, curb_l), (canopy, canopy_l), (tiers, tiers_l) = effect_stats(f)
    stat(s, cell(6, 6, 0, 2), curb, curb_l, kind=ACCENT, size=26, label_size=10.5)
    stat(s, cell(6, 6, 2, 2), trees, trees_l, kind=GLASS, size=24, label_size=10.5)
    stat(s, cell(6, 3, 4, 2), canopy, canopy_l, kind=GLASS, size=18, label_size=10)
    stat(s, cell(9, 3, 4, 2), tiers, tiers_l, kind=GLASS, size=16, label_size=10)
    notes(
        s,
        "Эффект для города: тень, пылезащита, ярусность - то, что заказчик назвал признаками хорошего плана.",
    )


# --------------------------------------------------------------------------- 04 техника


def s_deploy(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 4, "Архитектура: единое ядро и гибкие интерфейсы", bg="dark")
    for box, (head, sub) in zip(
        (cell(0, 2, 0, 2), cell(2, 2, 0, 2), cell(4, 3, 0, 2)),
        (
            ("CLI", "пакетная обработка улиц, аудит чужих чертежей"),
            ("REST API", "OpenAPI 3.1, Swagger для интеграции с ГИС"),
            ("Веб-интерфейс", "React: просмотр и правка плана, 3D и фото"),
        ),
        strict=True,
    ):
        note(
            s,
            box,
            head,
            sub,
            kind=GLASS,
            head_size=14,
            body_size=10,
            anchor=MSO_ANCHOR.TOP,
        )
    b = card(s, cell(0, 7, 2, 1), ACCENT)
    fill_frame(
        b.text_frame,
        [
            [
                ("Единое ядро:  ", Style(X_BOLD, 13, WHITE)),
                ("общие правила и алгоритмы для всех интерфейсов", Style(MEDIUM, 11.5, WHITE)),
            ]
        ],
        anchor=MSO_ANCHOR.MIDDLE,
    )
    b.text_frame.margin_left = Inches(PAD)
    code = rect(s, cell(0, 7, 3, 1), "000000", radius=R)
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
        f"Тесты бэкенда и фронтенда; покрытие строк {COVER_BACKEND} и {COVER_FRONTEND}",
        kind=GLASS,
        size=20,
        label_size=10.5,
    )
    note(
        s,
        cell(3, 4, 4, 2),
        f"{f['params']} параметров",
        (
            "5 профилей. Образ на Ubuntu 26.04: по ТЗ МосТех.ОС близка к Ubuntu; ODA File Converter - аргументом сборки.",
            "Ollama для подсказок - профиль llm в compose. Манифесты Kubernetes проверены kubeconform.",
        ),
        kind=GLASS,
        head_size=13,
        body_size=9,
    )
    shot(
        s,
        "swagger.png",
        cell(7, 5, 0, 6),
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
    s = new_slide(prs, 4, "Результаты пилота на реальных данных")
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
        "улиц каталога с планом; Фрунзенская собрана из PDF-генплана, DWG у неё нет",
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
        cell(0, 4, 0, 6),
        Crop((0.12, 0.0)),
        "Уточнение объектов чертежа: класс каждого слоя и основание",
    )
    (head, body), *rest = INPUT_ITEMS
    note(s, cell(4, 8, 0, 2), head, body, kind=ACCENT, head_size=14, body_size=11)
    for i, (head, body) in enumerate(rest):
        note(
            s,
            cell(4 + (i % 2) * 4, 4, 2 + (i // 2) * 2, 2),
            head,
            body,
            head_size=12.5,
            body_size=10.5,
        )
    notes(s, INPUT_NOTES)


def s_workspace(prs: Deck, f: dict[str, str]) -> None:
    s = new_slide(prs, 4, "Рабочее место в браузере")
    home, work, *small = workspace_tiles(f)
    # главная карточка - план с замерами; вокруг пять экранов того же рабочего места
    shot(s, work[0], cell(0, 6, 0, 4), work[1], work[2])
    boxes = (
        cell(6, 3, 0, 2),
        cell(9, 3, 0, 2),
        cell(6, 3, 2, 2),
        cell(9, 3, 2, 2),
        cell(0, 3, 4, 2),
    )
    for (name, crop, label), box in zip((home, *small), boxes, strict=True):
        picture(s, name, box, crop, radius=R, shadow=False, border=BLUSH)
        caption(s, box, label)
    box = cell(3, 9, 4, 2)
    card(s, box, ACCENT)
    text(
        s,
        inset(box, 0.3),
        [
            para("ПРАВКА ПЛАНА", Style(SEMI, 9.5, WHITE)),
            para(WORKSPACE_FOOT, Style(X_BOLD, 15, WHITE)),
        ],
        line=1.15,
        after=4,
        anchor=MSO_ANCHOR.MIDDLE,
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
                "Каждая посадка и каждый отказ - с замером, кодом проверки и цитатой из акта. "
                "Текст собирает детерминированный алгоритм, без LLM.",
                Style(MEDIUM, 11.5, WHITE),
            ),
        ],
        line=1.12,
        after=6,
    )
    small = (
        (
            cell(8, 4, 0, 3),
            "Нормы в YAML",
            "Обновление норм без релиза",
            "Правила, коэффициенты и профили (включая прикорневые барьеры по СП 42) вынесены в YAML. Новая редакция норм действует без пересборки Docker-образа.",
        ),
        (
            cell(4, 4, 0, 2),
            f"{f['violations']} нарушений",
            "Двухконтурный аудит",
            f"Готовый план повторно проверяется всеми правилами. Тот же нормоконтроль нашёл в принятом плане Берзарина {AUDIT_BAD} из {AUDIT_ALL} посадок с нарушениями.",
        ),
        (
            cell(4, 4, 4, 2),
            f"{f['species']} видов",
            "Вид под место",
            "Задача MILP подбирает породу по условиям места: соль у проезда, свет, сети рядом, квоты на разнообразие пород.",
        ),
        (
            cell(4, 4, 2, 2),
            f"{f['entities_changed']} из {f['entities']}",
            "Гарантия неизменности CAD",
            "Новое пишется только в слои GREEN_*. Каждый примитив исходной подосновы сверяется по хэшу blake2b до и после записи.",
        ),
        (
            cell(8, 4, 3, 3),
            "Один план",
            "DXF, 3D, фото и отчёты",
            "Проектировщик получает CAD-слои, согласующий - отчёт HTML и Markdown с нормами, жители - 3D-сцену. Всё строится из одного проверенного плана.",
        ),
    )
    for b, metric, head, body in small:
        card(s, b, GLASS)
        x, y, w, h = inset(b, 0.2)
        text(
            s,
            (x, y, w, h),
            [
                para(metric, Style(X_BOLD, 16, ROSE)),
                para(head, Style(SEMI, 12.5, WHITE)),
                para(body, Style(MEDIUM, 9.5, MIST)),
            ],
            line=1.06,
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
                "образ Docker на МосТех.ОС, работает без интернета",
                "проектировщики получают черновик улицы с объяснениями",
                "нормоконтроль проектов подрядчиков по запуску команды green audit",
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
