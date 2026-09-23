"""Cheap structural guard before tolerant loading: recovery must not hide truncation."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from green.application.errors import InputError

if TYPE_CHECKING:
    from pathlib import Path

_BINARY_HEADER = b"AutoCAD Binary DXF\r\n\x1a\x00"
_ASCII_ENTITIES = re.compile(
    rb"(?:^|\n)[ \t]*0+[ \t]*\nSECTION[ \t]*\n[ \t]*0*2[ \t]*\nENTITIES[ \t]*\n"
)
_ASCII_EOF = re.compile(rb"(?:^|\n)[ \t]*0+[ \t]*\nEOF[ \t\n]*$")
_BINARY_ENTITIES = (b"\x00\x00SECTION\x00\x02\x00ENTITIES\x00", b"\x00SECTION\x00\x02ENTITIES\x00")
_CHUNK = 1_048_576
_OVERLAP = 128


def require_complete_container(path: Path) -> None:
    """Require ENTITIES and a terminal EOF in ASCII or binary DXF.

    This proves only a container boundary, not that a DWG converter retained all
    source objects. The actual DXF grammar and repairs remain ezdxf's responsibility.
    """
    with path.open("rb") as stream:
        binary = stream.read(len(_BINARY_HEADER)) == _BINARY_HEADER
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - _CHUNK))
        tail = stream.read()
        complete = (
            tail.rstrip(b"\r\n").endswith(b"\x00EOF\x00")
            if binary
            else _ASCII_EOF.search(_newlines(tail)) is not None
        )
        if not complete:
            raise InputError(f"Неполный DXF {path.name}: отсутствует конечный маркер EOF")
        stream.seek(0)
        carry = b""
        while chunk := stream.read(_CHUNK):
            data = carry + chunk
            found = (
                any(marker in data for marker in _BINARY_ENTITIES)
                if binary
                else _ASCII_ENTITIES.search(_newlines(data)) is not None
            )
            if found:
                return
            carry = data[-_OVERLAP:]
    raise InputError(f"Неполный DXF {path.name}: отсутствует секция ENTITIES")


def _newlines(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n") if b"\r" in data else data
