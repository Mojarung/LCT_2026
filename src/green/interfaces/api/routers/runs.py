"""Прогоны: загрузка, фоновое выполнение, статус и артефакты."""

from __future__ import annotations

import mimetypes
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse

from green.application.errors import InputError, NotFoundError
from green.infrastructure.cad.sample import SAMPLE_NAME, write_sample
from green.interfaces.api.dependencies import ContainerDep
from green.interfaces.api.errors import PROBLEM_RESPONSES, conflict_response
from green.interfaces.api.intake import accept_run, accept_street_run
from green.interfaces.api.schemas import RunListOut, RunOut

if TYPE_CHECKING:
    from collections.abc import Callable

    from green.bootstrap.container import Container

router = APIRouter(prefix="/runs", tags=["runs"], responses=PROBLEM_RESPONSES)
# Артефакты, которые читает браузер: их нужно провести через сжатие, см. get_artifact.
COMPRESSIBLE = frozenset({".json", ".geojson", ".csv", ".md", ".txt", ".html"})
# Открывается в браузере, а не скачивается: отчёт интерпретаций печатается в PDF из вкладки.
INLINE = frozenset({".html"})
MEDIA_TYPES = {
    ".dxf": "image/vnd.dxf",
    ".json": "application/json",
    ".geojson": "application/geo+json",
    ".csv": "text/csv; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".html": "text/html; charset=utf-8",
}


def _artifact_url(request: Request) -> Callable[[str, str], str]:
    return lambda run_id, name: str(
        request.app.url_path_for("get_artifact", run_id=run_id, name=name)
    )


def _artifact_size(container: Container) -> Callable[[str, str], int | None]:
    """Размер артефакта с диска; пропавший файл - не ошибка ответа, а пустой размер."""

    def size(run_id: str, name: str) -> int | None:
        try:
            return container.store.artifact(run_id, name).stat().st_size
        except NotFoundError, OSError, ValueError:
            return None

    return size


@router.post("", status_code=202, summary="Запустить прогон")
async def create_run(  # noqa: PLR0913 - form fields are separate parameters by design
    *,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    container: ContainerDep,
    file: Annotated[
        UploadFile | None, File(description="Чертёж DXF или DWG; или street, но не оба")
    ] = None,
    street: Annotated[
        str | None, Form(description="Улица пилотного проекта из /streets (slug); или file")
    ] = None,
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
    layers: Annotated[
        list[UploadFile] | None,
        File(
            description=(
                "Слои ГИС: GeoJSON (.geojson, .json) или SHP в .zip (.shp, .shx, .dbf, .prj) -"
                " охранные зоны, здания и границы data.mos.ru, кадастр. Класс объектов - по"
                " config/geo_layers.yaml или атрибуту green_class; WGS 84 пересчитывается в"
                " систему чертежа"
            )
        ),
    ] = None,
) -> RunOut:
    """Принять чертёж или улицу из каталога и поставить прогон в очередь.

    Источник ровно один: свой чертёж (`file`, к нему комплект `extra`) или улица пилотного
    проекта (`street`, её комплект уже лежит в каталоге). Статус: GET /runs/{id}.
    """
    has_file = file is not None and bool(file.filename)
    if street and has_file:
        raise InputError("Укажите что-то одно: улицу пилотного проекта или свой чертёж")
    if street:
        if any(upload.filename for upload in extra or ()):
            raise InputError("У улицы свой комплект файлов: extra с улицей не передаётся")
        source = container.streets.get(street)
        if source is None:
            raise InputError(f"Улицы {street} нет в каталоге")
        record = await accept_street_run(
            container=container,
            background=background,
            street=source,
            profile=profile,
            overrides=overrides,
            inventory=inventory,
            layers=layers,
        )
    elif file is not None and has_file:
        record = await accept_run(
            container=container,
            background=background,
            file=file,
            profile=profile,
            overrides=overrides,
            inventory=inventory,
            extra=extra,
            layers=layers,
        )
    else:
        raise InputError("Выберите улицу пилотного проекта или свой чертёж")
    response.headers["Location"] = str(request.app.url_path_for("get_run", run_id=record.run_id))
    return RunOut.from_record(record, _artifact_url(request), _artifact_size(container))


@router.post("/demo", status_code=202, summary="Запустить демонстрационный прогон")
def create_demo_run(
    request: Request, response: Response, background: BackgroundTasks, container: ContainerDep
) -> RunOut:
    """Прогон встроенного фрагмента улицы Берзарина с профилем по умолчанию.

    Фрагмент лежит в пакете: на стенде жюри датасета нет, а показывать сервис надо с
    первого клика, не заставляя искать DXF. Статус: GET /runs/{id}.
    """
    record = container.runs.register(SAMPLE_NAME, container.settings.default_profile, {})
    write_sample(container.store.input_path(record.run_id))
    background.add_task(container.runs.execute, record.run_id, None, ())
    response.headers["Location"] = str(request.app.url_path_for("get_run", run_id=record.run_id))
    return RunOut.from_record(record, _artifact_url(request), _artifact_size(container))


@router.get("", summary="Список прогонов")
def list_runs(
    request: Request, container: ContainerDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> RunListOut:
    """Последние прогоны, новые первыми."""
    url, size = _artifact_url(request), _artifact_size(container)
    return RunListOut(
        items=[RunOut.from_record(r, url, size) for r in container.store.recent(limit)]
    )


@router.get("/{run_id}", name="get_run", summary="Статус прогона")
def get_run(run_id: str, request: Request, container: ContainerDep) -> RunOut:
    """Статус прогона, сводка и ссылки на артефакты."""
    return RunOut.from_record(
        container.store.get(run_id), _artifact_url(request), _artifact_size(container)
    )


# {run_id:path}, а не {run_id}: обход вида /runs/..%2F.. иначе не совпал бы ни с одним
# маршрутом API и получил бы 405 от маршрута интерфейса. Так он доходит до хранилища, а
# оно проверяет id по виду uuid и отвечает 404, ничего не трогая.
@router.delete(
    "/{run_id:path}",
    status_code=204,
    response_class=Response,
    summary="Удалить прогон",
    responses=conflict_response(),
)
def delete_run(run_id: str, container: ContainerDep) -> None:
    """Удалить законченный прогон (готовый, упавший или прерванный) со всеми файлами:
    исходником, артефактами и состоянием правки.

    Идущий прогон - в очереди, считается или пересобирается после правки - не удаляется:
    409, файлы остаются на месте. Неизвестный или некорректный id - 404.
    """
    container.runs.delete(run_id)


@router.get(
    "/{run_id}/artifacts/{name}",
    name="get_artifact",
    response_class=FileResponse,
    summary="Скачать артефакт прогона",
)
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
        disposition = "inline" if path.suffix in INLINE else f'attachment; filename="{name}"'
        return Response(
            path.read_bytes(),
            media_type=media_type,
            headers={"Content-Disposition": disposition},
        )
    return FileResponse(path, media_type=media_type, filename=name)
