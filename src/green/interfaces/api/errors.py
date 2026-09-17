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


_STATUS: dict[type[GreenError], HTTPStatus] = {
    NotFoundError: HTTPStatus.NOT_FOUND,
    InputError: HTTPStatus.UNPROCESSABLE_ENTITY,
    ConversionError: HTTPStatus.UNPROCESSABLE_ENTITY,
    PayloadTooLargeError: HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    ConfigurationError: HTTPStatus.INTERNAL_SERVER_ERROR,
}


def problem(
    status: HTTPStatus,
    detail: str | None,
    instance: str,
    errors: list[dict[str, object]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = Problem(
        title=status.phrase, status=status.value, detail=detail, instance=instance, errors=errors
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
    status: {"model": Problem, "description": HTTPStatus(status).phrase}
    for status in (404, 413, 422, 500)
}
