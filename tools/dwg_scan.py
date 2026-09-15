"""Пакетная конвертация всех DWG датасета через dwg2dxf и потоковый сбор слоёв.

Для каждого DWG: конвертация во временный DXF, скан тегов без загрузки в ezdxf
(версия, единицы, типы сущностей, слои, имена блоков INSERT, имена XREF), запись
одной строки JSON в results.jsonl, удаление DXF. Повторный запуск пропускает
уже обработанные файлы.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(sys.argv[1])
OUT = Path(sys.argv[2])
DWG2DXF = Path(sys.argv[3])
WORKERS = int(sys.argv[4]) if len(sys.argv) > 4 else 4
TMP = OUT / "tmp"
RESULTS = OUT / "results.jsonl"
TIMEOUT_S = 900


def scan_dxf(path: Path) -> dict:
    """Один проход по тегам DXF: только коды 0, 2, 8, 9 и значения заголовка."""
    header: dict[str, str] = {}
    section = ""
    entity = ""
    in_block_def = False
    kinds: Counter[str] = Counter()
    layers: Counter[str] = Counter()
    layer_kinds: Counter[tuple[str, str]] = Counter()
    inserts: Counter[str] = Counter()
    block_layers: Counter[str] = Counter()
    xrefs: set[str] = set()
    want_header = None
    pending_insert = False

    def decode(raw: bytes) -> str:
        # DXF до R2007 хранит строки в кодировке $DWGCODEPAGE (здесь ANSI_1251), новее - UTF-8.
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("cp1251", errors="replace")

    with path.open("rb") as stream:
        while True:
            code_line = stream.readline()
            if not code_line:
                break
            value = decode(stream.readline().rstrip(b"\r\n"))
            try:
                code = int(code_line)
            except ValueError:
                continue
            if code == 0:
                if value == "SECTION":
                    section = ""
                elif value == "ENDSEC":
                    section = ""
                elif section == "BLOCKS" and value == "BLOCK":
                    in_block_def = True
                elif section == "BLOCKS" and value == "ENDBLK":
                    in_block_def = False
                entity = value
                pending_insert = value == "INSERT"
                if section == "ENTITIES":
                    kinds[value] += 1
                continue
            if code == 2:
                if section == "" and value in ("HEADER", "BLOCKS", "ENTITIES", "TABLES", "OBJECTS"):
                    section = value
                elif section == "ENTITIES" and pending_insert:
                    inserts[value] += 1
                    pending_insert = False
                elif section == "BLOCKS" and entity == "BLOCK" and in_block_def:
                    pass
                continue
            if code == 8:
                if section == "ENTITIES":
                    layers[value] += 1
                    layer_kinds[(value, entity)] += 1
                elif section == "BLOCKS" and in_block_def and entity not in ("BLOCK", "ENDBLK"):
                    block_layers[value] += 1
                continue
            if code == 1 and section == "BLOCKS" and entity == "BLOCK":
                xrefs.add(value)
                continue
            if code == 9 and section == "HEADER":
                want_header = (
                    value
                    if value in ("$ACADVER", "$INSUNITS", "$DWGCODEPAGE", "$MEASUREMENT")
                    else None
                )
                continue
            if want_header and code in (1, 3, 70):
                header[want_header] = value
                want_header = None
    return {
        "header": header,
        "entities": sum(kinds.values()),
        "kinds": dict(kinds.most_common()),
        "layers": dict(layers.most_common()),
        "layer_kinds": [[k[0], k[1], n] for k, n in layer_kinds.most_common()],
        "inserts": dict(inserts.most_common(60)),
        "block_layers": dict(block_layers.most_common(60)),
        "xrefs": sorted(xrefs),
    }


def process(dwg: Path) -> dict:
    rel = str(dwg.relative_to(ROOT))
    row: dict = {"file": rel, "size": dwg.stat().st_size}
    target = TMP / f"{abs(hash(rel))}.dxf"
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [str(DWG2DXF), "-y", "-o", str(target), str(dwg)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        row["returncode"] = completed.returncode
        row["stderr_tail"] = completed.stderr[-300:]
    except subprocess.TimeoutExpired:
        row["error"] = "timeout"
        target.unlink(missing_ok=True)
        return row
    row["convert_s"] = round(time.perf_counter() - started, 1)
    if not target.exists() or target.stat().st_size == 0:
        row["error"] = "no output"
        target.unlink(missing_ok=True)
        return row
    row["dxf_size"] = target.stat().st_size
    try:
        row.update(scan_dxf(target))
    except Exception as error:  # noqa: BLE001
        row["error"] = f"scan: {type(error).__name__}: {error}"
    finally:
        target.unlink(missing_ok=True)
    return row


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(exist_ok=True)
    done = set()
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["file"])
    files = sorted(p for p in ROOT.rglob("*") if p.suffix.lower() == ".dwg")
    todo = [p for p in files if str(p.relative_to(ROOT)) not in done]
    print(f"total {len(files)}, done {len(done)}, todo {len(todo)}", flush=True)
    with RESULTS.open("a", encoding="utf-8") as sink, ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(process, p): p for p in todo}
        for index, future in enumerate(as_completed(futures), 1):
            row = future.result()
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            sink.flush()
            status = row.get("error") or f"ok {row.get('entities', 0)} ent {row.get('convert_s')}s"
            print(f"[{index}/{len(todo)}] {status}: {row['file'][:90]}", flush=True)


if __name__ == "__main__":
    main()
