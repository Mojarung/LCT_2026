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
_MIN_TRANSFORM_FIELDS = 5


def _length_prefixed_token(marker: str, value: str) -> bool:
    return marker.startswith("@") and marker[1:].isdigit() and int(marker[1:]) == len(value)


def sidecar_path(dxf: Path) -> Path:
    return dxf.with_suffix(".acis.json")


def normalize_sab_sat(value: str) -> tuple[str, ...]:
    """Normalize verified SAB-to-SAT variants without changing the geometric data."""
    lines = value.splitlines()
    if not lines or not lines[0].split()[0].isdigit():
        raise InputError("Некорректный SAT из ACIS bridge")
    output = []
    for original in lines:
        if original.startswith("coedge "):
            output.append(_normalize_coedge(original))
        elif original.startswith("vertex "):
            output.append(_normalize_vertex(original))
        elif original.startswith("transform "):
            output.append(_normalize_transform(original))
        else:
            output.append(original)
    return tuple(output)


def _normalize_coedge(line: str) -> str:
    fields = line.split()
    if len(fields) < _MIN_COEDGE_FIELDS or fields[-1] != "#":
        raise InputError("Неизвестный формат SAB coedge")
    if fields[-3] == "0" and fields[-2].startswith("$"):
        fields.pop(-3)
    elif not (fields[-3].startswith("$") and fields[-2].startswith("$")):
        raise InputError("Неизвестный формат SAB coedge")
    return " ".join(fields)


def _normalize_vertex(line: str) -> str:
    fields = line.split()
    if len(fields) < _MIN_VERTEX_FIELDS or fields[-1] != "#":
        raise InputError("Неизвестный формат SAB vertex")
    if fields[-3].lstrip("-").isdigit() and fields[-2].startswith("$"):
        fields.pop(-3)
    elif not (fields[-3].startswith("$") and fields[-2].startswith("$")):
        raise InputError("Неизвестный формат SAB vertex")
    return " ".join(fields)


def _normalize_transform(line: str) -> str:
    fields = line.split()
    if len(fields) >= _MIN_TRANSFORM_FIELDS and fields[3].startswith("@"):
        payload = " ".join(fields[4:-1]) + " "
        if fields[-1] != "#" or not _length_prefixed_token(fields[3], payload):
            raise InputError("Неизвестный формат SAB transform")
        fields.pop(3)
        return " ".join(fields)
    return line


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
