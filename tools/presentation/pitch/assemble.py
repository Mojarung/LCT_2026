# ruff: noqa: INP001, T201 - standalone deck assembler next to build.mjs
"""Собирает презентацию к сдаче: обязательные слайды 7-11 шаблона ЛЦТ 2026 и свободные слайды.

Обязательные слайды заполняет deck/mandatory.py в исходном оформлении шаблона (меняется только
текст), свободные рисует build.mjs в HTML. PDF обязательных - LibreOffice, склейка - PyMuPDF;
в PPTX свободные слайды вставляются картинками во весь кадр после обязательных.

Запуск (после shots.mjs и build.mjs):
    uv run --with python-pptx --with pillow --with pymupdf python \
        tools/presentation/pitch/assemble.py "ЛЦТ2026 Шаблон презентации.pptx"
Выход: out/presentation/pitch/green-lct2026.pdf и green-lct2026.pptx.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pymupdf
from PIL import Image
from pptx import Presentation
from pptx.util import Emu

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "deck"))

import build_pptx as deck  # noqa: E402 - модуль колоды лежит рядом, путь добавлен выше

ROOT = HERE.parents[2]
PITCH = ROOT / "out" / "presentation" / "pitch"
SOFFICE = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")


def plan_band() -> Path:
    """Полоса плана для слайда «О команде»: свежий снимок целой улицы, центральная часть."""
    deck.ASSETS.mkdir(parents=True, exist_ok=True)
    shot = Image.open(PITCH / "shots" / "plan-street-light.png").convert("RGB")
    return deck.jpg(shot.crop((1080, 380, 2220, 1420)), "plan_band.jpg")


def mandatory_deck(template: Path) -> Presentation:
    prs = Presentation(str(template))
    deck.drop_slides(prs, set(deck.MANDATORY))
    title_s, about_s, team_s, history_s, short_s = list(prs.slides)
    assets = {"plan_band": plan_band(), **deck.poser_logo()}
    deck.fill_title_slide(title_s, assets)
    deck.fill_about_slide(about_s, assets)
    deck.fill_team_slide(team_s, [deck.portrait(*spec) for spec in deck.TEAM_PHOTOS])
    deck.fill_history_slide(history_s)
    deck.fill_short_slide(short_s)
    return prs


def to_pdf(pptx: Path) -> Path:
    subprocess.run(  # noqa: S603 - LibreOffice по фиксированному пути, аргументы - наши файлы
        [
            str(SOFFICE),
            "--headless",
            "--convert-to",
            "pdf",
            str(pptx),
            "--outdir",
            str(pptx.parent),
        ],
        check=True,
        capture_output=True,
    )
    return pptx.with_suffix(".pdf")


def main() -> None:
    template = Path(sys.argv[1])
    free_png = sorted((PITCH / "slides").glob("*.png"))
    if not free_png:
        raise SystemExit("Нет свободных слайдов: сначала node tools/presentation/pitch/build.mjs")

    mandatory = PITCH / "mandatory.pptx"
    mandatory_deck(template).save(str(mandatory))
    mandatory_pdf = to_pdf(mandatory)

    out_pdf = PITCH / "green-lct2026.pdf"
    with pymupdf.open(mandatory_pdf) as doc, pymupdf.open(PITCH / "free.pdf") as free:
        doc.insert_pdf(free)
        doc.set_metadata({"title": "green - озеленение улиц по нормам", "author": "MISIS MOJARUNG"})
        # Снимки сервиса сняты в 2x: 150 dpi на слайде 1920 px хватает, файл меньше вчетверо.
        doc.rewrite_images(dpi_threshold=180, dpi_target=150, quality=82)
        doc.save(out_pdf, garbage=4, deflate=True, clean=True)

    prs = mandatory_deck(template)
    blank = prs.slide_layouts[len(prs.slide_layouts) - 1]
    for png in free_png:
        slide = prs.slides.add_slide(blank)
        for ph in list(slide.placeholders):
            ph._element.getparent().remove(ph._element)  # noqa: SLF001 - у python-pptx нет API
        slide.shapes.add_picture(str(png), 0, 0, Emu(prs.slide_width), Emu(prs.slide_height))
    out_pptx = PITCH / "green-lct2026.pptx"
    prs.save(str(out_pptx))

    with pymupdf.open(out_pdf) as doc:
        pages = doc.page_count
    print(f"{out_pdf}: {pages} слайдов, {out_pdf.stat().st_size / 1e6:.1f} МБ")
    print(f"{out_pptx}: {out_pptx.stat().st_size / 1e6:.1f} МБ")


if __name__ == "__main__":
    main()
