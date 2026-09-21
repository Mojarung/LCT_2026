"""Приём прогона: сохранение загруженных файлов и постановка в очередь.

Общий код для JSON-API и для веб-формы: оба принимают один и тот же комплект файлов и
обязаны одинаково обрабатывать превышение размера и неверные расширения. Дублировать это
в двух роутерах - гарантированно разойтись в поведении.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import orjson

from green.application.errors import InputError
from green.interfaces.api.errors import PayloadTooLargeError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi import BackgroundTasks, UploadFile

    from green.application.results import RunRecord
    from green.bootstrap.container import Container

CHUNK = 1024 * 1024
DRAWING_SUFFIXES = frozenset({".dxf", ".dwg"})


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

    inventory_path = None
    if inventory is not None and inventory.filename:
        suffix = Path(inventory.filename).suffix or ".xlsx"
        inventory_path = container.store.input_path(record.run_id).with_name(f"inventory{suffix}")
        try:
            await store_upload(inventory, inventory_path, limit)
        except PayloadTooLargeError as error:
            container.runs.reject(record.run_id, str(error))
            raise

    extra_paths: list[Path] = []
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

    background.add_task(container.runs.execute, record.run_id, inventory_path, tuple(extra_paths))
    return record
