"""Раздача веб-интерфейса: собранный React-бандл из GREEN_WEB_DIR и Swagger без интернета.

Интерфейс - статический SPA (frontend/, сборка `npm run build`), который ходит только в
/api/v1. Сервер отдаёт файлы бандла, а на любой другой GET вне API - index.html: маршруты
вроде /runs/{id} разбирает клиент. Запрос к несуществующему файлу - 404, а не страница:
иначе битая ссылка на скрипт превращается в HTML и ломает интерфейс молча.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from green.application.errors import NotFoundError

SWAGGER = Path("vendor") / "swagger"
# Имена в assets/ несут хеш содержимого (Vite): такой файл не меняется никогда.
FOREVER = "public, max-age=31536000, immutable"
# Тип по расширению задаётся явно: mimetypes на Windows читает реестр, где .js бывает
# text/plain, а модульный скрипт с таким типом браузер не исполняет - интерфейс пустой.
MEDIA = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".json": "application/json",
    ".map": "application/json",
}
NOT_BUILT = (
    "Веб-интерфейс не собран. Соберите его: cd frontend && npm ci && npm run build "
    "(или укажите готовую сборку в GREEN_WEB_DIR). API работает: /api/v1, Swagger: /docs."
)


def mount_spa(app: FastAPI, web_dir: Path) -> None:
    """Swagger на /docs и интерфейс на всём, что не /api. Подключается последним."""
    root = web_dir.resolve()
    index = root / "index.html"
    swagger = root / SWAGGER

    @app.get("/docs", include_in_schema=False)
    def docs() -> HTMLResponse:
        local = (swagger / "swagger-ui-bundle.js").is_file()
        assets = (
            {
                "swagger_js_url": f"/{SWAGGER.as_posix()}/swagger-ui-bundle.js",
                "swagger_css_url": f"/{SWAGGER.as_posix()}/swagger-ui.css",
                "swagger_favicon_url": "/mark.svg",
            }
            if local
            else {}
        )
        return get_swagger_ui_html(
            openapi_url=app.openapi_url or "/openapi.json",
            title=f"{app.title} - Swagger UI",
            **assets,
        )

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            msg = f"Адреса /{path} в API нет. Список адресов: /docs"
            raise NotFoundError(msg)
        target = (root / path).resolve()
        if path and target.is_relative_to(root) and target.is_file():
            cache = FOREVER if path.startswith("assets/") else "no-cache"
            return FileResponse(
                target,
                media_type=MEDIA.get(target.suffix.lower()),
                headers={"Cache-Control": cache},
            )
        # Запрос называет файл (есть расширение или это каталог бандла), а файла нет.
        if "." in path.rsplit("/", 1)[-1] or path.startswith(("assets/", "vendor/")):
            msg = f"Файла /{path} в сборке интерфейса нет"
            raise NotFoundError(msg)
        if not index.is_file():
            return PlainTextResponse(NOT_BUILT, status_code=503)
        return FileResponse(index, media_type=MEDIA[".html"], headers={"Cache-Control": "no-cache"})
