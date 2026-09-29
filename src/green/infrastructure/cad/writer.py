"""Запись плана в копию исходного DXF: только новые слои GREEN_*, блоки и XDATA."""

from __future__ import annotations

from typing import TYPE_CHECKING

import shapely
from ezdxf.lldxf.const import BOUNDARY_PATH_DEFAULT, BOUNDARY_PATH_EXTERNAL

from green.application.barriers import BARRIER_NOTE
from green.application.explain import LAWN_LABELS, citation_text
from green.application.results import SourceSnapshot
from green.application.schedule import build_schedule
from green.domain.norms import LawnKind
from green.domain.planting import CheckOutcome, Verdict
from green.infrastructure.cad.documents import APPID, RESULT_PREFIX, load_document
from green.infrastructure.cad.integrity import fingerprints

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from ezdxf.document import Drawing
    from ezdxf.layouts import Modelspace

    from green.application.schedule import ScheduleRow
    from green.domain.norms import RuleBook
    from green.domain.planting import (
        Lawn,
        Placement,
        Plan,
        Rejection,
        RuleCheck,
        Species,
        Zone,
    )
    from green.infrastructure.cad.documents import DocumentCache

TEXT_STYLE = f"{RESULT_PREFIX}TEXT"
LAYER_TREES = f"{RESULT_PREFIX}TREES"
LAYER_TREES_APPROVAL = f"{RESULT_PREFIX}TREES_APPROVAL"
LAYER_TREES_BARRIER = f"{RESULT_PREFIX}TREES_BARRIER"
LAYER_SHRUBS = f"{RESULT_PREFIX}SHRUBS"
LAYER_SHRUBS_APPROVAL = f"{RESULT_PREFIX}SHRUBS_APPROVAL"
LAYER_REJECT = f"{RESULT_PREFIX}REJECT"
LAYER_LABELS = f"{RESULT_PREFIX}LABELS"
LAYER_ZONE_ALLOWED = f"{RESULT_PREFIX}ZONE_ALLOWED"
LAYER_ZONE_APPROVAL = f"{RESULT_PREFIX}ZONE_APPROVAL"
LAYER_LAWN = f"{RESULT_PREFIX}LAWN"
# Ведомость элементов озеленения (ГОСТ 21.508-2020, п. 10.8, форма 9) таблицей рядом с планом.
LAYER_SCHEDULE = f"{RESULT_PREFIX}SCHEDULE"
REJECT_BLOCK = f"{RESULT_PREFIX}REJECT_MARK"
LAYER_COLORS = {
    LAYER_TREES: 3,
    LAYER_TREES_APPROVAL: 30,
    LAYER_TREES_BARRIER: 4,
    LAYER_SHRUBS: 94,
    LAYER_SHRUBS_APPROVAL: 40,
    LAYER_REJECT: 1,
    LAYER_LABELS: 7,
    LAYER_ZONE_ALLOWED: 3,
    LAYER_ZONE_APPROVAL: 30,
    LAYER_LAWN: 82,
    LAYER_SCHEDULE: 7,
}
ZONE_LAYERS = {Verdict.ALLOWED: LAYER_ZONE_ALLOWED, Verdict.NEEDS_APPROVAL: LAYER_ZONE_APPROVAL}
ZONE_TRANSPARENCY = 0.7
# Газон - условное обозначение (ГОСТ 21.508-2020, п. 10.4), а не заливка: травяной узор GRASS из
# acad.pat не закрывает подоснову под собой. Узор описан в своих единицах, масштаб в метрах
# чертежа даёт пучок травы 0,4 м через 2 м. Устраиваемый газон отличается цветом.
LAWN_PATTERN = "GRASS"
LAWN_PATTERN_SCALE_M = 0.08
LAWN_COLORS = {LawnKind.KEPT: 82, LawnKind.NEW: 52}
XDATA_CHUNK = 240
XDATA_REAL = 1040
NPA_REFS = 2
NPA_MAX = 250  # длиннее значение атрибута старые просмотрщики режут
# Отметка отказа - крест 1 x 1 м в метрах чертежа.
REJECT_HALF_M = 0.5
# Лист результата в высотах текста таблицы: ведомость правее габарита плана, легенда правил
# колонкой заданной ширины правее ведомости - ни одна из них не ложится на план.
SCHEDULE_GAP_HEIGHTS = 20.0
LEGEND_GAP_HEIGHTS = 5.0
LEGEND_WIDTH_HEIGHTS = 70.0
MTEXT_TOP_LEFT = 1
# Столбцы ведомости: заголовок и ширина в высотах текста.
SCHEDULE_COLUMNS = (
    ("Поз.", 4.0),
    ("Наименование породы или вида", 26.0),
    ("Кол-во, шт.", 9.0),
    ("Примечание", 30.0),
)


