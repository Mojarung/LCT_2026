"""Provenance of a supplied drawing package, independent of CAD implementation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PackageInput:
    name: str
    dxf_sha256: str
    role: str


@dataclass(frozen=True, slots=True)
class ReferenceBinding:
    host: str
    block: str
    reference: str
    source: str | None
    action: str
    modelspace_entities: int


@dataclass(frozen=True, slots=True)
class PackageAssembly:
    inputs: tuple[PackageInput, ...]
    references: tuple[ReferenceBinding, ...]
    coordinate_policy: str = (
        "XREF uses existing INSERT transforms and source INSBASE, without an extra unit factor; "
        "independent overlay drawings are normalised by declared/overridden units."
    )
    scope: str = (
        "Only explicitly supplied files are resolved; nested overlay XREFs are excluded per CAD "
        "semantics. Expanded entity-type counts check import loss, not semantic accuracy."
    )
