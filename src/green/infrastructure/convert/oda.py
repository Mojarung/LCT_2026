"""ODA File Converter (freeware, проприетарный): внешний процесс, под Linux через xvfb-run."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from green.application.errors import ConversionError
from green.infrastructure.convert.output import publish_conversion


class OdaFileConverter:
    name = "oda"

    def __init__(
        self,
        *,
        binary: str = "ODAFileConverter",
        timeout_s: int = 600,
        output_version: str = "ACAD2018",
    ) -> None:
        self._binary = binary
        self._timeout = timeout_s
        self._version = output_version

    def available(self) -> bool:
        if shutil.which(self._binary) is None:
            return False
        return not sys.platform.startswith("linux") or shutil.which("xvfb-run") is not None

    def to_dxf(self, source: Path, workdir: Path) -> Path:
        executable = shutil.which(self._binary)
        if executable is None:
            raise ConversionError(f"Не найден {self._binary}")
        workdir.mkdir(parents=True, exist_ok=True)
        target = workdir / "oda_out" / f"{source.stem}.dxf"
        target.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="oda_", dir=workdir) as staging:
            return self._convert(executable, source, Path(staging), target)

    def _convert(self, executable: str, source: Path, staging: Path, target: Path) -> Path:
        inbox, outbox = staging / "in", staging / "out"
        inbox.mkdir(parents=True, exist_ok=True)
        outbox.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, inbox / source.name)
        command = [executable, str(inbox), str(outbox), self._version, "DXF", "0", "1", source.name]
        if sys.platform.startswith("linux"):
            command = [shutil.which("xvfb-run") or "xvfb-run", "-a", *command]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise ConversionError(f"ODA File Converter не уложился в {self._timeout} с") from error
        fresh = outbox / f"{source.stem}.dxf"
        return publish_conversion(completed, fresh, target, name=self.name)
