"""LibreDWG (GPLv3): вызывается как внешний процесс dwg2dxf, без линковки."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

from green.application.errors import ConversionError

if TYPE_CHECKING:
    from pathlib import Path

STDERR_TAIL = 400


class LibreDwgConverter:
    name = "libredwg"

    def __init__(self, *, binary: str = "dwg2dxf", timeout_s: int = 600) -> None:
        self._binary = binary
        self._timeout = timeout_s

    def available(self) -> bool:
        return shutil.which(self._binary) is not None

    def to_dxf(self, source: Path, workdir: Path) -> Path:
        executable = shutil.which(self._binary)
        if executable is None:
            raise ConversionError(f"Не найден {self._binary}")
        target = workdir / f"{source.stem}.dxf"
        try:
            completed = subprocess.run(
                [executable, "-y", "-o", str(target), str(source)],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise ConversionError(f"dwg2dxf не уложился в {self._timeout} с") from error
        if not target.exists() or target.stat().st_size == 0:
            tail = completed.stderr[-STDERR_TAIL:]
            raise ConversionError(f"dwg2dxf завершился с кодом {completed.returncode}: {tail}")
        return target
