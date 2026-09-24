"""Перепись условных знаков по всем улицам: сколько, где, на каких слоях и как выглядят.

Сырьё - итоги tools/reader_check.py: out/reader-check/<улица>.json (знаки по базовому имени,
слои, число штрихов, примеры) и рисунки определений блоков out/reader-check/symbols/.
Итог:
  out/reader-check/census/symbols.json   базовое имя -> число, улицы, слои, штрихи, примеры
  out/reader-check/census/sheet-NN.png   листы рисунков по 48 знаков: имя, число, главный слой
  out/reader-check/census/unlisted.txt   знаки, которых нет в config/symbols.yaml

    uv run python tools/symbol_census.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "out" / "reader-check"
OUT = CHECK / "census"
DICTIONARY = ROOT / "config" / "symbols.yaml"
CELL, LABEL, COLUMNS, PER_SHEET = 200, 46, 8, 48


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def collect() -> dict[str, dict]:
    census: dict[str, dict] = {}
    for path in sorted(CHECK.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if "symbol_detail" not in row:
            continue
        for base, info in row["symbol_detail"].items():
            entry = census.setdefault(
                base,
                {"count": 0, "streets": {}, "layers": Counter(), "strokes": Counter(),
                 "examples": [], "drawing": None},
            )
            entry["count"] += info["count"]
            entry["streets"][row["slug"]] = info["count"]
            entry["layers"].update(info["layers"])
            entry["strokes"].update({int(k): v for k, v in info["strokes"].items()})
            entry["examples"].extend(
                {**example, "street": row["slug"]} for example in info["examples"][:2]
            )
    for base, entry in census.items():
        safe = re.sub(r'[\\/:*?"<>|\s]+', "_", base)
        # Рисунок - с улицы, где знака больше всего.
        for slug, _ in sorted(entry["streets"].items(), key=lambda kv: -kv[1]):
            drawing = CHECK / "symbols" / f"{safe}__{slug}.png"
            if drawing.exists():
                entry["drawing"] = str(drawing)
                break
    return dict(sorted(census.items(), key=lambda kv: -kv[1]["count"]))


def sheets(census: dict[str, dict]) -> list[Path]:
    font = _font(15)
    small = _font(12)
    names = list(census)
    produced = []
    for start in range(0, len(names), PER_SHEET):
        chunk = names[start : start + PER_SHEET]
        rows = (len(chunk) + COLUMNS - 1) // COLUMNS
        sheet = Image.new("RGB", (COLUMNS * CELL, rows * (CELL + LABEL)), "white")
        draw = ImageDraw.Draw(sheet)
        for index, base in enumerate(chunk):
            entry = census[base]
            x, y = (index % COLUMNS) * CELL, (index // COLUMNS) * (CELL + LABEL)
            if entry["drawing"]:
                picture = Image.open(entry["drawing"]).convert("RGB")
                picture.thumbnail((CELL - 8, CELL - 8))
                sheet.paste(picture, (x + (CELL - picture.width) // 2, y + 4))
            else:
                draw.text((x + 10, y + CELL // 2), "нет рисунка", fill="red", font=small)
            layer = entry["layers"].most_common(1)[0][0] if entry["layers"] else ""
            draw.rectangle((x, y, x + CELL - 1, y + CELL + LABEL - 1), outline="#cccccc")
            draw.text((x + 4, y + CELL), f"{base}  {entry['count']}", fill="black", font=font)
            draw.text((x + 4, y + CELL + 20), layer[:30], fill="#555555", font=small)
        path = OUT / f"sheet-{start // PER_SHEET + 1:02d}.png"
        sheet.save(path)
        produced.append(path)
    return produced


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    census = collect()
    if not census:
        sys.exit("нет итогов reader_check с деталями знаков")
    (OUT / "symbols.json").write_text(
        json.dumps(
            {base: {**e, "layers": dict(e["layers"].most_common()),
                    "strokes": dict(e["strokes"].most_common())} for base, e in census.items()},
            ensure_ascii=False, indent=1,
        ),
        encoding="utf-8",
    )
    listed = set()
    if DICTIONARY.exists():
        listed = set((yaml.safe_load(DICTIONARY.read_text(encoding="utf-8")) or {}).get("symbols", {}))
    unlisted = [base for base in census if base not in listed]
    (OUT / "unlisted.txt").write_text(
        "\n".join(f"{census[b]['count']:>7}  {b}" for b in unlisted), encoding="utf-8"
    )
    produced = sheets(census)
    total = sum(e["count"] for e in census.values())
    print(f"знаков {total}, базовых имён {len(census)}, без словаря {len(unlisted)}")
    print(f"листы: {', '.join(p.name for p in produced)} в {OUT}")
    for base in list(census)[:40]:
        e = census[base]
        layer = e["layers"].most_common(1)[0][0] if e["layers"] else ""
        print(f"  {e['count']:>7}  {base:<24} улиц {len(e['streets']):>2}  {layer}")


if __name__ == "__main__":
    main()