class EzdxfPlanWriter:
    def __init__(
        self,
        *,
        text_font: str,
        label_height_m: float = 0.5,
        documents: DocumentCache | None = None,
    ) -> None:
        self._font = text_font
        self._height = label_height_m
        self._documents = documents

    def write(
        self,
        source: Path,
        plan: Plan,
        rulebook: RuleBook,
        target: Path,
        *,
        unit_m: float = 1.0,
    ) -> SourceSnapshot:
        """Пишет результат в копию исходника, возвращает отпечатки исходных сущностей до правок.

        План в метрах, чертёж может быть в миллиметрах: координаты делятся на unit_m, блоки
        описаны в метрах и вставляются с масштабом 1 / unit_m.
        """
        scale = 1.0 / unit_m
        doc, _ = self._documents.take(source) if self._documents else load_document(source)
        added = self._documents.added_since_load(doc) if self._documents else frozenset()
        digests, unexportable = fingerprints(doc)
        # Сущность, появившаяся после загрузки, исходной не считается: проверка целостности
        # найдёт её в результате и назовёт добавленной вне слоёв GREEN_*.
        digests = {handle: value for handle, value in digests.items() if handle not in added}
        snapshot = SourceSnapshot(digests, unexportable)
        self._prepare(doc)
        msp = doc.modelspace()
        rows = build_schedule(plan.placements)
        positions = {row.code: str(row.number) for row in rows}
        for zone in plan.zones:
            self._zone(msp, zone, scale)
        for lawn in plan.lawns:
            self._lawn(msp, lawn, scale)
        for placement in plan.placements:
            position = positions.get(placement.species.code, "")
            self._placement(doc, msp, placement, position, scale=scale, rulebook=rulebook)
        for rejection in plan.rejections:
            self._rejection(msp, rejection, scale)
        extent = plan_extent(plan)
        if extent is not None:
            left = self._schedule(msp, rows, extent, scale)
            self._legend(msp, plan, rulebook, (left, extent[3] * scale), scale)
        target.parent.mkdir(parents=True, exist_ok=True)
        doc.saveas(target)
        return snapshot

    def _prepare(self, doc: Drawing) -> None:
        if APPID not in doc.appids:
            doc.appids.add(APPID)
        for name, color in LAYER_COLORS.items():
            if name not in doc.layers:
                doc.layers.add(name, color=color)
        if TEXT_STYLE not in doc.styles:
            doc.styles.add(TEXT_STYLE, font=self._font)
        if REJECT_BLOCK not in doc.blocks:
            block = doc.blocks.new(REJECT_BLOCK)
            half = REJECT_HALF_M
            block.add_line((-half, -half), (half, half))
            block.add_line((-half, half), (half, -half))
            block.add_attdef(
                "NUM", (0.6, 0.2), dxfattribs={"height": self._height, "style": TEXT_STYLE}
            )

    def _tree_block(self, doc: Drawing, species: Species) -> str:
        kind = "SHRUB" if species.is_shrub else "TREE"
        name = f"{RESULT_PREFIX}{kind}_{species.code.upper()}"
        if name not in doc.blocks:
            block = doc.blocks.new(name)
            block.add_circle((0, 0), radius=species.crown_diameter_m / 2)
            block.add_line((-0.3, 0), (0.3, 0))
            block.add_line((0, -0.3), (0, 0.3))
            # На плане видна только позиция ведомости, как у проектировщика (ГОСТ 21.508-2020,
            # форма 9): одна-две цифры у куста не наезжают на соседа при шаге 1 м. Номер, вид и
            # нормы остаются скрытыми атрибутами - по ним отчёт и сверка экспорта связывают
            # вставку с объяснением.
            attribs = {"height": self._height, "style": TEXT_STYLE}
            hidden = {**attribs, "flags": 1}
            block.add_attdef("POS", (0.4, 0.4), dxfattribs=attribs)
            block.add_attdef("NUM", (0.4, -0.4 - self._height), dxfattribs=hidden)
            block.add_attdef("SPECIES", (0.4, -0.8 - 2 * self._height), dxfattribs=hidden)
            block.add_attdef("NPA", (0.4, -1.2 - 3 * self._height), dxfattribs=hidden)
        return name

    def _placement(  # noqa: PLR0913 - позиция ведомости считается один раз на весь план
        self,
        doc: Drawing,
        msp: Modelspace,
        placement: Placement,
        position: str,
        *,
        scale: float,
        rulebook: RuleBook,
    ) -> None:
        allowed = placement.verdict is Verdict.ALLOWED
        if placement.species.is_shrub:
            layer = LAYER_SHRUBS if allowed else LAYER_SHRUBS_APPROVAL
        elif allowed and BARRIER_NOTE in placement.notes:
            layer = LAYER_TREES_BARRIER
        else:
            layer = LAYER_TREES if allowed else LAYER_TREES_APPROVAL
        ref = msp.add_blockref(
            self._tree_block(doc, placement.species),
            (placement.x * scale, placement.y * scale),
            dxfattribs={"layer": layer, **_insert_scale(scale)},
        )
        tightest = sorted(
            (c for c in placement.checks if c.measured_m is not None),
            key=lambda c: (c.measured_m or 0) - (c.threshold_m or 0),
        )[:NPA_REFS]
        ref.add_auto_attribs(
            {
                "POS": position,
                "NUM": str(placement.number),
                "SPECIES": placement.species.name_ru,
                "NPA": _npa(tightest, rulebook),
            }
        )
        for attrib in ref.attribs:
            attrib.dxf.layer = LAYER_LABELS
        rule_ids = ";".join(c.rule_id for c in placement.checks)
        ref.set_xdata(
            APPID,
            [
                (1000, placement.placement_id),
                (1000, placement.verdict.value),
                *(
                    (1000, rule_ids[i : i + XDATA_CHUNK])
                    for i in range(0, len(rule_ids), XDATA_CHUNK)
                ),
            ],
        )

    def _zone(self, msp: Modelspace, zone: Zone, scale: float) -> None:
        """Зона допустимости: сплошная полупрозрачная штриховка, по одной на каждый полигон."""
        layer = ZONE_LAYERS.get(zone.verdict)
        if layer is None:
            return
        color = LAYER_COLORS[layer]
        for polygon in shapely.get_parts(zone.geometry):
            if polygon.geom_type != "Polygon" or polygon.is_empty:
                continue
            hatch = msp.add_hatch(color=color, dxfattribs={"layer": layer})
            hatch.set_solid_fill(color=color)
            hatch.transparency = ZONE_TRANSPARENCY
            hatch.paths.add_polyline_path(
                _ring(polygon.exterior.coords, scale),
                is_closed=True,
                flags=BOUNDARY_PATH_EXTERNAL,
            )
            for ring in polygon.interiors:
                hatch.paths.add_polyline_path(
                    _ring(ring.coords, scale), is_closed=True, flags=BOUNDARY_PATH_DEFAULT
                )

    def _lawn(self, msp: Modelspace, lawn: Lawn, scale: float) -> None:
        """Участок газона: штриховка узором с отверстиями посадочных мест и XDATA решения."""
        color = LAWN_COLORS[lawn.kind]
        rule_ids = ";".join(lawn.rule_ids)
        for polygon in shapely.get_parts(lawn.geometry):
            if polygon.geom_type != "Polygon" or polygon.is_empty:
                continue
            hatch = msp.add_hatch(color=color, dxfattribs={"layer": LAYER_LAWN})
            hatch.set_pattern_fill(LAWN_PATTERN, color=color, scale=LAWN_PATTERN_SCALE_M * scale)
            hatch.paths.add_polyline_path(
                _ring(polygon.exterior.coords, scale),
                is_closed=True,
                flags=BOUNDARY_PATH_EXTERNAL,
            )
            for ring in polygon.interiors:
                hatch.paths.add_polyline_path(
                    _ring(ring.coords, scale), is_closed=True, flags=BOUNDARY_PATH_DEFAULT
                )
            hatch.set_xdata(
                APPID,
                [
                    (1000, lawn.lawn_id),
                    (1000, lawn.kind.value),
                    (XDATA_REAL, round(float(polygon.area), 2)),
                    *(
                        (1000, rule_ids[i : i + XDATA_CHUNK])
                        for i in range(0, len(rule_ids), XDATA_CHUNK)
                    ),
                ],
            )

    def _rejection(self, msp: Modelspace, rejection: Rejection, scale: float) -> None:
        ref = msp.add_blockref(
            REJECT_BLOCK,
            (rejection.x * scale, rejection.y * scale),
            dxfattribs={"layer": LAYER_REJECT, **_insert_scale(scale)},
        )
        ref.add_auto_attribs({"NUM": str(rejection.number)})
        for attrib in ref.attribs:
            attrib.dxf.layer = LAYER_LABELS
        failed = ";".join(
            c.rule_id for c in rejection.blocking if c.outcome is not CheckOutcome.PASS
        )
        ref.set_xdata(
            APPID,
            [
                (1000, rejection.rejection_id),
                (1000, rejection.verdict.value),
                (1000, failed[:XDATA_CHUNK]),
            ],
        )

    def _legend(
        self,
        msp: Modelspace,
        plan: Plan,
        rulebook: RuleBook,
        corner: tuple[float, float],
        scale: float,
    ) -> None:
        """Легенда правил колонкой заданной ширины; corner - левый край колонки и верх плана
        в единицах чертежа."""
        used = sorted({c.rule_id for p in plan.placements for c in p.checks})
        used += sorted({c.rule_id for r in plan.rejections for c in r.blocking} - set(used))
        used += sorted({rule_id for lawn in plan.lawns for rule_id in lawn.rule_ids} - set(used))
        lines = ["Результат сервиса green: слои GREEN_*. Правила:"]
        for rule_id in used:
            rule = rulebook.rule(rule_id)
            if rule is not None:
                lines.append(f"{rule_id}: {citation_text(rule, rulebook)}")
        if plan.lawns:
            totals = {
                kind: sum(g.area_m2 for g in plan.lawns if g.kind is kind) for kind in LawnKind
            }
            areas = ", ".join(f"{LAWN_LABELS[k]} {_area(a)}" for k, a in totals.items() if a > 0)
            lines.append(f"Газоны {LAYER_LAWN}, м²: {areas}.")
        height = self._height * 2 * scale
        mtext = msp.add_mtext(
            "\\P".join(lines),
            dxfattribs={
                "layer": LAYER_LABELS,
                "style": TEXT_STYLE,
                "char_height": height,
                # Ширина колонки: CAD переносит длинные цитаты внутри неё, а не тянет строку
                # на десятки метров поверх чертежа.
                "width": LEGEND_WIDTH_HEIGHTS * height,
            },
        )
        left, top = corner
        mtext.set_location((left, top + 2 * height), attachment_point=MTEXT_TOP_LEFT)

    def _schedule(
        self,
        msp: Modelspace,
        rows: Sequence[ScheduleRow],
        extent: tuple[float, float, float, float],
        scale: float,
    ) -> float:
        """Ведомость элементов озеленения таблицей справа от габарита плана: поз., порода или
        вид, количество, стандарт посадочного материала (ГОСТ 21.508-2020, п. 10.8, форма 9).

        Возвращает левый край места под легенду в единицах чертежа: правее таблицы, а без
        строк ведомости - правее плана.
        """
        height = self._height * 2 * scale
        x0 = extent[2] * scale + SCHEDULE_GAP_HEIGHTS * height
        if not rows:
            return x0
        step = height * 2
        y0 = extent[3] * scale
        widths = [w * height for _, w in SCHEDULE_COLUMNS]
        right = x0 + sum(widths)
        attribs = {"layer": LAYER_SCHEDULE, "style": TEXT_STYLE, "height": height}
        msp.add_text("Ведомость элементов озеленения", dxfattribs=attribs).set_placement(
            (x0, y0 + height)
        )
        table = [
            [title for title, _ in SCHEDULE_COLUMNS],
            *(
                [
                    str(row.number),
                    row.name_ru,
                    str(row.count),
                    f"{row.stock.group}, ком {row.stock.ball}",
                ]
                for row in rows
            ),
        ]
        y = y0
        msp.add_line((x0, y), (right, y), dxfattribs={"layer": LAYER_SCHEDULE})
        for cells in table:
            x = x0
            for text, width in zip(cells, widths, strict=True):
                msp.add_text(text, dxfattribs=attribs).set_placement(
                    (x + height * 0.4, y - step + height * 0.5)
                )
                x += width
            y -= step
            msp.add_line((x0, y), (right, y), dxfattribs={"layer": LAYER_SCHEDULE})
        x = x0
        for width in (0.0, *widths):
            x += width
            msp.add_line((x, y0), (x, y), dxfattribs={"layer": LAYER_SCHEDULE})
        return right + LEGEND_GAP_HEIGHTS * height


