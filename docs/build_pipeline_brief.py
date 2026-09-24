"""Build the technical brief PDF from its Markdown source using ReportLab.

Usage: python docs/build_pipeline_brief.py --font-dir DIR [--output FILE]
The font directory must contain DejaVuSans.ttf, DejaVuSans-Bold.ttf and
DejaVuSansMono.ttf. ReportLab is a documentation dependency, not a runtime dependency.
"""

# ruff: noqa: INP001 -- standalone documentation builder, not an importable package

from __future__ import annotations

import argparse
import re
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

if TYPE_CHECKING:
    from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]


def rich(text: str) -> str:
    text = escape(text.replace("—", "-").replace("–", "-").replace("‑", "-"))
    text = re.sub(r"`([^`]+)`", r'<font name="Mono" size="9">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2" color="#1d4568">\1</a>', text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "output/pdf/pipeline-brief.pdf")
    args = parser.parse_args()
    for name, filename in (
        ("Body", "DejaVuSans.ttf"),
        ("BodyBold", "DejaVuSans-Bold.ttf"),
        ("Mono", "DejaVuSansMono.ttf"),
    ):
        pdfmetrics.registerFont(TTFont(name, str(args.font_dir / filename)))
    pdfmetrics.registerFontFamily(
        "Body", normal="Body", bold="BodyBold", italic="Body", boldItalic="BodyBold"
    )
    body = ParagraphStyle(
        "BriefBody",
        fontName="Body",
        fontSize=10.1,
        leading=14.5,
        spaceAfter=9,
        textColor=colors.black,
        alignment=TA_LEFT,
    )
    h1 = ParagraphStyle(
        "BriefTitle",
        parent=body,
        fontName="BodyBold",
        fontSize=20,
        leading=25,
        spaceAfter=16,
        keepWithNext=True,
    )
    h2 = ParagraphStyle(
        "BriefHeading",
        parent=body,
        fontName="BodyBold",
        fontSize=12.2,
        leading=17,
        spaceBefore=7,
        spaceAfter=7,
        keepWithNext=True,
    )
    cell = ParagraphStyle("BriefCell", parent=body, fontSize=9.3, leading=13, spaceAfter=0)
    numbered = ParagraphStyle(
        "BriefNumbered", parent=body, leftIndent=14, firstLineIndent=-14, spaceAfter=9
    )
    blocks = (ROOT / "docs/pipeline-brief.md").read_text().strip().split("\n\n")
    flow = []
    for block in blocks:
        if block == "---":
            flow.append(PageBreak())
        elif block.startswith("# "):
            flow.append(Paragraph(rich(block[2:]), h1))
        elif block.startswith("## "):
            flow.append(Paragraph(rich(block[3:]), h2))
        elif block.startswith("| "):
            rows = [line.strip().strip("|").split("|") for line in block.splitlines()]
            rows = [rows[0], *rows[2:]]
            cells = [[Paragraph(rich(value.strip()), cell) for value in row] for row in rows]
            table = Table(cells, colWidths=[170, A4[0] - 88 - 170], repeatRows=1, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9D9D9")),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF0F5")),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 9),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                        ("TOPPADDING", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            flow.extend((table, Spacer(1, 13)))
        elif re.match(r"^\d+\. ", block):
            flow.extend(Paragraph(rich(line), numbered) for line in block.splitlines())
        else:
            flow.append(Paragraph(rich(block.replace("\n", " ")), body))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(args.output),
        pagesize=A4,
        leftMargin=44,
        rightMargin=44,
        topMargin=43,
        bottomMargin=46,
        title="Как работает посадка растений",
        author="LCT 2026",
        subject="Алгоритм, проверки и ограничения сервиса green",
    )

    def footer(canvas: Canvas, _doc: SimpleDocTemplate) -> None:
        canvas.saveState()
        canvas.setFont("Body", 8)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawString(44, 24, "green  |  Пайплайн посадок  |  25.09.2026")
        canvas.drawRightString(A4[0] - 44, 24, str(canvas.getPageNumber()))
        canvas.restoreState()

    doc.build(flow, onFirstPage=footer, onLaterPages=footer)
    print(args.output)  # noqa: T201 -- show the generated artifact to CLI callers


if __name__ == "__main__":
    main()
