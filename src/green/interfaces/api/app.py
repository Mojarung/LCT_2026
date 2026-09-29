"""Фабрика FastAPI-приложения."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from green import __version__
from green.bootstrap.container import Container, build_container
from green.infrastructure.logs import configure_logging
from green.interfaces.api.errors import install_error_handlers
from green.interfaces.api.routers import edits, runs, system
from green.interfaces.web import mount_spa

API_PREFIX = "/api/v1"
TAGS = [
    {"name": "system", "description": "Состояние сервиса и справочники для клиента."},
    {"name": "runs", "description": "Прогоны: загрузка DXF/DWG, статус, артефакты результата."},
    {"name": "edits", "description": "Правка плана на карте: проверка точки, правки, пересборка."},
]


def create_app(container: Container | None = None) -> FastAPI:
    container = container or build_container()
    settings = container.settings
    configure_logging(json=settings.log_json, level=settings.log_level)

    app = FastAPI(
        title="green API",
        version=__version__,
        summary="Автопроектирование озеленения улиц с учётом подземных сетей и норм.",
        description=(
            "Прогон принимает DXF или DWG, строит план посадок на отдельных слоях GREEN_* "
            "и возвращает DXF, объяснения со ссылками на пункты НПА "
            "и отчёт о целостности исходных слоёв."
        ),
        openapi_tags=TAGS,
        openapi_url=f"{API_PREFIX}/openapi.json",
        # /docs отдаёт mount_spa: Swagger берёт статику из сборки интерфейса, а не с CDN.
        # ReDoc убран - он грузит скрипт из интернета, а ТЗ требует только Swagger.
        docs_url=None,
        redoc_url=None,
    )
    app.state.container = container
    # Подоснова на настоящем чертеже - 12,9 МБ JSON, который жмётся до 1,3 МБ. Без сжатия
    # карта в браузере открывалась бы десятки секунд даже по локальной сети.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["*"],
            expose_headers=["Location"],
        )
    install_error_handlers(app)
    app.include_router(system.router, prefix=API_PREFIX)
    app.include_router(runs.router, prefix=API_PREFIX)
    app.include_router(edits.router, prefix=API_PREFIX)
    # Интерфейс подключается последним: он держит всё, что не /api, и не должен
    # перехватывать маршруты API.
    mount_spa(app, settings.web_dir)
    return app
