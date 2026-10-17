"""Сквозной прогон сервиса по улицам каталога (задача 13 плана): чтение, классы, посадки, запись.

Тем же путём, что кнопка улицы в веб-форме и прогон улицы через API: регистрация прогона с
единицами улицы из каталога, копия комплекта, прогон в профиле (по умолчанию strict). Одна
улица - один свежий процесс, от лёгких к тяжёлым: на комплекте в 300 МБ два прогона в памяти
не помещаются. Итог - out/street-runs/<улица>.json и таблица out/street-runs/summary.md.

    uv run python tools/street_runs.py                         все улицы каталога
    uv run python tools/street_runs.py --only 6 --only 18      выбранные
    uv run python tools/street_runs.py --profile strict --catalog dataset/streets_oda
    uv run python tools/street_runs.py --workers 7 --ram-fill 0.93 --skip-done   параллельно

Параллельный режим запускает следующую улицу, только если хватает памяти: оценка пика улицы -
1 ГБ + 25 x размер комплекта (Олимпийская деревня, 337 МБ -> 8,2 ГБ по замеру 28.09), сумма
оценок идущих улиц и новой не выходит за долю ram-fill от всей памяти минус уже занятое.
"""
# ruff: noqa: INP001, T201 - инструмент прогона

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
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


def _need_gb(street: object, factor: float = 25.0) -> float:
    size = sum(p.stat().st_size for p in (street.main, *street.extra))  # ty: ignore[unresolved-attribute]
    return 1.0 + factor * size / 1e9


def _memory_gb() -> tuple[float, float]:
    """Вся и свободная память, ГБ (Windows - GlobalMemoryStatusEx, Linux - /proc/meminfo)."""
    if os.name == "nt":

        class _Status(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("load", ctypes.c_ulong),
                ("total", ctypes.c_ulonglong),
                ("free", ctypes.c_ulonglong),
                ("page_total", ctypes.c_ulonglong),
                ("page_free", ctypes.c_ulonglong),
                ("virtual_total", ctypes.c_ulonglong),
                ("virtual_free", ctypes.c_ulonglong),
                ("extended", ctypes.c_ulonglong),
            ]

        status = _Status()
        status.length = ctypes.sizeof(_Status)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # ty: ignore[unresolved-attribute]
        return status.total / 2**30, status.free / 2**30
    info = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    total = int(info["MemTotal"].split()[0]) / 2**20
    return total, int(info["MemAvailable"].split()[0]) / 2**20


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "dataset" / "streets_oda")
    parser.add_argument("--only", action="append", type=int, help="номера улиц")
    parser.add_argument("--profile", default="strict")
    # Параллельно: процесс на улицу, не больше ядер и памяти (тяжёлая улица - до 8 ГБ).
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--skip-done", action="store_true", help="не перегонять succeeded")
    parser.add_argument("--ram-fill", type=float, default=0.93, help="доля всей памяти")
    parser.add_argument(
        "--ram-factor", type=float, default=25.0, help="пик памяти улицы / размер комплекта"
    )
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
    if args.skip_done:
        for street in list(streets):
            done = OUT / f"{street.slug}.json"
            if (
                done.exists()
                and json.loads(done.read_text(encoding="utf-8")).get("state") == "succeeded"
            ):
                rows.append(json.loads(done.read_text(encoding="utf-8")))
                streets.remove(street)
    queue = list(streets)
    total_gb, free_gb = _memory_gb()
    budget = max(0.0, free_gb - (1 - args.ram_fill) * total_gb)
    print(
        f"память {total_gb:.1f} ГБ, свободно {free_gb:.1f}, бюджет прогонов {budget:.1f} ГБ, "
        f"процессов до {args.workers}",
        flush=True,
    )
    running: dict[object, tuple[object, float]] = {}
    with ProcessPoolExecutor(max_workers=args.workers, max_tasks_per_child=1) as pool:
        while queue or running:
            committed = sum(need for _, need in running.values())
            while queue and len(running) < args.workers:
                need = _need_gb(queue[0], args.ram_factor)
                # Первая улица идёт всегда; дальше - пока оценки помещаются в бюджет.
                if running and committed + need > budget:
                    break
                street = queue.pop(0)
                job = (street.slug, str(args.catalog), args.profile)
                running[pool.submit(run, job)] = (street, need)
                committed += need
            done, _ = wait(list(running), return_when=FIRST_COMPLETED)
            for future in done:
                street, _ = running.pop(future)
                try:
                    row = future.result()
                except Exception as error:  # noqa: BLE001 - упавший воркер (память) - строка итога
                    row = {"slug": street.slug, "state": "crashed", "error": repr(error)}
                row["number"] = street.number
                rows.append(row)
                (OUT / f"{street.slug}.json").write_text(
                    json.dumps(row, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
                )
                print(
                    f"{street.number:>2} {street.slug[:30]:<30} {row['state']:<10} "
                    f"{row.get('seconds', 0):>7} с  {row.get('summary', {})}  "
                    f"{row.get('error') or ''}"[:400],
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
