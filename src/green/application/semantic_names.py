"""Canonical CAD names and conservative construction-context checks."""

from __future__ import annotations

import re
import unicodedata


def name_key(value: str) -> str:
    """CAD names are case-insensitive; Unicode spelling must not change a decision."""
    return unicodedata.normalize("NFC", value).casefold()


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}  # fmt: skip


def slug_key(value: str) -> str:
    """Латинский ключ имени, как каталог улиц называет файлы и папки.

    Внешние ссылки комплекта помнят исходные имена («00.1_10004141_Топография»), каталог
    хранит их транслитом («00-1-10004141-topografiya»): ключ сводит оба к одному.
    """
    text = "".join(_TRANSLIT.get(char, char) for char in name_key(value))
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def local_name(value: str) -> str:
    """XREF filenames are namespaces, not semantic labels of their children."""
    return re.split(r"\||\$\d+\$", unicodedata.normalize("NFC", value))[-1]


def base_name(block: str) -> str:
    """Код условного знака: локальное имя без номера экземпляра.

    Мосгеотрест выгружает каждую вставку знака отдельным блоком с номером на конце
    (`DEREVO_935`, `KUST1_162`), а копии первого экземпляра получают ещё один номер:
    `AFIS_1`, `AFIS_1_1`, `AFIS_1_2` - один и тот же знак (одинаковые рисунок и слой,
    перепись 25.09.2026). Поэтому снимаются все хвостовые группы `_цифры`.
    """
    return re.sub(r"(_\d+)+$", "", local_name(block))


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
