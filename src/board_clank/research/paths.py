"""Database path identity. Equivalent Windows spellings are the same file."""

from __future__ import annotations

import os
from pathlib import Path


def _strip_extended(text: str) -> str:
    if text.startswith("\\\\?\\UNC\\"):
        return "\\\\" + text[8:]
    if text.startswith("\\\\?\\"):
        return text[4:]
    return text


def database_identity(path: str | Path) -> str:
    raw = Path(path).expanduser()
    try:
        absolute = raw.resolve(strict=False)
    except OSError:
        absolute = raw.absolute()
    text = _strip_extended(os.path.normpath(str(absolute)))
    if os.name == "nt":
        text = os.path.normcase(text)
    return text.rstrip("\\/")


def same_database(left: str | Path | None, right: str | Path | None) -> bool:
    if not left or not right:
        return False
    first, second = Path(left), Path(right)
    try:
        if first.exists() and second.exists() and first.samefile(second):
            return True
    except OSError:
        pass
    return database_identity(first) == database_identity(second)
