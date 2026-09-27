"""Баланс «было - стало» по уже выданным прогонам, без перепрогона.

В каталоге каждого прогона лежит контекст правки (context.pickle): прочитанный чертёж, план и
параметры. Скрипт строит по ним участок и существующие насаждения и считает эффект тем же
модулем, что и сервис (green.application.effect), затем пишет effect.json рядом с артефактами
прогона. Планы при этом не меняются: это планы, выбранные тем индексом, которым они были
посчитаны. Контексты по одному: сцена генплана весит сотни мегабайт.

    uv run python tools/effect_from_runs.py            # все улицы приложения B
    uv run python tools/effect_from_runs.py --only 5   # одна улица по номеру
"""

from __future__ import annotations

import argparse
import gc
import json
import pathlib
import pickle
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "docs"))

from annexes import street_rows  # noqa: E402

from green.application.effect import street_effect  # noqa: E402
from green.application.params import PlanParams  # noqa: E402
from green.application.quality import site_of  # noqa: E402
from green.application.stock import EXISTING_CROWN_M  # noqa: E402
from green.infrastructure.reports.artifacts import effect_payload  # noqa: E402

EFFECT_JSON = "effect.json"


def _load(path: Path) -> object:
    # Контексты из образа Docker записаны под Linux: пути в них - PosixPath.
    posix = pathlib.PosixPath
    pathlib.PosixPath = pathlib.WindowsPath  # type: ignore[misc]
    try:
        with path.open("rb") as handle:
            _, context = pickle.load(handle)  # noqa: S301 - файл пишет сам сервис
    finally:
        pathlib.PosixPath = posix  # type: ignore[misc]
    # Посадки, сохранённые до поля place, его не имеют: место не определялось.
    for placement in context.plan.placements:  # type: ignore[attr-defined]
        if not hasattr(placement, "place"):
            object.__setattr__(placement, "place", "")
    return context


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", type=int, action="append", help="номер улицы")
    args = parser.parse_args()
    for row in street_rows():
        if row.get("state") != "succeeded" or (args.only and row["number"] not in args.only):
            continue
        output = Path(str(row["output"]))
        source = output.parent / "context.pickle"
        if not source.is_file():
            print(f"{row['slug']}: нет контекста прогона", flush=True)  # noqa: T201
            continue
        start = time.perf_counter()
        context = _load(source)
        # Параметры прогона записаны прежней версией кода: эффекту нужны только шаги рядов,
        # полоса у борта и нормы на 1 км - берутся текущие; длина улицы - по оси границы.
        params = PlanParams()
        site = site_of(context.features, crown_m=EXISTING_CROWN_M)  # type: ignore[attr-defined]
        surface = getattr(context, "_surface", None)
        effect = street_effect(context.plan, site, params, surface=surface)  # type: ignore[attr-defined]
        payload = effect_payload(effect)
        (output / EFFECT_JSON).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        values = {m.key: (m.before, m.after) for m in effect.measures}
        print(  # noqa: T201 - итог по улице в консоль
            f"{row['slug']}: деревья {values['trees']}, кроны {values['canopy_share']} %, "
            f"борта {values['curb_green_share']} %, ярус {values['tiers_trees']}, "
            f"шум {values['noise_curb_m']} м; {time.perf_counter() - start:.0f} с",
            flush=True,
        )
        del context, site, effect
        gc.collect()


if __name__ == "__main__":
    main()
