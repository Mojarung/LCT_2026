"""CLI: прогон, нормоконтроль, осмотр слоёв, проверка целостности, API, схема API."""

from __future__ import annotations

import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import orjson
import yaml
from cyclopts import App, Parameter

from green import __version__
from green.application.audit import AuditRequest
from green.application.classification import (
    ClassificationError,
    classification_report,
    classify_scene,
)
from green.application.errors import GreenError, InputError
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.domain.norms import PlantingType
from green.infrastructure.inventory import read_inventory
from green.infrastructure.reports.artifacts import classification_payload

if TYPE_CHECKING:
    from collections.abc import Iterator

    from green.application.ports import InventoryCounts
    from green.bootstrap.container import Container

app = App(
    name="green",
    help="Автопроектирование озеленения: DXF -> план посадок на слоях GREEN_* -> DXF.",
    version=__version__,
)


@contextmanager
def _save_review(container: Container, directory: Path) -> Iterator[None]:
    try:
        yield
    except ClassificationError as error:
        container.artifacts.save_classification(directory, error.report)
        raise


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
    with _save_review(container, work_dir):
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
def audit(  # noqa: PLR0913 - CLI options are separate parameters by design
    source: Path,
    /,
    *more: Path,
    plantings: Annotated[str, Parameter(help="Регулярное выражение для слоёв с посадками")],
    profile: str | None = None,
    set_: Annotated[tuple[str, ...], Parameter(name="--set")] = (),
    trees: Annotated[str | None, Parameter(help="Слои, где посадка точно дерево")] = None,
    shrubs: Annotated[str | None, Parameter(help="Слои, где посадка точно кустарник")] = None,
    min_tree_crown: float = 2.0,
    no_crown_is: Annotated[str, Parameter(help="tree или shrub: посадка без круга кроны")] = "tree",
    out: Path | None = None,
) -> None:
    """Нормоконтроль готового чертежа: посадки на слоях --plantings проверяются по нормам."""
    container = build_container()
    name = profile or container.settings.default_profile
    params = container.profiles.load(name, _overrides(set_))
    try:
        default_type = PlantingType(no_crown_is)
    except ValueError as error:
        raise InputError("--no-crown-is: ожидается tree или shrub") from error
    run_id = uuid.uuid4().hex
    work_dir = out or container.settings.runs_dir / f"audit-{run_id}"
    with _save_review(container, work_dir):
        report = container.audit.execute(
            AuditRequest(
                run_id=run_id,
                source=source,
                work_dir=work_dir,
                profile=name,
                params=params,
                planting_layers=plantings,
                tree_layers=trees,
                shrub_layers=shrubs,
                min_tree_crown_m=min_tree_crown,
                default_type=default_type,
                extra_sources=tuple(more),
            )
        )
    artifacts = container.audit_artifacts.save(work_dir, report)
    _print(
        {
            **report.summary(),
            "timings_ms": {t.stage: t.ms for t in report.timings},
            "artifacts": {name: str(path) for name, path in artifacts.items()},
        }
    )
    if not report.integrity.ok:
        sys.exit(1)


@app.command
def inspect(
    source: Path,
    /,
    *,
    profile: str | None = None,
    set_: Annotated[tuple[str, ...], Parameter(name="--set")] = (),
) -> None:
    """Показать слои DXF и присвоенные им классы по config/layer_map.yaml."""
    container = build_container()
    params = container.profiles.load(
        profile or container.settings.default_profile, _overrides(set_)
    )
    layer_map = container.layers.load()
    scene, coverage = classify_scene(
        container.reader.read(source, unit=params.drawing_unit), layer_map, params
    )
    _print(
        {
            "source": scene.source_name,
            "dxf_version": scene.dxf_version,
            "features": len(scene.features),
            "labels": len(scene.labels),
            "classification": classification_payload(
                classification_report(scene, layer_map, params)
            ),
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


@app.command
def openapi(*, out: Path | None = None) -> None:
    """Выгрузить схему OpenAPI: в файл (--out docs/openapi.json) или в stdout."""
    from green.interfaces.api.app import create_app  # noqa: PLC0415 - FastAPI нужен только здесь

    schema = orjson.dumps(create_app().openapi(), option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    if out is None:
        sys.stdout.write(schema.decode() + "\n")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(schema + b"\n")


def main() -> None:
    try:
        app()
    except GreenError as error:
        sys.stderr.write(f"Ошибка: {error}\n")
        sys.exit(2)
