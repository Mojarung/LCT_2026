"""Страницы веб-интерфейса: загрузка комплекта и просмотр прогона.

Роутер намеренно тонкий: приём файлов - общий с JSON-API (`intake.accept_run`), данные для
карты фронт берёт из тех же артефактов, что скачивает эксперт. Никакой второй реализации
бизнес-логики тут нет и быть не должно.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import orjson
from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from green import __version__
from green.application.errors import InputError, NotFoundError
from green.application.progress import estimate
from green.infrastructure.cad.sample import SAMPLE_NAME, write_sample
from green.interfaces.api.dependencies import ContainerDep
from green.interfaces.api.intake import accept_run, accept_street_run, parse_overrides

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
RECENT_LIMIT = 12

#: Файлы, ради которых прогон и запускали. Остальные одиннадцать - служебные: в плоском
#: списке по алфавиту `result.dxf` стоял девятым и весил столько же, сколько `zones.geojson`.
HEADLINE_FILES = {
    "result.dxf": "план посадок на слоях GREEN_*, исходные слои целы",
    "interpretations.csv": "по строке на посадку: вид, отступы, пункт акта",
}

#: Предупреждения, которые меняют смысл всего плана, а не уточняют деталь. Остальные живут
#: в свёрнутом списке; эти три - нет. На улице без границы работ (Нижние Поля: в датасете
#: границ нет вовсе) сервис засаживает весь чертёж, и число посадок читается как результат,
#: пока не скажешь обратного. То же с комплектом из несовпавших листов и с чертежом без сетей:
#: план в этих случаях верен по своим данным и неверен по участку.
KEY_WARNINGS = (
    "Граница работ не найдена",
    "Склейка: габариты",
    "В чертеже нет подземных сетей",
)

_KIB = 1024


def _human_size(size: int) -> str:
    """Размер файла словами человека, а не байтами."""
    if size < _KIB:
        return f"{size} Б"
    if size < _KIB * _KIB:
        return f"{size / _KIB:.0f} КБ"
    return f"{size / _KIB / _KIB:.1f} МБ".replace(".", ",")


def plural(count: int, one: str, few: str, many: str) -> str:
    """Русское числительное: «1 место», «2 места», «5 мест».

    Без этого подписи приходится формулировать так, чтобы обойти падеж, и они кривеют.
    """
    tail, hundred = count % 10, count % 100
    if tail == 1 and hundred != 11:  # noqa: PLR2004 - 11 - исключение самого правила
        return one
    if 2 <= tail <= 4 and not 12 <= hundred <= 14:  # noqa: PLR2004 - границы правила
        return few
    return many


TEMPLATES.env.globals["plural"] = plural  # ty: ignore[invalid-assignment]

router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse, name="web_index")
def index(request: Request, container: ContainerDep) -> HTMLResponse:
    """Форма запуска и последние прогоны."""
    rules = container.rules.load().all_rules
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "version": __version__,
            "profiles": list(container.profiles.names()),
            "default_profile": container.settings.default_profile,
            "runs": container.store.recent(RECENT_LIMIT),
            "streets": container.streets.all(),
            "rules_total": len(rules),
            "rules_verified": sum(r.citation.is_verified for r in rules),
            "species_total": len(container.species.all()),
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
    street: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
    profile: Annotated[str | None, Form()] = None,
    overrides: Annotated[str | None, Form()] = None,
    spacing_m: Annotated[float | None, Form()] = None,
    root_barriers: Annotated[str | None, Form()] = None,
    shrub_groups: Annotated[str | None, Form()] = None,
    inventory: Annotated[UploadFile | None, File()] = None,
    extra: Annotated[list[UploadFile] | None, File()] = None,
) -> RedirectResponse:
    """Принять прогон из формы: улица из каталога или загруженный комплект.

    Оба источника приходят одной формой с общими параметрами, поэтому выбор разбирается
    здесь: выбранная улица имеет приоритет над полем файла, которое в этом случае пустое.
    """
    values = _form_overrides(
        overrides,
        spacing_m=spacing_m,
        root_barriers=root_barriers,
        shrub_groups=shrub_groups,
    )
    if street:
        source = container.streets.get(street)
        if source is None:
            raise InputError(f"Улицы {street} нет в каталоге")
        record = accept_street_run(
            container=container,
            background=background,
            street=source,
            profile=profile,
            overrides=values,
        )
    else:
        if file is None or not file.filename:
            raise InputError("Выберите улицу пилотного проекта или свой чертёж")
        record = await accept_run(
            container=container,
            background=background,
            file=file,
            profile=profile,
            overrides=values,
            inventory=inventory,
            extra=extra,
        )
    url = request.url_for("web_run", run_id=record.run_id)
    return RedirectResponse(str(url), status_code=303)


@router.post("/web/demo", name="web_demo")
def demo(
    request: Request,
    background: BackgroundTasks,
    container: ContainerDep,
    *,
    exploratory: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    """Запустить прогон на встроенном демонстрационном участке.

    Фрагмент настоящей улицы лежит в пакете: на стенде жюри датасета нет, а показывать
    сервис надо с первого клика, не заставляя искать DXF.
    """
    # The real fragment has unresolved spatial layers. Only an explicitly requested
    # sketch may bypass semantic review; uploads and ordinary demo requests stay strict.
    overrides = (
        {"require_known_objects": False, "surface_inference_mode": "distance"}
        if exploratory
        else {}
    )
    record = container.runs.register(SAMPLE_NAME, container.settings.default_profile, overrides)
    write_sample(container.store.input_path(record.run_id))
    background.add_task(container.runs.execute, record.run_id, None, ())
    return RedirectResponse(str(request.url_for("web_run", run_id=record.run_id)), status_code=303)


def _files(container: ContainerDep, run_id: str, names: tuple[str, ...]) -> dict[str, list[dict]]:
    """Разложить артефакты на результат и служебные, приписав размеры."""
    headline: list[dict] = []
    service: list[dict] = []
    for name in names:
        try:
            size = container.store.artifact(run_id, name).stat().st_size
        except OSError, ValueError:
            continue
        row = {"name": name, "size": _human_size(size)}
        if name in HEADLINE_FILES:
            headline.append(row | {"what": HEADLINE_FILES[name]})
        else:
            service.append(row)
    headline.sort(key=lambda row: list(HEADLINE_FILES).index(row["name"]))
    return {"headline": headline, "service": service}


def _quality(container: ContainerDep, run_id: str) -> dict | None:
    """Индекс качества прогона. У прогонов до появления индекса файла нет - блока тоже."""
    try:
        return orjson.loads(container.store.artifact(run_id, "quality.json").read_bytes())
    except NotFoundError, OSError, orjson.JSONDecodeError:
        return None


@router.get("/runs/{run_id}", response_class=HTMLResponse, name="web_run")
def run_page(run_id: str, request: Request, container: ContainerDep) -> HTMLResponse:
    """Страница прогона: статус, сводка, артефакты и карта плана.

    Пока прогон идёт, страница сама опрашивает `GET /api/v1/runs/{id}`: ход расчёта и
    момент, когда подоснова готова для карты, берутся оттуда же, откуда их берёт любой клиент.
    Первая отрисовка полосы хода идёт с сервера, чтобы до первого опроса не мигал ноль.
    """
    record = container.store.get(run_id)
    progress = estimate(record.progress, datetime.now(UTC)) if record.progress else None
    # Сводка прогона - это JSON с диска, а не типизированная структура: список
    # предупреждений оттуда приходит как `object`.
    raw = record.summary.get("warnings", [])
    warnings = [str(w) for w in raw] if isinstance(raw, list) else []
    return TEMPLATES.TemplateResponse(
        request,
        "run.html",
        {
            "version": __version__,
            "run": record,
            "progress": progress,
            "species": container.species.all(),
            "files": _files(container, run_id, record.artifacts),
            "notices": [w for w in warnings if w.startswith(KEY_WARNINGS)],
            "quality": _quality(container, run_id),
        },
    )


__all__ = ["router"]
