"""Сборка технической документации: главы и приложения в Markdown -> HTML -> PDF.

    uv run python tools/docs/annexes.py      # приложения из конфигов и прогонов
    uv run python tools/docs/build.py        # docs/documentation/green-documentation.pdf

Проверки сборки: ссылки «разд. N» и «приложение X» ведут на существующие разделы, в тексте
нет длинных тире. Номера страниц оглавления берутся из закладок первого прохода PDF.
"""
# ruff: noqa: INP001, T201, S603, S607, E501, C901, PERF401 - инструмент сборки документации

from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import markdown
from markdown.extensions.toc import slugify_unicode

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "documentation"
TOOLS = ROOT / "tools" / "docs"
OUT = ROOT / "out" / "docs"
PDF = DOCS / "green-documentation.pdf"
CHAPTERS = sorted(DOCS.glob("[0-9][0-9]-*.md"))
ANNEXES = sorted((DOCS / "generated").glob("[A-Z]-*.md"))
FONTS = [
    "@fontsource/ibm-plex-sans/400.css",
    "@fontsource/ibm-plex-sans/400-italic.css",
    "@fontsource/ibm-plex-sans/500.css",
    "@fontsource/ibm-plex-sans/600.css",
    "@fontsource/ibm-plex-mono/400.css",
]
EXTENSIONS = ["tables", "attr_list", "fenced_code", "md_in_html", "sane_lists", "toc"]


LIST_ITEM = re.compile(r"^\s*(?:[-*]|\d+\.) ")


def loosen_lists(text: str) -> str:
    """Пустая строка перед списком, который идёт сразу за абзацем.

    GitHub принимает список вплотную к абзацу, python-markdown - нет и склеивает пункты в
    строку. Блок, начатый пунктом списка, не трогается: его продолжения - не абзац.
    """
    out: list[str] = []
    block_start = ""
    for line in text.split("\n"):
        if not line.strip():
            block_start = ""
        elif not block_start:
            block_start = line
        elif (
            LIST_ITEM.match(line)
            and not LIST_ITEM.match(block_start)
            and not block_start.lstrip().startswith(("|", "#", "<", "```", ">"))
        ):
            out.append("")
            block_start = line
        out.append(line)
    return "\n".join(out)


def convert(text: str) -> tuple[str, list[dict[str, object]]]:
    text = loosen_lists(text)
    md = markdown.Markdown(
        extensions=EXTENSIONS,
        extension_configs={"toc": {"slugify": slugify_unicode, "toc_depth": "2-3"}},
    )
    body = md.convert(text)
    return body, md.toc_tokens  # type: ignore[attr-defined]


def fill(text: str) -> str:
    """Числа {{ключ}} из generated/facts.json: аннотация не расходится с приложениями."""
    facts = json.loads((DOCS / "generated" / "facts.json").read_text(encoding="utf-8"))

    def value(match: re.Match[str]) -> str:
        if match.group(1) not in facts:
            msg = f"нет факта {match.group(1)} в generated/facts.json"
            raise SystemExit(msg)
        return facts[match.group(1)]

    return re.sub(r"\{\{(\w+)\}\}", value, text)


def breakable_code(html_text: str) -> str:
    """Идентификаторы переносятся только после «_», «/» и «.», а не посреди слова."""

    def soften(match: re.Match[str]) -> str:
        return "<code>" + re.sub(r"([_/.])(?=\w)", r"\1<wbr>", match.group(1)) + "</code>"

    return re.sub(r"<code>(.*?)</code>", soften, html_text, flags=re.DOTALL)


def check_references(sources: dict[str, str]) -> list[str]:
    """Каждая ссылка «разд. N» и «приложение X» должна вести на существующий заголовок."""
    text = "\n".join(sources.values())
    sections = set(re.findall(r"^#{2,4} (\d+(?:\.\d+)*)\.", text, flags=re.MULTILINE))
    annexes = set(re.findall(r"^## Приложение ([A-Z])\.", text, flags=re.MULTILINE))
    problems = []
    for name, source in sources.items():
        for ref in re.findall(r"разд\. (\d+(?:\.\d+)*)(?:[,;]\s*(\d+(?:\.\d+)*))*", source):
            for number in filter(None, ref):
                if number not in sections:
                    problems.append(f"{name}: нет раздела {number}")
        for many in re.findall(r"разд\. ((?:\d+(?:\.\d+)*(?:, | и ))+\d+(?:\.\d+)*)", source):
            for number in re.split(r", | и ", many):
                if number not in sections:
                    problems.append(f"{name}: нет раздела {number}")
        for letter in re.findall(r"[Пп]рил(?:ожени[еяию]|\.) ([A-Z])\b", source):
            if letter not in annexes:
                problems.append(f"{name}: нет приложения {letter}")
        for dash in re.findall(r".{0,30}[—–].{0,30}", source):
            problems.append(f"{name}: длинное тире в «{dash}»")
    return sorted(set(problems))


