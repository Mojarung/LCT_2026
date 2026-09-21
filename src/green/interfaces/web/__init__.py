"""Веб-интерфейс: тонкая обёртка над теми же сценариями, что CLI и HTTP API."""

from green.interfaces.web.pages import router

__all__ = ["router"]
