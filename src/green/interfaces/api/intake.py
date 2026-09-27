"""Приём прогона: сохранение загруженных файлов и постановка в очередь.

Общий код для JSON-API и для веб-формы: оба принимают один и тот же комплект файлов и
обязаны одинаково обрабатывать превышение размера и неверные расширения. Дублировать это
в двух роутерах - гарантированно разойтись в поведении.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import orjson

from green.application.errors import InputError
from green.interfaces.api.errors import PayloadTooLargeError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi import BackgroundTasks, UploadFile

    from green.application.ports import StreetSource
    from green.application.results import RunRecord
    from green.bootstrap.container import Container

CHUNK = 1024 * 1024
DRAWING_SUFFIXES = frozenset({".dxf", ".dwg"})
# Слой ГИС через форму: GeoJSON или SHP одним архивом (.shp без .shx и .dbf не читается).
UPLOAD_LAYER_SUFFIXES = frozenset({".geojson", ".json", ".zip"})
_UNSAFE = re.compile(r"[^\w.\- ]", re.UNICODE)


def parse_overrides(raw: str | None) -> dict[str, object]:
    """Параметры поверх профиля: JSON-объект строкой, как его присылает форма или клиент."""
    if not raw or not raw.strip():
        return {}
    try:
        value = orjson.loads(raw)
    except orjson.JSONDecodeError as error:
        raise InputError(f"overrides: некорректный JSON: {error}") from error
    if not isinstance(value, dict):
        raise InputError("overrides: ожидается JSON-объект")
    return value


async def store_upload(upload: UploadFile, target: Path, limit_bytes: int) -> None:
    written = 0
    async with await anyio.open_file(target, "wb") as stream:
        while chunk := await upload.read(CHUNK):
            written += len(chunk)
            if written > limit_bytes:
                raise PayloadTooLargeError(f"Файл больше {limit_bytes // CHUNK} МБ")
            await stream.write(chunk)


async def accept_run(  # noqa: PLR0913 - комплект приходит отдельными полями формы
    *,
    container: Container,
    background: BackgroundTasks,
    file: UploadFile,
    profile: str | None = None,
    overrides: str | None = None,
    inventory: UploadFile | None = None,
    extra: Sequence[UploadFile] | None = None,
    layers: Sequence[UploadFile] | None = None,
) -> RunRecord:
    """Сохранить комплект, зарегистрировать прогон и поставить его в фоновую очередь."""
    settings = container.settings
    limit = settings.max_upload_mb * CHUNK
    record = container.runs.register(
        file.filename or "drawing.dxf",
        profile or settings.default_profile,
        parse_overrides(overrides),
    )
    try:
        await store_upload(file, container.store.input_path(record.run_id), limit)
    except PayloadTooLargeError as error:
        container.runs.reject(record.run_id, str(error))
        raise

    inventory_path = await _store_inventory(container, record.run_id, inventory)
    layer_paths = await _store_layers(container, record.run_id, layers)

    extra_paths: list[Path] = []
    source_names = [file.filename or "drawing.dxf"]
    for position, upload in enumerate(extra or (), 1):
        if not upload.filename:
            continue
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in DRAWING_SUFFIXES:
            container.runs.reject(record.run_id, f"extra: ожидается DXF или DWG, получен {suffix}")
            raise InputError(f"extra: ожидается DXF или DWG, получен {suffix or 'файл без типа'}")
        target = container.store.input_path(record.run_id).with_name(f"extra_{position}{suffix}")
        try:
            await store_upload(upload, target, limit)
        except PayloadTooLargeError as error:
            container.runs.reject(record.run_id, str(error))
            raise
        extra_paths.append(target)
        source_names.append(upload.filename)

    background.add_task(
        container.runs.execute,
        record.run_id,
        inventory_path,
        tuple(extra_paths),
        tuple(source_names),
        gis_layers=layer_paths,
    )
    return record


async def _store_layers(
    container: Container, run_id: str, layers: Sequence[UploadFile] | None
) -> tuple[Path, ...]:
    """Слои ГИС - под исходными именами: по имени файла конфиг выбирает класс объектов."""
    paths: list[Path] = []
    folder = container.store.input_path(run_id).parent / "gis"
    for upload in layers or ():
        if not upload.filename:
            continue
        name = _UNSAFE.sub("_", Path(upload.filename).name)[:120] or "layer.geojson"
        suffix = Path(name).suffix.lower()
        if suffix not in UPLOAD_LAYER_SUFFIXES:
            message = (
                "layers: ожидается GeoJSON (.geojson, .json) или SHP в .zip, получен "
                f"{suffix or 'файл без типа'}"
            )
            container.runs.reject(run_id, message)
            raise InputError(message)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        try:
            await store_upload(upload, target, container.settings.max_upload_mb * CHUNK)
        except PayloadTooLargeError as error:
            container.runs.reject(run_id, str(error))
            raise
        paths.append(target)
    return tuple(paths)


async def _store_inventory(
    container: Container, run_id: str, inventory: UploadFile | None
) -> Path | None:
    """Сохранить перечётную ведомость рядом с чертежом прогона, если её прислали."""
    if inventory is None or not inventory.filename:
        return None
    suffix = Path(inventory.filename).suffix or ".xlsx"
    target = container.store.input_path(run_id).with_name(f"inventory{suffix}")
    try:
        await store_upload(inventory, target, container.settings.max_upload_mb * CHUNK)
    except PayloadTooLargeError as error:
        container.runs.reject(run_id, str(error))
        raise
    return target


def _copy_and_execute(
    container: Container,
    run_id: str,
    street: StreetSource,
    inventory: Path | None = None,
    gis_layers: tuple[Path, ...] = (),
) -> None:
    """Скопировать комплект улицы в прогон и посчитать его.

    Копия, а не ссылка на файл каталога: прогон пишет рядом с исходником и правится на
    карте, а каталог - общие данные, которые обязаны пережить любой прогон.
    """
    target = container.store.input_path(run_id)
    try:
        shutil.copyfile(street.main, target)
        extra_paths: list[Path] = []
        for position, source in enumerate(street.extra, 1):
            copy = target.with_name(f"extra_{position}{source.suffix}")
            shutil.copyfile(source, copy)
            extra_paths.append(copy)
    except OSError as error:
        container.runs.reject(run_id, f"комплект улицы не скопирован: {error}")
        return
    names = street.sources or tuple(str(path) for path in (street.main, *street.extra))
    container.runs.execute(
        run_id,
        inventory,
        tuple(extra_paths),
        names,
        street.absent_references,
        gis_layers=gis_layers,
    )


async def accept_street_run(  # noqa: PLR0913 - те же поля, что у прогона своего чертежа
    *,
    container: Container,
    background: BackgroundTasks,
    street: StreetSource,
    profile: str | None = None,
    overrides: str | None = None,
    inventory: UploadFile | None = None,
    layers: Sequence[UploadFile] | None = None,
) -> RunRecord:
    """Поставить в очередь прогон по улице из каталога.

    Файлы уже лежат на диске, поэтому копирование идёт фоном вместе с самим прогоном:
    подоснова улицы весит до двух сотен мегабайт, и копировать её в обработчике запроса
    значит держать event loop на время копирования. Перечётная ведомость приходит от
    человека и сохраняется сразу: у улицы из каталога её нет.
    """
    values = parse_overrides(overrides)
    # Единицы из каталога - когда заголовок основы с геометрией спорит; явный выбор
    # человека сильнее каталога.
    if street.drawing_unit and "drawing_unit" not in values:
        values["drawing_unit"] = street.drawing_unit
    # Имя прогона проходит ту же проверку, что имя загруженного файла, поэтому расширение
    # обязательно: в реестре человек ищет улицу по названию, а не по имени файла из архива.
    record = container.runs.register(
        f"{street.title}{street.main.suffix}",
        profile or container.settings.default_profile,
        values,
    )
    inventory_path = await _store_inventory(container, record.run_id, inventory)
    layer_paths = await _store_layers(container, record.run_id, layers)
    background.add_task(
        _copy_and_execute, container, record.run_id, street, inventory_path, layer_paths
    )
    return record
