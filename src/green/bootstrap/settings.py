"""Настройки из переменных окружения GREEN_* и файла .env."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GREEN_", env_file=".env", extra="ignore")

    config_dir: Path = Path("config")
    runs_dir: Path = Path("var/runs")
    default_profile: str = "strict"
    converter: Literal["auto", "libredwg", "oda", "none"] = "auto"
    libredwg_binary: str = "dwg2dxf"
    oda_binary: str = "ODAFileConverter"
    converter_timeout_s: int = Field(default=600, ge=10, le=7200)
    text_font: str = "DejaVuSans.ttf"
    cors_origins: list[str] = Field(default_factory=list)
    max_upload_mb: int = Field(default=512, ge=1, le=4096)
    # Сколько прогонов держать в памяти для правки на карте. Сцена генплана весит сотни МБ,
    # поэтому по умолчанию один: правят тот прогон, который только что открыли.
    edit_contexts: int = Field(default=1, ge=1, le=8)
    max_parallel_runs: int = Field(default=2, ge=1, le=64)
    log_json: bool = False
    log_level: str = "INFO"
