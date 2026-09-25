"""Сквозной прогон сервиса по улицам каталога (задача 13 плана): чтение, классы, посадки, запись.

Тем же путём, что кнопка улицы в веб-форме и прогон улицы через API: регистрация прогона с
единицами улицы из каталога, копия комплекта, прогон в профиле (по умолчанию strict). Одна
улица - один свежий процесс, от лёгких к тяжёлым: на комплекте в 300 МБ два прогона в памяти
не помещаются. Итог - out/street-runs/<улица>.json и таблица out/street-runs/summary.md.

    uv run python tools/street_runs.py                         все улицы каталога
    uv run python tools/street_runs.py --only 6 --only 18      выбранные
    uv run python tools/street_runs.py --profile strict --catalog dataset/streets_oda
"""
# ruff: noqa: INP001, T201 - инструмент прогона

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from green.bootstrap.container import build_container  # noqa: E402
from green.bootstrap.settings import Settings  # noqa: E402
from green.infrastructure.streets import JsonStreetCatalog  # noqa: E402
from green.interfaces.api.intake import _copy_and_execute  # noqa: E402

OUT = ROOT / "out" / "street-runs"
KEYS = (
    "placements",
    "allowed",
    "needs_approval",
    "rejections",
    "integrity_ok",
    "plan_valid",
    "export_matches_plan",
    "semantic_assignments_complete",
    "total_ms",
)


def run(job: tuple[str, str, str]) -> dict:
    slug, catalog, profile = job
    started = time.perf_counter()
    settings = Settings(
        config_dir=ROOT / "config", runs_dir=OUT / "runs", streets_dir=Path(catalog)
    )
    container = build_container(settings)
    street = container.streets.get(slug)
    if street is None:
        return {"slug": slug, "state": "missing", "error": "улицы нет в каталоге"}
    values: dict[str, object] = {}
    if street.drawing_unit:
        values["drawing_unit"] = street.drawing_unit
    try:
        record = container.runs.register(f"{street.title}{street.main.suffix}", profile, values)
        _copy_and_execute(container, record.run_id, street)
        record = container.store.get(record.run_id)
    except Exception as error:  # noqa: BLE001 - сбой улицы пишется в её итог
        return {
            "slug": slug,
            "state": "crashed",
            "error": str(error),
            "traceback": traceback.format_exc(limit=12),
        }
    summary = dict(record.summary)
    return {
        "slug": slug,
        "title": street.title,
        "run_id": record.run_id,
        "state": str(record.state),
        "error": record.error,
        "seconds": round(time.perf_counter() - started, 1),
        "summary": {key: summary.get(key) for key in KEYS if key in summary},
        "warnings": summary.get("warnings", [])[:30],
        "artifacts": list(record.artifacts),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "dataset" / "streets_oda")
    parser.add_argument("--only", action="append", type=int, help="номера улиц")
    parser.add_argument("--profile", default="strict")
    args = parser.parse_args()
    streets = [
        s
        for s in JsonStreetCatalog(args.catalog).all()
        if not args.only or s.number in set(args.only)
    ]
    # Лёгкие первыми: итоги по большинству улиц раньше, чем очередь дойдёт до тяжёлых.
    streets.sort(key=lambda s: sum(p.stat().st_size for p in (s.main, *s.extra)))
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    with ProcessPoolExecutor(max_workers=1, max_tasks_per_child=1) as pool:
        jobs = [(s.slug, str(args.catalog), args.profile) for s in streets]
        for street, row in zip(streets, pool.map(run, jobs), strict=True):
            row["number"] = street.number
            rows.append(row)
            (OUT / f"{street.slug}.json").write_text(
                json.dumps(row, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
            )
            print(
                f"{street.number:>2} {street.slug[:30]:<30} {row['state']:<10} "
                f"{row.get('seconds', 0):>7} с  {row.get('summary', {})}  {row.get('error') or ''}"[
                    :400
                ],
                flush=True,
            )
    lines = [
        "| № | Улица | Итог | Секунд | Посадок | Отказов | Целостность | План верен | Ошибка |",
        "|---" * 9 + "|",
    ]
    for row in sorted(rows, key=lambda r: r["number"]):
        summary = row.get("summary", {})
        lines.append(
            f"| {row['number']} | {row.get('title', row['slug'])} | {row['state']} | "
            f"{row.get('seconds', '')} | {summary.get('placements', '')} | "
            f"{summary.get('rejections', '')} | {summary.get('integrity_ok', '')} | "
            f"{summary.get('plan_valid', '')} | "
            f"{(row.get('error') or '')[:120]} |"
        )
    (OUT / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
