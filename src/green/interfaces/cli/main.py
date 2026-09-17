"""CLI: прогон, осмотр слоёв, проверка целостности, запуск API."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import orjson
import yaml
from cyclopts import App, Parameter

from green import __version__
from green.application.classification import classify_scene
from green.application.errors import GreenError, InputError
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.infrastructure.inventory import read_inventory

if TYPE_CHECKING:
    from green.application.ports import InventoryCounts
    from green.bootstrap.container import Container

app = App(
    name="green",
    help="Автопроектирование озеленения: DXF -> план посадок на слоях GREEN_* -> DXF.",
    version=__version__,
)


def _print(payload: object) -> None:
    sys.stdout.write(orjson.dumps(payload, option=orjson.OPT_INDENT_2).decode() + "\n")


def _overrides(items: tuple[str, ...]) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator or not key:
            raise InputError(f"Ожидается --set ключ=значение, получено '{item}'")
        parsed[key.strip()] = yaml.safe_load(value)
    return parsed


def _inventory(container: Container, path: Path | None) -> InventoryCounts | None:
    """Прочитать перечётку и напечатать, сколько строк доехало до квот, а сколько нет."""
    if path is None:
        return None
    counts = read_inventory(path, container.species.all())
    _print(
        {
            "inventory": {
                "rows_read": counts.rows_read,
                "matched_plants": counts.total,
                "matched_species": len(counts.matched),
                "unmatched_plants": sum(counts.unmatched.values()),
                "removed_rows": counts.rows_removed,
                "rows_without_count": counts.rows_without_count,
                "approximate_by_genus": len(counts.approximate),
            }
        }
    )
    return counts


@app.command
def run(
    source: Path,
    /,
    *more: Path,
    profile: str | None = None,
    out: Path | None = None,
    inventory: Path | None = None,
    set_: Annotated[tuple[str, ...], Parameter(name="--set")] = (),
) -> None:
    """Прогнать чертёж: план на слоях GREEN_*, объяснения и проверка целостности.

    Parameters
    ----------
    source
        Входной DXF или DWG: основа, в её копию записывается результат.
    more
        Остальные чертежи комплекта (геоподоснова, сети, дендроплан). Склеиваются с основой в
        один документ, результат пишется в него.
    profile
        Профиль параметров из config/profiles.
    out
        Каталог результата, по умолчанию out/<run_id>.
    inventory
        Перечётная ведомость (.xls или .xlsx): существующие деревья входят в квоты
        разнообразия при подборе ассортимента.
    set_
        Переопределение параметра профиля, например --set spacing_m=6.
    """
    container = build_container()
    profile_name = profile or container.settings.default_profile
    params = container.profiles.load(profile_name, _overrides(set_))
    run_id = str(uuid.uuid7())
    work_dir = out or Path("out") / run_id
    existing = _inventory(container, inventory)
    report = container.use_case.execute(
        PlanRequest(run_id, source, work_dir, profile_name, params, existing, tuple(more))
    )
    files = container.artifacts.save(work_dir, report)
    _print(
        {
            "run_id": run_id,
            "summary": report.summary(),
            "timings_ms": {t.stage: t.ms for t in report.timings},
            "artifacts": {name: str(path) for name, path in files.items()},
        }
    )


@app.command
def inspect(source: Path, /) -> None:
    """Показать слои DXF и присвоенные им классы по config/layer_map.yaml."""
    container = build_container()
    scene, coverage = classify_scene(container.reader.read(source), container.layers.load())
    _print(
        {
            "source": scene.source_name,
            "dxf_version": scene.dxf_version,
            "features": len(scene.features),
            "labels": len(scene.labels),
            "layers": [
                {"layer": c.layer, "class": c.object_class.value, "features": c.features}
                for c in coverage
            ],
            "warnings": list(scene.warnings),
        }
    )


@app.command
def verify(source: Path, result: Path, /) -> None:
    """Проверить, что исходные сущности в результате не изменены."""
    report = build_container().integrity.verify_files(source, result)
    _print(
        {
            "ok": report.ok,
            "source_entities": report.source_entities,
            "unchanged": report.unchanged,
            "changed": list(report.changed),
            "missing": list(report.missing),
            "added_outside_result_layers": list(report.added_outside_result_layers),
        }
    )
    if not report.ok:
        sys.exit(1)


@app.command
def serve(*, host: str = "127.0.0.1", port: int = 8000, workers: int = 1) -> None:
    """Запустить HTTP API (Granian, ASGI). OpenAPI: /docs."""
    from granian import Granian  # noqa: PLC0415 - сервер нужен только этой команде
    from granian.constants import Interfaces  # noqa: PLC0415

    Granian(
        "green.interfaces.api.asgi:create",
        factory=True,
        interface=Interfaces.ASGI,
        address=host,
        port=port,
        workers=workers,
    ).serve()


def main() -> None:
    try:
        app()
    except GreenError as error:
        sys.stderr.write(f"Ошибка: {error}\n")
        sys.exit(2)
