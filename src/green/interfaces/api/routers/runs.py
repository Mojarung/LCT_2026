"""Прогоны: загрузка, фоновое выполнение, статус и артефакты."""

from __future__ import annotations

import mimetypes
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse

from green.interfaces.api.dependencies import ContainerDep
from green.interfaces.api.errors import PROBLEM_RESPONSES
from green.interfaces.api.intake import accept_run
from green.interfaces.api.schemas import RunListOut, RunOut

if TYPE_CHECKING:
    from collections.abc import Callable

router = APIRouter(prefix="/runs", tags=["runs"], responses=PROBLEM_RESPONSES)
# Артефакты, которые читает браузер: их нужно провести через сжатие, см. get_artifact.
COMPRESSIBLE = frozenset({".json", ".geojson", ".csv", ".md", ".txt"})
MEDIA_TYPES = {
    ".dxf": "image/vnd.dxf",
    ".json": "application/json",
    ".geojson": "application/geo+json",
    ".csv": "text/csv; charset=utf-8",
}


def _artifact_url(request: Request) -> Callable[[str, str], str]:
    return lambda run_id, name: str(
        request.app.url_path_for("get_artifact", run_id=run_id, name=name)
    )


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
    inventory: Annotated[
        UploadFile | None,
        File(description="Перечётная ведомость .xls или .xlsx: существующие деревья в квотах"),
    ] = None,
    extra: Annotated[
        list[UploadFile] | None,
        File(description="Остальные чертежи комплекта (DXF или DWG): склеиваются с основным"),
    ] = None,
) -> RunOut:
    """Принять чертёж и поставить прогон в очередь. Статус: GET /runs/{id}."""
    record = await accept_run(
        container=container,
        background=background,
        file=file,
        profile=profile,
        overrides=overrides,
        inventory=inventory,
        extra=extra,
    )
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
def get_artifact(run_id: str, name: str, container: ContainerDep) -> Response:
    """Скачать артефакт: result.dxf, plan.json, interpretations.csv и другие.

    Текстовые артефакты отдаются обычным ответом, а не FileResponse, намеренно. Granian
    умеет отправлять файл в обход ASGI-конвейера (расширение pathsend), и тогда сжатие
    middleware не применяется: подоснова Берзарина уехала бы в браузер на 12,9 МБ вместо
    1,3 МБ. Крупный result.dxf, наоборот, скачивают целиком и жать его незачем.
    """
    path = container.store.artifact(run_id, name)
    media_type = (
        MEDIA_TYPES.get(path.suffix)
        or mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )
    if path.suffix in COMPRESSIBLE:
        return Response(
            path.read_bytes(),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )
    return FileResponse(path, media_type=media_type, filename=name)
