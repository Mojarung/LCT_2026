"""Отметки нормоконтроля в копии исходного DXF: только новые слои GREEN_AUDIT_*."""

from __future__ import annotations

from typing import TYPE_CHECKING

from green.application.explain import citation_text
from green.application.results import SourceSnapshot
from green.domain.planting import Verdict
from green.infrastructure.cad.documents import APPID, RESULT_PREFIX, load_document
from green.infrastructure.cad.integrity import fingerprints

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ezdxf.document import Drawing
    from ezdxf.layouts import Modelspace

    from green.application.audit import AuditedPlanting
    from green.domain.norms import RuleBook
    from green.infrastructure.cad.documents import DocumentCache

TEXT_STYLE = f"{RESULT_PREFIX}TEXT"
LAYER_VIOLATION = f"{RESULT_PREFIX}AUDIT_VIOLATION"
LAYER_BARRIER = f"{RESULT_PREFIX}AUDIT_BARRIER"
LAYER_APPROVAL = f"{RESULT_PREFIX}AUDIT_APPROVAL"
LAYER_OK = f"{RESULT_PREFIX}AUDIT_OK"
LAYER_LABELS = f"{RESULT_PREFIX}AUDIT_LABELS"
AUDIT_LAYER_COLORS = {
    LAYER_VIOLATION: 1,
    LAYER_BARRIER: 4,
    LAYER_APPROVAL: 30,
    LAYER_OK: 3,
    LAYER_LABELS: 7,
}
MARK_BLOCK = f"{RESULT_PREFIX}AUDIT_MARK"
OK_BLOCK = f"{RESULT_PREFIX}AUDIT_OK_MARK"
XDATA_CHUNK = 240
MARK_RADIUS_M = 1.0
OK_RADIUS_M = 0.4


class EzdxfAuditWriter:
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
        plantings: Sequence[AuditedPlanting],
        rulebook: RuleBook,
        target: Path,
        *,
        unit_m: float = 1.0,
    ) -> SourceSnapshot:
        """Отметка на каждую посадку: нарушение, условие барьера, согласование или «в норме»."""
        doc, _ = self._documents.take(source) if self._documents else load_document(source)
        added = self._documents.added_since_load(doc) if self._documents else frozenset()
        digests, unexportable = fingerprints(doc)
        digests = {handle: value for handle, value in digests.items() if handle not in added}
        self._prepare(doc)
        scale = 1.0 / unit_m
        msp = doc.modelspace()
        for planting in plantings:
            self._mark(msp, planting, scale)
        self._legend(msp, plantings, rulebook, scale)
        target.parent.mkdir(parents=True, exist_ok=True)
        doc.saveas(target)
        return SourceSnapshot(digests, unexportable)

    def _prepare(self, doc: Drawing) -> None:
        if APPID not in doc.appids:
            doc.appids.add(APPID)
        for name, color in AUDIT_LAYER_COLORS.items():
            if name not in doc.layers:
                doc.layers.add(name, color=color)
        if TEXT_STYLE not in doc.styles:
            doc.styles.add(TEXT_STYLE, font=self._font)
        attribs = {"height": self._height, "style": TEXT_STYLE}
        if MARK_BLOCK not in doc.blocks:
            block = doc.blocks.new(MARK_BLOCK)
            block.add_circle((0, 0), radius=MARK_RADIUS_M)
            block.add_line((-MARK_RADIUS_M, -MARK_RADIUS_M), (MARK_RADIUS_M, MARK_RADIUS_M))
            block.add_line((-MARK_RADIUS_M, MARK_RADIUS_M), (MARK_RADIUS_M, -MARK_RADIUS_M))
            block.add_attdef("NUM", (MARK_RADIUS_M + 0.2, 0.2), dxfattribs=attribs)
            block.add_attdef("NPA", (MARK_RADIUS_M + 0.2, -0.2 - self._height), dxfattribs=attribs)
        if OK_BLOCK not in doc.blocks:
            block = doc.blocks.new(OK_BLOCK)
            block.add_circle((0, 0), radius=OK_RADIUS_M)
            block.add_attdef("NUM", (OK_RADIUS_M + 0.1, 0.1), dxfattribs={**attribs, "flags": 1})

    def _mark(self, msp: Modelspace, planting: AuditedPlanting, scale: float) -> None:
        layer, block = _appearance(planting)
        ref = msp.add_blockref(
            block,
            (planting.x * scale, planting.y * scale),
            dxfattribs={"layer": layer, **_insert_scale(scale)},
        )
        listed = planting.violations or planting.with_barrier
        values = {"NUM": str(planting.number)}
        if block == MARK_BLOCK:
            values["NPA"] = "; ".join(c.rule_id for c in listed)
        ref.add_auto_attribs(values)
        for attrib in ref.attribs:
            attrib.dxf.layer = LAYER_LABELS
        rule_ids = ";".join(c.rule_id for c in listed)
        ref.set_xdata(
            APPID,
            [
                (1000, f"audit-{planting.number}"),
                (1000, planting.verdict.value),
                (1000, str(planting.ref)),
                *(
                    (1000, rule_ids[i : i + XDATA_CHUNK])
                    for i in range(0, len(rule_ids), XDATA_CHUNK)
                ),
            ],
        )

    def _legend(
        self,
        msp: Modelspace,
        plantings: Sequence[AuditedPlanting],
        rulebook: RuleBook,
        scale: float,
    ) -> None:
        if not plantings:
            return
        violating = [p for p in plantings if p.violations]
        lines = [
            "Нормоконтроль сервиса green: слои GREEN_AUDIT_*.",
            f"Посадок проверено: {len(plantings)}, с нарушением отступов: {len(violating)}.",
            "Нарушенные правила:",
        ]
        used = sorted({c.rule_id for p in violating for c in p.violations})
        for rule_id in used:
            rule = rulebook.rule(rule_id)
            if rule is not None:
                lines.append(f"{rule_id}: {citation_text(rule, rulebook)}")
        mtext = msp.add_mtext(
            "\\P".join(lines),
            dxfattribs={
                "layer": LAYER_LABELS,
                "style": TEXT_STYLE,
                "char_height": self._height * 2 * scale,
            },
        )
        x = min(p.x for p in plantings)
        y = max(p.y for p in plantings) + 10 * self._height
        mtext.set_location((x * scale, y * scale))


def _appearance(planting: AuditedPlanting) -> tuple[str, str]:
    if planting.violations:
        return LAYER_VIOLATION, MARK_BLOCK
    if planting.with_barrier:
        return LAYER_BARRIER, MARK_BLOCK
    if planting.approvals or planting.verdict is Verdict.NEEDS_APPROVAL:
        return LAYER_APPROVAL, OK_BLOCK
    return LAYER_OK, OK_BLOCK


def _insert_scale(scale: float) -> dict[str, float]:
    if scale == 1.0:
        return {}
    return {"xscale": scale, "yscale": scale, "zscale": scale}
