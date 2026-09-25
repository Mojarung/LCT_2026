"""Preserve LibreDWG DXF while recovering its missing ACIS data from the DWG."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import ezdxf

from green.application.errors import ConversionError, InputError
from green.infrastructure.cad.acis_sidecar import load_region_sidecar, sidecar_path
from green.infrastructure.cad.structure import require_complete_container
from green.infrastructure.convert.libredwg import LibreDwgConverter

if TYPE_CHECKING:
    from ezdxf.document import Drawing

_SECTION = re.compile(rb"(?m)^[ \t]*0\r?\nSECTION\r?\n[ \t]*2\r?\nACDSDATA\r?\n")
_ENDSEC = re.compile(rb"(?m)^[ \t]*0\r?\nENDSEC\r?\n")
_EOF = re.compile(rb"(?m)^[ \t]*0\r?\nEOF\r?\n?\Z")


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _acds_section(data: bytes) -> bytes:
    starts = list(_SECTION.finditer(data))
    if len(starts) != 1:
        raise ConversionError("ACIS bridge: ожидалась ровно одна секция ACDSDATA")
    ending = _ENDSEC.search(data, starts[0].end())
    if ending is None:
        raise ConversionError("ACIS bridge: секция ACDSDATA не закрыта")
    return data[starts[0].start() : ending.end()]


def _splice_acds(base: bytes, rich: bytes) -> bytes:
    """Replace only ACDSDATA; all other LibreDWG bytes stay identical."""
    section = _acds_section(rich)
    existing = list(_SECTION.finditer(base))
    if len(existing) > 1:
        raise ConversionError("LibreDWG DXF: неоднозначная секция ACDSDATA")
    if existing:
        ending = _ENDSEC.search(base, existing[0].end())
        if ending is None:
            raise ConversionError("LibreDWG DXF: секция ACDSDATA не закрыта")
        return base[: existing[0].start()] + section + base[ending.end() :]
    eof = _EOF.search(base)
    if eof is None:
        raise ConversionError("LibreDWG DXF: отсутствует конечный EOF")
    return base[: eof.start()] + section + base[eof.start() :]


class HybridDwgConverter:
    name = "hybrid-acis"

    def __init__(
        self,
        *,
        libredwg_binary: str = "dwg2dxf",
        bridge_binary: str = "green-acis-bridge",
        timeout_s: int = 600,
    ) -> None:
        self._base = LibreDwgConverter(binary=libredwg_binary, timeout_s=timeout_s)
        self._bridge = bridge_binary
        self._timeout = timeout_s

    def available(self) -> bool:
        return self._base.available() and shutil.which(self._bridge) is not None

    def to_dxf(self, source: Path, workdir: Path) -> Path:
        bridge = shutil.which(self._bridge)
        if bridge is None:
            raise ConversionError(f"Не найден {self._bridge}")
        workdir.mkdir(parents=True, exist_ok=True)
        target = workdir / f"{source.stem}.dxf"
        with TemporaryDirectory(prefix="hybrid_", dir=workdir) as staging:
            temporary = Path(staging)
            base = self._base.to_dxf(source, temporary / "base")
            rich = temporary / "rich.dxf"
            raw_sidecar = temporary / "regions.json"
            try:
                completed = subprocess.run(
                    [bridge, str(source), str(rich), str(raw_sidecar)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self._timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise ConversionError(f"ACIS bridge не уложился в {self._timeout} с") from error
            if completed.returncode or not rich.is_file() or not raw_sidecar.is_file():
                raise ConversionError(
                    f"ACIS bridge: код {completed.returncode}; {completed.stderr[-400:]}"
                )
            try:
                payload = json.loads(raw_sidecar.read_text(encoding="utf-8"))
                if not isinstance(payload, dict) or payload.get("source_sha256") != _sha256_file(
                    source
                ):
                    raise ConversionError("ACIS bridge: хеш исходного DWG не совпал")
                fresh = temporary / target.name
                fresh.write_bytes(_splice_acds(base.read_bytes(), rich.read_bytes()))
                require_complete_container(fresh)
                digest = _sha256_file(fresh)
                payload["dxf_sha256"] = digest
                doc = ezdxf.readfile(fresh)
                recovered = load_region_sidecar_from_payload(fresh, payload, doc)
                if len(recovered) != payload["source_regions"]:
                    raise ConversionError("ACIS bridge: часть REGION осталась без геометрии")
                sidecar_path(fresh).write_text(
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
            except (OSError, ValueError, KeyError, InputError) as error:
                raise ConversionError(f"ACIS bridge: проверка результата: {error}") from error
            final_sidecar = sidecar_path(target)
            fresh.replace(target)
            sidecar_path(fresh).replace(final_sidecar)
            return target


def load_region_sidecar_from_payload(
    path: Path, payload: dict[str, object], doc: Drawing
) -> dict[str, tuple[str, ...]]:
    """Validate exactly the sidecar that will accompany the published DXF."""
    sidecar_path(path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return load_region_sidecar(path, str(payload["dxf_sha256"]), doc)
