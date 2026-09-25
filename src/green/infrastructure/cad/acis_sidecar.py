"""Verified SAT sidecar for SAB recovered from the same source DWG."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from ezdxf.entities import Region

from green.application.errors import InputError

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.document import Drawing

_MAX_SIDECAR_BYTES = 128 * 1024 * 1024
_MIN_COEDGE_FIELDS = 11
_MIN_VERTEX_FIELDS = 7


def sidecar_path(dxf: Path) -> Path:
    return dxf.with_suffix(".acis.json")


def normalize_sab_sat(value: str) -> tuple[str, ...]:
    """Remove two SAB-only fields that acadrust writes into its SAT text."""
    lines = value.splitlines()
    if not lines or not lines[0].split()[0].isdigit():
        raise InputError("Некорректный SAT из ACIS bridge")
    output = []
    for original in lines:
        line = original
        if line.startswith("coedge "):
            fields = line.split()
            if (
                len(fields) < _MIN_COEDGE_FIELDS
                or fields[-3] != "0"
                or not fields[-2].startswith("$")
            ):
                raise InputError("Неизвестный формат SAB coedge")
            fields.pop(-3)
            line = " ".join(fields)
        elif line.startswith("vertex "):
            fields = line.split()
            if (
                len(fields) < _MIN_VERTEX_FIELDS
                or not fields[-3].isdigit()
                or not fields[-2].startswith("$")
            ):
                raise InputError("Неизвестный формат SAB vertex")
            fields.pop(-3)
            line = " ".join(fields)
        output.append(line)
    return tuple(output)


def load_region_sidecar(dxf: Path, dxf_sha256: str, doc: Drawing) -> dict[str, tuple[str, ...]]:
    path = sidecar_path(dxf)
    if not path.exists():
        return {}
    if path.stat().st_size > _MAX_SIDECAR_BYTES:
        raise InputError("ACIS sidecar слишком велик")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InputError("ACIS sidecar не читается") from error
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != 1
        or payload.get("engine") != "acadrust"
        or payload.get("engine_version") != "0.5.5"
        or payload.get("dxf_sha256") != dxf_sha256
        or not isinstance(payload.get("regions"), dict)
    ):
        raise InputError("ACIS sidecar не соответствует DXF или версии конвертера")
    regions = {
        entity.dxf.handle: entity for entity in doc.entitydb.values() if isinstance(entity, Region)
    }
    if payload.get("source_regions") != len(regions):
        raise InputError("ACIS sidecar не совпадает с числом REGION")
    result: dict[str, tuple[str, ...]] = {}
    for handle, entry in payload["regions"].items():
        region = regions.get(handle)
        if (
            region is None
            or not isinstance(entry, dict)
            or not isinstance(entry.get("sab_sha256"), str)
            or not isinstance(entry.get("sat"), str)
            or not region.sab
            or hashlib.sha256(region.sab).hexdigest() != entry["sab_sha256"]
        ):
            raise InputError(f"ACIS sidecar не совпадает с REGION {handle}")
        result[handle] = normalize_sab_sat(entry["sat"])
    return result
