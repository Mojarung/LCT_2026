"""Прогоны: загрузка, фоновое выполнение, статус и артефакты."""

from __future__ import annotations

import mimetypes
from typing import TYPE_CHECKING, Annotated

import anyio
import orjson
from fastapi import APIRouter, BackgroundTasks, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse

from green.application.errors import InputError
from green.interfaces.api.dependencies import ContainerDep
from green.interfaces.api.errors import PROBLEM_RESPONSES, PayloadTooLargeError
from green.interfaces.api.schemas import RunListOut, RunOut

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

router = APIRouter(prefix="/runs", tags=["runs"], responses=PROBLEM_RESPONSES)
CHUNK = 1024 * 1024
MEDIA_TYPES = {
    ".dxf": "image/vnd.dxf",
    ".json": "application/json",
    ".csv": "text/csv; charset=utf-8",
}


def _artifact_url(request: Request) -> Callable[[str, str], str]:
    return lambda run_id, name: str(
        request.app.url_path_for("get_artifact", run_id=run_id, name=name)
    )


def _parse_overrides(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        value = orjson.loads(raw)
    except orjson.JSONDecodeError as error:
        raise InputError(f"overrides: некорректный JSON: {error}") from error
    if not isinstance(value, dict):
        raise InputError("overrides: ожидается JSON-объект")
    return value


async def _store_upload(upload: UploadFile, target: Path, limit_bytes: int) -> None:
    written = 0
    async with await anyio.open_file(target, "wb") as stream:
        while chunk := await upload.read(CHUNK):
            written += len(chunk)
            if written > limit_bytes:
                raise PayloadTooLargeError(f"Файл больше {limit_bytes // CHUNK} МБ")
            await stream.write(chunk)


@router.post("", status_code=202)
async def create_run(  # noqa: PLR0913 - form fields are separate parameters by design
    *,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    container: ContainerDep,
    file: Annotated[UploadFile, File(description="Чертёж DXF или DWG")],
    profile: Annotated[str | None, Form(description="Профиль параметров из /meta")] = None,
    overrides: Annotated[
        str | None, Form(description="JSON-объект параметров поверх профиля")
    ] = None,
) -> RunOut:
    """Принять чертёж и поставить прогон в очередь. Статус: GET /runs/{id}."""
    settings = container.settings
    record = container.runs.register(
        file.filename or "drawing.dxf",
        profile or settings.default_profile,
        _parse_overrides(overrides),
    )
    try:
        await _store_upload(
            file, container.store.input_path(record.run_id), settings.max_upload_mb * CHUNK
        )
    except PayloadTooLargeError as error:
        container.runs.reject(record.run_id, str(error))
        raise
    background.add_task(container.runs.execute, record.run_id)
    response.headers["Location"] = str(request.app.url_path_for("get_run", run_id=record.run_id))
    return RunOut.from_record(record, _artifact_url(request))


@router.get("")
def list_runs(
    request: Request, container: ContainerDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> RunListOut:
    """Последние прогоны, новые первыми."""
    url = _artifact_url(request)
    return RunListOut(items=[RunOut.from_record(r, url) for r in container.store.recent(limit)])


@router.get("/{run_id}", name="get_run")
def get_run(run_id: str, request: Request, container: ContainerDep) -> RunOut:
    """Статус прогона, сводка и ссылки на артефакты."""
    return RunOut.from_record(container.store.get(run_id), _artifact_url(request))


@router.get("/{run_id}/artifacts/{name}", name="get_artifact", response_class=FileResponse)
def get_artifact(run_id: str, name: str, container: ContainerDep) -> FileResponse:
    """Скачать артефакт: result.dxf, plan.json, interpretations.csv и другие."""
    path = container.store.artifact(run_id, name)
    media_type = (
        MEDIA_TYPES.get(path.suffix)
        or mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )
    return FileResponse(path, media_type=media_type, filename=name)
