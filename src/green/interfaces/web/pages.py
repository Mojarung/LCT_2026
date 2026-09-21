"""Страницы веб-интерфейса: загрузка комплекта и просмотр прогона.

Роутер намеренно тонкий: приём файлов - общий с JSON-API (`intake.accept_run`), данные для
карты фронт берёт из тех же артефактов, что скачивает эксперт. Никакой второй реализации
бизнес-логики тут нет и быть не должно.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import orjson
from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from green import __version__
from green.interfaces.api.dependencies import ContainerDep
from green.interfaces.api.intake import accept_run, parse_overrides

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
RECENT_LIMIT = 12

router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse, name="web_index")
def index(request: Request, container: ContainerDep) -> HTMLResponse:
    """Форма запуска и последние прогоны."""
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "version": __version__,
            "profiles": list(container.profiles.names()),
            "default_profile": container.settings.default_profile,
            "runs": container.store.recent(RECENT_LIMIT),
        },
    )


def _form_overrides(
    raw: str | None, *, spacing_m: float | None, root_barriers: str | None, shrub_groups: str | None
) -> str | None:
    """Свести поля формы и «продвинутый» JSON в один набор параметров.

    Незаполненная галочка в HTML-форме не присылается вовсе, поэтому отсутствие значения
    означает «выключено»: обе галочки всегда есть в разметке, третьего состояния нет.
    """
    values = parse_overrides(raw)
    if spacing_m is not None:
        values["spacing_m"] = spacing_m
    values["root_barriers"] = root_barriers is not None
    values["shrub_groups"] = shrub_groups is not None
    return orjson.dumps(values).decode()


@router.post("/web/runs", name="web_create_run")
async def create_run(  # noqa: PLR0913 - поля формы приходят отдельными параметрами
    *,
    request: Request,
    background: BackgroundTasks,
    container: ContainerDep,
    file: Annotated[UploadFile, File()],
    profile: Annotated[str | None, Form()] = None,
    overrides: Annotated[str | None, Form()] = None,
    spacing_m: Annotated[float | None, Form()] = None,
    root_barriers: Annotated[str | None, Form()] = None,
    shrub_groups: Annotated[str | None, Form()] = None,
    inventory: Annotated[UploadFile | None, File()] = None,
    extra: Annotated[list[UploadFile] | None, File()] = None,
) -> RedirectResponse:
    """Принять комплект из формы и увести на страницу прогона."""
    record = await accept_run(
        container=container,
        background=background,
        file=file,
        profile=profile,
        overrides=_form_overrides(
            overrides,
            spacing_m=spacing_m,
            root_barriers=root_barriers,
            shrub_groups=shrub_groups,
        ),
        inventory=inventory,
        extra=extra,
    )
    url = request.url_for("web_run", run_id=record.run_id)
    return RedirectResponse(str(url), status_code=303)


@router.get("/runs/{run_id}", response_class=HTMLResponse, name="web_run")
def run_page(run_id: str, request: Request, container: ContainerDep) -> HTMLResponse:
    """Страница прогона: статус, сводка, артефакты и карта плана."""
    record = container.store.get(run_id)
    return TEMPLATES.TemplateResponse(
        request,
        "run.html",
        {"version": __version__, "run": record, "species": container.species.all()},
    )


@router.get("/web/runs/{run_id}/status", response_class=HTMLResponse, name="web_run_status")
def run_status(run_id: str, request: Request, container: ContainerDep) -> HTMLResponse:
    """Фрагмент статуса: его раз в две секунды забирает страница, пока прогон не закончится."""
    record = container.store.get(run_id)
    return TEMPLATES.TemplateResponse(request, "_run_status.html", {"run": record})


__all__ = ["router"]
