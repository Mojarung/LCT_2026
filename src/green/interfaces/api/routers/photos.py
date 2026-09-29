"""Фото участка по кадру 3D-вида: очередь генеративной модели.

Кадр присылает браузер: 3D-вид строится только там. Сервер ставит его в очередь модели и
отдаёт фото, когда оно готово (минута-две на кадр). Опрос - GET /runs/{id}/photos/{photo}.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse

from green.application.photos import (
    MAX_PROMPT,
    SIDE_MAX,
    PhotoJob,
    PhotoOptions,
    PhotoState,
    PhotoUnavailableError,
    Season,
    Viewpoint,
    build_prompt,
    species_names,
)
from green.interfaces.api.dependencies import ContainerDep
from green.interfaces.api.errors import PROBLEM_RESPONSES, Problem
from green.interfaces.api.schemas import PhotoListOut, PhotoOut, PromptOut

router = APIRouter(
    prefix="/runs",
    tags=["photos"],
    responses={**PROBLEM_RESPONSES, 503: {"model": Problem, "description": "Сервис недоступен"}},
)
SHOT_MAX = 160
MEDIA = {"source": "image/png", "raw": "image/png", "photo": "image/jpeg"}


def _out(request: Request, job: PhotoJob) -> PhotoOut:
    def url(kind: str) -> str:
        return str(
            request.app.url_path_for(
                "get_photo_file", run_id=job.run_id, photo_id=job.id, kind=kind
            )
        )

    done = job.state is PhotoState.SUCCEEDED
    o = job.options
    return PhotoOut(
        id=job.id,
        state=job.state.value,
        scenery=o.scenery,
        season=o.season,
        hour=o.hour,
        viewpoint=o.viewpoint,
        species=list(o.species),
        shrubs=list(o.shrubs),
        shot=o.shot,
        modern=o.modern,
        custom=bool(o.custom_text.strip()),
        width=job.width,
        height=job.height,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        seconds=job.seconds,
        error=job.error,
        upscaled=job.upscaled,
        source_url=url("source"),
        photo_url=url("photo") if done else None,
        raw_url=url("raw") if done else None,
    )


@router.get("/{run_id}/photos")
def list_photos(run_id: str, request: Request, container: ContainerDep) -> PhotoListOut:
    """Фото прогона, новые сверху, и можно ли делать новые на этом сервере."""
    reason = container.photos.unavailable_reason
    return PhotoListOut(
        available=reason is None,
        reason=reason,
        photos=[_out(request, job) for job in container.photos.jobs(run_id)],
    )


@router.post("/{run_id}/photos", status_code=202)
async def create_photo(  # noqa: PLR0913 - form fields are separate parameters by design
    *,
    run_id: str,
    request: Request,
    response: Response,
    container: ContainerDep,
    image: Annotated[
        UploadFile, File(description=f"Кадр 3D-вида, PNG, стороны кратны 32, до {SIDE_MAX} px")
    ],
    scenery: Annotated[
        bool, Form(description="Разрешить модели дорисовать фон и деревья, которых нет в плане")
    ] = False,
    season: Annotated[Season, Form()] = "summer",
    hour: Annotated[float, Form(ge=0, le=24)] = 11.0,
    viewpoint: Annotated[Viewpoint, Form()] = "aerial",
    species: Annotated[
        str, Form(description="Латинские названия деревьев в кадре через запятую")
    ] = "",
    shrubs: Annotated[
        str, Form(description="Латинские названия кустарников в кадре через запятую")
    ] = "",
    shot: Annotated[str, Form(max_length=SHOT_MAX, description="Подпись кадра в галерее")] = "",
    modern: Annotated[
        bool, Form(description="Современные московские фасады: объём и этажность домов те же")
    ] = True,
    prompt: Annotated[
        str, Form(max_length=MAX_PROMPT, description="Свой промпт вместо собранного сервисом")
    ] = "",
    negative: Annotated[
        str, Form(max_length=MAX_PROMPT, description="Свой негативный промпт")
    ] = "",
) -> PhotoOut:
    """Поставить кадр в очередь модели. Статус: GET по адресу из Location."""
    container.store.get(run_id)
    if container.photos.unavailable_reason is not None:
        raise PhotoUnavailableError(container.photos.unavailable_reason)
    options = PhotoOptions(
        scenery=scenery,
        season=season,
        hour=hour,
        viewpoint=viewpoint,
        species=species_names(species.split(",")),
        shrubs=species_names(shrubs.split(",")),
        shot=" ".join(shot.split()),
        modern=modern,
        custom_text=prompt,
        custom_negative=negative,
    )
    job = container.photos.submit(run_id, await image.read(), options)
    out = _out(request, job)
    response.headers["Location"] = str(
        request.app.url_path_for("get_photo", run_id=run_id, photo_id=job.id)
    )
    return out


@router.get("/{run_id}/photos/prompt")
def photo_prompt(  # noqa: PLR0913 - query parameters are separate by design
    *,
    run_id: str,
    container: ContainerDep,
    scenery: bool = False,
    modern: bool = True,
    season: Season = "summer",
    hour: Annotated[float, Query(ge=0, le=24)] = 11.0,
    viewpoint: Viewpoint = "aerial",
    species: str = "",
    shrubs: str = "",
) -> PromptOut:
    """Промпт, который сервис соберёт для фото с этими параметрами: основа для редактора."""
    container.store.get(run_id)
    built = build_prompt(
        PhotoOptions(
            scenery=scenery,
            modern=modern,
            season=season,
            hour=hour,
            viewpoint=viewpoint,
            species=species_names(species.split(",")),
            shrubs=species_names(shrubs.split(",")),
        )
    )
    return PromptOut(text=built.text, negative=built.negative)


@router.get("/{run_id}/photos/{photo_id}")
def get_photo(
    run_id: str, photo_id: str, request: Request, response: Response, container: ContainerDep
) -> PhotoOut:
    response.headers["Cache-Control"] = "no-store"
    return _out(request, container.photos.get(run_id, photo_id))


@router.delete("/{run_id}/photos/{photo_id}", status_code=204)
def delete_photo(run_id: str, photo_id: str, container: ContainerDep) -> Response:
    """Удалить фото вместе с кадром. Фото в очереди или в работе - 409."""
    container.photos.delete(run_id, photo_id)
    return Response(status_code=204)


@router.get(
    "/{run_id}/photos/{photo_id}/{kind}",
    response_class=FileResponse,
    responses={200: {"content": {"image/png": {}, "image/jpeg": {}}}},
)
def get_photo_file(
    run_id: str,
    photo_id: str,
    kind: Literal["source", "raw", "photo"],
    container: ContainerDep,
) -> FileResponse:
    """Кадр 3D-вида (source), выход модели (raw) или увеличенное фото (photo)."""
    path = container.photos.file(run_id, photo_id, kind)
    media = MEDIA["raw" if path.suffix == ".png" and kind == "photo" else kind]
    return FileResponse(path, media_type=media, filename=f"{run_id[:8]}-{photo_id}-{path.name}")