def toc_html(tokens: list[dict[str, object]], pages: dict[str, int]) -> str:
    items = []
    for chapter in tokens:
        items.append(_toc_item(chapter, pages, "l2"))
        items.extend(_toc_item(section, pages, "l3") for section in chapter["children"])  # type: ignore[attr-defined]
    return (
        '<nav class="toc"><h2 class="toc-title">Содержание</h2><ol>'
        + "".join(items)
        + "</ol></nav>"
    )


def _toc_item(token: dict[str, object], pages: dict[str, int], level: str) -> str:
    name = html.unescape(str(token["name"]))
    page = pages.get(name, "")
    return (
        f'<li class="{level}"><a href="#{token["id"]}"><span class="t">{html.escape(name)}</span>'
        f'<span class="fill"></span><span class="pg">{page}</span></a></li>'
    )


def cover(version: str, commit: str) -> str:
    today = datetime.now(tz=UTC).astimezone().strftime("%d.%m.%Y")
    return f"""
<section class="cover">
  <div class="cover-top">
    <p class="case">Лидеры цифровой трансформации 2026. Кейс Департамента природопользования
    и охраны окружающей среды города Москвы</p>
  </div>
  <div class="cover-main">
    <h1>green</h1>
    <p class="subtitle">Генеративное проектирование озеленения улиц по чертежу DXF
    с нормативными отступами и объяснением каждой посадки</p>
    <p class="doc-kind">Техническая документация</p>
  </div>
  <dl class="cover-meta">
    <div><dt>Версия сервиса</dt><dd>{version}, коммит {commit}</dd></div>
    <div><dt>Дата сборки</dt><dd>{today}</dd></div>
    <div><dt>Исходный код</dt><dd>github.com/Mojarung/LCT_2026</dd></div>
    <div><dt>Состав</dt><dd>разделы 1-8, приложения A-D; схемы BPMN 2.0 -
    <code>docs/documentation/diagrams/*.bpmn</code></dd></div>
  </dl>
</section>"""


def page(body: str, toc: str, version: str, commit: str) -> str:
    fonts = "\n".join(
        f'<link rel="stylesheet" href="{(TOOLS / "node_modules" / f).as_uri()}">' for f in FONTS
    )
    css = (TOOLS / "print.css").as_uri()
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<base href="{DOCS.as_uri()}/">
<title>green: техническая документация</title>
{fonts}
<link rel="stylesheet" href="{css}">
</head>
<body>
{cover(version, commit)}
{toc}
<main>
{body}
</main>
</body>
</html>
"""


def render(html_file: Path, pdf_file: Path, pages_file: Path) -> dict[str, int]:
    subprocess.run(
        ["node", str(TOOLS / "render.mjs"), "pdf", str(html_file), str(pdf_file), str(pages_file)],
        check=True,
        cwd=TOOLS,
    )
    found = json.loads(pages_file.read_text(encoding="utf-8"))
    return {_once(h["title"].strip()): h["page"] for h in found["headings"]}


def _once(title: str) -> str:
    """Chromium повторяет текст части закладок дважды подряд: «2. Архитектура2. Архитектура»."""
    half = len(title) // 2
    return title[:half] if len(title) % 2 == 0 and title[:half] == title[half:] else title


def main() -> None:
    sources = {p.name: fill(p.read_text(encoding="utf-8")) for p in (*CHAPTERS, *ANNEXES)}
    problems = check_references(sources)
    if problems:
        print("\n".join(problems))
        raise SystemExit(1)

    parts, tokens = [], []
    for name, source in sources.items():
        body, toc = convert(source)
        kind = "annex" if name[0].isalpha() else "chapter"
        parts.append(f'<section class="{kind}" data-source="{name}">{body}</section>')
        tokens.extend(toc)
    body = breakable_code("\n".join(parts))

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    ).stdout.strip()

    OUT.mkdir(parents=True, exist_ok=True)
    html_file, pages_file = OUT / "documentation.html", OUT / "pages.json"
    pages: dict[str, int] = {}
    for _ in range(3):
        html_file.write_text(
            page(body, toc_html(tokens, pages), project["version"], commit), encoding="utf-8"
        )
        found = render(html_file, PDF, pages_file)
        if found == pages:
            break
        pages = found
    missing = [t["name"] for t in tokens if html.unescape(str(t["name"])) not in pages]
    if missing:
        print("нет закладки для заголовков:", missing[:5])
    print(
        f"{PDF.relative_to(ROOT)}: {json.loads(pages_file.read_text(encoding='utf-8'))['pages']} стр."
    )


if __name__ == "__main__":
    sys.exit(main())
