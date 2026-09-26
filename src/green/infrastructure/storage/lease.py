"""Блокировка файла на время жизни прогона: ОС снимает её сама, когда процесс умер.

По ней видно, что прогон со статусом «идёт» никто больше не ведёт: процесс упал, его убили
или сервис перезапустили. Без неё такой прогон вечно показывал «осталось около 10 мин»
(Макеева, 26.09.2026: пять часов после остановки пакетного прогона). Блокировка на уровне
открытого файла, а не процесса: второй экземпляр хранилища в том же процессе её тоже видит.
"""

from __future__ import annotations

import sys
from typing import IO, TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def acquire(path: Path) -> IO[bytes] | None:
    """Открыть и заблокировать файл; None - блокировку держит кто-то живой."""
    handle = path.open("a+b")
    if _lock(handle):
        return handle
    handle.close()
    return None


def release(handle: IO[bytes]) -> None:
    try:
        _unlock(handle)
    finally:
        handle.close()


def held(path: Path) -> bool:
    """Блокировку держит живой процесс (или другое открытие файла в этом процессе)."""
    handle = acquire(path)
    if handle is None:
        return True
    release(handle)
    return False


def _lock(handle: IO[bytes]) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt  # noqa: PLC0415 - модуль есть только под Windows

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl  # noqa: PLC0415 - модуль есть только под POSIX

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt  # noqa: PLC0415

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl  # noqa: PLC0415

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
