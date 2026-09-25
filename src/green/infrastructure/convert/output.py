"""Publish only fresh successful conversion output; keep diagnostic logs locally."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from green.application.errors import ConversionError, InputError
from green.infrastructure.cad.structure import require_complete_container

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path


def publish_conversion(
    completed: subprocess.CompletedProcess[str], fresh: Path, target: Path, *, name: str
) -> Path:
    log = target.parent / f"{target.stem}.{name}.conversion.json"
    log.write_text(
        json.dumps(
            {
                "converter": name,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "scope": "Exit status and DXF structure do not prove complete DWG conversion",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if completed.returncode != 0 or not fresh.is_file() or fresh.stat().st_size == 0:
        raise ConversionError(
            f"{name}: конвертация не дала новый DXF, код {completed.returncode}; "
            f"{completed.stderr[-400:]}"
        )
    try:
        require_complete_container(fresh)
    except InputError as error:
        raise ConversionError(f"{name}: {error}") from error
    fresh.replace(target)
    # A previous hybrid conversion of the same DWG may have left a SAT sidecar.
    # Plain DXF output must never inherit metadata tied to different bytes.
    target.with_suffix(".acis.json").unlink(missing_ok=True)
    return target
