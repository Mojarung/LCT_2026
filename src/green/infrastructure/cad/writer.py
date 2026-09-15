"""Запись плана в копию исходного DXF: только новые слои GREEN_*, блоки и XDATA."""

from __future__ import annotations

from typing import TYPE_CHECKING

from green.application.explain import citation_text
from green.application.results import SourceSnapshot
from green.domain.planting import CheckOutcome, Verdict
from green.infrastructure.cad.documents import APPID, RESULT_PREFIX, load_document
from green.infrastructure.cad.integrity import fingerprints

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.document import Drawing
    from ezdxf.layouts import Modelspace

    from green.domain.norms import RuleBook
    from green.domain.planting import Placement, Plan, Rejection, Species
    from green.infrastructure.cad.documents import DocumentCache

TEXT_STYLE = f"{RESULT_PREFIX}TEXT"
LAYER_TREES = f"{RESULT_PREFIX}TREES"
LAYER_TREES_APPROVAL = f"{RESULT_PREFIX}TREES_APPROVAL"
LAYER_REJECT = f"{RESULT_PREFIX}REJECT"
LAYER_LABELS = f"{RESULT_PREFIX}LABELS"
REJECT_BLOCK = f"{RESULT_PREFIX}REJECT_MARK"
LAYER_COLORS = {LAYER_TREES: 3, LAYER_TREES_APPROVAL: 30, LAYER_REJECT: 1, LAYER_LABELS: 7}
XDATA_CHUNK = 240
NPA_REFS = 2


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

    def write(self, source: Path, plan: Plan, rulebook: RuleBook, target: Path) -> SourceSnapshot:
        """Пишет результат в копию исходника и возвращает отпечатки исходных сущностей до правок."""
        doc, _ = self._documents.take(source) if self._documents else load_document(source)
        digests, unexportable = fingerprints(doc)
        snapshot = SourceSnapshot(digests, unexportable)
        self._prepare(doc)
        msp = doc.modelspace()
        for placement in plan.placements:
            self._placement(doc, msp, placement)
        for rejection in plan.rejections:
            self._rejection(msp, rejection)
        self._legend(msp, plan, rulebook)
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
            block.add_line((-0.5, -0.5), (0.5, 0.5))
            block.add_line((-0.5, 0.5), (0.5, -0.5))
            block.add_attdef(
                "NUM", (0.6, 0.2), dxfattribs={"height": self._height, "style": TEXT_STYLE}
            )

    def _tree_block(self, doc: Drawing, species: Species) -> str:
        name = f"{RESULT_PREFIX}TREE_{species.code.upper()}"
        if name not in doc.blocks:
            block = doc.blocks.new(name)
            block.add_circle((0, 0), radius=species.crown_diameter_m / 2)
            block.add_line((-0.3, 0), (0.3, 0))
            block.add_line((0, -0.3), (0, 0.3))
            attribs = {"height": self._height, "style": TEXT_STYLE}
            block.add_attdef("NUM", (0.4, 0.4), dxfattribs=attribs)
            block.add_attdef("SPECIES", (0.4, -0.4 - self._height), dxfattribs=attribs)
            block.add_attdef(
                "NPA", (0.4, -0.8 - 2 * self._height), dxfattribs={**attribs, "flags": 1}
            )
        return name

    def _placement(self, doc: Drawing, msp: Modelspace, placement: Placement) -> None:
        layer = LAYER_TREES if placement.verdict is Verdict.ALLOWED else LAYER_TREES_APPROVAL
        ref = msp.add_blockref(
            self._tree_block(doc, placement.species),
            (placement.x, placement.y),
            dxfattribs={"layer": layer},
        )
        tightest = sorted(
            (c for c in placement.checks if c.measured_m is not None),
            key=lambda c: (c.measured_m or 0) - (c.threshold_m or 0),
        )[:NPA_REFS]
        ref.add_auto_attribs(
            {
                "NUM": str(placement.number),
                "SPECIES": placement.species.name_ru,
                "NPA": "; ".join(c.rule_id for c in tightest),
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

    def _rejection(self, msp: Modelspace, rejection: Rejection) -> None:
        ref = msp.add_blockref(
            REJECT_BLOCK, (rejection.x, rejection.y), dxfattribs={"layer": LAYER_REJECT}
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

    def _legend(self, msp: Modelspace, plan: Plan, rulebook: RuleBook) -> None:
        used = sorted({c.rule_id for p in plan.placements for c in p.checks})
        used += sorted({c.rule_id for r in plan.rejections for c in r.blocking} - set(used))
        lines = ["Результат сервиса green: слои GREEN_*. Правила:"]
        for rule_id in used:
            rule = rulebook.rule(rule_id)
            if rule is not None:
                lines.append(f"{rule_id}: {citation_text(rule, rulebook)}")
        xs = [p.x for p in plan.placements] + [r.x for r in plan.rejections]
        ys = [p.y for p in plan.placements] + [r.y for r in plan.rejections]
        if not xs:
            return
        mtext = msp.add_mtext(
            "\\P".join(lines),
            dxfattribs={
                "layer": LAYER_LABELS,
                "style": TEXT_STYLE,
                "char_height": self._height * 2,
            },
        )
        mtext.set_location((min(xs), max(ys) + 10 * self._height))
