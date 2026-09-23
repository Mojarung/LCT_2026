"""Canonical CAD names and conservative construction-context checks."""

from __future__ import annotations

import re
import unicodedata


def name_key(value: str) -> str:
    """CAD names are case-insensitive; Unicode spelling must not change a decision."""
    return unicodedata.normalize("NFC", value).casefold()


def local_name(value: str) -> str:
    """XREF filenames are namespaces, not semantic labels of their children."""
    return re.split(r"\||\$\d+\$", unicodedata.normalize("NFC", value))[-1]


# Detect reasons to ask for a per-input assignment, never to grant soil. This is
# deliberately not a universal construction-language parser: unseen wording
# remains an explicit limitation of automatic name rules.
_MATERIAL_CONTEXT = re.compile(
    r"\b(?:за|вместо|на месте|не|нет|без)\b|"
    r"\b(?:демонт|уничтож|снос|проектир|восстан|устройств|замен|новый|нового|новая|новое)|"
    r"\b(?:proposed|demolition|remove|removed|replace|replacement|new|not)\b|"
    r"\bгазон\s+[ру]\b|\bдв гп п газон\b",
    re.IGNORECASE,
)


def material_context_requires_review(*names: str | None) -> bool:
    """Work/negation wording cannot establish the material of a planting area."""
    return any(
        _MATERIAL_CONTEXT.search(re.sub(r"[_\-]+", " ", local_name(name))) for name in names if name
    )
