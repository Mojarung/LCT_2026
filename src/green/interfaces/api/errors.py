"""Ошибки в формате Problem Details (RFC 9457): одинаково для любого будущего клиента."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from green.application.errors import (
    ConfigurationError,
    ConversionError,
    GreenError,
    InputError,
    NotFoundError,
)
from green.application.photos import PhotoBusyError, PhotoUnavailableError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fastapi import FastAPI, Request

PROBLEM_JSON = "application/problem+json"


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    errors: list[dict[str, object]] | None = None


class PayloadTooLargeError(GreenError):
    """Загружаемый файл превышает лимит."""


class EditContextLostError(GreenError):
    """Состояние прогона для правки не найдено в памяти сервиса."""


# Заголовок ошибки (RFC 9457, title) - по-русски, как и подробность: ответ читает эксперт,
# а не только клиент. Статус без записи получает фразу HTTP.
TITLES: dict[int, str] = {
    400: "Некорректный запрос",
    404: "Не найдено",
    405: "Метод не поддерживается",
    409: "Состояние прогона изменилось",
    413: "Файл слишком большой",
    415: "Формат не поддерживается",
    422: "Данные не приняты",
    500: "Внутренняя ошибка сервиса",
    503: "Сервис недоступен",
}


def title_of(status: HTTPStatus) -> str:
    return TITLES.get(status.value, status.phrase)


_STATUS: dict[type[GreenError], HTTPStatus] = {
    NotFoundError: HTTPStatus.NOT_FOUND,
    InputError: HTTPStatus.UNPROCESSABLE_ENTITY,
    ConversionError: HTTPStatus.UNPROCESSABLE_ENTITY,
    PayloadTooLargeError: HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    EditContextLostError: HTTPStatus.CONFLICT,
    ConfigurationError: HTTPStatus.INTERNAL_SERVER_ERROR,
    PhotoUnavailableError: HTTPStatus.SERVICE_UNAVAILABLE,
    PhotoBusyError: HTTPStatus.CONFLICT,
}


def problem(
    status: HTTPStatus,
    detail: str | None,
    instance: str,
    errors: list[dict[str, object]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = Problem(
        title=title_of(status),
        status=status.value,
        detail=detail,
        instance=instance,
        errors=errors,
    )
    return JSONResponse(
        body.model_dump(exclude_none=True),
        status_code=status.value,
        media_type=PROBLEM_JSON,
        headers=dict(headers) if headers else None,
    )


def install_error_handlers(app: FastAPI) -> None:
    async def on_green_error(request: Request, error: Exception) -> JSONResponse:
        status = next(
            (code for kind, code in _STATUS.items() if isinstance(error, kind)),
            HTTPStatus.BAD_REQUEST,
        )
        return problem(status, str(error), request.url.path)

    async def on_validation_error(request: Request, error: Exception) -> JSONResponse:
        details = error.errors() if isinstance(error, RequestValidationError) else []
        cleaned = [{"loc": list(d.get("loc", ())), "msg": d.get("msg", "")} for d in details]
        return problem(
            HTTPStatus.UNPROCESSABLE_ENTITY, "Некорректный запрос", request.url.path, cleaned
        )

    async def on_http_error(request: Request, error: Exception) -> JSONResponse:
        """Ответы самого фреймворка: нет маршрута, не тот метод. Формат тот же."""
        if not isinstance(error, StarletteHTTPException):
            return problem(HTTPStatus.INTERNAL_SERVER_ERROR, None, request.url.path)
        status = HTTPStatus(error.status_code)
        detail = error.detail if error.detail != status.phrase else None
        return problem(status, detail, request.url.path, headers=error.headers)

    app.add_exception_handler(GreenError, on_green_error)
    app.add_exception_handler(StarletteHTTPException, on_http_error)
    app.add_exception_handler(RequestValidationError, on_validation_error)


PROBLEM_RESPONSES: dict[int | str, dict[str, object]] = {
    status: {"model": Problem, "description": title_of(HTTPStatus(status))}
    for status in (404, 413, 422, 500)
}


def conflict_response() -> dict[int | str, dict[str, object]]:
    """409 у методов правки: контекст прогона не сохранён, прогон нужно запустить заново."""
    return {409: {"model": Problem, "description": title_of(HTTPStatus.CONFLICT)}}