def plan_extent(plan: Plan) -> tuple[float, float, float, float] | None:
    """Габарит всего, что план рисует, в метрах (min_x, min_y, max_x, max_y): кроны посадок,
    отметки всех отказов, зоны допустимости и газоны. None - план пуст."""
    boxes = [
        (p.x - r, p.y - r, p.x + r, p.y + r)
        for p in plan.placements
        for r in (p.species.crown_diameter_m / 2,)
    ]
    half = REJECT_HALF_M
    boxes += [(r.x - half, r.y - half, r.x + half, r.y + half) for r in plan.rejections]
    for item in (*plan.zones, *plan.lawns):
        if not item.geometry.is_empty:
            min_x, min_y, max_x, max_y = item.geometry.bounds
            boxes.append((float(min_x), float(min_y), float(max_x), float(max_y)))
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _npa(checks: Sequence[RuleCheck], rulebook: RuleBook) -> str:
    """Определяющие нормы посадки: правило, акт и пункт - без обращения к легенде."""
    parts = []
    for check in checks:
        rule = rulebook.rule(check.rule_id)
        if rule is None:
            parts.append(check.rule_id)
            continue
        clause = rule.citation.clause.split(":")[0].strip()
        parts.append(f"{check.rule_id} ({rulebook.label_of(rule.citation.act_id)}, {clause})")
    text = "; ".join(parts)
    return text if len(text) <= NPA_MAX else text[: NPA_MAX - 1] + "…"


def _insert_scale(scale: float) -> dict[str, float]:
    """Блоки описаны в метрах: в чертеже с другой единицей вставка несёт масштаб."""
    if scale == 1.0:
        return {}
    return {"xscale": scale, "yscale": scale, "zscale": scale}


def _ring(coords: Iterable[Sequence[float]], scale: float) -> list[tuple[float, float]]:
    return [(point[0] * scale, point[1] * scale) for point in coords]


def _area(value: float) -> str:
    return f"{value:,.1f}".replace(",", " ").replace(".", ",")
