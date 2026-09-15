"""ASGI-фабрика для Granian: green.interfaces.api.asgi:create (factory=True)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from green.interfaces.api.app import create_app

if TYPE_CHECKING:
    from fastapi import FastAPI


def create() -> FastAPI:
    return create_app()
