"""A converter must produce a fresh, structurally complete DXF, not just leave a file."""

from __future__ import annotations

import subprocess
from pathlib import Path

import ezdxf
import pytest

from green.application.errors import ConversionError, InputError
from green.infrastructure.cad.documents import load_document
from green.infrastructure.cad.structure import require_complete_container
from green.infrastructure.convert.libredwg import LibreDwgConverter
from green.infrastructure.convert.oda import OdaFileConverter


def _dxf(path: Path, *, binary: bool = False) -> bytes:
    doc = ezdxf.new("R2018")
    doc.modelspace().add_line((1, 2), (3, 4))
    doc.saveas(path, fmt="bin" if binary else "asc")
    return path.read_bytes()


@pytest.mark.parametrize("binary", [False, True])
def test_truncated_dxf_is_not_recovered_as_complete_input(tmp_path: Path, *, binary: bool) -> None:
    source = tmp_path / "incomplete.dxf"
    data = _dxf(source, binary=binary)
    assert b"EOF" in data[-12:]
    source.write_bytes(data[: data.rfind(b"EOF")])
    with pytest.raises(InputError, match="EOF"):
        load_document(source)


@pytest.mark.parametrize("binary", [False, True])
def test_complete_ascii_and_binary_dxf_remain_readable(tmp_path: Path, *, binary: bool) -> None:
    source = tmp_path / "complete.dxf"
    _dxf(source, binary=binary)
    doc, _ = load_document(source)
    assert len(doc.modelspace().query("LINE")) == 1


@pytest.mark.parametrize("newline", [b"\n", b"\r\n", b"\r"])
def test_ascii_line_endings_and_chunk_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    newline: bytes,
) -> None:
    source = tmp_path / "newlines.dxf"
    # ezdxf пишет переводы строк ОС: на Windows это уже CRLF. Сначала к LF, потом к варианту теста.
    source.write_bytes(_dxf(source).replace(b"\r\n", b"\n").replace(b"\n", newline))
    monkeypatch.setattr("green.infrastructure.cad.structure._CHUNK", 32)
    require_complete_container(source)
    doc, _ = load_document(source)
    assert len(doc.modelspace().query("LINE")) == 1


def test_eof_without_entities_is_not_a_complete_conversion(tmp_path: Path) -> None:
    source = tmp_path / "header-only.dxf"
    source.write_bytes(b"0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nEOF\n")
    with pytest.raises(InputError, match="ENTITIES"):
        load_document(source)


def test_r12_binary_container(tmp_path: Path) -> None:
    source = tmp_path / "old-binary.dxf"
    doc = ezdxf.new("R12")
    doc.modelspace().add_line((1, 2), (3, 4))
    doc.saveas(source, fmt="bin")
    loaded, _ = load_document(source)
    assert len(loaded.modelspace().query("LINE")) == 1


@pytest.mark.parametrize("converter_name", ["libredwg", "oda"])
@pytest.mark.parametrize("failure", ["stale", "nonzero", "empty", "truncated", "timeout"])
def test_failed_conversion_preserves_previous_good_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    converter_name: str,
    failure: str,
) -> None:
    source = tmp_path / "source.dwg"
    source.write_bytes(b"original input")
    work = tmp_path / "converted"
    work.mkdir()
    previous = work / "source.dxf" if converter_name == "libredwg" else work / "oda_out/source.dxf"
    previous.parent.mkdir(exist_ok=True)
    old_bytes = _dxf(previous)
    valid_bytes = _dxf(tmp_path / "template.dxf")
    monkeypatch.setattr("shutil.which", lambda _name: "/unused/converter")

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        target = (
            Path(command[command.index("-o") + 1])
            if converter_name == "libredwg"
            else Path(command[-6]) / "source.dxf"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1)
        if failure == "nonzero":
            target.write_bytes(valid_bytes)
        elif failure == "empty":
            target.write_bytes(b"")
        elif failure == "truncated":
            target.write_bytes(b"0\nSECTION\n2\nHEADER\n0\nENDSEC\n")
        return subprocess.CompletedProcess(
            command, 1 if failure == "nonzero" else 0, "", "conversion error"
        )

    monkeypatch.setattr("subprocess.run", run)
    converter = LibreDwgConverter() if converter_name == "libredwg" else OdaFileConverter()
    with pytest.raises(ConversionError, match=r"конвертац|код|DXF|уложился"):
        converter.to_dxf(source, work)
    assert previous.read_bytes() == old_bytes
    assert source.read_bytes() == b"original input"


@pytest.mark.parametrize("converter_name", ["libredwg", "oda"])
def test_valid_conversion_replaces_previous_output_only_after_checking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    converter_name: str,
) -> None:
    source = tmp_path / "source.dwg"
    source.write_bytes(b"original input")
    work = tmp_path / "converted"
    work.mkdir()
    previous = work / "source.dxf" if converter_name == "libredwg" else work / "oda_out/source.dxf"
    previous.parent.mkdir(exist_ok=True)
    previous.write_bytes(b"stale output")
    valid_bytes = _dxf(tmp_path / "template.dxf")
    monkeypatch.setattr("shutil.which", lambda _name: "/unused/converter")

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        target = (
            Path(command[command.index("-o") + 1])
            if converter_name == "libredwg"
            else Path(command[-6]) / "source.dxf"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(valid_bytes)
        return subprocess.CompletedProcess(command, 0, "finished", "")

    monkeypatch.setattr("subprocess.run", run)
    converter = LibreDwgConverter() if converter_name == "libredwg" else OdaFileConverter()
    result = converter.to_dxf(source, work)
    assert result.read_bytes() == valid_bytes
    assert source.read_bytes() == b"original input"
