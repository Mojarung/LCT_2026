"""Перепись внешних ссылок каталога улиц: что есть в комплекте, чего нет и где оно в архиве.

Для каждого DXF каталога читается секция BLOCKS (без ezdxf, построчно): блоки с флагом XREF
и их пути. Ссылка ищется среди файлов комплекта по ключу имени (`slug_key` основы имени,
как каталог называет файлы), недостающая - в оглавлении архива по тому же ключу.

    uv run python tools/xref_census.py [--catalog dataset/streets_dxf_oda]
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from green.application.semantic_names import slug_key  # noqa: E402
from prepare_streets import TOP, ZIP, entry_name, xrefs  # noqa: E402

def key(reference: str) -> str:
    return slug_key(PureWindowsPath(reference.replace("/", "\\")).stem)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "dataset" / "streets_dxf_oda")
    args = parser.parse_args()
    catalog = json.loads((args.catalog / "catalog.json").read_text(encoding="utf-8"))
    archive_index: dict[tuple[str, str], list[str]] = defaultdict(list)
    with zipfile.ZipFile(ZIP) as archive:
        for info in archive.infolist():
            name = entry_name(info)
            parts = name.split("/")
            if len(parts) >= 3 and parts[0] == TOP and name.lower().endswith((".dwg", ".dxf")):
                archive_index[(parts[1].split(".")[0], key(parts[-1]))].append("/".join(parts[2:]))
    totals = defaultdict(int)
    for street in catalog:
        kit = {key(Path(f).stem): f for f in street["files"]}
        print(f"\n{street['number']:>2}. {street['title']}  (файлов в комплекте {len(street['files'])})")
        for file in street["files"]:
            refs = xrefs(args.catalog / street["slug"] / file)
            if not refs:
                continue
            print(f"   {file}: ссылок {len(refs)}")
            for block, reference, overlay in refs:
                k = key(reference)
                where = archive_index.get((str(street["number"]), k), [])
                if k in kit:
                    state, totals["в комплекте"] = f"в комплекте: {kit[k]}", totals["в комплекте"] + 1
                elif where:
                    state = f"НЕТ в комплекте, в архиве: {'; '.join(where[:2])}"
                    totals["есть в архиве"] += 1
                else:
                    state = "НЕТ ни в комплекте, ни в архиве"
                    totals["нигде"] += 1
                mark = " overlay" if overlay else ""
                print(f"      {block}{mark} -> {reference}\n         {state}")
    print("\nИТОГО ссылок:", dict(totals))


if __name__ == "__main__":
    main()
